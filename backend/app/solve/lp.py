"""A third backend: the simplex method, through OR-Tools' GLOP.

**Why a pure LP solver, when the MILP backend already takes linear models.**
Because "the right technique" is the whole point of the selection policy, and
for a model with no integer variables branch-and-cut is the wrong one. SCIP
and CBC solve an LP by solving the relaxation and then discovering there is
nothing to branch on; GLOP just solves it. On a model of any size that is the
difference between a screen that answers and a screen that waits, and it costs
nothing -- GLOP ships in the same `ortools` package.

It is also what makes the platform's classification *mean* something. Before
this, `LP` and `MILP` would have been labels on a model that went to the same
solver either way; a classifier that cannot change the outcome is decoration.

**What it will not take.** Any integer or binary variable. Handing it one
would silently solve the relaxation and report a fractional answer as though
it were the optimum -- three quarters of a nurse on Tuesday. The registry
declares that, and `solve` refuses it rather than trusting the registry to
have been right.
"""

from __future__ import annotations

from importlib.metadata import version as _pkg_version

from ortools.linear_solver import pywraplp

from app.api.quantity import report_quantity
from app.solve.compile import Compiled
from app.solve.pywraplp_model import load
from app.solve.result import Solution, fold_duals
from app.solve.stop import interrupt_when

_ORTOOLS_VERSION = _pkg_version("ortools")

_ENGINE = "GLOP"

_STATUS = {
    pywraplp.Solver.OPTIMAL: "optimal",
    pywraplp.Solver.FEASIBLE: "feasible",
    pywraplp.Solver.INFEASIBLE: "infeasible",
    # An unbounded LP is a modelling fault -- a variable free to grow without
    # limit -- and it is not "no answer", so it does not borrow `infeasible`.
    pywraplp.Solver.UNBOUNDED: "unbounded",
    pywraplp.Solver.ABNORMAL: "error",
    pywraplp.Solver.NOT_SOLVED: "unknown",
}


class NotContinuous(Exception):
    """This model has discrete variables, which the simplex method ignores."""


def available() -> bool:
    return pywraplp.Solver.CreateSolver(_ENGINE) is not None


def solve(
    compiled: Compiled,
    *,
    time_limit: float = 10.0,
    workers: int = 8,
    should_stop=None,
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
) -> Solution:
    discrete = [key[0] for key, spec in compiled.variables.items() if spec.is_integral]
    if discrete:
        raise NotContinuous(
            f"glop solves linear programs and {sorted(set(discrete))[0]!r} is discrete; "
            "solving the relaxation instead would report a fractional answer as the optimum"
        )

    solver = pywraplp.Solver.CreateSolver(_ENGINE)
    # One proto, loaded at once (D7): 0.435 s -> 0.054 s on 200,000 entries.
    # Loaded before the settings below, so a load cannot reset them.
    variables, loaded = load(solver, compiled)
    rows = [(constraint.id, row) for constraint, row in zip(compiled.constraints, loaded)]
    solver.SetTimeLimit(int(time_limit * 1000))
    if seed is not None:
        # GLOP's own parameters, in their text form; it perturbs with them.
        solver.SetSolverSpecificParametersAsString(f"random_seed: {int(seed)}")

    with interrupt_when(should_stop, solver.InterruptSolve):
        status = solver.Solve()
    solved = status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)
    duals = (
        fold_duals(
            (spec_id, report_quantity(row.dual_value()))
            for spec_id, row in rows
            if row is not None
        )
        if solved
        else None
    )

    return Solution(
        status=_STATUS.get(status, "unknown"),
        # The simplex method reaches a vertex or proves there is none; there
        # is no "ran out of time with something feasible in hand" the way
        # branch-and-bound has, so a solved LP is an optimal one.
        optimal=status == pywraplp.Solver.OPTIMAL,
        objective=(
            report_quantity(solver.Objective().Value())
            if solved and compiled.objective.coeffs
            else None
        ),
        assignments=(
            {
                key: report_quantity(var.solution_value())
                for key, var in variables.items()
            }
            if solved
            else {}
        ),
        # A simplex optimum is its own bound: the dual solution proves it.
        best_bound=(
            solver.Objective().Value()
            if status == pywraplp.Solver.OPTIMAL and compiled.objective.coeffs
            else None
        ),
        wall_seconds=round(solver.WallTime() / 1000, 3),
        solver=f"glop (ortools {_ORTOOLS_VERSION})",
        duals=duals,
        reduced_costs=(
            {
                key: report_quantity(var.reduced_cost())
                for key, var in variables.items()
            }
            if solved
            else None
        ),
    )

