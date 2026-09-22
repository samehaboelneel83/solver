"""The primal integral: how soon a solver had good answers, not only how soon it finished.

Two solvers that both prove the optimum in 30 s are not equal if one had
the optimal roster after 1 s and the other only at 29 s -- a person who
stops the run early gets very different answers. Berthold's primal
integral measures that (Berthold, "Measuring the impact of primal
heuristics", 2013):

* the **primal gap** of a value x against the reference optimum x* is
  0 when both are 0, 1 when they have different signs or there is no
  answer yet, and |x - x*| / max(|x|, |x*|) otherwise -- between 0 and 1,
  the same for minimising and maximising;
* p(t) is the primal gap of the best answer found by time t: a step
  function, 1 until the first answer, dropping at each better one;
* the **primal integral** is the area under p from 0 to the end of the
  solve, in seconds. Smaller is better; a solver that never finds an
  answer scores the whole run time.

The answers are the incumbents a backend streams while it solves
(`on_progress`, the same callbacks a run's live chart reads) plus the
answer it ended with. A backend that streams nothing -- GLOP and the MILP
wrapper today -- has one answer, at the end, and is charged for the wait;
that is what a person watching it would have seen.

The reference is the instance's proven optimum when any backend proved one,
else the best value any backend found (the usual convention when the
optimum is unknown).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

PROVEN_OPTIMAL = "optimal"


def primal_gap(value: float | None, optimum: float) -> float:
    if value is None:
        return 1.0
    if value == 0 and optimum == 0:
        return 0.0
    if value * optimum < 0:
        return 1.0
    return abs(value - optimum) / max(abs(value), abs(optimum))


def primal_integral(
    points: Iterable[tuple[float, float]], optimum: float, end: float, *, minimise: bool = True
) -> float:
    """Area under p(t) over [0, end]. `points` are (time, value) answers in any
    order; a later one that is not better than the best so far changes nothing,
    and one after `end` is ignored."""
    area = 0.0
    last_t = 0.0
    best: float | None = None
    for t, value in sorted(points):
        t = max(0.0, min(float(t), end))
        area += primal_gap(best, optimum) * (t - last_t)
        last_t = t
        if best is None or (value < best if minimise else value > best):
            best = float(value)
    area += primal_gap(best, optimum) * (end - last_t)
    return area


def mark_primal_integral(rows: list[dict[str, Any]]) -> None:
    """Set `primal_integral` on each row from its `incumbents`, then drop
    those. None on an instance nothing found an answer to (infeasible,
    unbounded, or every backend timed out empty)."""
    by_instance: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_instance[row["instance"]].append(row)
    for group in by_instance.values():
        reference = _reference(group)
        for row in group:
            points = row.pop("incumbents", [])
            if reference is None:
                row["primal_integral"] = None
                continue
            optimum, minimise = reference
            row["primal_integral"] = round(
                primal_integral(points, optimum, float(row["solve_s"]), minimise=minimise), 4
            )


def _reference(group: list[dict[str, Any]]) -> tuple[float, bool] | None:
    minimise = group[0].get("sense", "minimize") != "maximize"
    proven = [
        float(r["objective"])
        for r in group
        if r["status"] == PROVEN_OPTIMAL and r["objective"] is not None and not r.get("wrong")
    ]
    if proven:
        return proven[0], minimise
    found = [float(v) for r in group for _, v in r.get("incumbents", [])]
    found += [float(r["objective"]) for r in group if r["objective"] is not None]
    if not found:
        return None
    return (min(found) if minimise else max(found)), minimise
