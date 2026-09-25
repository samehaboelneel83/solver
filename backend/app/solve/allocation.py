"""An exact decomposition for resource allocation: separable convex pieces tied by one rule (queue R12).

The decomposition gate (`bench.decompose_gate`) found one family the solvers
cannot close: `load_balance` at 5,000 people -- a sum of squares to spread
hours evenly, each person within their own bounds, and one rule tying them
all (the hours add up to a total). HiGHS proves 1,000 people in a second and
5,000 in no time it was given; SCIP, likewise nothing. It is the textbook case
for decomposing by the linking rule (Dantzig-Wolfe / Lagrangian, which are
exact here: the problem is convex, so there is no duality gap):

    minimise  sum_i a_i x_i^2 + b_i x_i
    subject   sum_i w_i x_i  (=, <= or >=)  T,    l_i <= x_i <= u_i,   a_i > 0

Price the linking rule at `lam`; each piece then solves alone, in closed form:
`x_i(lam) = clamp((lam w_i - b_i) / (2 a_i), l_i, u_i)`, and `sum w_i x_i(lam)`
never falls as `lam` rises -- so bisection finds the `lam` that meets `T`.
The Lagrangian value at any `lam` of the right sign is a **lower bound** on
the optimum (weak duality), and at the `lam` found it equals the answer: the
answer is proven, with its bound recorded like any other solver's.

**When it applies** -- checked on the compiled model, never assumed: every
decision continuous; the goal a sum of squares (no cross terms, each square's
coefficient positive once the goal is read as a minimisation) plus a linear
part; exactly one rule reading more than one decision; every other rule on a
single decision (a bound). Anything else is left to the solvers, and the run
says why. Behind the setting `solve.decompose`, whose default the bench
decides (bench/results/2026-09-25-decomposition.md).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, VarKey

#: Bisection stops when the linking rule is met to this share of its right-hand side ...
TOLERANCE = 1e-10
#: ... or after this many halvings.
MAX_STEPS = 200


@dataclass
class _Shape:
    a: dict[VarKey, float]
    b: dict[VarKey, float]
    lower: dict[VarKey, float]
    upper: dict[VarKey, float]
    weight: dict[VarKey, float]
    relation: str
    total: float
    rule: str
    sign: float  # +1 to minimise; -1 when a maximisation was read as its negation
    constant: float


def _shape(compiled: Compiled) -> _Shape | str:
    """The model read as a resource allocation, or why it is not one."""
    if compiled.objective_mode != "weighted":
        return "a goal in order of importance"
    if compiled.pwl or compiled.functions or compiled.intervals or compiled.penalty_of or compiled.violations:
        return "curves, functions, intervals or soft rules"
    if any(var.is_integral for var in compiled.variables.values()):
        return "a whole-number decision"
    sign = 1.0 if compiled.sense == "minimize" else -1.0
    a: dict[VarKey, float] = {key: 0.0 for key in compiled.variables}
    for (x, y), coeff in compiled.objective_quadratic.items():
        if x != y:
            return "the goal multiplies two different decisions"
        a[x] += sign * float(coeff)
    b = {key: sign * float(compiled.objective.coeffs.get(key, Decimal(0))) for key in compiled.variables}
    lower = {key: float(var.lower) for key, var in compiled.variables.items()}
    upper = {key: float(var.upper) for key, var in compiled.variables.items()}
    linking = None
    for rule in compiled.constraints:
        if rule.quadratic or rule.when is not None or rule.schedule is not None:
            return "a conditional, scheduling or quadratic rule"
        coeffs = {k: float(rule.left.coeffs.get(k, 0)) - float(rule.right.coeffs.get(k, 0))
                  for k in {*rule.left.coeffs, *rule.right.coeffs}}
        coeffs = {k: c for k, c in coeffs.items() if c != 0}
        rhs = float(rule.right.const) - float(rule.left.const)
        if len(coeffs) > 1:
            if linking is not None:
                return "more than one rule ties decisions together"
            linking = (rule, coeffs, rhs)
            continue
        if not coeffs:
            holds = {"<=": 0 <= rhs, ">=": 0 >= rhs}.get(rule.relation, abs(rhs) < 1e-12)
            if not holds:
                return "a rule with no decision in it cannot hold"
            continue
        # A rule on one decision is a bound on it.
        (key, c), = coeffs.items()
        value = rhs / c
        relation = rule.relation if c > 0 else {"<=": ">=", ">=": "<="}.get(rule.relation, rule.relation)
        if relation in ("<=", "="):
            upper[key] = min(upper[key], value)
        if relation in (">=", "="):
            lower[key] = max(lower[key], value)
    if linking is None:
        return "no rule ties the decisions together (it is separable: solved block by block already)"
    rule, weight, total = linking
    for key in weight:
        if a[key] <= 0:
            return f"the goal does not curve upward in {key[0]} (the rule ties it, so it needs a square)"
    if any(lower[k] > upper[k] + 1e-12 for k in compiled.variables):
        return "a decision's bounds leave it no value"
    return _Shape(a, b, lower, upper, weight, rule.relation, total, rule.id, sign,
                  sign * float(compiled.objective.const))


def applies(compiled: Compiled) -> str | None:
    """None when the model is a resource allocation this solves exactly, else why not."""
    found = _shape(compiled)
    return found if isinstance(found, str) else None


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _at(shape: _Shape, lam: float) -> dict[VarKey, float]:
    """Each piece's best at the price `lam` on the linking rule."""
    out = {}
    for key, a in shape.a.items():
        w = shape.weight.get(key, 0.0)
        if a > 0:
            best = (lam * w - shape.b[key]) / (2 * a)
        else:
            # Linear and untied (the linking rule's decisions all have a square): an end of its range.
            best = shape.lower[key] if shape.b[key] - lam * w >= 0 else shape.upper[key]
        out[key] = _clamp(best, shape.lower[key], shape.upper[key])
    return out


