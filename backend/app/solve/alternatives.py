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

**How far apart.** `min_changes` asks each plan to differ from every other
in at least that many decisions (the cut's right-hand side), so the list is
not five copies of the best with one switch flipped.

**Whole numbers.** A whole-number decision with finite bounds counts as
changed when it moves by at least one. Each listed answer `x*` gets two
helper switches per such decision (`__alt_up`, `__alt_dn`), each forcing
`x >= x* + 1` or `x <= x* - 1` when on, and the cut counts them beside the
yes-or-no terms.

**What it does not do.** Quantities have infinitely many near neighbours,
and a whole number with no bound has no big-M to write the switch with, so
neither counts towards distinctness: a model with no yes-or-no and no
bounded whole-number decision is refused with that reason. A goal that multiplies decisions is
refused too -- the gap row is written on a linear goal.

**Goals in order (lexicographic).** Each goal gets its own gap row, held within `within` of the value
it has in the best answer, so an alternative may give up a little on any goal but never trade the
first goal away for the second; the solve itself stays term by term (improvement plan 0.3).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Callable

from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.result import Solution

ROW_ID = "__alternative"
UP, DOWN = "__alt_up", "__alt_dn"
MAX_ALTERNATIVES = 20
MAX_WITHIN = 1.0
MAX_MIN_CHANGES = 50
#: A whole-number decision wider than this is left out: its switch's big-M
#: would make the relaxation too weak to be worth solving.
MAX_RANGE = Decimal(1_000_000)


class NotApplicable(Exception):
    """Why this model has no alternatives to list, in words a planner reads."""


@dataclass(frozen=True)
class Alternative:
    seq: int
    solution: Solution
    #: How many decisions (yes-or-no, or bounded whole numbers) differ from the best answer.
    changed: int


def decisions(compiled: Compiled) -> list[Any]:
    """The model's own yes-or-no decisions -- not the compiler's helpers."""
    return [key for key, var in compiled.variables.items() if var.domain == "binary" and not key[0].startswith("__")]


def whole_numbers(compiled: Compiled) -> list[Any]:
    """The model's own whole-number decisions whose bounds give a switch its big-M."""
    return [
        key for key, var in compiled.variables.items()
        if var.domain == "integer" and not key[0].startswith("__") and not var.default_upper
        and var.lower.is_finite() and var.upper.is_finite() and var.upper - var.lower <= MAX_RANGE
    ]


def admissible(compiled: Compiled) -> None:
    """Raise `NotApplicable` with the reason, or return for a model it can serve."""
    if compiled.objective_mode == "lex" and not compiled.objective_terms:
        raise NotApplicable("the goals are solved in order, but the model has no goal terms to hold")
    if compiled.objective_quadratic:
        raise NotApplicable("the goal multiplies decisions together, and the gap is written on a linear goal")
    if not decisions(compiled) and not whole_numbers(compiled):
        raise NotApplicable(
            "the model has no yes-or-no decisions and no bounded whole-number ones, "
            "so its answers are not told apart one by one"
        )


def bound(best: float, within: float, sense: str) -> Decimal:
    """The goal's worst allowed value: `within` of the best, relative to its
    size (and absolute below 1, so a best of 0 still allows something)."""
    slack = Decimal(repr(within)) * max(Decimal(1), abs(Decimal(repr(best))))
    value = Decimal(repr(best))
    return value + slack if sense == "minimize" else value - slack


def _whole(value: Any) -> int:
    return int(round(float(value)))


def cut(keys: list[Any], answer: dict[Any, Any], need: int = 1) -> Constraint:
    """The row that asks for at least `need` of the yes-or-no decisions to
    differ from this answer; with `need` 1, it forbids exactly that combination."""
    coeffs: dict[Any, Decimal] = {}
    ones = 0
    for key in keys:
        if int(round(float(answer.get(key, 0)))) == 1:
            coeffs[key] = Decimal(-1)
            ones += 1
        else:
            coeffs[key] = Decimal(1)
    # sum(1 - x) over the ones + sum(x) over the zeros >= 1
    return Constraint(ROW_ID, {"cut": "no-good"}, Linear(coeffs=coeffs, const=Decimal(ones)), ">=", Linear(const=Decimal(need)))


def differs(
    compiled: Compiled, keys: list[Any], integers: list[Any], answer: dict[Any, Any], need: int, tag: int,
) -> tuple[dict[Any, Variable], list[Constraint]]:
    """What asks the next plan to differ from `answer` in at least `need`
    decisions: the helper switches for the whole numbers, their rows, and the
    counting row. `tag` keeps each answer's switches apart."""
    row = cut(keys, answer, need)
    helpers: dict[Any, Variable] = {}
    rows: list[Constraint] = []
    for i, key in enumerate(integers):
        var = compiled.variables[key]
        value = Decimal(_whole(answer.get(key, 0)))
        if value < var.upper:
            up = (UP, (str(tag), str(i)))
            helpers[up] = Variable(up, "binary", Decimal(0), Decimal(1))
            # x >= lower + (x* + 1 - lower) * up
            rows.append(Constraint(ROW_ID, {"cut": "moved-up"},
                                   Linear({key: Decimal(1), up: -(value + 1 - var.lower)}), ">=", Linear(const=var.lower)))
            row.left.coeffs[up] = Decimal(1)
        if value > var.lower:
            down = (DOWN, (str(tag), str(i)))
            helpers[down] = Variable(down, "binary", Decimal(0), Decimal(1))
            # x <= upper - (upper - x* + 1) * down
            rows.append(Constraint(ROW_ID, {"cut": "moved-down"},
                                   Linear({key: Decimal(1), down: var.upper - value + 1}), "<=", Linear(const=var.upper)))
            row.left.coeffs[down] = Decimal(1)
    return helpers, [*rows, row]


def gap_rows(compiled: Compiled, best: Solution, within: float, relation: str) -> list[Constraint]:
    """The rows holding the goal near the best: one on a weighted goal, one per goal when they are
    solved in order -- each at the value that goal has in the best answer."""
    if compiled.objective_mode == "lex" and compiled.objective_terms:
        rows = []
        for i, term in enumerate(compiled.objective_terms):
            value = float(term.evaluated_at(best.assignments))
            limit = bound(value, within, compiled.sense)
            if compiled.is_integral:
                # A whole-number goal takes no value in between: rounding inwards is exact, and keeps
                # the model whole for cp-sat and the stage freezes that follow.
                import math

                limit = Decimal(math.floor(limit) if relation == "<=" else math.ceil(limit))
            rows.append(Constraint(ROW_ID, {"cut": "gap", "goal": str(i)}, term.copy(), relation,
                                   Linear(const=limit)))
        return rows
    limit = bound(float(best.objective), within, compiled.sense)
    return [Constraint(ROW_ID, {"cut": "gap"}, compiled.objective.copy(), relation, Linear(const=limit))]


def changed_between(keys: list[Any], a: dict[Any, Any], b: dict[Any, Any]) -> int:
    return sum(1 for key in keys if _whole(a.get(key, 0)) != _whole(b.get(key, 0)))


def find(
    compiled: Compiled,
    solve: Callable[[Compiled, float], Solution],
    best: Solution,
    *,
    count: int,
    within: float,
    time_limit: float,
    min_changes: int = 1,
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
    if not 1 <= min_changes <= MAX_MIN_CHANGES:
        raise NotApplicable(f"plans differ in 1 to {MAX_MIN_CHANGES} decisions")
    if best.objective is None or not best.assignments:
        raise NotApplicable("there is no best answer to list alternatives to")
    keys = decisions(compiled)
    integers = whole_numbers(compiled)
    if min_changes > len(keys) + len(integers):
        raise NotApplicable(
            f"the model has {len(keys) + len(integers)} decisions to tell plans apart by, fewer than {min_changes}"
        )
    relation = "<=" if compiled.sense == "minimize" else ">="
    variables = dict(compiled.variables)
    rows = gap_rows(compiled, best, within, relation)

    def apart_from(answer: dict[Any, Any], tag: int) -> None:
        helpers, more = differs(compiled, keys, integers, answer, min_changes, tag)
        variables.update(helpers)
        rows.extend(more)

    apart_from(best.assignments, 0)
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
        model = replace(compiled, variables=dict(variables), constraints=[*compiled.constraints, *rows])
        answer = solve(model, share)
        if answer.status not in ("optimal", "feasible") or not answer.assignments:
            break
        changed = changed_between([*keys, *integers], answer.assignments, best.assignments)
        # The helper switches are the search's own; the plan is the model's decisions.
        plan = {key: value for key, value in answer.assignments.items() if key[0] not in (UP, DOWN)}
        found.append(Alternative(seq, replace(answer, assignments=plan), changed))
        apart_from(answer.assignments, seq)
    return found
