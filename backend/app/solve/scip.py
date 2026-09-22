"""A fifth backend: SCIP, through PySCIPOpt, as the global quadratic solver.

**Why it exists.** Stage 2 of the nonlinear roadmap refused two kinds of
model on purpose: a continuous quadratic objective that is not proven convex,
and a quadratic objective over a mix of whole-number and continuous
decisions. Both were refused because the only solvers here that take a
quadratic objective either need it convex (HiGHS) or need every decision
whole (CP-SAT). Solving them locally would give an answer that might only be
the best nearby, labelled "optimal".

SCIP closes both without that risk. It is spatial branch-and-bound: it
bounds a nonconvex product from below and above on every branch and keeps
splitting until the bounds meet, so an `optimal` from it is a proven global
optimum (to its gap tolerance, which is zero by default here) -- the same
claim every other backend in the registry makes, which is what lets it
declare `proves="global"`. When the clock runs out first it says so, and
the run is `feasible` with no claim about being best.

**Where it sits.** Rank 2, behind everything: a convex QP still goes to
HiGHS and an all-integer one to CP-SAT, which are faster on their own
ground. SCIP only takes what nothing else can.

**Quadratic rules** (a product of two decisions in a rule) go in unchanged:
SCIP takes a quadratic constraint natively, convex or not.

**How the objective goes in.** SCIP's objective is linear. The quadratic
part is moved into one constraint on an auxiliary variable `t` -- `t >= q(x)`
when minimising, `t <= q(x)` when maximising -- and `t` joins the objective.
At the optimum the constraint is tight, so the objective value is exact.

**In-process, unlike HiGHS.** PySCIPOpt bundles its own SCIP and does not
clash with OR-Tools' copy the way `libHighs` does; the suite exercises both
in one interpreter.
"""

from __future__ import annotations

from importlib.metadata import version as _pkg_version
from importlib.util import find_spec

from app.api.quantity import report_quantity
from app.solve.compile import Compiled, Constraint, Variable
from app.solve.result import Solution
from app.solve.progress import report
from app.solve.stop import interrupt_when

_available: bool | None = None


def available() -> bool:
    global _available
    if _available is None:
        _available = find_spec("pyscipopt") is not None
    return _available


# SCIP's status words, onto the platform's. A time limit or an interrupt
# with an answer in hand is `feasible`: an answer, no claim it is best.
_STOPPED = {"timelimit", "userinterrupt", "nodelimit", "gaplimit", "sollimit", "memlimit"}


def solve(
    compiled: Compiled,
    *,
    time_limit: float = 10.0,
    workers: int = 1,
    should_stop=None,
    seed: int | None = None,
    gap_rel: float = 0.0,
    on_progress=None,
) -> Solution:
    import pyscipopt

    model = pyscipopt.Model()
    model.hideOutput()
    model.setParam("limits/time", float(time_limit))
    if seed is not None:
        model.setParam("randomization/randomseedshift", int(seed))
    model.setParam("limits/gap", float(gap_rel))

    variables = {key: _declare(model, key, spec) for key, spec in compiled.variables.items()}
    for constraint in compiled.constraints:
        _add(model, variables, constraint)

    objective = pyscipopt.quicksum(
        float(coeff) * variables[key] for key, coeff in compiled.objective.coeffs.items()
    )
    if compiled.objective_quadratic:
        quadratic = pyscipopt.quicksum(
            float(coeff) * variables[a] * variables[b]
            for (a, b), coeff in compiled.objective_quadratic.items()
        )
        t = model.addVar(name="objective_quadratic", lb=None, ub=None)
        if compiled.sense == "minimize":
            model.addCons(t >= quadratic)
        else:
            model.addCons(t <= quadratic)
        objective = objective + t
    has_objective = bool(compiled.objective.coeffs or compiled.objective_quadratic)
    if has_objective:
        model.setObjective(objective, compiled.sense)

    # SCIP clears an interrupt when `optimize()` starts, so one asked for
    # before that would be lost and the model solved anyway. Honour it here.
    if should_stop is not None and should_stop():
        return Solution(
            status="unknown",
            optimal=False,
            objective=None,
            assignments={},
            wall_seconds=0.0,
            solver=_name(),
        )

    if on_progress is not None and has_objective:
        model.includeEventhdlr(_progress_handler(on_progress), "progress", "reports each better answer and bound")

    def interrupt() -> None:
        # From the watcher thread; SCIP refuses outside its solving stage,
        # which only means the solve has already ended.
        try:
            model.interruptSolve()
        except Exception:
            pass

    with interrupt_when(should_stop, interrupt):
        model.optimize()

    scip_status = model.getStatus()
    solved = model.getNSols() > 0 and scip_status not in ("infeasible", "unbounded", "inforunbd")
    if scip_status == "optimal":
        status = "optimal"
    elif scip_status == "infeasible":
        status = "infeasible"
    elif scip_status == "unbounded":
        status = "unbounded"
    elif solved and scip_status in _STOPPED:
        status = "feasible"
    else:
        status = "unknown"

    best = model.getBestSol() if solved else None
    bound = model.getDualbound() if best is not None and has_objective else None
    return Solution(
        status=status,
        optimal=status == "optimal",
        objective=(
            report_quantity(model.getSolObjVal(best), integral=compiled.is_integral)
            if best is not None and has_objective
            else None
        ),
        assignments=(
            {
                key: _read(compiled.variables[key], model.getSolVal(best, var))
                for key, var in variables.items()
            }
            if best is not None
            else {}
        ),
        best_bound=bound if bound is not None and abs(bound) < 1e20 else None,
        wall_seconds=round(model.getSolvingTime(), 3),
        solver=_name(),
    )


