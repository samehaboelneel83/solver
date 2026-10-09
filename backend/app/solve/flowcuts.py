"""Flow balances found in any model, and the cut-sets they imply (9 October 2026).

A flow balance is a rule over quantities with coefficients +1 and -1 only -- what comes in, less what goes out,
equals (or is at least) what a place keeps: a customer's demand met by shipments, a period's demand met by
production and stock carried in (`stock[t-1] + make[t] - stock[t] = demand[t]`), a junction of pipes or roads.
Read off the compiled model, with no name: each such rule is a node; a quantity in two of them (+1 in one, -1 in
the other, after each rule is turned the way round that makes them agree) is an arc between them; a quantity in
one only comes from, or goes to, outside.

**The cut-set rows.** For a set U of nodes with no supply in it, what U keeps -- D(U) -- must come in along the
arcs into U. An arc a can bring at most what it carries, and its share of U's demand is at most the demand of the
nodes it can reach inside U (D_a); behind an on/off limit (`x <= M*on`), at most `min(M, D_a)` and only when on:

    sum over arcs into U, each as   min(M_a, D_a) * on_a   or as   x_a   (whichever the relaxation is lower on)
        >= D(U)

That is the (l, S) inequality of lot sizing when U is a run of periods, the cut-set of network design when U is a
group of places, the cover of facility location when U is one customer -- one family, found in any model of the
shape. Sets are grown from each node with demand, adding the node an arc comes from while that breaks the
relaxation more (up to `MOST_NODES`); only rows the relaxation breaks are kept. Each holds at every answer.
"""
from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, Constraint, Linear, VarKey
from app.solve.fixed_charge import _normal

MOST_NODES = 40
STARTS = 20


