"""Two goals or more, the trade-off between them: an epsilon-constraint Pareto front.

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

**Three goals or more** (`MAX_GOALS`): the augmented epsilon-constraint method (AUGMECON, Mavrotas 2009).
A payoff table first -- each goal at its best, the others then as low as they go with it held -- gives each
goal's range (its best to the worst any other goal's best leaves it). A grid of bounds on every goal but the
first, `levels` per goal so the grid holds about `steps + 1` cells (the loosest leaves the goal free: the
table's worst only estimates the front's); for each cell, the best first goal with the
others held within their bounds, then the least sum of the others with that held: a point no other answer
beats on every goal. The grid is walked from loose to tight on its last goal, and once a cell has no answer the
tighter ones on that line are skipped (they have none either).

A goal that multiplies decisions is drawn by NSGA-II (`app.solve.evolve.nsga2`) for any number of goals.

**What it does not take.** Hard rules only: a soft rule's penalty belongs to no goal, so the front would not
say what it shows. A goal outside that is refused by name.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.solve.compile import Compiled, Constraint, Linear
from app.solve.result import Solution

DEFAULT_STEPS = 10
MAX_STEPS = 50
#: The most goals a front is drawn between: the grid grows as levels ** (goals - 1).
MAX_GOALS = 6
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
    #: Every goal's value, in the goal's order (`first` and `second` are the first two).
    values: tuple[float, ...] = ()


def admissible(compiled: Compiled, *, searched: bool = True) -> None:
    """Whether a front can be drawn. With `searched`, a goal that multiplies decisions is drawn by NSGA-II
    (`app.solve.evolve.nsga2`) rather than refused."""
    count = len(compiled.objective_terms)
    if count < 2 or count > MAX_GOALS:
        raise NotTwoGoals(
            f"a trade-off front is between two to {MAX_GOALS} goals, and this model's goal has {count} "
            f"term{'' if count == 1 else 's'}"
        )
    if compiled.objective_quadratic and not searched:
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
    if compiled.objective_quadratic:
        return searched_front(compiled, steps=steps, time_limit=time_limit)
    if len(compiled.objective_terms) > 2:
        return many_front(compiled, steps=steps, time_limit=time_limit, solve=solve)
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
        points.append(Point(float(a), float(b), epsilon, "optimal" if proven else "feasible", solution,
                            (float(a), float(b))))

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


def searched_front(compiled: Compiled, *, steps: int, time_limit: float, seed: int | None = 1) -> list[Point]:
    """The front of a goal no exact solve takes as two linear terms (one multiplies decisions): NSGA-II's final
    front, thinned to at most `steps + 1` points spread along the first term. Each point keeps every rule and
    is `feasible` -- found, not proven on the front."""
    from app.solve.evolve import nsga2
    from app.solve.result import Solution

    found = nsga2(compiled, time_limit=time_limit, seed=seed)
    if not found:
        return []
    sign = 1.0 if compiled.sense == "minimize" else -1.0
    found.sort(key=lambda item: tuple(sign * v for v in item[1]))
    if len(found) > steps + 1:
        if len(found[0][1]) == 2:
            picks = sorted({round(k * (len(found) - 1) / steps) for k in range(steps + 1)})
            found = [found[k] for k in picks]
        else:
            found = [found[k] for k in _spread([f for _, f in found], steps + 1)]
    points = []
    for values, goals in found:
        a, b = goals[0], goals[1]
        objective = float(compiled.objective.evaluated_at(values)) + sum(
            float(c) * float(values.get(x, 0)) * float(values.get(y, 0))
            for (x, y), c in compiled.objective_quadratic.items())
        solution = Solution("feasible", False, objective, values, 0.0, "nsga2")
        points.append(Point(a, b, None, "feasible", solution, tuple(float(v) for v in goals)))
    return points


def _spread(goals: list, count: int) -> list[int]:
    """`count` of the points, spread over the front: each goal scaled to [0, 1], the best of the first goal
    first, then each next the point farthest from every one picked (max-min distance)."""
    import numpy as np

    F = np.array(goals, dtype=float)
    span = F.max(axis=0) - F.min(axis=0)
    F = (F - F.min(axis=0)) / np.where(span > 0, span, 1.0)
    picked = [0]
    distance = np.linalg.norm(F - F[0], axis=1)
    while len(picked) < min(count, len(F)):
        nxt = int(np.argmax(distance))
        if distance[nxt] <= 0:
            break
        picked.append(nxt)
        distance = np.minimum(distance, np.linalg.norm(F - F[nxt], axis=1))
    return sorted(picked)


def many_front(compiled: Compiled, *, steps: int, time_limit: float, solve) -> list[Point]:
    """Three goals or more, linear: the augmented epsilon-constraint grid (module docstring)."""
    import itertools
    import math

    from app.solve.compile import directed_terms

    sign = Decimal(1) if compiled.sense == "minimize" else Decimal(-1)
    goals = [Linear().add(term, factor=sign) for term in directed_terms(compiled)]
    k = len(goals)
    # One level more than the spread: the loosest leaves the goal free.
    levels = max(2, math.ceil((steps + 1) ** (1.0 / (k - 1)))) + 1
    cells = levels ** (k - 1)
    # Two solves for each cell and each row of the payoff table.
    budget = max(1.0, time_limit / (2 * (cells + k)))

    def total(of: list[Linear]) -> Linear:
        out = Linear()
        for g in of:
            out = out.add(g)
        return out

    def best(primary: Linear, rest: list[Linear], extra: list[Constraint]) -> tuple[Solution, bool]:
        base = replace(compiled, objective=primary, sense="minimize", objective_mode="weighted",
                       objective_terms=[], objective_term_ids=[], objective_quadratic={},
                       constraints=[*compiled.constraints, *extra])
        first = solve(base, budget)
        if first.status not in ("optimal", "feasible"):
            return first, False
        value = primary.evaluated_at(first.assignments)
        hold = value if compiled.is_integral else value + max(Decimal("1e-6") * abs(value), Decimal("1e-9"))
        freeze = Constraint(_ID, {}, primary.copy(), "<=", Linear(const=hold))
        second = solve(replace(base, objective=total(rest), constraints=[*base.constraints, freeze]), budget)
        if second.status not in ("optimal", "feasible"):
            return first, first.status == "optimal"
        return second, first.status == "optimal" and second.status == "optimal"

    points: list[Point] = []

    def keep(solution: Solution, proven: bool) -> None:
        values = tuple(float(t.evaluated_at(solution.assignments)) for t in compiled.objective_terms)
        points.append(Point(values[0], values[1], None, "optimal" if proven else "feasible", solution, values))

    # The payoff table: each goal at its best, the others then as low as they go.
    table: list[list[Decimal]] = []
    for i in range(k):
        found, proven = best(goals[i], [g for j, g in enumerate(goals) if j != i], [])
        if found.status not in ("optimal", "feasible"):
            if i == 0:
                return []  # no answer at all: the caller says so
            continue
        keep(found, proven)
        table.append([g.evaluated_at(found.assignments) for g in goals])
    # The grid over goals 2..k: the loosest level leaves the goal free (the table's worst is only an estimate of
    # the front's, and a point past it would be missed), then from its worst in the table to its best.
    ranges = [(min(row[j] for row in table), max(row[j] for row in table)) for j in range(1, k)]
    whole = [all(compiled.variables[key].is_integral and c == c.to_integral_value() for key, c in g.coeffs.items()
                 if key in compiled.variables) and g.const == g.const.to_integral_value() for g in goals]

    def bound(j: int, t: int) -> Decimal | None:
        if t == 0:
            return None
        low, high = ranges[j]
        raw = high - (high - low) * Decimal(t - 1) / Decimal(max(1, levels - 2))
        # A goal that only takes whole values is held to a whole bound (exact, and a solver of whole numbers
        # takes it); any other to four places, rounded loose.
        return raw.to_integral_value(rounding=ROUND_FLOOR) if whole[j + 1] else raw.quantize(
            Decimal("0.0001"), rounding=ROUND_CEILING)

    empty_from: dict[tuple[int, ...], int] = {}
    for cell in itertools.product(range(levels), repeat=k - 1):
        outer, last = cell[:-1], cell[-1]
        if outer in empty_from and last >= empty_from[outer]:
            continue  # tighter than a cell with no answer: none here either
        if all(ranges[j][0] == ranges[j][1] for j in range(k - 1)) and any(cell):
            break  # every goal at one value: one point
        within = [Constraint(_ID, {}, goals[j + 1].copy(), "<=", Linear(const=bound(j, t)))
                  for j, t in enumerate(cell) if t > 0]
        found, proven = best(goals[0], goals[1:], within)
        if found.status in ("optimal", "feasible"):
            keep(found, proven)
        elif found.status == "infeasible":
            empty_from[outer] = last
    unique: dict[tuple[float, ...], Point] = {}
    for point in points:
        unique.setdefault(tuple(round(v, 6) for v in point.values), point)
    # No point another beats on every goal (a payoff row can be: its goal's ties broken by a sum).
    weights = compiled.objective_term_weights
    way = [float(sign) * (-1.0 if len(weights) == k and weights[i] < 0 else 1.0) for i in range(k)]

    def beaten(p: Point) -> bool:
        return any(all(w * (q - v) <= 1e-9 for w, q, v in zip(way, o.values, p.values))
                   and any(w * (q - v) < -1e-9 for w, q, v in zip(way, o.values, p.values))
                   for o in unique.values() if o is not p)

    kept = [p for p in unique.values() if not beaten(p)]
    return sorted(kept, key=lambda p: tuple(w * v for w, v in zip(way, p.values)))
