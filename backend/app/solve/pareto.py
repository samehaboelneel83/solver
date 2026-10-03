"""Two goals, the trade-off between them: an epsilon-constraint Pareto front.

A model whose goal has two terms -- cost and hours short, say -- has no one
best answer when the terms pull apart; it has a *front*: answers where
neither can improve without the other getting worse. A weighted sum finds
only the points on the front's convex hull, and which ones depends on the
weights; the epsilon-constraint method finds any point, supported or not
(target roadmap Phase 15).

The method, for terms f and g under the goal's sense:

1. The two ends. Best f, then the best g among those (lexicographic, as
   `_solve_lex` does); and best g, then the best f.
2. Between them, `steps - 1` bounds on g spread evenly from one end's g to
   the other's; for each, the best f with g held within the bound, then the
   best g with that f held -- so each point is on the front, not merely
   under it.

Every point is a full answer. The caller records each as a run of its own,
so the chart can link a point to its roster.

**What it does not take.** Exactly two terms, both linear, and hard rules
only: a soft rule's penalty belongs to neither term, so the front would
not say what it shows. A goal outside that is refused by name.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from app.solve.compile import Compiled, Constraint, Linear
from app.solve.result import Solution

DEFAULT_STEPS = 10
MAX_STEPS = 50
_ID = "__pareto"


class NotTwoGoals(ValueError):
    """The model's goal is not what a front is drawn from."""


@dataclass(frozen=True)
class Point:
    first: float
    second: float
    #: The bound on the second term this point was found under; None at an end.
    epsilon: float | None
    #: `optimal` when both of its solves were proven, else `feasible`.
    status: str
    solution: Solution


def admissible(compiled: Compiled) -> None:
    if len(compiled.objective_terms) != 2:
        raise NotTwoGoals(
            f"a trade-off front is between two goals, and this model's goal has "
            f"{len(compiled.objective_terms)} terms"
        )
    if compiled.objective_quadratic:
        raise NotTwoGoals("a trade-off front is drawn for linear goals; this one multiplies decisions")
    if compiled.violations:
        raise NotTwoGoals(
            "a trade-off front needs every rule to be required: a preferred rule's price belongs "
            "to neither goal, so the front would not show what it says"
        )


def front(backend, compiled: Compiled, *, steps: int, time_limit: float, solve) -> list[Point]:
    """The front, ends first then the steps between, duplicates dropped,
    ordered by the first term. `solve(compiled, time_limit)` is one solve
    (`solve_compiled`, bound to the backend and its knobs by the caller)."""
    admissible(compiled)
    sign = Decimal(1) if compiled.sense == "minimize" else Decimal(-1)
    # Each goal its own way, then both minimised (benchmark round 5: "less water" was drawn as "more").
    from app.solve.compile import directed_terms

    f, g = (Linear().add(term, factor=sign) for term in directed_terms(compiled))
    # The bound on the second goal, said on its own scale: turned back when it is "less is better".
    weights = compiled.objective_term_weights
    turned = Decimal(-1) if len(weights) == 2 and weights[1] < 0 else Decimal(1)
    # Two solves per point, the ends included.
    budget = max(1.0, time_limit / (2 * (steps + 1)))

    def best(primary: Linear, secondary: Linear, extra: list[Constraint]) -> tuple[Solution, bool]:
        base = replace(
            compiled,
            objective=primary,
            sense="minimize",
            objective_mode="weighted",
            objective_terms=[],
            objective_term_ids=[],
            objective_quadratic={},
            constraints=[*compiled.constraints, *extra],
        )
        first = solve(base, budget)
        if first.status not in ("optimal", "feasible"):
            return first, False
        value = primary.evaluated_at(first.assignments)
        hold = value if compiled.is_integral else value + max(Decimal("1e-6") * abs(value), Decimal("1e-9"))
        freeze = Constraint(_ID, {}, primary.copy(), "<=", Linear(const=hold))
        second = solve(replace(base, objective=secondary, constraints=[*base.constraints, freeze]), budget)
        if second.status not in ("optimal", "feasible"):
            # The first answer stands; it is only not refined.
            return first, first.status == "optimal"
        return second, first.status == "optimal" and second.status == "optimal"

    points: list[Point] = []

    def keep(solution: Solution, proven: bool, epsilon: float | None) -> None:
        a = compiled.objective_terms[0].evaluated_at(solution.assignments)
        b = compiled.objective_terms[1].evaluated_at(solution.assignments)
        points.append(Point(float(a), float(b), epsilon, "optimal" if proven else "feasible", solution))

    left, left_proven = best(f, g, [])
    if left.status not in ("optimal", "feasible"):
        # No answer at all (infeasible, or none in time): the caller says so.
        return []
    keep(left, left_proven, None)
    right, right_proven = best(g, f, [])
    if right.status in ("optimal", "feasible"):
        keep(right, right_proven, None)
        high = g.evaluated_at(left.assignments)
        low = g.evaluated_at(right.assignments)
        for k in range(1, steps):
            bound = high - (high - low) * Decimal(k) / Decimal(steps)
            within = Constraint(_ID, {}, g.copy(), "<=", Linear(const=bound))
            found, proven = best(f, g, [within])
            if found.status in ("optimal", "feasible"):
                keep(found, proven, float(bound * sign * turned))
    unique: dict[tuple[float, float], Point] = {}
    for point in points:
        unique.setdefault((round(point.first, 6), round(point.second, 6)), point)
    return sorted(unique.values(), key=lambda p: (p.first * float(sign), p.second * float(sign)))
