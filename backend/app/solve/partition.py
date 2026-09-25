"""A connected, balanced start for a `connected` model (queue R13: connectivity at scale).

The exact flow (`app.solve.connected`) is proven up to about 200 units; past
that no solver found even one feasible partition in two minutes
(bench/results/2026-09-24-districting.md). A solver handed a complete,
feasible answer to start from has one at once, and spends its time improving
it. This builds that answer from the compiled model itself, so it knows
nothing of districts, only of the model's own rows:

1. **Seeds**: each group starts at the unit where the goal most prefers it
   (the smallest cost on assigning that unit to that group).
2. **Grow**: the groups grow from their seeds along the `via` relationship,
   the next unit always the one whose joining mends the most breach of the
   rules over the assignment (a group short of its balance floor pulls
   hardest), then the one leaving its group least full -- each group
   connected by construction.
3. **Repair and improve**: a unit on a group's edge moves to the next group
   when that lowers the breach of the rules over the assignment (balance,
   say), or, with no breach left, the goal -- and only if the group it
   leaves stays connected and non-empty. A group short of its rules with no
   neighbour to spare takes a unit through a chain of groups, each passing
   one on, from the nearest that has.
4. **Complete**: each group's root and flows are set from a spanning tree
   of it (a unit's inflow is the size of the tree below it), so the start
   satisfies every flow row exactly.

Given to the solver as a warm start (CP-SAT, HiGHS and SCIP take one); what
it achieved is recorded on the run. One `connected` rule per model: a nested
partition (zones and sub-zones) is left to the solver.
"""

from __future__ import annotations

import heapq
import time
from collections import deque
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, VarKey
from app.solve.connected import FLOW, ROOT

#: The share of the time the start may take, and its ceiling in seconds.
SHARE, CEILING = 0.1, 10.0


def rule_of(ir: dict[str, Any]) -> dict[str, Any] | None:
    rules = [c for c in ir.get("constraints") or [] if isinstance(c, dict) and "connected" in c]
    return rules[0] if len(rules) == 1 else None


def applies(ir: dict[str, Any]) -> str | None:
    connected = [c for c in ir.get("constraints") or [] if isinstance(c, dict) and "connected" in c]
    if not connected:
        return "the model has no connected rule"
    if len(connected) > 1:
        return "more than one connected rule (a nested partition) is left to the solver"
    return None


