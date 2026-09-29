"""Alternative plans: the next-best distinct answers within a gap (Epic engine, E-1).

A planner shown one optimal roster often asks what else would do almost as
well -- to pick one that suits people the model knows nothing about. This
finds them: after the best answer, the best answer that differs from it in
at least one yes-or-no decision, then the best that differs from both, and so
on, each held to within `within` of the best value. In the order found they
are the k best distinct plans, each proven best among those not yet listed
when its solve proves optimality.

**How.** One row per answer found, a *no-good cut* that forbids exactly that
combination of the yes-or-no decisions::

    sum over x with x* = 1 of (1 - x)  +  sum over x with x* = 0 of x  >=  1

and one row holding the goal within the gap of the best. Rows the compiler
writes itself are named `__alternative` and never reach `constraint_result`.

**What it does not do.** Decisions that are quantities or whole numbers
beyond yes-or-no have infinitely many (or very many) near neighbours, so
distinctness is judged on the yes-or-no decisions only: a model with none is
refused with that reason. A lexicographic goal or one that multiplies
decisions is refused too -- the gap row is written on a linear goal.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Callable

from app.solve.compile import Compiled, Constraint, Linear
from app.solve.result import Solution

ROW_ID = "__alternative"
MAX_ALTERNATIVES = 20
MAX_WITHIN = 1.0


class NotApplicable(Exception):
    """Why this model has no alternatives to list, in words a planner reads."""


@dataclass(frozen=True)
class Alternative:
    seq: int
    solution: Solution
    #: How many yes-or-no decisions differ from the best answer.
    changed: int


def decisions(compiled: Compiled) -> list[Any]:
    """The model's own yes-or-no decisions -- not the compiler's helpers."""
    return [key for key, var in compiled.variables.items() if var.domain == "binary" and not key[0].startswith("__")]


def admissible(compiled: Compiled) -> None:
    """Raise `NotApplicable` with the reason, or return for a model it can serve."""
    if compiled.objective_mode == "lex":
        raise NotApplicable("alternatives are listed for a weighted goal; this one is solved term by term")
    if compiled.objective_quadratic:
        raise NotApplicable("the goal multiplies decisions together, and the gap is written on a linear goal")
    if not decisions(compiled):
        raise NotApplicable("the model has no yes-or-no decisions, so its answers are not told apart one by one")


def bound(best: float, within: float, sense: str) -> Decimal:
    """The goal's worst allowed value: `within` of the best, relative to its
    size (and absolute below 1, so a best of 0 still allows something)."""
    slack = Decimal(repr(within)) * max(Decimal(1), abs(Decimal(repr(best))))
    value = Decimal(repr(best))
    return value + slack if sense == "minimize" else value - slack


def cut(keys: list[Any], answer: dict[Any, Any]) -> Constraint:
    """The row that forbids exactly this combination of the decisions."""
    coeffs: dict[Any, Decimal] = {}
    ones = 0
    for key in keys:
        if int(round(float(answer.get(key, 0)))) == 1:
            coeffs[key] = Decimal(-1)
            ones += 1
        else:
            coeffs[key] = Decimal(1)
    # sum(1 - x) over the ones + sum(x) over the zeros >= 1
    return Constraint(ROW_ID, {"cut": "no-good"}, Linear(coeffs=coeffs, const=Decimal(ones)), ">=", Linear(const=Decimal(1)))


def find(
    compiled: Compiled,
    solve: Callable[[Compiled, float], Solution],
    best: Solution,
    *,
    count: int,
    within: float,
    time_limit: float,
    should_stop: Callable[[], bool] | None = None,
) -> list[Alternative]:
    """Up to `count` alternatives to `best`, best first. Each solve gets an
    equal share of the time left; the search ends early when none is left
    within the gap (the next solve is infeasible) or the clock runs out."""
    admissible(compiled)
    if not 1 <= count <= MAX_ALTERNATIVES:
        raise NotApplicable(f"between 1 and {MAX_ALTERNATIVES} alternatives are listed")
    if not 0 <= within <= MAX_WITHIN:
        raise NotApplicable("the gap is a share of the best value, from 0 to 1")
    if best.objective is None or not best.assignments:
        raise NotApplicable("there is no best answer to list alternatives to")
    keys = decisions(compiled)
    limit = bound(float(best.objective), within, compiled.sense)
    relation = "<=" if compiled.sense == "minimize" else ">="
    rows = [
        Constraint(ROW_ID, {"cut": "gap"}, compiled.objective.copy(), relation, Linear(const=limit)),
        cut(keys, best.assignments),
    ]
    import time

    started = time.monotonic()
    found: list[Alternative] = []
    for seq in range(1, count + 1):
        if should_stop is not None and should_stop():
            break
        left = time_limit - (time.monotonic() - started)
        if left <= 0.5:
            break
        share = max(0.5, left / (count - seq + 1))
        model = replace(compiled, constraints=[*compiled.constraints, *rows])
        answer = solve(model, share)
        if answer.status not in ("optimal", "feasible") or not answer.assignments:
            break
        changed = sum(
            1 for key in keys
            if int(round(float(answer.assignments.get(key, 0)))) != int(round(float(best.assignments.get(key, 0))))
        )
        found.append(Alternative(seq, answer, changed))
        rows.append(cut(keys, answer.assignments))
    return found
