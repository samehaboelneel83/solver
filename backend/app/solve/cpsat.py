"""Hand a compiled model to CP-SAT, and report the answer in domain terms.

One backend, behind a shape the roadmap's Phase 2 can put others beside:
`classify()` says what a model is, this says what CP-SAT does with it. The
compiler above knows nothing about either.

**Why CP-SAT first.** It is the strongest of the three on tightly constrained
combinatorial models, which is what the schema was designed around.

**What it will not take, since migration 0015.** Integers only -- every
variable and every coefficient. That is not a weakness papered over: it is
declared in the registry, and a model with a continuous variable or a
fractional coefficient is routed to a backend that takes it, with the reason
recorded on the run. Rounding such a model into CP-SAT would answer a
different question than the one asked, which is the one failure mode a
multi-backend platform exists to prevent. `_whole` below is the guard that
makes that a refusal rather than a silent rounding.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from importlib.metadata import version as _pkg_version

from ortools.sat.python import cp_model

# Recorded on every run: a result nobody can attribute to a solver version is
# not reproducible (roadmap, Phase 3).
_ORTOOLS_VERSION = _pkg_version("ortools")

from app.solve.compile import Compiled, Constraint
from app.solve.result import Solution
from app.solve.stop import interrupt_when

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


class NotIntegral(Exception):
    """This model is not one CP-SAT can answer without changing it."""


def _whole(value: Decimal, what: str) -> int:
    """The one place a decimal becomes an integer for CP-SAT.

    A refusal, never a rounding. `0.5` rounded to `0` or `1` is a different
    model, and the caller would read the answer as though it were to theirs.
    The registry is meant to have kept such a model away from here, so
    reaching this is a bug in selection -- and it says so rather than
    producing a plausible wrong number.
    """
    if value != value.to_integral_value():
        raise NotIntegral(
            f"cp-sat takes whole numbers, and {what} is {value}. A model with fractional "
            "numbers belongs to a linear-programming backend."
        )
    return int(value)


def solve(
    compiled: Compiled,
    *,
    time_limit: float = 10.0,
    workers: int = 8,
    should_stop=None,
    seed: int | None = None,
) -> Solution:
    if should_stop is not None and should_stop():
        return Solution(
            status="unknown",
            optimal=False,
            objective=None,
            assignments={},
            wall_seconds=0.0,
            solver=f"cp-sat (ortools {_ORTOOLS_VERSION})",
        )

    model = cp_model.CpModel()

    for key, v in compiled.variables.items():
        if not v.is_integral:
            raise NotIntegral(
                f"cp-sat has no continuous variables, and {v.key[0]!r} is {v.domain}"
            )

    cp_vars = {
        key: model.NewIntVar(
            _whole(v.lower, f"{key[0]}'s lower bound"),
            _whole(v.upper, f"{key[0]}'s upper bound"),
            f"{key[0]}[{','.join(key[1])}]",
        )
        for key, v in compiled.variables.items()
    }

    # One product variable per pair, however many rules and objective terms
    # mention it: the pair means the same number everywhere.
    products: dict = {}

    def product_of(a, b):
        if (a, b) not in products:
            products[(a, b)] = _product(
                model, cp_vars[a], cp_vars[b], compiled.variables[a], compiled.variables[b]
            )
        return products[(a, b)]

    for c in compiled.constraints:
        _add(model, cp_vars, c, product_of)

    has_objective = bool(compiled.objective.coeffs or compiled.objective_quadratic)
    if has_objective:
        expr = sum(
            cp_vars[k] * _whole(coeff, f"the objective coefficient of {k[0]!r}")
            for k, coeff in compiled.objective.coeffs.items()
        )
        # A quadratic objective, exactly: each product of two variables is a
        # new integer variable held equal to that product, so the search is
        # over the true objective -- no linearisation error, and no
        # convexity needed. That is why CP-SAT may take a nonconvex
        # whole-number model and still prove the global optimum.
        for (a, b), coeff in compiled.objective_quadratic.items():
            expr += product_of(a, b) * _whole(coeff, f"the objective coefficient of {a[0]!r} x {b[0]!r}")
        model.Minimize(expr) if compiled.sense == "minimize" else model.Maximize(expr)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    if seed is not None:
        solver.parameters.random_seed = int(seed)
    with interrupt_when(should_stop, solver.StopSearch):
        status = solver.Solve(model)

    solved = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return Solution(
        status=_STATUS.get(status, "unknown"),
        optimal=status == cp_model.OPTIMAL,
        objective=int(solver.ObjectiveValue()) if solved and has_objective else None,
        best_bound=float(solver.BestObjectiveBound()) if solved and has_objective else None,
        assignments={k: int(solver.Value(v)) for k, v in cp_vars.items()} if solved else {},
        wall_seconds=round(solver.WallTime(), 3),
        solver=f"cp-sat (ortools {_ORTOOLS_VERSION})",
    )


def _product(model: cp_model.CpModel, x, y, spec_x, spec_y):
    """An integer variable equal to `x * y`, bounded by the corners of the two
    ranges -- the smallest and largest a product of values in them can be."""
    corners = [
        _whole(p, "a product bound") * _whole(q, "a product bound")
        for p in (spec_x.lower, spec_x.upper)
        for q in (spec_y.lower, spec_y.upper)
    ]
    product = model.NewIntVar(min(corners), max(corners), "")
    model.AddMultiplicationEquality(product, [x, y])
    return product


def _add(model: cp_model.CpModel, cp_vars: dict, c: Constraint, product_of) -> None:
    """`left relation right`, rearranged to `terms relation rhs` because
    CP-SAT wants the variables on one side. A quadratic rule's products are
    held exactly, as in the objective (`product_of`)."""
    coeffs: dict[Any, Decimal] = dict(c.left.coeffs)
    for key, coeff in c.right.coeffs.items():
        coeffs[key] = coeffs.get(key, Decimal(0)) - coeff
    rhs = _whole(c.right.const - c.left.const, f"the bound of {c.id!r}")

    expr = (
        sum(cp_vars[k] * _whole(v, f"a coefficient of {c.id!r}") for k, v in coeffs.items())
        if coeffs
        else 0
    )
    for (a, b), coeff in c.quadratic.items():
        expr += product_of(a, b) * _whole(coeff, f"a coefficient of {c.id!r}")

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
