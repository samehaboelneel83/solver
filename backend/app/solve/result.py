"""What any backend returns, so the rest of the platform does not care which
one ran."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Solution:
    status: str
    optimal: bool
    objective: int | None
    # ("assign", ("ahmed", "mon", "morning")) -> 1
    assignments: dict[tuple[str, tuple[str, ...]], int]
    wall_seconds: float
    solver: str

    def chosen(self, variable: str) -> list[tuple[str, ...]]:
        """The index tuples a binary variable took as 1 -- the roster, in the
        domain's own keys."""
        return sorted(k[1] for k, v in self.assignments.items() if k[0] == variable and v)