def start(ir: dict[str, Any], data: dict[str, Any], compiled: Compiled, *, seconds: float) -> tuple[dict[VarKey, int], dict[str, Any]]:
    """A complete warm start (assignments, roots, flows) and what it achieved."""
    began = time.monotonic()
    rule = rule_of(ir)
    body = rule["connected"]
    var, rule_id = body["assign"]["var"], rule["id"]
    units = [str(row["id"]) for row in data["sets"].get(body["units"]["set"], [])]
    groups = [str(row["id"]) for row in data["sets"].get(body["groups"]["set"], [])]
    known = set(units)
    neighbours: dict[str, set[str]] = {u: set() for u in units}
    for edge in (data.get("relationships") or {}).get(body["via"], []):
        a, b = str(edge["from"]), str(edge["to"])
        if a in known and b in known and a != b:
            neighbours[a].add(b)
            neighbours[b].add(a)
    x = {(u, z): (var, (u, z)) for u in units for z in groups}
    cost = {key: float(compiled.objective.coeffs.get(k, Decimal(0))) for key, k in x.items()}
    if compiled.sense != "minimize":
        cost = {key: -c for key, c in cost.items()}

    # The rows over the assignment alone: what a move can breach or mend.
    assign_keys = set(x.values())
    rows = []
    for c in compiled.constraints:
        keys = {*c.left.coeffs, *c.right.coeffs}
        if keys and keys <= assign_keys and not c.quadratic and c.when is None:
            coeffs = {k: float(c.left.coeffs.get(k, 0)) - float(c.right.coeffs.get(k, 0)) for k in keys}
            rows.append((coeffs, float(c.right.const) - float(c.left.const), c.relation))
    touching: dict[VarKey, list[tuple[int, float]]] = {}
    for i, (coeffs, _, _) in enumerate(rows):
        for k, v in coeffs.items():
            touching.setdefault(k, []).append((i, v))
    value = [0.0] * len(rows)

    def breach(i: int, lhs: float) -> float:
        _, rhs, relation = rows[i]
        return max(0.0, lhs - rhs) if relation == "<=" else max(0.0, rhs - lhs) if relation == ">=" else abs(lhs - rhs)

    def gain(u: str, z: str) -> tuple[float, float, float]:
        """Adding unassigned `u` to `z`: the change in breach, how full it
        leaves the fullest ceiling it touches, and its cost to the goal."""
        changes = touching.get(x[(u, z)], ())
        before = sum(breach(i, value[i]) for i, _ in changes)
        after = sum(breach(i, value[i] + v) for i, v in changes)
        fill = max((((value[i] + v) / rows[i][1]) for i, v in changes if rows[i][2] == "<=" and rows[i][1] > 0), default=0.0)
        return after - before, fill, cost[(u, z)]

    def place(u: str, z: str) -> None:
        group_of[u] = z
        for i, v in touching.get(x[(u, z)], ()):
            value[i] += v

    # 1. Seeds: where the goal most wants each group, distinct units.
    group_of: dict[str, str] = {}
    for z in groups:
        place(min((u for u in units if u not in group_of), key=lambda u: cost[(u, z)]), z)
    # 2. Grow: the frontier unit whose joining mends the most breach (a group
    # under its floor pulls hardest), then leaves its group least full, then
    # costs the goal least, joins next -- so no group fills to its ceiling
    # while another is short; a stale gain is re-scored when it comes up.
    heap: list[tuple[float, float, float, str, str]] = []
    for u, z in list(group_of.items()):
        for v in neighbours[u]:
            if v not in group_of:
                heapq.heappush(heap, (*gain(v, z), v, z))
    while heap:
        *then, u, z = heapq.heappop(heap)
        if u in group_of:
            continue
        now = gain(u, z)
        if now != tuple(then):
            heapq.heappush(heap, (*now, u, z))
            continue
        place(u, z)
        for v in neighbours[u]:
            if v not in group_of:
                heapq.heappush(heap, (*gain(v, z), v, z))
    for u in units:  # a unit no edge reaches joins the group that wants it most
        if u not in group_of:
            place(u, min(groups, key=lambda z: cost[(u, z)]))

    members: dict[str, set[str]] = {z: set() for z in groups}
    for u, z in group_of.items():
        members[z].add(u)

    def stays_connected(z: str, without: str) -> bool:
        left = members[z] - {without}
        if not left:
            return False
        first = next(iter(left))
        seen, queue = {first}, deque([first])
        while queue:
            for v in neighbours[queue.popleft()]:
                if v in left and v not in seen:
                    seen.add(v)
                    queue.append(v)
        return len(seen) == len(left)

    def delta(u: str, a: str, b: str) -> tuple[float, float]:
        changes: dict[int, float] = {}
        for i, v in touching.get(x[(u, a)], ()):
            changes[i] = changes.get(i, 0.0) - v
        for i, v in touching.get(x[(u, b)], ()):
            changes[i] = changes.get(i, 0.0) + v
        before = sum(breach(i, value[i]) for i in changes)
        after = sum(breach(i, value[i] + d) for i, d in changes.items())
        return after - before, cost[(u, b)] - cost[(u, a)]

    def move(u: str, b: str) -> None:
        a = group_of[u]
        for i, v in touching.get(x[(u, a)], ()):
            value[i] -= v
        for i, v in touching.get(x[(u, b)], ()):
            value[i] += v
        members[a].discard(u)
        members[b].add(u)
        group_of[u] = b

    def total() -> float:
        return sum(breach(i, value[i]) for i in range(len(rows)))

    # 3. Move edge units while the breach, then the goal, improves.
    limit = began + seconds
    moves = 0

    def descend() -> None:
        nonlocal moves
        improved = True
        while improved and time.monotonic() < limit:
            improved = False
            for u in units:
                if time.monotonic() >= limit:
                    break
                a = group_of[u]
                best = None
                for b in sorted({group_of[v] for v in neighbours[u]} - {a}):
                    d_breach, d_goal = delta(u, a, b)
                    if d_breach < -1e-9 or (abs(d_breach) <= 1e-9 and d_goal < -1e-9):
                        if best is None or (d_breach, d_goal) < best[0]:
                            best = ((d_breach, d_goal), b)
                if best is None or not stays_connected(a, u):
                    continue
                move(u, best[1])
                moves += 1
                improved = True

    # Rows that speak of one group only (its balance, say): a group's own breach.
    own: dict[str, list[int]] = {z: [] for z in groups}
    for i, (coeffs, _, _) in enumerate(rows):
        named = {k[1][1] for k in coeffs}
        if len(named) == 1:
            own[next(iter(named))].append(i)

    def shift(src: str, dst: str) -> str | None:
        """Move the best edge unit of `src` into `dst`, keeping `src` whole."""
        options = [u for u in members[src] if any(group_of[v] == dst for v in neighbours[u])]
        options.sort(key=lambda u: (delta(u, src, dst), u))  # ties by name: the same start every time
        for u in options:
            if stays_connected(src, u):
                move(u, dst)
                return u
        return None

    def chain() -> bool:
        """A group short of (or past) its rules takes (or gives) a unit through a
        path of groups, each passing one on, so that a group with room to
        spare, however far, makes up the difference."""
        adjacent = {z: set() for z in groups}
        for u in units:
            for v in neighbours[u]:
                if group_of[u] != group_of[v]:
                    adjacent[group_of[u]].add(group_of[v])
        now = total()
        for target in sorted(groups, key=lambda z: -sum(breach(i, value[i]) for i in own[z])):
            if sum(breach(i, value[i]) for i in own[target]) <= 1e-9:
                break
            parent = {target: None}
            queue = deque([target])
            while queue:
                g = queue.popleft()
                for h in sorted(adjacent[g]):
                    if h in parent:
                        continue
                    parent[h] = g
                    queue.append(h)
                    path = [h]
                    while parent[path[-1]] is not None:
                        path.append(parent[path[-1]])
                    # path: h ... target. Pull toward the target, then push away from it.
                    for steps in (list(zip(path, path[1:])), [(b, a) for a, b in reversed(list(zip(path, path[1:])))]):
                        done = []
                        for src, dst in steps:
                            u = shift(src, dst)
                            if u is None:
                                break
                            done.append((u, src))
                        if len(done) == len(steps) and total() < now - 1e-9:
                            return True
                        for u, src in reversed(done):
                            move(u, src)
        return False

    descend()
    while total() > 1e-9 and time.monotonic() < limit and chain():
        moves += 1
        descend()

    # 4. Complete: assignments, a root per group, and the flows of a spanning tree.
    hint: dict[VarKey, int] = {key: int(group_of[u] == z) for (u, z), key in x.items()}
    n_arcs = {(a, b) for a in units for b in neighbours[a]}
    for z in groups:
        for u in units:
            hint[(ROOT, (rule_id, u, z))] = 0
        for a, b in n_arcs:
            hint[(FLOW, (rule_id, a, b, z))] = 0
        inside = members[z]
        if not inside:
            continue
        root = min(inside, key=lambda u: (cost[(u, z)], u))
        hint[(ROOT, (rule_id, root, z))] = 1
        parent: dict[str, str | None] = {root: None}
        order, queue = [root], deque([root])
        while queue:
            u = queue.popleft()
            for v in sorted(neighbours[u]):
                if v in inside and v not in parent:
                    parent[v] = u
                    order.append(v)
                    queue.append(v)
        below = {u: 1 for u in order}
        for u in reversed(order):
            if parent[u] is not None:
                below[parent[u]] += below[u]
                hint[(FLOW, (rule_id, parent[u], u, z))] = below[u]
    total_breach = sum(breach(i, value[i]) for i in range(len(rows)))
    goal = sum(cost[(u, z)] for u, z in group_of.items())
    goal = goal if compiled.sense == "minimize" else -goal
    return {k: v for k, v in hint.items() if k in compiled.variables}, {
        "rule": rule_id, "units": len(units), "groups": len(groups), "moves": moves,
        "breach": round(total_breach, 6), "feasible": total_breach <= 1e-6, "objective": round(goal + float(compiled.objective.const), 6),
        "seconds": round(time.monotonic() - began, 3)}


def as_answer(compiled: Compiled, hint: dict[VarKey, int], solver: str, seconds: float) -> "Solution":
    """The start itself, when the solver ended with nothing better: every row
    holds at it, so it is an answer -- a feasible one, with no bound and no claim."""
    from app.solve.result import Solution

    objective = compiled.objective.evaluated_at(hint) + sum(
        c * hint.get(a, 0) * hint.get(b, 0) for (a, b), c in compiled.objective_quadratic.items())
    value = int(objective) if objective == int(objective) else float(objective)
    return Solution("feasible", False, value, dict(hint), seconds, solver)
