"""A second backend: branch-and-cut MILP, through OR-Tools' linear solver.

**Why a second one at all.** The roadmap's Phase 2 asks the platform to pick
a technique and say why. A classifier with one backend behind it is not a
choice, it is a label — the policy could be wrong in every case and nothing
would show it. Two backends that must agree on the same model is the first
point at which "we picked the right one" means anything.

**Why this one.** CP-SAT is constraint programming: excellent on tightly
constrained combinatorial models, which is what the schema was designed
around. SCIP and CBC are branch-and-cut over a linear relaxation, which is a
genuinely different search — better on models with strong linear structure
and weak combinatorial structure, worse on the opposite. They are already in
the `ortools` package, so this adds a technique without adding a dependency.

**What it cannot do.** Nothing here is continuous: the contract admits only
`binary` and `integer` variables (§7), so this solves integer programs, not
LPs. The gap is the schema's integer-only decision, not the backend's.
"""

from __future__ import annotations

from importlib.metadata import version as _pkg_version

from ortools.linear_solver import pywraplp

from app.solve.compile import Compiled, Constraint
from app.solve.result import Solution

_ORTOOLS_VERSION = _pkg_version("ortools")

# SCIP first: it is the stronger of the two on the models this platform
# expresses, and CBC is the fallback for a build without it.
_PREFERRED = ("SCIP", "CBC")

_STATUS = {
    pywraplp.Solver.OPTIMAL: "optimal",
    pywraplp.Solver.FEASIBLE: "feasible",
    pywraplp.Solver.INFEASIBLE: "infeasible",
    pywraplp.Solver.UNBOUNDED: "unknown",
    pywraplp.Solver.ABNORMAL: "error",
    pywraplp.Solver.NOT_SOLVED: "unknown",
}


def available() -> str | None:
    """The engine this build has, or None. Checked rather than assumed: the
    registry must not offer a backend that cannot be created."""
    for name in _PREFERRED:
        if pywraplp.Solver.CreateSolver(name) is not None:
            return name
    return None


def solve(compiled: Compiled, *, time_limit: float = 10.0, workers: int = 8) -> Solution:
    engine = available()
    if engine is None:  # pragma: no cover -- both ship with ortools
        raise RuntimeError("no MILP engine in this build")

    solver = pywraplp.Solver.CreateSolver(engine)
    solver.SetTimeLimit(int(time_limit * 1000))
    if workers > 1:
        solver.SetNumThreads(workers)

    variables = {
        key: (
            solver.BoolVar(f"{key[0]}[{','.join(key[1])}]")
            if spec.domain == "binary"
            else solver.IntVar(spec.lower, spec.upper, f"{key[0]}[{','.join(key[1])}]")
        )
        for key, spec in compiled.variables.items()
    }

    for constraint in compiled.constraints:
        _add(solver, variables, constraint)

    if compiled.objective.coeffs:
        expression = solver.Sum(
            [variables[key] * coeff for key, coeff in compiled.objective.coeffs.items()]
        )
        solver.Minimize(expression) if compiled.sense == "minimize" else solver.Maximize(expression)

    status = solver.Solve()
    solved = status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

    return Solution(
        status=_STATUS.get(status, "unknown"),
        optimal=status == pywraplp.Solver.OPTIMAL,
        # Values come back as floats even for integer variables; rounding
        # rather than truncating, because 0.9999999 is a 1 that took a
        # floating-point detour and `int()` would read it as 0.
        objective=(
            round(solver.Objective().Value()) if solved and compiled.objective.coeffs else None
        ),
        assignments=(
            {key: round(var.solution_value()) for key, var in variables.items()} if solved else {}
        ),
        wall_seconds=round(solver.WallTime() / 1000, 3),
        solver=f"{engine.lower()} (ortools {_ORTOOLS_VERSION})",
    )


def _add(solver: pywraplp.Solver, variables: dict, c: Constraint) -> None:
    """`left relation right`, rearranged so the variables sit on one side."""
    coeffs: dict = dict(c.left.coeffs)
    for key, coeff in c.right.coeffs.items():
        coeffs[key] = coeffs.get(key, 0) - coeff
    rhs = c.right.const - c.left.const

    expression = solver.Sum([variables[key] * coeff for key, coeff in coeffs.items()])

    if c.relation == ">=":
        solver.Add(expression >= rhs)
    elif c.relation == "<=":
        solver.Add(expression <= rhs)
    elif c.relation in ("=", "=="):
        solver.Add(expression == rhs)
    elif c.relation == "<":
        solver.Add(expression <= rhs - 1)
    elif c.relation == ">":
        solver.Add(expression >= rhs + 1)
    else:  # pragma: no cover -- the contract's relation vocabulary
        raise ValueError(f"unknown relation {c.relation!r}")
