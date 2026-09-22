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

**What it takes, since migration 0015.** Integer, binary and continuous
variables, and fractional coefficients -- so integer programs, mixed-integer
programs and pure linear programs. It is the only one of the three backends
that takes a *mixed* model, which is why its rank matters less than its
breadth: for a pure LP, GLOP's simplex is the better technique, and for a
pure integer model CP-SAT usually is. This is the one that catches everything
in between.
"""

from __future__ import annotations

from decimal import Decimal
from importlib.metadata import version as _pkg_version

from ortools.linear_solver import pywraplp

from app.api.quantity import report_quantity
from app.solve.compile import Compiled, Constraint, Variable
from app.solve.result import Solution
from app.solve.stop import interrupt_when

_ORTOOLS_VERSION = _pkg_version("ortools")

# SCIP first: it is the stronger of the two on the models this platform
# expresses, and CBC is the fallback for a build without it.
_PREFERRED = ("SCIP", "CBC")

_STATUS = {
    pywraplp.Solver.OPTIMAL: "optimal",
    pywraplp.Solver.FEASIBLE: "feasible",
    pywraplp.Solver.INFEASIBLE: "infeasible",
    pywraplp.Solver.UNBOUNDED: "unbounded",
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


def solve(
    compiled: Compiled,
    *,
    time_limit: float = 10.0,
    workers: int = 8,
    should_stop=None,
    seed: int | None = None,
    gap_rel: float = 0.0,
) -> Solution:
    engine = available()
    if engine is None:  # pragma: no cover -- both ship with ortools
        raise RuntimeError("no MILP engine in this build")

    solver = pywraplp.Solver.CreateSolver(engine)
    solver.SetTimeLimit(int(time_limit * 1000))
    if workers > 1:
        solver.SetNumThreads(workers)
    if seed is not None and engine == "SCIP":
        solver.SetSolverSpecificParametersAsString(
            f"randomization/randomseedshift = {int(seed)}"
        )

    variables = {key: _declare(solver, key, spec) for key, spec in compiled.variables.items()}

    for constraint in compiled.constraints:
        _add(solver, variables, constraint)

    if compiled.objective.coeffs:
        expression = solver.Sum(
            [variables[key] * float(coeff) for key, coeff in compiled.objective.coeffs.items()]
        )
        solver.Minimize(expression) if compiled.sense == "minimize" else solver.Maximize(expression)

    # pywraplp's own default gap is 1e-4, which would let a run be called
    # optimal 0.01% short of the best. The setting decides, 0 by default.
    parameters = pywraplp.MPSolverParameters()
    parameters.SetDoubleParam(pywraplp.MPSolverParameters.RELATIVE_MIP_GAP, float(gap_rel))
    with interrupt_when(should_stop, solver.InterruptSolve):
        status = solver.Solve(parameters)
    solved = status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

    return Solution(
        status=_STATUS.get(status, "unknown"),
        optimal=status == pywraplp.Solver.OPTIMAL,
        # Values come back as floats even for integer variables; rounding
        # rather than truncating, because 0.9999999 is a 1 that took a
        # floating-point detour and `int()` would read it as 0.
        objective=(
            _report(compiled, solver.Objective().Value())
            if solved and compiled.objective.coeffs
            else None
        ),
        assignments=(
            {
                key: _read(compiled.variables[key], var.solution_value())
                for key, var in variables.items()
            }
            if solved
            else {}
        ),
        best_bound=(
            solver.Objective().BestBound() if solved and compiled.objective.coeffs else None
        ),
        wall_seconds=round(solver.WallTime() / 1000, 3),
        solver=f"{engine.lower()} (ortools {_ORTOOLS_VERSION})",
    )


def _report(compiled: Compiled, value: float) -> float | int:
    """A wholly integral model's answer keeps its integer shape.

    The arithmetic runs in `Decimal` from migration 0015 onwards, but an
    integer program's optimum is still an integer, and letting it come back
    as `2.0000000001` would make two runs of the same model look different.
    A continuous optimum is cut to six decimal places — numeric(15, 6).
    """
    return report_quantity(value, integral=compiled.is_integral)


def _declare(solver: pywraplp.Solver, key, spec: Variable):
    name = f"{key[0]}[{','.join(key[1])}]"
    if spec.domain == "binary":
        return solver.BoolVar(name)
    if spec.domain == "integer":
        return solver.IntVar(float(spec.lower), float(spec.upper), name)
    return solver.NumVar(float(spec.lower), float(spec.upper), name)


def _read(spec: Variable, value: float) -> float | int:
    """An integer variable's value comes back as a float and is rounded; a
    continuous one is kept at six decimal places.

    Rounding an integer rather than truncating it, because 0.9999999 is a 1
    that took a floating-point detour and `int()` reads it as 0 -- a roster
    that silently loses a shift. Rounding a *continuous* value to a whole
    number would be the opposite error: 0.6 of an hour is the answer, not 1.
    """
    return report_quantity(value, integral=spec.is_integral)


def _add(solver: pywraplp.Solver, variables: dict, c: Constraint) -> None:
    """`left relation right`, rearranged so the variables sit on one side."""
    if c.quadratic:  # pragma: no cover -- `quadratic-constraints` keeps it away
        raise ValueError(f"{c.id!r} is a quadratic rule, which this backend cannot take")
    coeffs: dict = dict(c.left.coeffs)
    for key, coeff in c.right.coeffs.items():
        coeffs[key] = coeffs.get(key, Decimal(0)) - coeff
    rhs = float(c.right.const - c.left.const)

    expression = solver.Sum([variables[key] * float(coeff) for key, coeff in coeffs.items()])

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