class Flows:
    """The balances of a compiled model as nodes and arcs, with each arc's on/off limit when it has one."""

    def __init__(self, compiled: Compiled, limits: dict[VarKey, tuple[VarKey, Decimal]]):
        self.ok = False
        self.ids = {i: c.id for i, c in enumerate(compiled.constraints)}
        rows: dict[int, tuple[dict[VarKey, Decimal], str, Decimal]] = {}
        where: dict[VarKey, list[tuple[int, int]]] = {}
        for i, c in enumerate(compiled.constraints):
            normal = _normal(c)
            if normal is None:
                continue
            coeffs, relation, rhs = normal
            if relation not in ("=", "==", ">=", "<=") or not coeffs:
                continue
            if any(abs(v) != 1 for v in coeffs.values()):
                continue
            if any(compiled.variables[k].lower < 0 for k in coeffs):
                continue
            rows[i] = (coeffs, relation, rhs)
            for k, v in coeffs.items():
                where.setdefault(k, []).append((i, 1 if v > 0 else -1))
        # A quantity in more than two balances is no arc: those rules are not balances of this network.
        bad = {i for k, at in where.items() if len(at) > 2 for i, _ in at}
        rows = {i: r for i, r in rows.items() if i not in bad}
        where = {k: [(i, s) for i, s in at if i in rows] for k, at in where.items()}
        # Turn each rule so every arc is +1 at its head and -1 at its tail (two-colouring of the rules).
        flip: dict[int, int] = {}
        links: dict[int, list[tuple[int, bool]]] = {i: [] for i in rows}
        for k, at in where.items():
            if len(at) == 2:
                (i, si), (j, sj) = at
                same = si == sj  # then one of the two rules must be turned
                links[i].append((j, same))
                links[j].append((i, same))
        dropped: set[int] = set()
        for start in rows:
            if start in flip:
                continue
            flip[start] = 1
            part, queue, clash = [start], deque([start]), False
            while queue:
                i = queue.popleft()
                for j, same in links[i]:
                    want = -flip[i] if same else flip[i]
                    if j not in flip:
                        flip[j] = want
                        part.append(j)
                        queue.append(j)
                    elif flip[j] != want:
                        clash = True
            if clash:
                dropped.update(part)
                continue
            # The way round that makes most of the part's rules keep something (demand >= 0, "=" or ">=").
            def keeps(sign: int) -> int:
                score = 0
                for i in part:
                    _, relation, rhs = rows[i]
                    relation = relation if sign * flip[i] > 0 else {"<=": ">=", ">=": "<="}.get(relation, relation)
                    score += (sign * flip[i] * rhs >= 0) and relation in ("=", "==", ">=")
                return score
            if keeps(-1) > keeps(1):
                for i in part:
                    flip[i] = -flip[i]
        self.demand: dict[int, Decimal] = {}
        self.sink: set[int] = set()
        for i, (coeffs, relation, rhs) in rows.items():
            if i in dropped:
                continue
            relation = relation if flip[i] > 0 else {"<=": ">=", ">=": "<="}.get(relation, relation)
            d = flip[i] * rhs
            self.demand[i] = d
            if relation in ("=", "==", ">=") and d >= 0:
                self.sink.add(i)  # what comes in, less what goes out, is at least d: a node U may hold
        self.arcs: dict[VarKey, tuple[int | None, int | None]] = {}
        self.into: dict[int, list[VarKey]] = {i: [] for i in self.demand}
        self.out: dict[int, list[VarKey]] = {i: [] for i in self.demand}
        for k, at in where.items():
            at = [(i, s * flip[i]) for i, s in at if i in self.demand]
            head = next((i for i, s in at if s > 0), None)
            tail = next((i for i, s in at if s < 0), None)
            if head is None and tail is None:
                continue
            self.arcs[k] = (tail, head)
            if head is not None:
                self.into[head].append(k)
            if tail is not None:
                self.out[tail].append(k)
        self.limits = limits
        self.ok = any(d > 0 for d in self.demand.values()) and bool(self.arcs)

    def cut(self, members: set[int], values: dict[VarKey, float]):
        """The cut-set row of `members` at the relaxation's values: (shortfall, Constraint, coeffs, low) or None."""
        need = sum((self.demand[i] for i in members), Decimal(0))
        if need <= 0:
            return None
        entering = [k for i in members for k in self.into[i] if self.arcs[k][0] not in members]
        if not entering:
            return None
        # The demand each arc can reach inside the set, along arcs inside it.
        reach_cache: dict[int, Decimal] = {}

        def reach(start: int) -> Decimal:
            if start in reach_cache:
                return reach_cache[start]
            seen, queue = {start}, deque([start])
            while queue:
                i = queue.popleft()
                for k in self.out[i]:
                    j = self.arcs[k][1]
                    if j is not None and j in members and j not in seen:
                        seen.add(j)
                        queue.append(j)
            reach_cache[start] = sum((self.demand[i] for i in seen), Decimal(0))
            return reach_cache[start]

        coeffs: dict[VarKey, Decimal] = {}
        have = 0.0
        for k in entering:
            flow = values.get(k, 0.0)
            limit = self.limits.get(k)
            if limit is not None:
                on, most = limit
                weight = min(most, reach(self.arcs[k][1]))
                switched = float(weight) * values.get(on, 0.0)
                if switched < flow:
                    coeffs[on] = coeffs.get(on, Decimal(0)) + weight
                    have += switched
                    continue
            coeffs[k] = coeffs.get(k, Decimal(0)) + Decimal(1)
            have += flow
        short = float(need) - have
        if short <= 1e-6 * max(1.0, float(need)):
            return None
        row = Constraint(self.ids[min(members)], {}, Linear(coeffs=dict(coeffs)), ">=", Linear(const=need))
        return short, row, {k: float(v) for k, v in coeffs.items()}, float(need)

    def separate(self, values: dict[VarKey, float], most: int,
                 deadline: float | None = None) -> list[tuple[float, Any, dict, float]]:
        """Cut-set rows the relaxation breaks, grown from every node that keeps something (until `deadline`)."""
        import time

        found: dict[frozenset, tuple] = {}
        # Every node's own cut first (cheap, and on a network the strongest: a place needs a link in); then sets
        # grown from the STARTS nodes whose own cut is broken most (or that keep most).
        alone: dict[int, float] = {}
        for i in self.sink:
            if self.demand[i] > 0:
                c = self.cut({i}, values)
                alone[i] = c[0] if c else 0.0
                if c:
                    found[frozenset({i})] = c
        starts = sorted(alone, key=lambda i: (-alone[i], -float(self.demand[i]), i))[:STARTS]
        for start in starts:
            if deadline is not None and time.monotonic() > deadline:
                break
            members = {start}
            best = self.cut(members, values)
            best_members = set(members) if best else None
            for _ in range(MOST_NODES - 1):
                # The node an arc into the set comes from, when it may join (it keeps, it supplies nothing).
                tails = {self.arcs[k][0] for i in members for k in self.into[i]} - members - {None}
                tails = {t for t in tails if t in self.sink}
                if not tails:
                    break
                if len(tails) > 8:
                    # The eight sending the most into the set: growth follows the flow.
                    sent = {t: sum(values.get(k, 0.0) for k in self.out[t] if self.arcs[k][1] in members) for t in tails}
                    tails = set(sorted(tails, key=lambda t: (-sent[t], t))[:8])
                scored = [(c[0], t, c) for t in tails if (c := self.cut(members | {t}, values)) is not None]
                if not scored:
                    # No single node breaks the relaxation yet: grow along the arc carrying the most.
                    t = max(tails, key=lambda t: sum(values.get(k, 0.0) for k in self.out[t]))
                    members = members | {t}
                    continue
                score, t, c = max(scored, key=lambda item: item[0])
                members = members | {t}
                if best is None or score > best[0]:
                    best, best_members = c, set(members)
            if best is not None:
                found.setdefault(frozenset(best_members), best)
        rows = sorted(found.values(), key=lambda item: -item[0])
        return rows[:most]