def _progress_handler(on_progress):
    """An event handler for SCIP's better-answer and better-bound events."""
    import pyscipopt

    class Progress(pyscipopt.Eventhdlr):
        def eventinit(self):
            self.model.catchEvent(pyscipopt.SCIP_EVENTTYPE.BESTSOLFOUND, self)
            self.model.catchEvent(pyscipopt.SCIP_EVENTTYPE.DUALBOUNDIMPROVED, self)

        def eventexit(self):
            self.model.dropEvent(pyscipopt.SCIP_EVENTTYPE.BESTSOLFOUND, self)
            self.model.dropEvent(pyscipopt.SCIP_EVENTTYPE.DUALBOUNDIMPROVED, self)

        def eventexec(self, event):
            model = self.model
            found = event.getType() == pyscipopt.SCIP_EVENTTYPE.BESTSOLFOUND
            best = model.getBestSol() if model.getNSols() else None
            report(
                on_progress,
                "incumbent" if found else "bound",
                model.getSolvingTime(),
                model.getSolObjVal(best) if best is not None else None,
                model.getDualbound(),
            )

    return Progress()


def _name() -> str:
    return f"scip (pyscipopt {_pkg_version('pyscipopt')})"


def _declare(model, key, spec: Variable):
    name = f"{key[0]}[{','.join(key[1])}]"
    if spec.domain == "binary":
        return model.addVar(name=name, vtype="B")
    vtype = "I" if spec.domain == "integer" else "C"
    return model.addVar(name=name, vtype=vtype, lb=float(spec.lower), ub=float(spec.upper))


def _read(spec: Variable, value: float) -> float | int:
    """Rounded when integral, six places when continuous -- as `milp._read`."""
    return report_quantity(value, integral=spec.is_integral)


def _add(model, variables: dict, c: Constraint) -> None:
    """`left relation right`, rearranged so the variables sit on one side."""
    import pyscipopt

    coeffs: dict = dict(c.left.coeffs)
    for key, coeff in c.right.coeffs.items():
        coeffs[key] = coeffs.get(key, 0) - coeff
    coeffs = {key: coeff for key, coeff in coeffs.items() if coeff}
    rhs = float(c.right.const - c.left.const)
    if not coeffs and not c.quadratic:
        # Nothing left to decide: SCIP refuses a constraint on a constant, so
        # a true one is dropped and a false one stands as `0 >= 1`.
        if not _holds(0.0, c.relation, rhs):
            never = model.addVar(name=f"{c.id}_cannot_hold", lb=0, ub=0)
            model.addCons(never >= 1)
        return
    expression = pyscipopt.quicksum(float(coeff) * variables[key] for key, coeff in coeffs.items())
    if c.quadratic:
        # A quadratic rule goes in as it is: SCIP bounds each product on
        # every branch, so a nonconvex rule is searched, not approximated.
        expression = expression + pyscipopt.quicksum(
            float(coeff) * variables[a] * variables[b] for (a, b), coeff in c.quadratic.items()
        )

    if c.relation == ">=":
        model.addCons(expression >= rhs)
    elif c.relation == "<=":
        model.addCons(expression <= rhs)
    elif c.relation in ("=", "=="):
        model.addCons(expression == rhs)
    elif c.relation == "<":
        model.addCons(expression <= rhs - 1)
    elif c.relation == ">":
        model.addCons(expression >= rhs + 1)
    else:  # pragma: no cover -- the contract's relation vocabulary
        raise ValueError(f"unknown relation {c.relation!r}")


def _holds(value: float, relation: str, rhs: float) -> bool:
    return {
        ">=": value >= rhs,
        "<=": value <= rhs,
        "=": value == rhs,
        "==": value == rhs,
        "<": value <= rhs - 1,
        ">": value >= rhs + 1,
    }[relation]
