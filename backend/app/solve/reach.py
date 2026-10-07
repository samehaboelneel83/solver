"""A start for a model with a sourced `connected` rule: solve without it, then repair (October 2026).

The exact flow (`app.solve.connected`) states "every chosen unit is reached from a source" exactly, but on a
large model the solver finds poor answers with it: the camp layout -- 12,008 candidate items, 1,777 units -- gave
340 to 419 where a repaired answer gives 530. This builds that repaired answer, for any model of the shape it
can repair, and hands it to the solver as a complete start (the run never returns worse than it):

1. the model without the rule (its flow rows and flow variables) is solved for a share of the time;
2. every chosen unit not reached from a chosen source is either joined to the reached part along the cheapest
   path, or dropped -- whichever costs the goal less. Switching a unit on, or dropping one, may break other
   rules; they are mended by switching off the yes/no decisions that break them ("zeroing");
3. decisions that would improve the goal are switched on one at a time where every rule and the reach still hold;
4. the flow variables are set from a tree of the reached units, so the start sets every variable.

It applies when zeroing can always mend a rule: every variable is yes/no and every rule (but the reach) holds
with all of them at 0 -- packing, covering-by-choice, assignment-with-capacity: rules of the form "at most".
Nothing here knows what a unit is: beds and doors, pipes and supplies, roads and depots are all the same.
"""

from __future__ import annotations

import heapq
import time
from collections import defaultdict
from dataclasses import replace
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, VarKey
from app.solve.connected import FLOW, sources_of

#: The share of the run's time the start may take, and its ceiling in seconds.
SHARE, CEILING = 0.5, 90.0


def rule_of(ir: dict[str, Any]) -> dict[str, Any] | None:
    rules = [c for c in ir.get("constraints") or [] if isinstance(c, dict) and "connected" in c]
    return rules[0] if len(rules) == 1 and rules[0]["connected"].get("sources") else None


def applies(ir: dict[str, Any], compiled: Compiled | None = None) -> str | None:
    rule = rule_of(ir)
    if rule is None:
        return "the model has no single connected rule rooted at sources"
    if (ir.get("objective") or {}).get("mode") == "lex":
        return "goals solved in order are left to the solver"
    if compiled is None:
        return None
    for key, var in compiled.variables.items():
        if key[0] != FLOW and var.domain != "binary":
            return f"{key[0]} is not yes/no, so switching decisions off may not mend a rule"
    for c in compiled.constraints:
        if c.id == rule["id"]:
            continue
        if c.quadratic or c.when is not None or c.relation == "=":
            return f"rule {c.id} is not of the 'at most' kind a start can mend by switching decisions off"
        if c.relation not in ("<=", ">="):
            return f"rule {c.id} is not linear"
        slack = (c.right.const - c.left.const) if c.relation == "<=" else (c.left.const - c.right.const)
        if slack < 0:
            return f"rule {c.id} does not hold with every decision off"
    return None


class _Rows:
    """The model's rules (but the reach) as `sum(a_k x_k) <= b`, their values at the current answer, and an undo
    log so a trial costs only what it changes."""

    def __init__(self, compiled: Compiled, skip: str, x: dict[VarKey, int]):
        self.x = x
        self.rows: list[tuple[dict[VarKey, float], float]] = []
        self.of: dict[VarKey, list[tuple[int, float]]] = defaultdict(list)
        for c in compiled.constraints:
            if c.id == skip:
                continue
            sign = 1.0 if c.relation == "<=" else -1.0
            coeffs = {k: sign * float(c.left.coeffs.get(k, 0)) - sign * float(c.right.coeffs.get(k, 0))
                      for k in {*c.left.coeffs, *c.right.coeffs}}
            coeffs = {k: v for k, v in coeffs.items() if v}
            if not coeffs:
                continue
            i = len(self.rows)
            self.rows.append((coeffs, sign * (float(c.right.const) - float(c.left.const))))
            for k, v in coeffs.items():
                self.of[k].append((i, v))
        self.value = [sum(v * x.get(k, 0) for k, v in coeffs.items()) for coeffs, _ in self.rows]
        self.log: list[tuple[VarKey, int]] = []

    def set(self, key: VarKey, to: int) -> None:
        was = self.x.get(key, 0)
        if was != to:
            for i, v in self.of.get(key, ()):
                self.value[i] += v * (to - was)
            self.x[key] = to
            self.log.append((key, was))

    def mark(self) -> int:
        return len(self.log)

    def undo(self, mark: int) -> None:
        while len(self.log) > mark:
            key, was = self.log.pop()
            now = self.x.get(key, 0)
            for i, v in self.of.get(key, ()):
                self.value[i] += v * (was - now)
            self.x[key] = was

    def changed_since(self, mark: int) -> list[tuple[VarKey, int]]:
        return self.log[mark:]

    def breached(self, keys) -> list[int]:
        seen = {i for k in keys for i, _ in self.of.get(k, ())}
        return [i for i in seen if self.value[i] > self.rows[i][1] + 1e-9]

    def mend(self, changed: list[VarKey], keep: set[VarKey]) -> None:
        """Switch off yes/no decisions (never one in `keep`) until every rule touched holds; ValueError if not."""
        todo = list(changed)
        while todo:
            new = []
            for i in self.breached(todo):
                coeffs, bound = self.rows[i]
                for k, v in sorted(coeffs.items(), key=lambda kv: -kv[1]):
                    if self.value[i] <= bound + 1e-9:
                        break
                    if v > 0 and self.x.get(k, 0) == 1 and k not in keep:
                        self.set(k, 0)
                        new.append(k)
                if self.value[i] > bound + 1e-9:
                    raise ValueError("a rule cannot be mended by switching decisions off")
            todo = new


