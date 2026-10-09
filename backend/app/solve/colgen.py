"""Column generation over a model's own decisions, built on HiGHS (plan of 8 October 2026, 1D).

Some models have far more decisions than rules: a candidate list of positions (hundreds of thousands of
yes-or-no columns over a few thousand cells), every pairing of crews and duties, every pattern of a cut. Most of
those decisions are zero in any good answer, and a simplex over all of them spends its time on columns that never
enter. Column generation keeps a small **restricted master** -- the rules over a few columns -- and asks, after
each solve, which left-out columns would improve it:

* the master's row prices `y` give each column its **reduced cost** `c_j - y . A_j`, computed for all of them at
  once from the rule matrix (pricing by the matrix, so it holds for any linear model -- no problem-specific
  pricing routine);
* the columns that improve the most are added and the master solved again, until none improves: the master's
  linear optimum is then the whole model's.

**The bound.** At any row prices of the right sign (a positive price only on a row with a lower side, a negative
one only on a row with an upper side), the Lagrangian of the rules,

    L(y) = sum over rows of y_i * (the side its sign selects)  +  sum over all columns of min (c_j - y . A_j) x_j
                                                                  over x_j in its bounds,

is a lower bound on the whole model -- its linear relaxation and so every whole-number answer -- computed over
every column, not only the master's. It is checked each round and the best is kept, so even a loop stopped early
reports a proven bound.

**The answer.** With the columns found, the master is solved once more with the whole-number decisions whole
("price and branch"): an answer of the whole model, every left-out decision at zero. When its value meets the
bound it is proven best; otherwise the gap is reported, never claimed closed.

**Feasibility.** Each row the starting point does not meet has two slack columns at a large price, so the first
masters always have an answer;
a slack still used once no column improves means the rows cannot be met by the model's linear relaxation, and
the model is reported infeasible only if the final whole-number solve over every column says so too.

**What it takes.** A linear model -- a linear goal and linear rules, no curves, conditions or schedules -- whose
decisions may be left at zero (zero within every left-out decision's bounds; any other decision is kept in the
master from the start). It is asked for by name (`automatic=False`): it pays on models with many more decisions
than rules.

A model with fewer than twice as many decisions as rules gains nothing from a small master (each master solve
grows towards the whole model): the master is then the whole model from the start, solved as HiGHS would, and the
solver string says so.

**Where it runs.** In HiGHS's child process (`app.solve.highs_worker`), which never loads ortools.
"""

from __future__ import annotations

import json
import math
import signal
import time

from app.api.quantity import report_quantity
from app.solve.compile import Compiled, Unsupported
from app.solve.result import Solution

#: A column improves when its reduced cost is below minus this (relative to the largest cost).
_PRICE_TOLERANCE = 1e-9
#: The gap at which the answer is proven best: below `service.OPTIMAL_GAP`.
_GAP = 1e-7
#: The share of the time the column loop may take before the whole-number solve has the rest.
LOOP_SHARE = 0.6
#: Columns added a round: a fiftieth of them, at least MIN_ADDED and at most MAX_ADDED.
MIN_ADDED, MAX_ADDED = 200, 5_000
#: The master's first columns: the best by cost -- twice the rows, at most a tenth of the columns, at least this many
#: (and every column that cannot be left at zero).
MIN_START = 500
MAX_ROUNDS = 10_000
#: Decisions per rule below which the master would be nearly the whole model: it is then the whole model from the
#: start (the camp's candidate list at 0.5 m: 54,468 positions, 116,686 rules -- each master solve slower than the
#: last, the method's work all cost and no saving).
RATIO = 2


def refuse(compiled: Compiled) -> str | None:
    """Why this model is not one column generation can take -- or None."""
    if compiled.objective_quadratic:
        return "the goal multiplies decisions together; column generation is written on a linear goal"
    if compiled.pwl or compiled.functions or compiled.intervals or getattr(compiled, "placements", None):
        return "the model has a curve, a function, a schedule or a placement, which the master cannot hold"
    for c in compiled.constraints:
        if c.quadratic or c.when is not None or c.schedule is not None:
            return f"the rule {c.id!r} is not linear, and the master is a linear program"
    if not compiled.variables:
        return "the model has no decisions"
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
        raise Unsupported(f"colgen: {reason}")
    if should_stop is not None and should_stop():
        return _blank("unknown")
    if not highs.available():
        raise RuntimeError("colgen needs highs, which is not available in this build")
    return highs._in_child(
        {"mode": "colgen", "compiled": compiled, "time_limit": time_limit, "workers": workers, "seed": seed,
         "gap_rel": gap_rel, "progress": on_progress is not None},
        time_limit=time_limit,
        should_stop=should_stop,
        on_progress=on_progress,
    )


def _blank(status: str, wall: float = 0.0, solver: str = "colgen") -> Solution:
    return Solution(status=status, optimal=False, objective=None, assignments={}, wall_seconds=round(wall, 3),
                    solver=solver)


