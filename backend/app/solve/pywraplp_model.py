"""Hand a compiled model to a pywraplp solver in one piece (target roadmap D7).

GLOP (`lp.py`) and the MILP wrapper (`milp.py`) used to build it the way
the library's examples do: one expression object per term, `solver.Sum`,
`solver.Add(expr >= rhs)`. That is Python work for every entry. Filling an
`MPModelProto` -- two bulk `extend`s per row -- and loading it once costs a
fraction of it (`python -m bench.build_speed`, 2026-09-23):

    200,000 entries, GLOP     0.435 s -> 0.054 s
    321,000 entries, SCIP     1.608 s -> 0.427 s

The variables and rows come back from the solver in the order they went
in, so the adapters read values, duals and reduced costs from them exactly
as before.

A rule left with no variables (`0 >= 1` after its terms cancel) is still a
row -- empty, with its bounds -- so an unsatisfiable one keeps the model
infeasible. Dropping such rows is the bug HiGHS's array build once had.
"""

from __future__ import annotations

import math
from decimal import Decimal

from ortools.linear_solver import linear_solver_pb2, pywraplp

from app.solve.compile import Compiled, Constraint

INF = math.inf


def row_bounds(c: Constraint) -> tuple[dict, float, float]:
    """`left relation right` as `lower <= coeffs . x <= upper`.

    `<` and `>` are the contract's strict relations, which only an integer
    row can honour: `< r` is `<= r - 1`. The GLOP adapter refuses discrete
    models before it gets here, and no continuous model reaches it with one.
    """
    if c.quadratic:  # pragma: no cover -- `quadratic-constraints` keeps it away
        raise ValueError(f"{c.id!r} is a quadratic rule, which this backend cannot take")
    if c.when is not None:  # pragma: no cover -- `indicator` keeps it away
        raise ValueError(f"{c.id!r} is a conditional rule, which this backend cannot take")
    coeffs: dict = dict(c.left.coeffs)
    for key, coeff in c.right.coeffs.items():
        coeffs[key] = coeffs.get(key, Decimal(0)) - coeff
    rhs = float(c.right.const - c.left.const)
    if c.relation == ">=":
        return coeffs, rhs, INF
    if c.relation == "<=":
        return coeffs, -INF, rhs
    if c.relation in ("=", "=="):
        return coeffs, rhs, rhs
    if c.relation == ">":
        return coeffs, rhs + 1, INF
    if c.relation == "<":
        return coeffs, -INF, rhs - 1
    raise ValueError(f"unknown relation {c.relation!r}")  # pragma: no cover


def load(solver: pywraplp.Solver, compiled: Compiled) -> tuple[dict, list]:
    """Load the model; return {variable key: MPVariable} and the rows'
    MPConstraints, in `compiled.constraints` order."""
    if compiled.pwl:  # pragma: no cover -- solve_compiled rewrites curves first
        raise ValueError("a piecewise curve reached a backend that holds none")
    if compiled.functions:  # pragma: no cover -- the registry offers these to SCIP only
        raise ValueError("a function reached a backend that holds none")
    model = linear_solver_pb2.MPModelProto()
    model.maximize = compiled.sense != "minimize"
    keys = list(compiled.variables)
    position = {key: i for i, key in enumerate(keys)}
    objective = compiled.objective.coeffs
    for key in keys:
        spec = compiled.variables[key]
        var = model.variable.add()
        var.name = f"{key[0]}[{','.join(key[1])}]"
        if spec.domain == "binary":
            var.lower_bound, var.upper_bound = 0.0, 1.0
        else:
            var.lower_bound, var.upper_bound = float(spec.lower), float(spec.upper)
        var.is_integer = spec.domain in ("binary", "integer")
        coeff = objective.get(key)
        if coeff:
            var.objective_coefficient = float(coeff)
    for constraint in compiled.constraints:
        coeffs, lower, upper = row_bounds(constraint)
        row = model.constraint.add()
        row.lower_bound, row.upper_bound = lower, upper
        row.var_index.extend([position[key] for key in coeffs])
        row.coefficient.extend([float(coeff) for coeff in coeffs.values()])

    error = solver.LoadModelFromProto(model)
    if error:  # pragma: no cover -- a malformed proto is this module's bug
        raise RuntimeError(f"pywraplp refused the model: {error}")
    return dict(zip(keys, solver.variables())), list(solver.constraints())
