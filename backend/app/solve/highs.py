"""A fourth backend: HiGHS, through `highspy`, in a child process.

OR-Tools' `CreateSolver("HIGHS")` is not HiGHS in this build -- it opens
PDLP -- so this adapter talks to the solver itself. The registry treats it
as a row: same `Backend.solve(Compiled)` interface as GLOP and the MILP
wrapper, capabilities declared as data.

**Why a child process.** `highspy` and `ortools` both ship `libHighs`.
Whichever loads first poisons the other (`undefined symbol`). The roadmap
already wanted adapters as processes behind one interface; this is that,
for the one backend that cannot share the worker.

**What it takes.** Integer, binary and continuous variables, and fractional
coefficients -- LP, IP and MILP. Rank 1, so GLOP still wins a pure LP
(simplex is the right technique there) and CP-SAT still wins a pure integer
model. HiGHS wins the mixed case when it is installed, which is why it sits
ahead of SCIP/CBC in the registry rather than inside `milp.py`.
"""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
import tempfile
from decimal import Decimal
from importlib.metadata import version as _pkg_version
from importlib.util import find_spec
from pathlib import Path

from app.api.quantity import report_quantity
from app.solve.compile import Compiled, Constraint, Variable
from app.solve.result import Solution, fold_duals
from app.solve.stop import interrupt_when

_BACKEND_ROOT = str(Path(__file__).resolve().parents[2])
_HIGHS_VERSION = None
try:
    _HIGHS_VERSION = _pkg_version("highspy")
except Exception:
    pass

_available: bool | None = None


def available() -> bool:
    global _available
    if _available is None:
        _available = find_spec("highspy") is not None and _probe()
    return _available


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        _BACKEND_ROOT if not existing else os.pathsep.join((_BACKEND_ROOT, existing))
    )
    return env


