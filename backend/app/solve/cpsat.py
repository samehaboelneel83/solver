"""Hand a compiled model to CP-SAT, and report the answer in domain terms.

One backend, behind a shape the roadmap's Phase 2 can put others beside:
`classify()` says what a model is, this says what CP-SAT does with it. The
compiler above knows nothing about either.

**Why CP-SAT first.** The schema is integer-only by decision (spec §2) and the
IR contract admits `binary` and `integer` variables only (§7), so every model
the platform can express today is exactly what CP-SAT is for. A continuous
backend would need the numeric-parameter decision taken first.
"""

from __future__ import annotations

from typing import Any

from importlib.metadata import version as _pkg_version

from ortools.sat.python import cp_model

# Recorded on every run: a result nobody can attribute to a solver version is
# not reproducible (roadmap, Phase 3).
_ORTOOLS_VERSION = _pkg_version("ortools")

from app.solve.compile import Compiled, Constraint
from app.solve.result import Solution

# CP-SAT's own status codes, in the platform's `run_status` vocabulary --
# which already distinguishes a proven optimum from a merely feasible answer,
# so the distinction is kept rather than flattened into "succeeded".
_STATUS = {
    cp_model.OPTIMAL: "optimal",
    cp_model.FEASIBLE: "feasible",
    cp_model.INFEASIBLE: "infeasible",
    cp_model.MODEL_INVALID: "error",
    cp_model.UNKNOWN: "unknown",
}


def solve(compiled: Compiled, *, time_limit: float = 10.0, workers: int = 8) -> Solution:
    model = cp_model.CpModel()

    cp_vars = {
        key: model.NewIntVar(v.lower, v.upper, f"{key[0]}[{','.join(key[1])}]")
        for key, v in compiled.variables.items()
    }

    for c in compiled.constraints:
        _add(model, cp_vars, c)

    if compiled.objective.coeffs:
        expr = sum(cp_vars[k] * coeff for k, coeff in compiled.objective.coeffs.items())
        model.Minimize(expr) if compiled.sense == "minimize" else model.Maximize(expr)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    status = solver.Solve(model)

    solved = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return Solution(
        status=_STATUS.get(status, "unknown"),
        optimal=status == cp_model.OPTIMAL,
        objective=int(solver.ObjectiveValue()) if solved and compiled.objective.coeffs else None,
        assignments={k: int(solver.Value(v)) for k, v in cp_vars.items()} if solved else {},
        wall_seconds=round(solver.WallTime(), 3),
        solver=f"cp-sat (ortools {_ORTOOLS_VERSION})",
    )


def _add(model: cp_model.CpModel, cp_vars: dict, c: Constraint) -> None:
    """`left relation right`, rearranged to `terms relation rhs` because
    CP-SAT wants the variables on one side."""
    coeffs: dict[Any, int] = dict(c.left.coeffs)
    for key, coeff in c.right.coeffs.items():
        coeffs[key] = coeffs.get(key, 0) - coeff
    rhs = c.right.const - c.left.const

    expr = sum(cp_vars[k] * v for k, v in coeffs.items()) if coeffs else 0

    if c.relation in (">=",):
        model.Add(expr >= rhs)
    elif c.relation in ("<=",):
        model.Add(expr <= rhs)
    elif c.relation in ("=", "=="):
        model.Add(expr == rhs)
    elif c.relation == "<":
        model.Add(expr <= rhs - 1)
    elif c.relation == ">":
        model.Add(expr >= rhs + 1)
    else:  # pragma: no cover -- the contract's relation vocabulary
        raise ValueError(f"unknown relation {c.relation!r}")
