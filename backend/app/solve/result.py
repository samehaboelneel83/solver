"""What any backend returns, so the rest of the platform does not care which
one ran."""

from __future__ import annotations

from dataclasses import dataclass


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

    def chosen(self, variable: str) -> list[tuple[str, ...]]:
        """The index tuples a binary variable took as 1 -- the roster, in the
        domain's own keys."""
        return sorted(k[1] for k, v in self.assignments.items() if k[0] == variable and v)