def _net(log: list[tuple[VarKey, int]]) -> list[tuple[VarKey, int]]:
    """Each variable a log touched, with its value before the first change."""
    first: dict[VarKey, int] = {}
    for key, was in log:
        first.setdefault(key, was)
    return list(first.items())


def start(ir: dict[str, Any], data: dict[str, Any], compiled: Compiled, *, seconds: float,
          solve: Any = None) -> tuple[dict[VarKey, int], dict[str, Any]]:
    """A complete start (every decision and flow) that keeps every rule, and what it achieved."""
    began = time.monotonic()
    rule = rule_of(ir)
    body = rule["connected"]
    var = body["assign"]["var"]
    grouped = body.get("groups") is not None
    if grouped:
        return {}, {"seconds": 0.0, "why": "a sourced rule with groups is left to the solver for now"}
    unit_rows = data["sets"].get(body["units"]["set"], [])
    units = [str(r["id"]) for r in unit_rows]
    known = set(units)

    class _Sets:  # what sources_of reads
        sets = data["sets"]
    sources = {str(u) for u in sources_of(_Sets, body)}
    neighbours: dict[str, set[str]] = {u: set() for u in units}
    for e in (data.get("relationships") or {}).get(body["via"], []):
        a, b = str(e["from"]), str(e["to"])
        if a in known and b in known and a != b:
            neighbours[a].add(b)
            neighbours[b].add(a)
    unit_key = {u: (var, (u,)) for u in units}

    # 1. Without the reach.
    relaxed = replace(compiled,
                      variables={k: v for k, v in compiled.variables.items() if k[0] != FLOW},
                      constraints=[c for c in compiled.constraints if c.id != rule["id"]])
    if solve is None:
        from app.solve.backends import by_name
        from app.solve.service import solve_compiled

        def solve(model, limit):
            return solve_compiled(by_name("cp-sat"), model, time_limit=limit, seed=1, workers=8)[0]
    result = solve(relaxed, max(1.0, seconds * 0.7))
    if not result.assignments:
        return {}, {"seconds": round(time.monotonic() - began, 2), "why": "the model without the reach had no answer"}
    x: dict[VarKey, int] = {k: int(round(float(result.assignments.get(k, 0)))) for k in relaxed.variables}
    relaxed_value = float(result.objective) if result.objective is not None else None
    rows = _Rows(compiled, rule["id"], x)
    sign = 1.0 if compiled.sense == "maximize" else -1.0
    gain = {k: sign * float(compiled.objective.coeffs.get(k, 0)) for k in relaxed.variables}

    def reached() -> set[str]:
        seen = {u for u in sources if x.get(unit_key[u], 0)}
        stack = list(seen)
        while stack:
            for v in neighbours[stack.pop()]:
                if v not in seen and x.get(unit_key[v], 0):
                    seen.add(v)
                    stack.append(v)
        return seen

    def apply(keys_on: list[VarKey], keys_off: list[VarKey]) -> float:
        """Switch these on and those off, mend the rules; returns the goal lost (ValueError if impossible)."""
        mark = rows.mark()
        for k in keys_off:
            rows.set(k, 0)
        for k in keys_on:
            rows.set(k, 1)
        rows.mend([*keys_on, *keys_off], set(keys_on))
        return -sum(gain[k] * (x.get(k, 0) - was) for k, was in _net(rows.changed_since(mark)))

    def trial(keys_on: list[VarKey], keys_off: list[VarKey]) -> float | None:
        mark = rows.mark()
        try:
            return apply(keys_on, keys_off)
        except ValueError:
            return None
        finally:
            rows.undo(mark)

    # 2. Join or drop each unit the sources do not reach.
    joined = dropped = 0
    for _ in range(4 * len(units) + 10):
        if time.monotonic() - began > seconds:
            break
        seen = reached()
        stranded = [u for u in units if x.get(unit_key[u], 0) and u not in seen]
        if not stranded:
            break
        u0 = stranded[0]
        # Cheapest path from u0 to the reached part: entering a unit costs the goal it forces off.
        cost_on: dict[str, float] = {}
        dist, prev = {u0: 0.0}, {}
        heap, goal = [(0.0, u0)], None
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, float("inf")):
                continue
            if u in seen or u in sources:
                goal = u  # a source still closed is a target too: opened as the path's last step
                break
            for v in neighbours[u]:
                if v in seen or x.get(unit_key[v], 0):
                    step = 0.0
                else:
                    if v not in cost_on:
                        c = trial([unit_key[v]], [])
                        cost_on[v] = float("inf") if c is None else max(c, 0.0) + 1e-6
                    step = cost_on[v]
                if step < float("inf") and d + step < dist.get(v, float("inf")):
                    dist[v], prev[v] = d + step, u
                    heapq.heappush(heap, (d + step, v))
        path = []
        if goal is not None:
            v = goal
            while True:
                if not x.get(unit_key[v], 0):
                    path.append(unit_key[v])
                if v not in prev:
                    break
                v = prev[v]
        join = trial(path, []) if goal is not None else None
        drop = trial([], [unit_key[u0]])
        mark = rows.mark()
        if join is not None and (drop is None or join <= drop):
            apply(path, [])
            if u0 in reached():
                joined += 1
                continue
            rows.undo(mark)  # what the path forced off broke it: drop instead
        try:
            apply([], [unit_key[u0]])
        except ValueError:
            rows.undo(mark)
            break
        dropped += 1
    seen = reached()
    for u in units:
        if x.get(unit_key[u], 0) and u not in seen:
            apply([], [unit_key[u]])
            dropped += 1
    if any(x.get(unit_key[u], 0) and u not in reached() for u in units):
        return {}, {"seconds": round(time.monotonic() - began, 2), "why": "the repair did not reach every unit"}

    # 3. Switch on what improves the goal, where every rule and the reach still hold. A decision that needs
    # others on ("at most" with them on the right: x <= y) switches those on too, one level deep.
    added = 0
    for k in sorted((k for k, g in gain.items() if g > 0), key=lambda k: -gain[k]):
        if time.monotonic() - began > seconds * 1.2:
            break
        if x.get(k, 0):
            continue
        mark = rows.mark()
        try:
            rows.set(k, 1)
            need = []
            for i in rows.breached([k]):
                coeffs, bound = rows.rows[i]
                for kk, v in coeffs.items():
                    if v < 0 and not x.get(kk, 0) and rows.value[i] > bound + 1e-9:
                        rows.set(kk, 1)
                        need.append(kk)
            rows.mend([k, *need], {k, *need})
            lost = -sum(gain[kk] * (x.get(kk, 0) - was) for kk, was in _net(rows.changed_since(mark)))
            if lost < 0 and not rows.breached([kk for kk, _ in rows.changed_since(mark)]):
                now = reached()
                if all(u in now for u in units if x.get(unit_key[u], 0)):
                    added += 1
                    continue
        except ValueError:
            pass
        rows.undo(mark)

    # 4. Flows along a tree of the reached units: each arc carries the size of what hangs below it.
    hint: dict[VarKey, int] = {k: int(x.get(k, 0)) for k in relaxed.variables}
    order, parent = [], {}
    frontier = [u for u in units if u in sources and x.get(unit_key[u], 0)]
    seen_tree = set(frontier)
    while frontier:
        nxt = []
        for u in frontier:
            order.append(u)
            for v in neighbours[u]:
                if v not in seen_tree and x.get(unit_key[v], 0):
                    seen_tree.add(v); parent[v] = u; nxt.append(v)
        frontier = nxt
    below = defaultdict(int)
    for u in reversed(order):
        if u in parent:
            below[u] += 1
            below[parent[u]] += below[u]
    for k in compiled.variables:
        if k[0] == FLOW:
            _, a, b = k[1][0], k[1][1], k[1][2]
            hint[k] = below[b] if parent.get(b) == a else 0
    value = sum(float(compiled.objective.coeffs.get(k, 0)) * v for k, v in hint.items()) + float(compiled.objective.const)
    return hint, {"seconds": round(time.monotonic() - began, 2), "feasible": True,
                  "without_reach": relaxed_value, "objective": value, "joined": joined, "dropped": dropped,
                  "added": added}