def _probe() -> bool:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "app.solve.highs_worker", "--probe"],
            cwd=_BACKEND_ROOT,
            env=_child_env(),
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def solve(
    compiled: Compiled,
    *,
    time_limit: float = 10.0,
    workers: int = 8,
    should_stop=None,
    seed: int | None = None,
    gap_rel: float = 0.0,
) -> Solution:
    if should_stop is not None and should_stop():
        return _blank("unknown")
    if not available():
        raise RuntimeError("highs is not available in this build")

    with tempfile.TemporaryDirectory(prefix="solver-highs-") as tmp:
        req_path = os.path.join(tmp, "in.pkl")
        out_path = os.path.join(tmp, "out.pkl")
        with open(req_path, "wb") as handle:
            pickle.dump(
                {
                    "compiled": compiled,
                    "time_limit": time_limit,
                    "workers": workers,
                    "seed": seed,
                    "gap_rel": gap_rel,
                },
                handle,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.solve.highs_worker", req_path, out_path],
            cwd=_BACKEND_ROOT,
            env=_child_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            with interrupt_when(should_stop, proc.terminate):
                _, stderr = proc.communicate(timeout=max(time_limit + 15.0, 20.0))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise RuntimeError("highs worker timed out") from None

        if proc.returncode != 0:
            if should_stop is not None and should_stop():
                return _blank("unknown")
            msg = (stderr or b"").decode("utf-8", "replace")[-2000:]
            raise RuntimeError(f"highs worker failed: {msg}")

        with open(out_path, "rb") as handle:
            return pickle.load(handle)


def solve_in_process(
    compiled: Compiled,
    *,
    time_limit: float = 10.0,
    workers: int = 8,
    seed: int | None = None,
    gap_rel: float = 0.0,
) -> Solution:
    """Called only from `highs_worker`, in a process that has never imported ortools."""
    import highspy

    solver = highspy.Highs()
    solver.setOptionValue("output_flag", False)
    solver.setOptionValue("time_limit", float(time_limit))
    if workers > 1:
        solver.setOptionValue("threads", int(workers))
    if seed is not None:
        solver.setOptionValue("random_seed", int(seed))
    # HiGHS's own default is 1e-4: "optimal" up to 0.01% short of the best.
    # The setting decides, 0 by default.
    solver.setOptionValue("mip_rel_gap", float(gap_rel))

    variables = {key: _declare(solver, highspy, spec) for key, spec in compiled.variables.items()}

    added_ids: list[str] = []
    for constraint in compiled.constraints:
        if _add(solver, variables, constraint):
            added_ids.append(constraint.id)

    has_objective = bool(
        compiled.objective.coeffs or compiled.objective.const or compiled.objective_quadratic
    )
    # HiGHS solves a quadratic program as a minimisation only, so a maximised
    # QP goes in negated and its value comes out negated back.
    sign = -1.0 if compiled.objective_quadratic and compiled.sense != "minimize" else 1.0
    if has_objective:
        expression = _expression(
            variables, {key: coeff * _decimal(sign) for key, coeff in compiled.objective.coeffs.items()}
        )
        offset = float(compiled.objective.const) * sign
        objective_sense = (
            highspy.ObjSense.kMinimize
            if compiled.sense == "minimize" or compiled.objective_quadratic
            else highspy.ObjSense.kMaximize
        )
        # `setObjective`, not `minimize()`/`maximize()`: those also SOLVE,
        # and the `run()` below then solved every model a second time.
        if expression is not None:
            solver.setObjective(expression + offset, objective_sense)
        else:
            # A purely quadratic objective has no linear part, and
            # `setObjective` refuses a bare number: set its pieces directly.
            solver.changeObjectiveSense(objective_sense)
            solver.changeObjectiveOffset(offset)
        if compiled.objective_quadratic:
            solver.passHessian(_hessian(highspy, solver, variables, compiled.objective_quadratic, sign))

    solver.run()

    status = _status(solver.getModelStatus())
    if status == "feasible" and not _has_solution(solver):
        # A limit (time, iterations) reached before any feasible point was
        # found. The column values HiGHS holds then are not an answer --
        # reading them gave invented numbers, or an infinite objective --
        # so this is `unknown`: stopped before deciding anything.
        status = "unknown"
    solved = status in ("optimal", "feasible")
    values = solver.allVariableValues() if solved else []
    keys = list(compiled.variables)

    return Solution(
        status=status,
        optimal=status == "optimal",
        objective=(
            _report(compiled, solver.getObjectiveValue() * sign)
            if solved and has_objective
            else None
        ),
        assignments=(
            {
                key: _read(compiled.variables[key], values[i])
                for i, key in enumerate(keys)
            }
            if solved
            else {}
        ),
        best_bound=_bound(solver, compiled, status, sign) if solved and has_objective else None,
        wall_seconds=round(solver.getRunTime(), 3),
        solver=f"highs {_HIGHS_VERSION}",
        duals=_lp_duals(solver, compiled, added_ids) if solved else None,
        reduced_costs=_lp_reduced(solver, compiled, keys) if solved else None,
    )


def _lp_duals(solver, compiled: Compiled, added_ids: list[str]) -> dict[str, float] | None:
    if any(spec.is_integral for spec in compiled.variables.values()):
        return None
    getter = getattr(solver, "getDualConstraintValues", None)
    if getter is None:
        return None
    try:
        raw = list(getter())
    except Exception:
        return None
    if len(raw) != len(added_ids):
        return None
    return fold_duals(
        zip(added_ids, (report_quantity(float(value)) for value in raw))
    )


def _lp_reduced(solver, compiled: Compiled, keys: list) -> dict | None:
    if any(spec.is_integral for spec in compiled.variables.values()):
        return None
    getter = getattr(solver, "getReducedCosts", None) or getattr(
        solver, "allReducedCosts", None
    )
    if getter is None:
        return None
    try:
        raw = list(getter())
    except Exception:
        return None
    if len(raw) != len(keys):
        return None
    return {key: report_quantity(float(value)) for key, value in zip(keys, raw)}


def _blank(status: str) -> Solution:
    return Solution(
        status=status,
        optimal=False,
        objective=None,
        assignments={},
        wall_seconds=0.0,
        solver=f"highs {_HIGHS_VERSION}",
    )


def _bound(solver, compiled: Compiled, status: str, sign: float) -> float | None:
    """The proven limit on the goal, on the same scale as the objective.

    A mixed-integer model has HiGHS's own dual bound. A continuous one is
    solved to optimality or not at all, and its optimum is its own bound.
    """
    if any(spec.is_integral for spec in compiled.variables.values()):
        try:
            bound = float(solver.getInfo().mip_dual_bound)
        except Exception:  # pragma: no cover
            return None
        return bound * sign if abs(bound) < 1e20 else None
    return solver.getObjectiveValue() * sign if status == "optimal" else None


def _has_solution(solver) -> bool:
    """Whether HiGHS holds a primal-feasible point (its solution status 2)."""
    try:
        return int(solver.getInfo().primal_solution_status) == 2
    except Exception:  # pragma: no cover -- every pinned highspy has it
        return False


def _status(model_status) -> str:
    import highspy

    mapping = {}
    for name, ours in (
        ("kOptimal", "optimal"),
        ("kTimeLimit", "feasible"),
        ("kIterationLimit", "feasible"),
        ("kSolutionLimit", "feasible"),
        ("kInfeasible", "infeasible"),
        ("kUnbounded", "unbounded"),
        ("kUnboundedOrInfeasible", "unknown"),
        ("kInterrupt", "unknown"),
        ("kHighsInterrupt", "unknown"),
    ):
        code = getattr(highspy.HighsModelStatus, name, None)
        if code is not None:
            mapping[code] = ours
    return mapping.get(model_status, "error")


def _declare(solver, highspy, spec: Variable):
    if spec.domain == "binary":
        return solver.addBinary()
    if spec.domain == "integer":
        return solver.addVariable(
            lb=float(spec.lower), ub=float(spec.upper), type=highspy.HighsVarType.kInteger
        )
    return solver.addVariable(lb=float(spec.lower), ub=float(spec.upper))


def _read(spec: Variable, value: float) -> float | int:
    return report_quantity(value, integral=spec.is_integral)


def _report(compiled: Compiled, value: float) -> float | int:
    return report_quantity(value, integral=compiled.is_integral)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _hessian(highspy, solver, variables: dict, quadratic: dict, sign: float):
    """The objective's quadratic part as HiGHS takes it.

    HiGHS minimises `c'x + 1/2 x'Qx`, reading Q's lower triangle column by
    column. A term `c * x_i * x_j` (i != j) is `1/2 (Q_ij + Q_ji) x_i x_j`
    with Q symmetric, so it contributes `c` to Q_ij; a square `c * x_i^2` is
    `1/2 Q_ii x_i^2`, so it contributes `2c` to the diagonal.
    """
    import numpy as np

    entries: dict[tuple[int, int], float] = {}
    for (a, b), coeff in quadratic.items():
        i, j = variables[a].index, variables[b].index
        row, col = max(i, j), min(i, j)
        value = float(coeff) * sign * (2.0 if i == j else 1.0)
        entries[(row, col)] = entries.get((row, col), 0.0) + value

    dim = solver.getNumCol()
    by_column: list[list[tuple[int, float]]] = [[] for _ in range(dim)]
    for (row, col), value in sorted(entries.items(), key=lambda item: (item[0][1], item[0][0])):
        by_column[col].append((row, value))
    start, index, values = [0], [], []
    for column in by_column:
        for row, value in column:
            index.append(row)
            values.append(value)
        start.append(len(index))

    hessian = highspy.HighsHessian()
    hessian.dim_ = dim
    hessian.format_ = highspy.HessianFormat.kTriangular
    hessian.start_ = np.array(start, dtype=np.int32)
    hessian.index_ = np.array(index, dtype=np.int32)
    hessian.value_ = np.array(values, dtype=np.float64)
    return hessian


def _expression(variables: dict, coeffs: dict):
    parts = [variables[key] * float(coeff) for key, coeff in coeffs.items() if coeff]
    if not parts:
        return None
    total = parts[0]
    for part in parts[1:]:
        total = total + part
    return total


def _add(solver, variables: dict, c: Constraint) -> bool:
    if c.quadratic:  # pragma: no cover -- `quadratic-constraints` keeps it away
        raise ValueError(f"{c.id!r} is a quadratic rule, which this backend cannot take")
    coeffs: dict = dict(c.left.coeffs)
    for key, coeff in c.right.coeffs.items():
        coeffs[key] = coeffs.get(key, Decimal(0)) - coeff
    rhs = float(c.right.const - c.left.const)
    expression = _expression(variables, coeffs)
    if expression is None:
        return False

    if c.relation == ">=":
        solver.addConstr(expression >= rhs)
    elif c.relation == "<=":
        solver.addConstr(expression <= rhs)
    elif c.relation in ("=", "=="):
        solver.addConstr(expression == rhs)
    elif c.relation == "<":
        solver.addConstr(expression <= rhs - 1)
    elif c.relation == ">":
        solver.addConstr(expression >= rhs + 1)
    else:  # pragma: no cover -- the contract's relation vocabulary
        raise ValueError(f"unknown relation {c.relation!r}")
    return True
