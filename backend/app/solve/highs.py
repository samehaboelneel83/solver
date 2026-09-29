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
import signal
import subprocess
import sys
import tempfile
import threading
from decimal import Decimal
from importlib.metadata import version as _pkg_version
from importlib.util import find_spec
from pathlib import Path

from app.api.quantity import report_quantity
from app.solve.compile import Compiled, Constraint, Variable
from app.solve.result import Solution, fold_duals
from app.solve.progress import report
from app.solve.stop import interrupt_when

_BACKEND_ROOT = str(Path(__file__).resolve().parents[2])
_HIGHS_VERSION = None
try:
    _HIGHS_VERSION = _pkg_version("highspy")
except Exception:
    pass

_available: bool | None = None

# How long a child asked to stop may take to write out its answer.
_STOP_GRACE = 3.0


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
    on_progress=None,
    hint: dict | None = None,
    solver_params: dict | None = None,
) -> Solution:
    if should_stop is not None and should_stop():
        return _blank("unknown")
    from app.solve.params import check as check_params

    # Checked here, in the parent, so a refusal names the option rather than
    # a child that died.
    options = check_params("highs", solver_params)
    if not available():
        raise RuntimeError("highs is not available in this build")

    return _in_child(
        {
            "compiled": compiled,
            "time_limit": time_limit,
            "workers": workers,
            "seed": seed,
            "gap_rel": gap_rel,
            "progress": on_progress is not None,
            "hint": hint,
            "options": options,
        },
        time_limit=time_limit,
        should_stop=should_stop,
        on_progress=on_progress,
    )


def iis(compiled: Compiled, *, time_limit: float = 10.0) -> list[int] | None:
    """The positions in `compiled.constraints` of an irreducible infeasible
    subset HiGHS finds in the model's **linear relaxation** -- or None when
    it finds none: the relaxation is feasible (only the whole-number model
    is not), the model holds something HiGHS cannot take as a row, or HiGHS
    is not in this build.

    A core, not a verdict: the relaxation's IIS is infeasible for the model
    too (its answers are a subset), but the caller confirms it with the
    run's own backend and shrinks it there (`diagnose.explain`).
    """
    if not available():
        return None
    if compiled.pwl or compiled.functions or compiled.intervals or any(
        c.quadratic or c.when is not None or c.schedule is not None for c in compiled.constraints
    ):
        return None
    try:
        return _in_child({"mode": "iis", "compiled": compiled, "time_limit": time_limit}, time_limit=time_limit)
    except RuntimeError:
        # A core is an optimisation of the diagnosis, never a condition of
        # it: HiGHS's IIS search does not stop at `time_limit` (seen on a
        # large facility model), and the child is killed at its deadline.
        # No core, and the full search runs.
        return None


