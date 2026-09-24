"""A proven bound from Lagrangian relaxation of the linking rules (queue R5).

On a large model a solver often ends with a good answer and a weak bound: a
wide gap that says little. A near-separable model (`blocks.structure`, R4)
is many small models tied together by a few rules. Take those rules out and
charge the goal for breaking them instead -- a price per rule instance, its
multiplier -- and what is left falls apart into blocks that solve easily.
The best value of that relaxed model is a bound on the real one, for any
prices of the right sign; searching the prices (subgradient steps towards
the answer in hand) tightens it. The bound is reported beside the answer,
and the gap with it: never a claim the answer is best unless they meet.

Signs, for a goal read in its own direction (`σ` = +1 to minimize, -1 to
maximize): the relaxed goal is `f + σ Σ λ_i (left_i - right_i)` with
`λ_i >= 0` for a `<=` rule, `λ_i <= 0` for `>=`, free for `=`. At any answer
that keeps the rules each added term helps the goal, so the relaxed best
is at least as good as the real best: a lower bound when minimizing, an
upper bound when maximizing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Callable

from app.solve.compile import Compiled, Linear

#: The share of the time given to the bound when it applies.
SHARE = 0.25
#: Polyak step scale, halved after this many rounds with no better bound.
THETA_START, PATIENCE = 2.0, 3
#: Each round's solve: a tenth of the bound's time, at least half a second.
ROUND_SHARE, ROUND_MIN_S = 0.1, 0.5


def applies(compiled: Compiled, found: dict[str, Any] | None) -> str | None:
    """None when a Lagrangian bound can be computed, else why not (recorded on the run)."""
    if not found or not found.get("linking_rules"):
        return "the model is not a few blocks tied by a few rules"
    if compiled.objective_mode != "weighted":
        return "a goal in order of importance has no single bound"
    if compiled.objective_quadratic or compiled.functions:
        return "the goal or a rule is not linear"
    if compiled.penalty_of or compiled.violations:
        return "soft rules' penalties are settled against the whole goal"
    return None


def linking_rows(compiled: Compiled, found: dict[str, Any]) -> list[int]:
    """The rule instances that tie the blocks: those reading decisions of two groups of `found["by"]`."""
    from app.solve.blocks import _is_decision, _row_keys

    by = found["by"]

    def group(key):
        index = compiled.var_index_sets.get(key[0], [])
        return key[1][index.index(by)] if by in index and len(key[1]) > index.index(by) else None

    rows = []
    for i, rule in enumerate(compiled.constraints):
        groups = {g for g in (group(k) for k in _row_keys(compiled, i) if _is_decision(k)) if g is not None}
        if len(groups) > 1 and not rule.quadratic and rule.when is None and rule.schedule is None:
            rows.append(i)
    return rows


def relaxed(compiled: Compiled, rows: list[int], prices: dict[int, float]) -> Compiled:
    """The model without `rows`, its goal charged `σ λ_i (left_i - right_i)` for each."""
    sigma = Decimal(1 if compiled.sense == "minimize" else -1)
    coeffs = dict(compiled.objective.coeffs)
    const = compiled.objective.const
    for i in rows:
        price = Decimal(str(prices.get(i, 0.0)))
        if price == 0:
            continue
        rule = compiled.constraints[i]
        weight = sigma * price
        for key, c in rule.left.coeffs.items():
            coeffs[key] = coeffs.get(key, Decimal(0)) + weight * c
        for key, c in rule.right.coeffs.items():
            coeffs[key] = coeffs.get(key, Decimal(0)) - weight * c
        const += weight * (rule.left.const - rule.right.const)
    dropped = set(rows)
    goal = Linear(coeffs={k: c for k, c in coeffs.items() if c != 0}, const=const)
    return replace(compiled, constraints=[c for i, c in enumerate(compiled.constraints) if i not in dropped],
                   objective=goal, objective_terms=[goal], symmetry=[])


def _project(price: float, relation: str) -> float:
    if relation == "<=":
        return max(0.0, price)
    if relation == ">=":
        return min(0.0, price)
    return price


def _better(a: float, b: float | None, sense: str) -> bool:
    return b is None or (a > b if sense == "minimize" else a < b)


@dataclass
class Bounded:
    #: The best bound found, in the goal's own direction, or None.
    bound: float | None
    record: dict[str, Any]


def search(compiled: Compiled, rows: list[int], run: Callable[[Compiled, float], Any], *, answer: float | None,
           time_limit: float, should_stop: Callable[[], bool] | None = None, clock=time.monotonic) -> Bounded:
    """Subgradient search over the prices. `run(model, seconds) -> Solution` solves a relaxed model;
    a round counts only when that solve's own bound is known (its optimum, or its proven bound)."""
    started = clock()
    prices = {i: 0.0 for i in rows}
    best: float | None = None
    theta, stale, rounds = THETA_START, 0, 0
    while not (should_stop and should_stop()):
        left = time_limit - (clock() - started)
        if left < ROUND_MIN_S:
            break
        model = relaxed(compiled, rows, prices)
        solved = run(model, min(left, max(ROUND_MIN_S, ROUND_SHARE * time_limit)))
        rounds += 1
        value = solved.best_bound if solved.best_bound is not None else (
            solved.objective if solved.status == "optimal" else None)
        if value is None or not solved.assignments:
            break
        value = float(value)
        if _better(value, best, compiled.sense):
            best, stale = value, 0
        else:
            stale += 1
            if stale >= PATIENCE:
                theta, stale = theta / 2, 0
        # The rules' breach at this answer: the direction that tightens the bound.
        g = {i: float(compiled.constraints[i].left.evaluated_at(solved.assignments)
                      - compiled.constraints[i].right.evaluated_at(solved.assignments)) for i in rows}
        norm = sum(v * v for v in g.values())
        if norm == 0 or answer is None:
            break  # the relaxed answer keeps every linking rule: the bound cannot move further this way
        step = theta * max(abs(float(answer) - value), 1e-6) / norm
        prices = {i: _project(prices[i] + step * g[i], compiled.constraints[i].relation) for i in rows}
    return Bounded(best, {"rounds": rounds, "linking_rules": len(rows), "bound": best,
                          "seconds": round(clock() - started, 3)})
