"""A network lane: a model that is a network, solved as one (queue R15a).

Transportation, assignment, shortest paths, maximum flow and every mix of
them share one shape: each decision is the flow on an arc, and each rule
says what flows into a place less what flows out of it. Such a model's
rule matrix is *totally unimodular*: its LP optimum is whole wherever the
data are, so a network algorithm proves the same optimum a MIP solver does
-- only by walking the network instead of branching. OR-Tools'
`SimpleMinCostFlow` does min-cost flow, and max flow, assignment and
shortest paths are all min-cost flows, so one algorithm serves them all.

**When it applies** -- read off the compiled model, never assumed:

- every rule linear and plain (no `when`, schedule, curve, function or product),
  with every coefficient +1 or -1;
- each decision in at most two rules, and after turning some rules round
  (multiplying by -1: the "supply" side of an assignment) in the one with +1
  (the flow arrives) and the other with -1 (it leaves). Turning round is a
  two-colouring, checked, not guessed;
- every number whole: bounds, right-hand sides and goal coefficients (min-cost
  flow works in integers; a fractional model is left to the solvers);
- every lower bound finite.

A rule on a single decision (`flow[a] <= cap[a]`) is read as that decision's
bound, not as a place, so a capacity written as a rule keeps the network.

A decision in one rule is an arc to or from an outside node; a `<=` or `>=`
rule gets a free arc to the outside for its slack. The answer is proven:
`optimal` claims `global`, and `infeasible` is a proof too. A decision with
no declared upper bound whose flow could grow without end makes the model
unbounded. Behind the setting `solve.network` (on), and used only when some
decision takes whole numbers: a MIP solver would branch there (CP-SAT runs
out of memory on a 400 x 400 assignment this proves in a second), while on a
continuous network an LP solver is nearly as quick and also gives shadow
prices, which min-cost flow does not (bench/results/2026-09-25-network.md).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, VarKey


@dataclass
class Networked:
    solution: Any
    record: dict[str, Any]


def _whole(value: Decimal) -> bool:
    return value == value.to_integral_value()


def _shape(compiled: Compiled):
    """(rows, flips, columns) of the model read as a network, or why it is not one."""
    if compiled.objective_quadratic:
        return "the goal multiplies decisions together"
    if compiled.pwl or compiled.functions or compiled.intervals:
        return "the model has curves, functions or time intervals"
    if compiled.objective_mode == "lex":
        return "goals in order are solved one after another"
    if any(not _whole(v) for v in compiled.objective.coeffs.values()):
        return "a goal coefficient is fractional"
    # Bounds: declared, then tightened by every rule on a single decision (a capacity written as a rule).
    lower = {k: v.lower for k, v in compiled.variables.items()}
    upper = {k: (None if v.default_upper else v.upper) for k, v in compiled.variables.items()}
    broken: str | None = None
    rows: list[tuple[dict[VarKey, int], str, int]] = []
    for c in compiled.constraints:
        if c.when is not None or getattr(c, "schedule", None) is not None or c.quadratic:
            return f"the rule {c.id!r} is not a plain linear rule"
        coeffs: dict[VarKey, Decimal] = {}
        for k, v in c.left.coeffs.items():
            coeffs[k] = coeffs.get(k, Decimal(0)) + v
        for k, v in c.right.coeffs.items():
            coeffs[k] = coeffs.get(k, Decimal(0)) - v
        coeffs = {k: v for k, v in coeffs.items() if v}
        rhs = c.right.const - c.left.const
        if not coeffs:
            holds = {"<=": 0 <= rhs, ">=": 0 >= rhs}.get(c.relation, rhs == 0)
            broken = broken or (None if holds else c.id)
            continue
        if len(coeffs) == 1:
            (k, a), = coeffs.items()
            bound = rhs / a
            relation = c.relation if a > 0 else {"<=": ">=", ">=": "<="}.get(c.relation, c.relation)
            if relation in ("<=", "=") and (upper[k] is None or bound < upper[k]):
                upper[k] = bound
            if relation in (">=", "=") and bound > lower[k]:
                lower[k] = bound
            continue
        if any(abs(v) != 1 for v in coeffs.values()):
            return f"the rule {c.id!r} weighs a decision by more than one"
        if not _whole(rhs):
            return f"the rule {c.id!r} has a fractional right-hand side"
        rows.append(({k: int(v) for k, v in coeffs.items()}, c.relation, int(rhs)))
    for key in compiled.variables:
        if abs(lower[key]) >= Decimal("1e15"):
            return f"{key[0]!r} has no lower bound"
        if not _whole(lower[key]) or (upper[key] is not None and not _whole(upper[key])):
            return f"{key[0]!r} has a fractional bound"
    if not rows:
        return "no rule joins two decisions: there is no network to walk"
    columns: dict[VarKey, list[tuple[int, int]]] = {k: [] for k in compiled.variables}
    for i, (coeffs, _, _) in enumerate(rows):
        for k, v in coeffs.items():
            columns[k].append((i, v))
    over = next((k for k, where in columns.items() if len(where) > 2), None)
    if over is not None:
        return f"{over[0]!r} is in more than two rules"
    # Turn rows round so each two-rule decision has +1 in one and -1 in the other:
    # the same sign in both asks for opposite turns, opposite signs for the same.
    links: dict[int, list[tuple[int, int]]] = {i: [] for i in range(len(rows))}
    for where in columns.values():
        if len(where) == 2:
            (a, va), (b, vb) = where
            parity = 1 if va == vb else 0
            links[a].append((b, parity))
            links[b].append((a, parity))
    flip: dict[int, int] = {}
    for start in range(len(rows)):
        if start in flip:
            continue
        flip[start] = 0
        queue = deque([start])
        while queue:
            a = queue.popleft()
            for b, parity in links[a]:
                want = flip[a] ^ parity
                if b not in flip:
                    flip[b] = want
                    queue.append(b)
                elif flip[b] != want:
                    return "its rules cannot all be read as flow in less flow out"
    bounds = {k: (int(lower[k]), None if upper[k] is None else int(upper[k])) for k in compiled.variables}
    return rows, flip, columns, bounds, broken


def applies(compiled: Compiled) -> str | None:
    shape = _shape(compiled)
    return shape if isinstance(shape, str) else None


def solve(compiled: Compiled) -> Networked:
    """The proven optimum by min-cost flow, or a proof that there is none."""
    from ortools.graph.python import min_cost_flow

    from app.solve.result import Solution

    started = time.monotonic()
    shape = _shape(compiled)
    if isinstance(shape, str):
        raise ValueError(shape)
    rows, flip, columns, bounds, broken = shape
    if broken is not None:
        return _none(compiled, started, "infeasible", {"kind": "min-cost flow", "why": f"the rule {broken!r} reads no decision and does not hold"})
    outside = len(rows)
    sign = 1 if compiled.sense == "minimize" else -1
    # Row i, turned: sum(+1 in) - sum(-1 out) (relation) b. Node i must take in b net: supply -b.
    supply = [0] * (len(rows) + 1)
    turned = []
    for i, (_, relation, rhs) in enumerate(rows):
        if flip[i]:
            relation, rhs = {"<=": ">=", ">=": "<="}.get(relation, relation), -rhs
        turned.append(relation)
        supply[i] -= rhs
        supply[outside] += rhs
    # Whatever flow a model could need, and more: a decision with no declared ceiling gets this.
    unbounded_cap = sum(abs(v) for v in supply) + sum(
        abs(hi - lo) + abs(lo) for lo, hi in bounds.values() if hi is not None) + 1
    arcs: list[tuple[VarKey | None, int, int, int, int, int]] = []  # key, tail, head, lower, capacity, cost
    for key, where in columns.items():
        signed = [(i, v * (-1 if flip[i] else 1)) for i, v in where]
        head = next((i for i, v in signed if v > 0), outside)
        tail = next((i for i, v in signed if v < 0), outside)
        if head == tail:  # in no rule: an arc from outside to outside, set by its cost alone
            head = tail = outside
        lower, upper = bounds[key]
        capacity = unbounded_cap if upper is None else upper - lower
        if capacity < 0:
            return _none(compiled, started, "infeasible", {"why": f"{key[0]!r} has its upper bound below its lower"})
        arcs.append((key, tail, head, lower, capacity, sign * int(compiled.objective.coeffs.get(key, 0))))
    for i, relation in enumerate(turned):
        # Slack: a `<=` rule may take in less (flow from outside), a `>=` rule more (flow to outside).
        if relation == "<=":
            arcs.append((None, outside, i, 0, unbounded_cap, 0))
        elif relation == ">=":
            arcs.append((None, i, outside, 0, unbounded_cap, 0))
    flow = min_cost_flow.SimpleMinCostFlow()
    handles, fixed_cost, loops = [], 0, []
    for key, tail, head, lower, capacity, cost in arcs:
        # A lower bound moves `lower` along the arc before anything is solved.
        supply[tail] -= lower
        supply[head] += lower
        fixed_cost += cost * lower
        if tail == head:
            loops.append((key, lower, capacity, cost))
            continue
        handles.append((flow.add_arc_with_capacity_and_unit_cost(tail, head, capacity, cost), key, lower, capacity))
    for node, value in enumerate(supply):
        flow.set_node_supply(node, value)
    record = {"kind": "min-cost flow", "nodes": len(rows) + 1, "arcs": len(handles) + len(loops),
              "turned_rules": sum(flip.values())}
    status = flow.solve()
    if status == flow.INFEASIBLE:
        return _none(compiled, started, "infeasible", record)
    if status != flow.OPTIMAL:
        return _none(compiled, started, "unknown", {**record, "why": f"min-cost flow ended {status}"})
    assignments: dict[VarKey, int] = {}
    for arc, key, lower, capacity in handles:
        value = flow.flow(arc)
        if key is not None and bounds[key][1] is None and value >= unbounded_cap and flow.unit_cost(arc) < 0:
            return _none(compiled, started, "unbounded", {**record, "why": f"{key[0]!r} can grow without end"})
        if key is not None:
            assignments[key] = lower + value
    for key, lower, capacity, cost in loops:
        if cost < 0 and bounds[key][1] is None:
            return _none(compiled, started, "unbounded", {**record, "why": f"{key[0]!r} can grow without end"})
        assignments[key] = lower + (capacity if cost < 0 else 0)
    objective = float(compiled.objective.evaluated_at(assignments))
    value = int(objective) if objective == int(objective) else objective
    return Networked(Solution(status="optimal", optimal=True, objective=value, assignments=assignments,
                              wall_seconds=round(time.monotonic() - started, 3),
                              solver="network (min-cost flow, OR-Tools)", best_bound=value), record)


def _none(compiled: Compiled, started: float, status: str, record: dict[str, Any]) -> Networked:
    from app.solve.result import Solution

    return Networked(Solution(status=status, optimal=False, objective=None, assignments={},
                              wall_seconds=round(time.monotonic() - started, 3),
                              solver="network (min-cost flow, OR-Tools)"), record)