def _in_child(payload: dict, *, time_limit: float, should_stop=None, on_progress=None):
    """Run `highs_worker` on `payload` and return what it wrote."""
    with tempfile.TemporaryDirectory(prefix="solver-highs-") as tmp:
        req_path = os.path.join(tmp, "in.pkl")
        out_path = os.path.join(tmp, "out.pkl")
        with open(req_path, "wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.solve.highs_worker", req_path, out_path],
            cwd=_BACKEND_ROOT,
            env=_child_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # The child reports progress as one JSON line per event on stdout
        # (HiGHS itself prints nothing: `output_flag` is off). Both pipes are
        # drained on threads, so neither can fill and stall the child.
        errors: list[bytes] = []
        readers = [
            threading.Thread(target=_relay_progress, args=(proc.stdout, on_progress), daemon=True),
            threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True),
        ]
        for reader in readers:
            reader.start()
        def stop_child() -> None:
            # SIGTERM first: the child turns it into HiGHS's own cancel and
            # writes out the best answer it has. Killed only if it has not
            # gone within `_STOP_GRACE` seconds.
            proc.terminate()
            timer = threading.Timer(_STOP_GRACE, lambda: proc.poll() is None and proc.kill())
            timer.daemon = True
            timer.start()

        try:
            with interrupt_when(should_stop, stop_child):
                proc.wait(timeout=max(time_limit + 15.0, 20.0))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise RuntimeError("highs worker timed out") from None
        for reader in readers:
            reader.join(timeout=5)
        stderr = b"".join(errors)

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
    progress: bool = False,
    hint: dict | None = None,
    options: dict | None = None,
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
    for name, value in (options or {}).items():
        solver.setOptionValue(name, value)

    # The whole model goes in as arrays, a handful of calls however large it
    # is (target roadmap D7). One `addVariable`/`addConstr` per column and row
    # cost two seconds of Python on a 200,000-entry model HiGHS then solved
    # in three milliseconds.
    if compiled.pwl:  # pragma: no cover -- solve_compiled rewrites curves first
        raise ValueError("a piecewise curve reached a backend that holds none")
    if compiled.functions:  # pragma: no cover -- the registry offers these to SCIP only
        raise ValueError("a function reached a backend that holds none")
    keys = list(compiled.variables)
    position = {key: i for i, key in enumerate(keys)}
    _add_columns(highspy, solver, compiled, keys)
    added_ids = _add_rows(highspy, solver, compiled.constraints, position)
    has_objective = bool(
        compiled.objective.coeffs or compiled.objective.const or compiled.objective_quadratic
    )
    # HiGHS solves a quadratic program as a minimisation only, so a maximised
    # QP goes in negated and its value comes out negated back.
    sign = -1.0 if compiled.objective_quadratic and compiled.sense != "minimize" else 1.0
    if has_objective:
        _set_objective(highspy, solver, compiled, position, sign)
        if compiled.objective_quadratic:
            solver.passHessian(_hessian(highspy, len(keys), position, compiled.objective_quadratic, sign))

    if hint:
        # A partial starting point (`app.solve.warm`): HiGHS completes and
        # checks it, and uses it as an incumbent if it holds. Given after the
        # objective: setting the objective drops a start given before it, so
        # HiGHS never tried one (found by queue R13's bench).
        import numpy as np

        known = [(position[key], float(value)) for key, value in hint.items() if key in position]
        if known:
            solver.setSolution(
                len(known),
                np.array([i for i, _ in known], dtype=np.int32),
                np.array([v for _, v in known], dtype=np.float64),
            )

    if progress:
        _subscribe_progress(solver, sign)

    # `solve()` with keyboard-interrupt handling, not `run()`: HiGHS then
    # solves on a thread, and an interrupt -- the SIGTERM the parent sends
    # to stop a run, turned into one below -- calls `cancelSolve()`, which
    # ends the search keeping the incumbent. `run()` could only be killed.
    solver.HandleKeyboardInterrupt = True
    previous = signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        solver.solve()
    finally:
        signal.signal(signal.SIGTERM, previous)

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
        ranges=_lp_ranges(solver, compiled, keys, values) if status == "optimal" else None,
    )


def iis_in_process(compiled: Compiled, *, time_limit: float = 10.0) -> list[int] | None:
    """Called only from `highs_worker`. Rows are added one per constraint, in
    order, so a row index is a position in `compiled.constraints`."""
    import highspy

    solver = highspy.Highs()
    solver.setOptionValue("output_flag", False)
    solver.setOptionValue("time_limit", float(time_limit))
    keys = list(compiled.variables)
    position = {key: i for i, key in enumerate(keys)}
    # The relaxation: HiGHS computes an IIS of an LP. Whole numbers are
    # dropped, and there is no objective -- only feasibility is asked.
    _add_columns(highspy, solver, compiled, keys, relax=True)
    _add_rows(highspy, solver, compiled.constraints, position)
    solver.run()
    if _status(solver.getModelStatus()) != "infeasible":
        return None
    # From the LP, *not* made irreducible by HiGHS: on a 12,340-row facility
    # model that step took 49 s for a core 2% smaller (334 rows, not 340),
    # against 1 s without it -- and HiGHS does not stop it at `time_limit`.
    # The caller shrinks the core to irreducible anyway, with its own
    # backend (bench/results/2026-09-23-native-iis.md).
    solver.setOptionValue("iis_strategy", int(highspy.IisStrategy.kIisStrategyFromLp))
    status, found = solver.getIis()
    if status != highspy.HighsStatus.kOk or not found.valid_:
        return None
    rows = sorted(int(i) for i in found.row_index_)
    return rows or None


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


#: At most this many rows and this many costs are ranged on one run.
RANGED = 500


