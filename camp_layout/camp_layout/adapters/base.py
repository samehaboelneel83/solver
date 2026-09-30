"""H. Solver adapter: the one door between the model and a solver.

An adapter takes the solver-independent model, one objective expression and
some extra constraints (earlier lexicographic stages), and returns values for
every variable with an honest status. Nothing above this layer imports a
solver; adding Gurobi, Xpress, CPLEX or SCIP is one new file.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from ..model import Constraint, Expr, MathematicalModel

Status = Literal["optimal", "feasible", "infeasible", "unknown", "error"]


@dataclass
class SolveResult:
    status: Status
    values: list[float] = field(default_factory=list)
    objective: float | None = None
    bound: float | None = None
    seconds: float = 0.0
    solver: str = ""
    message: str = ""

    @property
    def has_solution(self) -> bool:
        return self.status in ("optimal", "feasible") and bool(self.values)


class SolverAdapter(ABC):
    name: str = "abstract"

    @abstractmethod
    def solve(self, model: MathematicalModel, objective: Expr, sense: Literal["max", "min"], *,
              extra: list[Constraint] = (), time_limit: float = 60.0, hint: list[float] | None = None,
              threads: int = 4, relative_gap: float = 0.0) -> SolveResult:
        """Optimise `objective` over `model` plus `extra`."""


def adapter(name: str) -> SolverAdapter:
    if name == "cpsat":
        from .cpsat import CpSatAdapter
        return CpSatAdapter()
    if name in ("scip", "cbc", "highs"):
        from .mip import MipAdapter
        return MipAdapter(name)
    raise ValueError(f"no solver adapter named {name!r} (known: cpsat, scip, cbc, highs)")