def _load(shape: _Shape, x: dict[VarKey, float]) -> float:
    return sum(w * x[k] for k, w in shape.weight.items())


def _value(shape: _Shape, x: dict[VarKey, float]) -> float:
    return sum(shape.a[k] * v * v + shape.b[k] * v for k, v in x.items()) + shape.constant


@dataclass
class Allocated:
    solution: Any
    record: dict[str, Any]


def solve(compiled: Compiled) -> Allocated:
    """The exact optimum by bisection on the linking rule's multiplier, with its dual bound."""
    from app.solve.result import Solution

    started = time.monotonic()
    shape = _shape(compiled)
    if isinstance(shape, str):
        raise ValueError(shape)
    target, relation = shape.total, shape.relation
    free = _at(shape, 0.0)
    load = _load(shape, free)
    record = {"kind": "one linking rule, priced", "rule": shape.rule, "pieces": len(shape.a)}
    # An inequality that holds unpriced needs no price (lam = 0).
    if (relation == "<=" and load <= target) or (relation == ">=" and load >= target):
        x, lam, steps = free, 0.0, 0
    else:
        low_x = {k: shape.lower[k] for k in shape.weight}
        high_x = {k: shape.upper[k] for k in shape.weight}
        reach = sorted([sum(w * (low_x[k] if w > 0 else high_x[k]) for k, w in shape.weight.items()),
                        sum(w * (high_x[k] if w > 0 else low_x[k]) for k, w in shape.weight.items())])
        if target < reach[0] - 1e-9 or target > reach[1] + 1e-9:
            status = "infeasible"
            return Allocated(Solution(status=status, optimal=False, objective=None, assignments={},
                                      wall_seconds=round(time.monotonic() - started, 3), solver="allocation"),
                             {**record, "why": f"the rule {shape.rule!r} cannot be met within the decisions' bounds"})
        # Bracket the price: the load rises with lam.
        lo, hi = -1.0, 1.0
        while _load(shape, _at(shape, lo)) > target:
            lo *= 2
        while _load(shape, _at(shape, hi)) < target:
            hi *= 2
        steps = 0
        scale = max(1.0, abs(target))
        while steps < MAX_STEPS:
            lam = (lo + hi) / 2
            gap = _load(shape, _at(shape, lam)) - target
            if abs(gap) <= TOLERANCE * scale:
                break
            lo, hi = (lam, hi) if gap < 0 else (lo, lam)
            steps += 1
        x = _at(shape, lam)
    objective = _value(shape, x)
    # The Lagrangian at lam is a bound on the optimum (weak duality); at this lam it is the answer.
    bound = objective - lam * (_load(shape, x) - target)
    # A bound never passes the answer: rounding in the last bisection step can put it a hair beyond.
    bound = min(bound, objective)
    # Back in the goal's own direction.
    objective, bound = shape.sign * objective, shape.sign * bound
    assignments = {k: round(v, 9) for k, v in x.items()}
    record.update(multiplier=round(shape.sign * lam, 9), steps=steps)
    return Allocated(Solution(status="optimal", optimal=True, objective=round(objective, 6), assignments=assignments,
                              wall_seconds=round(time.monotonic() - started, 3),
                              solver="allocation (the linking rule priced, each piece in closed form)",
                              best_bound=bound), record)