def _lp_ranges(solver, compiled: Compiled, keys: list, values) -> dict | None:
    """LP ranging (queue R27) at a proven optimum of a linear program, in the model's own terms.

    **Rows**: every rule instance whose dual is not zero (the binding ones -- a slack rule's
    limit may move freely until it binds), with its limit (`rhs`, the right side less the left's
    constant), the dual (what one more unit of the limit is worth to the goal) and the range the
    limit may move in with that dual still exact. **Costs**: each used decision's goal
    coefficient and the range it may move in with the plan unchanged. HiGHS reports both as the
    bounds of the current basis; checked by moving each number just inside and just outside.
    Nothing for a model with a whole-number decision or a quadratic goal."""
    if any(spec.is_integral for spec in compiled.variables.values()) or compiled.objective_quadratic:
        return None
    try:
        status, found = solver.getRanging()
        duals = list(solver.getSolution().row_dual)
    except Exception:
        return None
    if int(status) != 0 or len(duals) != len(compiled.constraints):
        return None
    rows = []
    for i, c in enumerate(compiled.constraints):
        if abs(duals[i]) < 1e-9 or len(rows) >= RANGED:
            continue
        rows.append({
            "rule": c.id, "index": c.index, "rhs": _finite(float(c.right.const - c.left.const)),
            "dual": report_quantity(float(duals[i])),
            "low": _finite(float(found.row_bound_dn.value_[i])), "high": _finite(float(found.row_bound_up.value_[i])),
        })
    costs = []
    for i, key in enumerate(keys):
        if key[0].startswith("__") or abs(float(values[i])) < 1e-9 or len(costs) >= RANGED:
            continue
        costs.append({
            "var": key[0], "index": list(key[1]), "cost": _finite(float(compiled.objective.coeffs.get(key, 0))),
            "low": _finite(float(found.col_cost_dn.value_[i])), "high": _finite(float(found.col_cost_up.value_[i])),
        })
    return {"rows": rows, "costs": costs}


def _finite(value: float) -> float | None:
    """A number for JSON; an unlimited end of a range is None."""
    if value != value or abs(value) >= 1e30:
        return None
    return report_quantity(value)


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


# How often the child writes a bound-only line: HiGHS's MIP interrupt
# callback fires constantly, and the parent throttles again anyway.
_BOUND_EVERY = 0.5


def _subscribe_progress(solver, sign: float) -> None:
    """In the child: print each better answer, and the bound now and then,
    as JSON lines for the parent (`_relay_progress`)."""
    import json
    import time

    last = [0.0]

    def line(kind: str, data) -> None:
        print(
            json.dumps(
                {
                    "kind": kind,
                    "t": float(data.running_time),
                    "objective": float(data.objective_function_value) * sign,
                    "bound": float(data.mip_dual_bound) * sign,
                },
                allow_nan=True,
            ),
            flush=True,
        )

    def improving(event) -> None:
        line("incumbent", event.data_out)

    def interrupt(event) -> None:
        now = time.monotonic()
        if now - last[0] >= _BOUND_EVERY:
            last[0] = now
            line("bound", event.data_out)

    solver.cbMipImprovingSolution.subscribe(improving)
    solver.cbMipInterrupt.subscribe(interrupt)


def _relay_progress(stream, on_progress) -> None:
    """In the parent: turn the child's progress lines into `on_progress`."""
    import json

    for raw in stream:
        if on_progress is None:
            continue
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        report(on_progress, event.get("kind", "bound"), event.get("t", 0), event.get("objective"), event.get("bound"))


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
        # Stopped on request: an answer if it has one (`_has_solution`
        # decides), otherwise nothing.
        ("kInterrupt", "feasible"),
        ("kHighsInterrupt", "feasible"),
    ):
        code = getattr(highspy.HighsModelStatus, name, None)
        if code is not None:
            mapping[code] = ours
    return mapping.get(model_status, "error")


def _read(spec: Variable, value: float) -> float | int:
    return report_quantity(value, integral=spec.is_integral)


def _report(compiled: Compiled, value: float) -> float | int:
    return report_quantity(value, integral=compiled.is_integral)