def lagrangian(y, low, high, rc, lo, hi) -> float:
    """L(y): a lower bound on the minimised model for row prices `y` -- minus infinity when a price has the wrong
    sign for its row's sides or a column could run to infinity at its price."""
    import numpy as np

    tol = 1e-12
    rows = 0.0
    up, down = y > tol, y < -tol
    if np.any(up & ~np.isfinite(low)) or np.any(down & ~np.isfinite(high)):
        return -math.inf
    rows = float(y[up] @ low[up]) + float(y[down] @ high[down])
    neg, pos = rc < -tol, rc > tol
    if np.any(neg & ~np.isfinite(hi)) or np.any(pos & ~np.isfinite(lo)):
        return -math.inf
    return rows + float(rc[neg] @ hi[neg]) + float(rc[pos] @ lo[pos])


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

    from app.solve.highs import _HIGHS_VERSION, _has_solution, _status, row_of

    started = time.monotonic()
    inf = highspy.kHighsInf
    sign = 1.0 if compiled.sense == "minimize" else -1.0  # minimised inside
    keys = list(compiled.variables)
    n = len(keys)
    pos = {k: j for j, k in enumerate(keys)}
    cost = np.zeros(n)
    for k, v in compiled.objective.coeffs.items():
        if v:
            cost[pos[k]] = sign * float(v)
    offset = sign * float(compiled.objective.const)
    lo = np.array([float(compiled.variables[k].lower) for k in keys])
    hi = np.array([float(compiled.variables[k].upper) for k in keys])
    integral = np.array([compiled.variables[k].is_integral for k in keys])

    # The rule matrix as (row, column, value) triples, and each row's sides.
    r_idx, c_idx, vals, low, high = [], [], [], [], []
    for i, c in enumerate(compiled.constraints):
        coeffs, lo_i, hi_i = row_of(c, inf)
        for k, v in coeffs.items():
            if v:
                r_idx.append(i)
                c_idx.append(pos[k])
                vals.append(float(v))
        low.append(lo_i)
        high.append(hi_i)
    m = len(compiled.constraints)
    r_idx, c_idx, vals = np.array(r_idx, dtype=np.int64), np.array(c_idx, dtype=np.int64), np.array(vals)
    low = np.where(np.array(low) <= -inf, -np.inf, np.array(low, dtype=float))
    high = np.where(np.array(high) >= inf, np.inf, np.array(high, dtype=float))
    order = np.argsort(c_idx, kind="stable")  # by column, for adding a column's entries
    col_start = np.searchsorted(c_idx[order], np.arange(n + 1))

    def emit(kind, objective, bound):
        if progress:
            print(json.dumps({"kind": kind, "t": time.monotonic() - started,
                              "objective": None if objective is None else objective * sign,
                              "bound": None if bound is None or not math.isfinite(bound) else bound * sign}),
                  flush=True)

    # The master starts with every column that cannot be left at zero, and the cheapest of the rest.
    fixed_in = (lo > 0) | (hi < 0)
    whole_model = n < RATIO * m
    start_count = n if whole_model else min(n, max(MIN_START, min(2 * m, n // 10)))
    cheapest = np.argsort(cost, kind="stable")
    chosen = np.zeros(n, dtype=bool)
    chosen[fixed_in] = True
    chosen[cheapest[:start_count]] = True
    big = 1e6 * (1.0 + float(np.abs(cost).max(initial=0.0)))

    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    if workers > 1:
        h.setOptionValue("threads", int(workers))
    if seed is not None:
        h.setOptionValue("random_seed", int(seed))
    h.HandleKeyboardInterrupt = True

    def limit(left: float) -> None:
        # HiGHS counts its time limit against all the run time of one solver, not each solve's.
        h.setOptionValue("time_limit", h.getRunTime() + max(0.01, float(left)))
    # The rows, empty; then two slack columns (+ and -) for each row the start does not meet -- every decision at
    # zero, or at its bound nearest zero when zero is outside it -- so the first master has an answer; then the
    # chosen columns.
    h.addRows(m, np.where(np.isfinite(low), low, -inf), np.where(np.isfinite(high), high, inf), 0,
              np.zeros(m, dtype=np.int32), np.zeros(0, dtype=np.int32), np.zeros(0))
    x0 = np.where(lo > 0, lo, np.where(hi < 0, hi, 0.0))
    act = np.bincount(r_idx, weights=vals * x0[c_idx], minlength=m) if m else np.zeros(0)
    unmet = np.flatnonzero((act < low - 1e-9) | (act > high + 1e-9)).astype(np.int32)
    n_slack = 2 * len(unmet)
    if len(unmet):
        k = len(unmet)
        for s in (1.0, -1.0):
            h.addCols(k, np.full(k, big), np.zeros(k), np.full(k, inf), k, np.arange(k, dtype=np.int32), unmet,
                      np.full(k, s))
    master_cols: list[int] = []  # model column of each master column after the slacks

    def add(columns) -> None:
        columns = [int(j) for j in columns]
        if not columns:
            return
        starts, index, values = [], [], []
        for j in columns:
            starts.append(len(index))
            sel = order[col_start[j]:col_start[j + 1]]
            index.extend(r_idx[sel].tolist())
            values.extend(vals[sel].tolist())
        h.addCols(len(columns), cost[columns], np.where(np.isfinite(lo[columns]), lo[columns], -inf),
                  np.where(np.isfinite(hi[columns]), hi[columns], inf), len(index),
                  np.array(starts, dtype=np.int32), np.array(index, dtype=np.int32), np.array(values))
        master_cols.extend(columns)

    add(np.flatnonzero(chosen))
    h.changeObjectiveOffset(offset)
    scale = 1.0 + float(np.abs(cost).max(initial=0.0))
    per_round = min(MAX_ADDED, max(MIN_ADDED, n // 50))
    bound, rounds, converged, slack_left = -math.inf, 0, False, False
    previous = signal.signal(signal.SIGTERM, signal.default_int_handler)
    loop_end = started + LOOP_SHARE * time_limit
    status: str | None = None
    try:
        while rounds < MAX_ROUNDS:
            left = loop_end - time.monotonic()
            if left <= 0:
                break
            rounds += 1
            limit(left)
            h.solve()
            found = _status(h.getModelStatus())
            if found == "unbounded":
                status = "unbounded"
                break
            if found != "optimal":
                break
            sol = h.getSolution()
            y = np.array(sol.row_dual) if m else np.zeros(0)
            # Every column's reduced cost, at once: c - A^T y.
            rc = cost - (np.bincount(c_idx, weights=vals * y[r_idx], minlength=n) if m else 0.0)
            here = lagrangian(y, low, high, rc, lo, hi)
            if here > bound:
                bound = here
                emit("bound", None, bound)
            # Improving: a left-out column at zero whose cost falls below zero in a direction it may move.
            improving = ~chosen & (((rc < -_PRICE_TOLERANCE * scale) & (hi > 0))
                                   | ((rc > _PRICE_TOLERANCE * scale) & (lo < 0)))
            if not improving.any():
                converged = True
                slack_left = n_slack > 0 and float(np.sum(np.array(sol.col_value)[:n_slack])) > 1e-6
                lp_value = h.getObjectiveValue()
                if not slack_left:
                    bound = max(bound, lp_value)
                break
            picks = np.flatnonzero(improving)
            picks = picks[np.argsort(-np.abs(rc[picks]), kind="stable")[:per_round]]
            chosen[picks] = True
            add(picks)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)

    # Price and branch: the whole-number decisions whole, over the columns found; slacks kept out.
    best, values = None, None
    try:
        if n_slack:
            h.changeColsBounds(n_slack, np.arange(n_slack, dtype=np.int32), np.zeros(n_slack), np.zeros(n_slack))
        whole = [i + n_slack for i, j in enumerate(master_cols) if integral[j]]
        if whole:
            h.changeColsIntegrality(len(whole), np.array(whole, dtype=np.int32),
                                    np.array([highspy.HighsVarType.kInteger] * len(whole)))
        h.setOptionValue("mip_rel_gap", max(float(gap_rel), _GAP))
        previous = signal.signal(signal.SIGTERM, signal.default_int_handler)
        try:
            limit(max(0.05, time_limit - (time.monotonic() - started)))
            h.solve()
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGTERM, previous)
        final = _status(h.getModelStatus())
        if final in ("optimal", "feasible") and _has_solution(h):
            values = np.array(h.getSolution().col_value)[n_slack:]
            best = h.getObjectiveValue()
            if len(master_cols) == n and final == "optimal":
                # Every column is in the master: its whole-number optimum is the model's.
                bound = max(bound, best)
            emit("incumbent", best, bound)
        elif final == "infeasible" and (len(master_cols) == n or (converged and slack_left)):
            status = "infeasible"
    except KeyboardInterrupt:  # pragma: no cover -- stopped between the two solves
        pass

    wall = time.monotonic() - started
    name = (f"colgen (highs {_HIGHS_VERSION}): {rounds} rounds, {len(master_cols):,} of {n:,} columns"
            + (" (fewer than twice as many decisions as rules: the master was the whole model)" if whole_model
               else "" if converged else ", stopped before every column was priced out"))
    if best is None:
        return _blank(status or "unknown", wall, name)
    assignments = {}
    full = np.zeros(n)
    full[master_cols] = values
    for j, k in enumerate(keys):
        assignments[k] = report_quantity(float(round(full[j]) if integral[j] else full[j]),
                                         integral=bool(integral[j]))
    proven = math.isfinite(bound) and best - bound <= max(float(gap_rel), _GAP) * max(1.0, abs(best))
    return Solution(
        status="optimal" if proven else "feasible",
        optimal=proven,
        objective=report_quantity(best * sign, integral=compiled.is_integral),
        assignments=assignments,
        best_bound=None if not math.isfinite(bound) else min(bound, best) * sign,
        wall_seconds=round(wall, 3),
        solver=name,
    )
