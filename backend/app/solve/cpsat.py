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

**Fractional data, scaled exactly (migration 0039).** A rule whose numbers
have a few decimal places is multiplied into whole numbers (`scaling.py`)
-- `7.5 x <= 30` is `x <= 4` -- which changes no whole-number solution; the
objective is scaled the same way and divided back when reported. Such a
model reaches CP-SAT only when the setting `solve.cpsat_scaling` admits it.
"""

from __future__ import annotations

import time

from decimal import Decimal
from typing import Any

from importlib.metadata import version as _pkg_version

from ortools.sat.python import cp_model

# Recorded on every run: a result nobody can attribute to a solver version is
# not reproducible (roadmap, Phase 3).
_ORTOOLS_VERSION = _pkg_version("ortools")

from app.api.quantity import report_quantity
from app.solve.compile import Compiled, Constraint
from app.solve.result import Solution
from app.solve.scaling import NotScalable, ScaledRow, reach_of, scale
from app.solve.progress import report
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
    gap_rel: float = 0.0,
    on_progress=None,
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

    model, cp_vars, product_of, reach, _ = _build(compiled)

    has_objective = bool(compiled.objective.coeffs or compiled.objective_quadratic)
    # The objective as one scaled row: whole coefficients, and the factor its
    # value and bound are divided by on the way out -- 1 when it was whole.
    goal = _scaled(
        compiled.objective.coeffs, Decimal(0), compiled.objective_quadratic, reach, "the objective"
    )

    def unscale(value):
        if value is None or goal.factor == 1:
            return value
        return float(Decimal(str(value)) / goal.factor)

    if has_objective:
        expr = sum(cp_vars[k] * coeff for k, coeff in goal.coeffs.items())
        # A quadratic objective, exactly: each product of two variables is a
        # new integer variable held equal to that product, so the search is
        # over the true objective -- no linearisation error, and no
        # convexity needed. That is why CP-SAT may take a nonconvex
        # whole-number model and still prove the global optimum.
        for (a, b), coeff in goal.quadratic.items():
            expr += product_of(a, b) * coeff
        model.Minimize(expr) if compiled.sense == "minimize" else model.Maximize(expr)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    if seed is not None:
        solver.parameters.random_seed = int(seed)
    # Stop once the answer is proven within this fraction of the best. 0, the
    # default, is "prove the optimum"; the run then checks the recorded gap
    # before it lets the answer be called optimal.
    solver.parameters.relative_gap_limit = float(gap_rel)
    callback = None
    if on_progress is not None and has_objective:
        callback = _Progress(on_progress, unscale)
        # Our own clock: `solver.wall_time` is only readable once the solve
        # has returned, and this fires while it runs.
        started = time.monotonic()
        solver.best_bound_callback = lambda bound: report(
            on_progress, "bound", time.monotonic() - started, callback.best, unscale(bound)
        )
    with interrupt_when(should_stop, solver.StopSearch):
        status = solver.Solve(model, callback) if callback else solver.Solve(model)

    solved = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return Solution(
        status=_STATUS.get(status, "unknown"),
        optimal=status == cp_model.OPTIMAL,
        objective=(
            _objective(solver.ObjectiveValue(), goal) if solved and has_objective else None
        ),
        best_bound=(
            unscale(float(solver.BestObjectiveBound())) if solved and has_objective else None
        ),
        assignments={k: int(solver.Value(v)) for k, v in cp_vars.items()} if solved else {},
        wall_seconds=round(solver.WallTime(), 3),
        solver=f"cp-sat (ortools {_ORTOOLS_VERSION})",
    )


class _Progress(cp_model.CpSolverSolutionCallback):
    """Each better answer CP-SAT finds, with the bound at that moment."""

    def __init__(self, on_progress, unscale):
        super().__init__()
        self.on_progress = on_progress
        self.unscale = unscale
        self.best = None

    def on_solution_callback(self) -> None:
        self.best = self.unscale(self.ObjectiveValue())
        report(
            self.on_progress, "incumbent", self.WallTime(), self.best,
            self.unscale(self.BestObjectiveBound()),
        )


def _interval(model: cp_model.CpModel, cp_vars: dict, spec):
    """`end = start + size`, held by the interval itself; an optional one
    holds it only while its presence is 1."""
    start, end = cp_vars[spec.start], cp_vars[spec.end]
    name = f"{spec.key[0]}[{','.join(spec.key[1])}]"
    if spec.presence is None:
        return model.NewIntervalVar(start, spec.size, end, name)
    return model.NewOptionalIntervalVar(start, spec.size, end, cp_vars[spec.presence], name)


def _add_schedule(model: cp_model.CpModel, intervals: dict, c: Constraint) -> None:
    schedule = c.schedule
    members = [intervals[key] for key, _ in schedule.members]
    if schedule.kind == "no_overlap":
        model.AddNoOverlap(members)
    else:
        model.AddCumulative(members, [demand for _, demand in schedule.members], schedule.capacity)


def _add_curve(model: cp_model.CpModel, cp_vars: dict, curve) -> None:
    """y = f(x) as a table over every whole x the curve covers: exact, with x
    kept within it. Compile made y whole only when f is whole at each of them."""
    import math

    lo, hi = math.ceil(curve.points[0][0]), math.floor(curve.points[-1][0])
    if hi < lo:
        # No whole x on the curve at all: nothing can hold, as on every
        # other backend -- infeasible, not an invalid model.
        model.Add(cp_vars[curve.x] < 0)
        model.Add(cp_vars[curve.x] > 0)
        return
    table = [_whole(curve.value_at(Decimal(k)), f"the curve at {k}") for k in range(lo, hi + 1)]
    position = model.NewIntVar(0, hi - lo, "")
    model.Add(position == cp_vars[curve.x] - lo)
    model.AddElement(position, table, cp_vars[curve.y])


def _scaled(coeffs, rhs, quadratic, reach, what) -> ScaledRow:
    """`scaling.scale`, with its refusal in this module's words: the registry
    keeps an unscalable model away, so reaching this is a selection bug."""
    try:
        return scale(coeffs, rhs, quadratic, reach, what)
    except NotScalable as exc:
        raise NotIntegral(f"cp-sat takes whole numbers, and {exc}") from exc


def _objective(value: float, goal: ScaledRow) -> float | int:
    """The objective in the model's own units. A whole-number objective keeps
    its integer shape; a scaled one is divided back exactly and reported at
    the platform's precision."""
    exact = Decimal(int(round(value))) / goal.factor
    # A common factor divided out of whole coefficients comes back whole.
    if exact == exact.to_integral_value():
        return int(exact)
    return report_quantity(exact)


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


