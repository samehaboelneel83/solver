"""What any backend returns, so the rest of the platform does not care which
one ran."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class Solution:
    status: str
    optimal: bool
    # A whole number for a wholly integral model, a decimal otherwise. The
    # backend decides, because only it knows whether the model it solved had
    # anything fractional in it (migration 0015).
    objective: float | int | None
    # ("assign", ("ahmed", "mon", "morning")) -> 1, or 0.6 of an hour
    assignments: dict[tuple[str, tuple[str, ...]], float | int]
    wall_seconds: float
    solver: str
    # Shadow price per IR constraint id, filled only by a linear solver at a
    # vertex. None means this backend has no duals to report -- not zero.
    duals: dict[str, float] | None = None
    # Reduced cost per variable instance, same honesty: None, not {}.
    reduced_costs: dict[tuple[str, tuple[str, ...]], float] | None = None
    # The solver's proven limit on the goal: no answer can beat it. Equal to
    # the objective at a proven optimum; None when the solver has none.
    # Measured on the same objective the backend reports (migration 0029).
    best_bound: float | None = None
    # How far each number may move before the plan changes (queue R27): LP ranging, from a
    # linear solver at a proven optimum of a model with no whole-number decision -- `rows`, each
    # binding rule instance's limit with its range, and `costs`, each goal coefficient's range.
    # None anywhere else: ranging is not defined for a MIP, and no relaxation stands in for it.
    ranges: dict | None = None
    execution: dict | None = None

    def chosen(self, variable: str) -> list[tuple[str, ...]]:
        """The index tuples a binary variable took as 1 -- the roster, in the
        domain's own keys."""
        return sorted(k[1] for k, v in self.assignments.items() if k[0] == variable and v)


def fold_duals(pairs: Iterable[tuple[str, float]]) -> dict[str, float]:
    """One number per IR constraint: the instance whose dual is largest in
    magnitude -- the rule that moves the goal the most."""
    folded: dict[str, float] = {}
    for spec_id, value in pairs:
        current = folded.get(spec_id)
        if current is None or abs(value) > abs(current):
            folded[spec_id] = value
    return folded