def _hessian(highspy, dim: int, position: dict, quadratic: dict, sign: float):
    """The objective's quadratic part as HiGHS takes it.

    HiGHS minimises `c'x + 1/2 x'Qx`, reading Q's lower triangle column by
    column. A term `c * x_i * x_j` (i != j) is `1/2 (Q_ij + Q_ji) x_i x_j`
    with Q symmetric, so it contributes `c` to Q_ij; a square `c * x_i^2` is
    `1/2 Q_ii x_i^2`, so it contributes `2c` to the diagonal.
    """
    import numpy as np

    entries: dict[tuple[int, int], float] = {}
    for (a, b), coeff in quadratic.items():
        i, j = position[a], position[b]
        row, col = max(i, j), min(i, j)
        value = float(coeff) * sign * (2.0 if i == j else 1.0)
        entries[(row, col)] = entries.get((row, col), 0.0) + value

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


def _add_columns(highspy, solver, compiled: Compiled, keys: list, relax: bool = False) -> None:
    import numpy as np

    specs = [compiled.variables[key] for key in keys]
    lower = np.array([float(spec.lower) for spec in specs], dtype=np.float64)
    upper = np.array([float(spec.upper) for spec in specs], dtype=np.float64)
    solver.addVars(len(specs), lower, upper)
    integral = [] if relax else [i for i, spec in enumerate(specs) if spec.is_integral]
    if integral:
        solver.changeColsIntegrality(
            len(integral),
            np.array(integral, dtype=np.int32),
            np.array([highspy.HighsVarType.kInteger] * len(integral)),
        )


def _add_rows(highspy, solver, constraints: list[Constraint], position: dict) -> list[str]:
    """Every rule as one row, all in one call. Returns the rule id of each row.

    A rule left with no variables still becomes a row -- an empty one whose
    bounds either hold or cannot. Dropping it, as this adapter once did, let a
    rule like `0 >= 1` vanish and a model that has no answer get one.
    """
    import numpy as np

    inf = highspy.kHighsInf
    lower, upper, starts, index, values, ids = [], [], [], [], [], []
    for c in constraints:
        coeffs, low, high = row_of(c, inf)
        starts.append(len(index))
        for key, coeff in coeffs.items():
            if coeff:
                index.append(position[key])
                values.append(float(coeff))
        lower.append(low)
        upper.append(high)
        ids.append(c.id)
    if ids:
        solver.addRows(
            len(ids),
            np.array(lower, dtype=np.float64),
            np.array(upper, dtype=np.float64),
            len(index),
            np.array(starts, dtype=np.int32),
            np.array(index, dtype=np.int32),
            np.array(values, dtype=np.float64),
        )
    return ids


def row_of(c: Constraint, inf: float) -> tuple[dict, float, float]:
    """A linear rule as `low <= sum(coeff * var) <= high`: both sides' terms
    on the left, both constants on the right. Shared with `app.solve.benders`."""
    if c.quadratic:  # pragma: no cover -- `quadratic-constraints` keeps it away
        raise ValueError(f"{c.id!r} is a quadratic rule, which this backend cannot take")
    if c.when is not None:  # pragma: no cover -- `indicator` keeps it away
        raise ValueError(f"{c.id!r} is a conditional rule, which this backend cannot take")
    coeffs: dict = dict(c.left.coeffs)
    for key, coeff in c.right.coeffs.items():
        coeffs[key] = coeffs.get(key, Decimal(0)) - coeff
    rhs = float(c.right.const - c.left.const)
    low, high = {
        ">=": (rhs, inf),
        "<=": (-inf, rhs),
        "=": (rhs, rhs),
        "==": (rhs, rhs),
        "<": (-inf, rhs - 1),
        ">": (rhs + 1, inf),
    }[c.relation]
    return coeffs, low, high


def _set_objective(highspy, solver, compiled: Compiled, position: dict, sign: float) -> None:
    import numpy as np

    costs = {position[key]: float(coeff) * sign for key, coeff in compiled.objective.coeffs.items() if coeff}
    if costs:
        solver.changeColsCost(
            len(costs),
            np.array(list(costs), dtype=np.int32),
            np.array(list(costs.values()), dtype=np.float64),
        )
    solver.changeObjectiveOffset(float(compiled.objective.const) * sign)
    solver.changeObjectiveSense(
        highspy.ObjSense.kMinimize
        if compiled.sense == "minimize" or compiled.objective_quadratic
        else highspy.ObjSense.kMaximize
    )