def _build(compiled: Compiled, *, assumable: bool = False):
    """The model's variables, rules, intervals and curves. With `assumable`,
    each rule instance is also enforced by a literal of its own, returned
    by position in `compiled.constraints` -- what `core` assumes."""
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

    reach = reach_of(compiled)
    intervals = {
        key: _interval(model, cp_vars, spec) for key, spec in compiled.intervals.items()
    }
    literals: dict[int, Any] = {}
    for i, c in enumerate(compiled.constraints):
        if c.schedule is not None:
            _add_schedule(model, intervals, c)
            continue
        literal = model.NewBoolVar(f"holds_{i}") if assumable else None
        _add(model, cp_vars, c, product_of, reach, literal)
        if literal is not None:
            literals[i] = literal
    for curve in compiled.pwl:
        _add_curve(model, cp_vars, curve)
    return model, cp_vars, product_of, reach, literals


def core(compiled: Compiled, *, time_limit: float = 10.0) -> list[int] | None:
    """Positions in `compiled.constraints` of a set of rule instances CP-SAT
    shows cannot all hold -- or None.

    Each instance is enforced by a literal of its own and every literal is
    assumed true; an infeasible solve then names, in
    `SufficientAssumptionsForInfeasibility`, assumptions that are enough to
    make it so. Exact for the whole-number model, where HiGHS's IIS of the
    relaxation can find nothing (`2x = 1` over whole x). Not necessarily
    irreducible: the caller shrinks it (`diagnose.explain`).

    None when CP-SAT cannot take the model, it is not shown infeasible in
    time, or it holds a scheduling rule: `NoOverlap` and `Cumulative` take
    no enforcement literal, so one could not be assumed away.
    """
    if any(c.schedule is not None for c in compiled.constraints):
        return None
    try:
        model, _, _, _, literals = _build(compiled, assumable=True)
    except (NotIntegral, ValueError):
        return None
    if not literals:
        return None
    model.AddAssumptions(list(literals.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    # The core is read from the sequential search's final conflict; a
    # portfolio of workers may prove infeasibility without one.
    solver.parameters.num_search_workers = 1
    if solver.Solve(model) != cp_model.INFEASIBLE:
        return None
    position = {literal.Index(): i for i, literal in literals.items()}
    found = sorted(position[index] for index in solver.SufficientAssumptionsForInfeasibility() if index in position)
    return found or None


def _add(model: cp_model.CpModel, cp_vars: dict, c: Constraint, product_of, reach, literal=None) -> None:
    """`left relation right`, rearranged to `terms relation rhs` because
    CP-SAT wants the variables on one side, and scaled to whole numbers
    (`scaling.scale`) -- a no-op but for a common factor when they already
    were. A quadratic rule's products are held exactly, as in the objective
    (`product_of`)."""
    coeffs: dict[Any, Decimal] = dict(c.left.coeffs)
    for key, coeff in c.right.coeffs.items():
        coeffs[key] = coeffs.get(key, Decimal(0)) - coeff
    row = _scaled(coeffs, c.right.const - c.left.const, c.quadratic, reach, f"rule {c.id!r}")
    rhs = row.rhs

    expr = sum(cp_vars[k] * v for k, v in row.coeffs.items()) if row.coeffs else 0
    for (a, b), coeff in row.quadratic.items():
        expr += product_of(a, b) * coeff

    if c.relation in (">=",):
        added = model.Add(expr >= rhs)
    elif c.relation in ("<=",):
        added = model.Add(expr <= rhs)
    elif c.relation in ("=", "=="):
        added = model.Add(expr == rhs)
    elif c.relation == "<":
        added = model.Add(expr <= rhs - 1)
    elif c.relation == ">":
        added = model.Add(expr >= rhs + 1)
    else:  # pragma: no cover -- the contract's relation vocabulary
        raise ValueError(f"unknown relation {c.relation!r}")
    enforce = []
    if c.when is not None:
        # The rule holds while its switch is set: an enforcement literal,
        # exact, with no big number standing in for "off".
        key, value = c.when
        switch = cp_vars[key]
        enforce.append(switch if value == 1 else switch.Not())
    if literal is not None:
        # Its own literal, to be assumed (`core`).
        enforce.append(literal)
    if enforce:
        added.OnlyEnforceIf(enforce)
