"""Benders decomposition, built on HiGHS (Epic engine, E-3).

A mixed model often has a small set of yes-or-no or whole-number decisions --
which sites to open, which machines to run -- and a large continuous part that
is easy once those are fixed: how much to ship, how much to make. Branch and
bound carries the whole continuous part into every node. Benders splits it:

* the **master** holds the whole-number decisions `y`, the rules on them
  alone, and one number `θ` standing in for the best cost of the continuous
  part;
* the **subproblem** is the continuous part with `y` fixed -- a linear
  program -- whose answer either prices `y` (an *optimality cut*) or shows
  that `y` leaves the continuous part with no answer (a *feasibility cut*).

Each round the master proposes `y` and a lower bound; the subproblem gives an
answer and so an upper bound, and a cut that removes the proposal unless it
was already priced right. The loop ends when the two bounds meet, which makes
the answer a proven, global optimum: every cut holds for every answer, so the
master's bound is a bound on the model.

**The cuts.** The subproblem's best cost `v(r)` is a convex function of its
right-hand side `r = b - A_y y`, and its row duals `π` are a slope of it at
`r̄`. So for every `y`::

    θ  >=  v(r̄) - π · A_y (y - ȳ)                    (optimality)

When `ȳ` leaves no answer, the same holds for the least total violation `w(r)`
of a phase-one program (every row given a slack both ways, their sum
minimised), which is zero exactly where an answer exists::

    0  >=  w(r̄) - μ · A_y (y - ȳ)                    (feasibility)

Both come from row duals alone -- the bounds on the continuous decisions stay
in the subproblem and need no dual of their own.

**What it takes.** A linear, mixed model -- whole-number and continuous
decisions both, the goal and every rule linear -- with the continuous part
bounded in the direction the goal pushes it (the master needs a floor for
`θ`). It is asked for by name (`automatic=False`): on most models HiGHS's own
branch and cut is faster, and Benders pays off on the structured ones.

**Where it runs.** In HiGHS's child process (`app.solve.highs_worker`), which
never loads ortools -- the same reason `app.solve.highs` runs there.
"""

from __future__ import annotations

import json
import math
import signal
import time

from app.api.quantity import report_quantity
from app.solve.compile import Compiled, Unsupported
from app.solve.result import Solution

#: A round's cut is taken as closing the gap when it would move `θ` by less than this.
_CUT_TOLERANCE = 1e-9
#: The gap at which the loop stops, below `service.OPTIMAL_GAP` so the answer is called optimal.
_GAP = 1e-7
#: A master that has proposed the same decisions this often is making no progress.
MAX_ROUNDS = 10_000


def refuse(compiled: Compiled) -> str | None:
    """Why this model is not one Benders can take -- or None."""
    if compiled.objective_quadratic:
        return "the goal multiplies decisions together; Benders is written on a linear goal"
    if compiled.pwl or compiled.functions or compiled.intervals:
        return "the model has a curve, a function or a schedule, which the subproblem cannot hold"
    for c in compiled.constraints:
        if c.quadratic or c.when is not None or c.schedule is not None:
            return f"the rule {c.id!r} is not linear, and both halves of Benders are"
    specs = list(compiled.variables.values())
    if not any(s.is_integral for s in specs):
        return "the model has no whole-number decisions to fix; solve it as a linear program"
    if not any(not s.is_integral for s in specs):
        return "the model has no continuous decisions to split off; there is no subproblem"
    sign = 1.0 if compiled.sense == "minimize" else -1.0
    for key, spec in compiled.variables.items():
        if spec.is_integral:
            continue
        cost = sign * float(compiled.objective.coeffs.get(key, 0))
        if (cost > 0 and not math.isfinite(float(spec.lower))) or (cost < 0 and not math.isfinite(float(spec.upper))):
            return f"{key[0]} has no bound in the direction the goal pushes it, so the master has no floor"
    return None


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
    from app.solve import highs

    reason = refuse(compiled)
    if reason is not None:
        raise Unsupported(f"benders: {reason}")
    if should_stop is not None and should_stop():
        return _blank("unknown")
    if not highs.available():
        raise RuntimeError("benders needs highs, which is not available in this build")
    return highs._in_child(
        {
            "mode": "benders",
            "compiled": compiled,
            "time_limit": time_limit,
            "workers": workers,
            "seed": seed,
            "gap_rel": gap_rel,
            "progress": on_progress is not None,
        },
        time_limit=time_limit,
        should_stop=should_stop,
        on_progress=on_progress,
    )


def _blank(status: str, wall: float = 0.0, solver: str = "benders") -> Solution:
    return Solution(status=status, optimal=False, objective=None, assignments={}, wall_seconds=round(wall, 3), solver=solver)


class _Lp:
    """A HiGHS program built once, whose rows' bounds move each round."""

    def __init__(self, highspy, *, workers: int, seed: int | None):
        self.h = highspy.Highs()
        self.h.setOptionValue("output_flag", False)
        if workers > 1:
            self.h.setOptionValue("threads", int(workers))
        if seed is not None:
            self.h.setOptionValue("random_seed", int(seed))
        self.h.HandleKeyboardInterrupt = True

    def run(self, left: float) -> str:
        from app.solve.highs import _has_solution, _status

        self.h.setOptionValue("time_limit", max(0.01, float(left)))
        self.h.solve()
        status = _status(self.h.getModelStatus())
        if status == "feasible" and not _has_solution(self.h):
            status = "unknown"
        return status


def solve_in_process(
    compiled: Compiled,
    *,
    time_limit: float = 10.0,
    workers: int = 8,
    seed: int | None = None,
    gap_rel: float = 0.0,
    progress: bool = False,
) -> Solution:
    """Called only from `highs_worker`, in a process that has never imported ortools."""
    import highspy
    import numpy as np

    from app.solve.highs import _HIGHS_VERSION, row_of

    started = time.monotonic()
    inf = highspy.kHighsInf
    # Minimised inside: a maximised goal goes in negated and comes out negated back.
    sign = 1.0 if compiled.sense == "minimize" else -1.0
    keys = list(compiled.variables)
    ys = [k for k in keys if compiled.variables[k].is_integral]
    xs = [k for k in keys if not compiled.variables[k].is_integral]
    ypos = {k: i for i, k in enumerate(ys)}
    xpos = {k: i for i, k in enumerate(xs)}
    ny, nx = len(ys), len(xs)
    cost = {k: sign * float(v) for k, v in compiled.objective.coeffs.items() if v}
    offset = sign * float(compiled.objective.const)
    cy = np.array([cost.get(k, 0.0) for k in ys])
    cx = np.array([cost.get(k, 0.0) for k in xs])

    master_rows, sub_rows = [], []
    for c in compiled.constraints:
        coeffs, low, high = row_of(c, inf)
        coeffs = {k: float(v) for k, v in coeffs.items() if v}
        if any(k in xpos for k in coeffs):
            sub_rows.append((
                {ypos[k]: v for k, v in coeffs.items() if k in ypos},
                {xpos[k]: v for k, v in coeffs.items() if k in xpos},
                low, high,
            ))
        else:
            master_rows.append(({ypos[k]: v for k, v in coeffs.items()}, low, high))

    def bounds(keys_):
        return (np.array([float(compiled.variables[k].lower) for k in keys_]),
                np.array([float(compiled.variables[k].upper) for k in keys_]))

    ylo, yhi = bounds(ys)
    xlo, xhi = bounds(xs)
    # The floor of θ: the continuous part's cost at the best corner of its box.
    theta_floor = float(sum(min(c * lo, c * hi) if c else 0.0 for c, lo, hi in zip(cx, xlo, xhi)))

    def add_rows(h, rows, width):
        if not rows:
            return
        starts, index, values, lower, upper = [], [], [], [], []
        for coeffs, low, high in rows:
            starts.append(len(index))
            for j, v in coeffs.items():
                index.append(j)
                values.append(v)
            lower.append(low)
            upper.append(high)
        h.addRows(len(rows), np.array(lower, dtype=np.float64), np.array(upper, dtype=np.float64), len(index),
                  np.array(starts, dtype=np.int32), np.array(index, dtype=np.int32), np.array(values, dtype=np.float64))

    # The master: y, then θ.
    master = _Lp(highspy, workers=workers, seed=seed)
    m = master.h
    m.setOptionValue("mip_rel_gap", 0.0)
    m.addVars(ny + 1, np.append(ylo, theta_floor), np.append(yhi, inf))
    m.changeColsIntegrality(ny, np.arange(ny, dtype=np.int32), np.array([highspy.HighsVarType.kInteger] * ny))
    m.changeColsCost(ny + 1, np.arange(ny + 1, dtype=np.int32), np.append(cy, 1.0))
    m.changeObjectiveOffset(offset)
    add_rows(m, master_rows, ny)

    # The subproblem: x alone, its rows' bounds set from ȳ each round.
    sub = _Lp(highspy, workers=workers, seed=seed)
    sub.h.addVars(nx, xlo, xhi)
    sub.h.changeColsCost(nx, np.arange(nx, dtype=np.int32), cx)
    add_rows(sub.h, [(xc, low, high) for _, xc, low, high in sub_rows], nx)
    nrows = len(sub_rows)
    ay = [yc for yc, _, _, _ in sub_rows]
    row_lo = np.array([low for _, _, low, _ in sub_rows])
    row_hi = np.array([high for _, _, _, high in sub_rows])

    # Phase one, built when first needed: x and a slack each way per row, their sum minimised.
    phase: list = []

    def phase_one():
        if not phase:
            p = _Lp(highspy, workers=workers, seed=seed)
            p.h.addVars(nx + 2 * nrows, np.concatenate([xlo, np.zeros(2 * nrows)]),
                        np.concatenate([xhi, np.full(2 * nrows, inf)]))
            p.h.changeColsCost(nx + 2 * nrows, np.arange(nx + 2 * nrows, dtype=np.int32),
                               np.concatenate([np.zeros(nx), np.ones(2 * nrows)]))
            rows = []
            for i, (_, xc, low, high) in enumerate(sub_rows):
                coeffs = dict(xc)
                coeffs[nx + i] = 1.0
                coeffs[nx + nrows + i] = -1.0
                rows.append((coeffs, low, high))
            add_rows(p.h, rows, nx + 2 * nrows)
            phase.append(p)
        return phase[0]

    def shift(ybar):
        """`A_y ȳ`, row by row."""
        return np.array([sum(v * ybar[j] for j, v in yc.items()) for yc in ay])

    def cut(duals, value, ybar):
        """`π·A_y y (+ θ) >= value + π·A_y ȳ`, as master coefficients over y."""
        g = np.zeros(ny)
        for i, yc in enumerate(ay):
            if abs(duals[i]) > _CUT_TOLERANCE:
                for j, v in yc.items():
                    g[j] += duals[i] * v
        return g, float(value + g @ ybar)

    def emit(kind, objective, bound):
        if progress:
            print(json.dumps({"kind": kind, "t": time.monotonic() - started,
                              "objective": None if objective is None else objective * sign,
                              "bound": None if bound is None or not math.isfinite(bound) else bound * sign}),
                  flush=True)

    best_ub, best_y, best_x = math.inf, None, None
    lb = -math.inf
    rounds = optimality = feasibility = 0
    status = None
    previous = signal.signal(signal.SIGTERM, signal.default_int_handler)
    tolerance = max(float(gap_rel), _GAP)
    try:
        while rounds < MAX_ROUNDS:
            left = time_limit - (time.monotonic() - started)
            if left <= 0:
                break
            rounds += 1
            found = master.run(left)
            if found == "infeasible":
                # Every cut holds for every answer: a master with none means the model has none.
                status = "infeasible"
                break
            if found == "unbounded":
                status = "unbounded"
                break
            if found not in ("optimal", "feasible"):
                break
            values = np.array(m.getSolution().col_value)
            ybar = np.round(values[:ny])
            theta = float(values[ny])
            info = m.getInfo()
            round_lb = m.getObjectiveValue() if found == "optimal" else float(info.mip_dual_bound)
            if math.isfinite(round_lb) and abs(round_lb) < 1e20:
                lb = max(lb, round_lb)

            moved = shift(ybar)
            if nrows:
                sub.h.changeRowsBounds(nrows, np.arange(nrows, dtype=np.int32), row_lo - moved, row_hi - moved)
            left = time_limit - (time.monotonic() - started)
            outcome = sub.run(left)
            if outcome == "optimal":
                v = sub.h.getObjectiveValue()
                ub = float(cy @ ybar) + v + offset
                if ub < best_ub - _CUT_TOLERANCE * max(1.0, abs(ub)):
                    best_ub, best_y, best_x = ub, ybar.copy(), np.array(sub.h.getSolution().col_value)
                    emit("incumbent", best_ub, lb)
                else:
                    emit("bound", best_ub, lb)
                # Priced right already (θ >= v): the master's bound has met this answer, and
                # the gap test below ends the loop. Otherwise the cut removes the proposal.
                if theta < v - _CUT_TOLERANCE * max(1.0, abs(v)):
                    g, rhs = cut(list(sub.h.getSolution().row_dual), v, ybar)
                    index = np.append(np.nonzero(g)[0], ny).astype(np.int32)
                    m.addRow(rhs, inf, len(index), index, np.append(g[np.nonzero(g)[0]], 1.0))
                    optimality += 1
            elif outcome == "infeasible":
                p = phase_one()
                p.h.changeRowsBounds(nrows, np.arange(nrows, dtype=np.int32), row_lo - moved, row_hi - moved)
                if p.run(time_limit - (time.monotonic() - started)) != "optimal":
                    break
                w = p.h.getObjectiveValue()
                g, rhs = cut(list(p.h.getSolution().row_dual), w, ybar)
                nz = np.nonzero(g)[0]
                if not len(nz):  # pragma: no cover -- an infeasible subproblem always has a slope
                    status = "infeasible"
                    break
                m.addRow(rhs, inf, len(nz), nz.astype(np.int32), g[nz])
                feasibility += 1
            elif outcome == "unbounded":
                status = "unbounded"
                break
            else:
                break
            if best_y is not None and best_ub - lb <= tolerance * max(1.0, abs(best_ub)):
                status = "optimal"
                break
    except KeyboardInterrupt:
        # Asked to stop (the parent's SIGTERM): keep the best answer found.
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)

    wall = time.monotonic() - started
    name = (f"benders (highs {_HIGHS_VERSION}): {rounds} rounds, {optimality} optimality "
            f"and {feasibility} feasibility cuts")
    if best_y is None:
        return _blank(status if status in ("infeasible", "unbounded") else "unknown", wall, name)
    if status == "unbounded":
        return _blank("unbounded", wall, name)
    assignments = {}
    for k in keys:
        spec = compiled.variables[k]
        value = best_y[ypos[k]] if k in ypos else best_x[xpos[k]]
        assignments[k] = report_quantity(float(value), integral=spec.is_integral)
    status = "optimal" if status == "optimal" else "feasible"
    return Solution(
        status=status,
        optimal=status == "optimal",
        objective=report_quantity(best_ub * sign, integral=compiled.is_integral),
        assignments=assignments,
        best_bound=None if not math.isfinite(lb) else min(lb, best_ub) * sign,
        wall_seconds=round(wall, 3),
        solver=name,
    )
