"""Rows any model with on/off limits implies but its relaxation does not see (9 October 2026).

An on/off limit is a rule `a1*x1 + a2*x2 + ... <= M * on` with `on` yes or no and every `x >= 0`: a site's
shipments within its capacity once it opens, production within a machine's capacity once it is set up, flow on a
link once it is built. The relaxation reads such a rule as `on >= usage / M` -- with M large, almost nothing --
which is why branch and bound is slow on these models. Two families of rows, read off the compiled model and
named by nothing in it, close much of that:

1. **Each quantity on its own** (disaggregated limits). Where another rule already bounds a quantity below what
   its limit allows -- one customer's shipment by that customer's demand, `x <= u` -- the quantity is also within
   `u * on`: `a*x <= min(M, a*u) * on`. With M a site's whole capacity and u one customer's demand, that is the
   classic strengthening of facility location, and here it is found for any model of that shape.
2. **Covers.** A rule that needs at least `d` of quantities each behind its own limit -- a customer's demand met
   from sites -- needs enough of those limits switched on: `sum over on of min(capacity it allows, d) * on >= d`.

Both hold at every answer (the optimum is unchanged). Covers are few and added at once. Disaggregated limits can
be many (one per quantity), so they are added where the relaxation breaks them, round by round
(`strengthen_in_process`, in the HiGHS worker on one model changed in place), until it breaks none or the
time is spent. The run records `strengthen_run`: rows added, and the relaxation's bound before and after.
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, Constraint, Linear, VarKey
from app.solve.fixed_charge import _normal

SHARE, CEILING = 0.1, 15.0
#: The most rows added in one round, and in all.
PER_ROUND, MOST = 2_000, 50_000


def _limits(compiled: Compiled):
    """[(row, on, {x: a}, M)] for every on/off limit, whatever the decision costs."""
    out = []
    for i, c in enumerate(compiled.constraints):
        normal = _normal(c)
        if normal is None:
            continue
        coeffs, relation, rhs = normal
        if relation == ">=":
            coeffs, rhs, relation = {k: -v for k, v in coeffs.items()}, -rhs, "<="
        if relation != "<=" or rhs != 0:
            continue
        negative = [k for k, v in coeffs.items() if v < 0]
        if len(negative) != 1 or len(coeffs) < 2:
            continue
        on = negative[0]
        if compiled.variables[on].domain != "binary":
            continue
        limited = {k: v for k, v in coeffs.items() if k != on}
        if any(compiled.variables[k].lower < 0 for k in limited):
            continue
        out.append((i, on, limited, -coeffs[on]))
    return out


def _upper_bounds(compiled: Compiled, skip: set[int]) -> dict[VarKey, Decimal]:
    """Each quantity's tightest upper bound another rule implies on its own: its declared bound, or `b / c` from
    a rule `c*x + (terms that cannot go below 0) <= b` (or `= b`)."""
    upper = {k: v.upper for k, v in compiled.variables.items()}
    for i, c in enumerate(compiled.constraints):
        if i in skip:
            continue
        normal = _normal(c)
        if normal is None:
            continue
        coeffs, relation, rhs = normal
        if relation == ">=":
            continue
        if any(v < 0 or compiled.variables[k].lower < 0 for k, v in coeffs.items()):
            continue
        # Every term at least 0: each one alone is at most what the others leave of b.
        floor = sum((v * compiled.variables[k].lower for k, v in coeffs.items()), Decimal(0))
        for k, v in coeffs.items():
            bound = (rhs - floor + v * compiled.variables[k].lower) / v
            if bound < upper[k]:
                upper[k] = bound
    return upper


def applies(compiled: Compiled) -> str | None:
    if compiled.objective_mode == "lex" or compiled.objective_quadratic:
        return "the goal is not one linear sum"
    if compiled.pwl or compiled.functions or compiled.intervals or compiled.placements or compiled.predictions:
        return "the model has curves, functions, schedules, placements or predictions"
    if not _limits(compiled):
        return "no rule limits quantities by a yes/no decision (sum(a*x) <= M*on)"
    return None


def candidates(compiled: Compiled):
    """(disaggregated limits, covers) the model implies: lists of (Constraint, {key: coefficient}, lower) with the
    row read as `sum(coefficient * key) >= lower`, for checking against a relaxation."""
    limits = _limits(compiled)
    upper = _upper_bounds(compiled, {i for i, *_ in limits})
    single: list[tuple[Constraint, dict[VarKey, float], float]] = []
    allows: dict[VarKey, list[tuple[VarKey, Decimal]]] = {}
    for i, on, limited, m in limits:
        rule = compiled.constraints[i]
        for x, a in limited.items():
            room = min(m, a * upper[x])
            allows.setdefault(x, []).append((on, room / a))
            if room < m and len(limited) > 1:
                # a*x <= room*on, as `room*on - a*x >= 0`.
                single.append((Constraint(rule.id, dict(rule.index), Linear(coeffs={on: room, x: -a}), ">=",
                                          Linear()), {on: float(room), x: -float(a)}, 0.0))
    covers: list[tuple[Constraint, dict[VarKey, float], float]] = []
    for i, c in enumerate(compiled.constraints):
        normal = _normal(c)
        if normal is None:
            continue
        coeffs, relation, rhs = normal
        if relation == "<=":
            continue
        if relation == ">=" or relation in ("=", "=="):
            pass
        if rhs <= 0 or any(v <= 0 for v in coeffs.values()) or any(k not in allows for k in coeffs):
            continue
        # Each quantity's limit by one decision (the tightest, when several hold).
        weight: dict[VarKey, Decimal] = {}
        for x, coeff in coeffs.items():
            on, most = min(allows[x], key=lambda pair: pair[1])
            weight[on] = weight.get(on, Decimal(0)) + coeff * most
        cover = {on: min(w, rhs) for on, w in weight.items()}
        if sum(cover.values(), Decimal(0)) < rhs:
            continue  # cannot be met even with all on: the model will say so; no cut
        if all(w >= rhs for w in cover.values()) and len(cover) == 1:
            continue  # "the one decision is on" -- a bound the solver finds itself
        covers.append((Constraint(c.id, dict(c.index), Linear(coeffs=dict(cover)), ">=", Linear(const=rhs)),
                       {k: float(v) for k, v in cover.items()}, float(rhs)))
    return single, covers


def tightest(compiled: Compiled) -> dict[VarKey, tuple[VarKey, Decimal]]:
    """Each limited quantity's tightest on/off limit: (on, most it may be while on)."""
    limits = _limits(compiled)
    upper = _upper_bounds(compiled, {i for i, *_ in limits})
    out: dict[VarKey, tuple[VarKey, Decimal]] = {}
    for _, on, limited, m in limits:
        for x, a in limited.items():
            most = min(m / a, upper[x])
            if x not in out or most < out[x][1]:
                out[x] = (on, most)
    return out


def strengthen(compiled: Compiled, *, seconds: float = CEILING) -> tuple[Compiled, dict[str, Any]]:
    """The model with the rows its relaxation breaks added, and what was added (runs in the HiGHS worker)."""
    from dataclasses import replace

    from app.solve import highs

    began = time.monotonic()
    if not highs.available():
        return compiled, {"why": "HiGHS is not in this build", "seconds": 0.0}
    try:
        chosen, record = highs._in_child({"mode": "strengthen", "compiled": compiled, "seconds": float(seconds)},
                                         time_limit=float(seconds))
    except RuntimeError as failed:
        return compiled, {"why": str(failed)[:300], "seconds": round(time.monotonic() - began, 3)}
    record["seconds"] = round(time.monotonic() - began, 3)
    if not chosen:
        return compiled, record
    return replace(compiled, constraints=[*compiled.constraints, *chosen]), record


def strengthen_in_process(compiled: Compiled, *, seconds: float) -> tuple[list[Constraint], dict[str, Any]]:
    import highspy
    import numpy as np

    from app.solve.highs import _add_columns, _add_rows, _set_objective

    began = time.monotonic()
    deadline = began + max(1.0, seconds)
    from app.solve.flowcuts import Flows

    single, covers = candidates(compiled)
    flows = Flows(compiled, tightest(compiled))
    record: dict[str, Any] = {"limits": len(single), "covers": len(covers), "rounds": 0, "added": 0,
                              "flow_nodes": len(flows.demand) if flows.ok else 0, "flow_cuts": 0,
                              "bound_before": None, "bound_after": None}
    if not single and not covers and not flows.ok:
        # Nothing the limits imply beyond themselves: no relaxation is worth its time.
        return [], {**record, "why": "the on/off limits imply no row beyond themselves"}
    solver = highspy.Highs()
    solver.setOptionValue("output_flag", False)
    solver.setOptionValue("threads", 1)
    keys = list(compiled.variables)
    position = {k: i for i, k in enumerate(keys)}
    _add_columns(highspy, solver, compiled, keys, relax=True)
    _add_rows(highspy, solver, compiled.constraints, position)
    _set_objective(highspy, solver, compiled, position, 1.0)
    inf = highspy.kHighsInf

    def add(rows: list[tuple[Constraint, dict[VarKey, float], float]]) -> None:
        starts, index, values = [], [], []
        for _, coeffs, _low in rows:
            starts.append(len(index))
            for k, v in coeffs.items():
                index.append(position[k])
                values.append(v)
        solver.addRows(len(rows), np.array([low for *_, low in rows], dtype=np.float64),
                       np.array([inf] * len(rows), dtype=np.float64), len(index),
                       np.array(starts, dtype=np.int32), np.array(index, dtype=np.int32),
                       np.array(values, dtype=np.float64))

    def relaxation():
        solver.setOptionValue("time_limit", float(solver.getRunTime() + max(0.1, deadline - time.monotonic())))
        solver.solve()
        if solver.getModelStatus() != highspy.HighsModelStatus.kOptimal:
            return None
        return np.array(solver.allVariableValues()), float(solver.getInfo().objective_function_value)

    first = relaxation()
    if first is None:
        return [], {**record, "why": "the relaxation did not solve in the time"}
    record["bound_before"] = record["bound_after"] = first[1]
    chosen: list[Constraint] = []
    pool = [*covers, *single]
    # Every candidate as one sparse row, so a round's check is one product, whatever their number.
    rows_idx, cols_idx, vals = [], [], []
    for r, (_, coeffs, _low) in enumerate(pool):
        for k, v in coeffs.items():
            rows_idx.append(r)
            cols_idx.append(position[k])
            vals.append(v)
    from scipy.sparse import csr_matrix

    matrix = csr_matrix((np.array(vals), (np.array(rows_idx), np.array(cols_idx))), shape=(len(pool), len(keys)))
    lows = np.array([low for *_, low in pool], dtype=np.float64)
    live = np.ones(len(pool), dtype=bool)
    values = first[0]
    watched = sorted({*flows.arcs, *(on for on, _ in flows.limits.values())}, key=str) if flows.ok else []
    while time.monotonic() < deadline and len(chosen) < MOST:
        short = lows - matrix @ values if len(pool) else np.zeros(0)
        short[~live] = 0.0
        broken = np.nonzero(short > 1e-6 * np.maximum(1.0, np.abs(lows)))[0]
        take_idx = broken[np.argsort(-short[broken])][:PER_ROUND]
        take = [pool[i] for i in take_idx]
        if flows.ok and time.monotonic() < deadline:
            # Cut-sets of the balances, at this relaxation (built afresh each round).
            at = {k: float(values[position[k]]) for k in watched}
            cuts = flows.separate(at, PER_ROUND // 2, deadline=deadline)
            take += [(row, coeffs, low) for _, row, coeffs, low in cuts]
            record["flow_cuts"] += len(cuts)
        if not take:
            break
        add(take)
        chosen.extend(item[0] for item in take)
        live[take_idx] = False
        record["rounds"] += 1
        again = relaxation()
        if again is None:
            break
        values = again[0]
        record["bound_after"] = again[1]
    # Only the rows the last relaxation holds tight are kept: the others did their work in the rounds before (the
    # relaxation moved off them) and would only make each of the solver's own relaxations larger. Measured
    # (lot sizing, 20 items x 30 periods): all 4,653 rows made HiGHS take 22 s instead of 5.
    if chosen and values is not None:
        kept = []
        for row in chosen:
            have = sum(float(v) * values[position[k]] for k, v in row.left.coeffs.items())
            if have - float(row.right.const) <= 1e-6 * max(1.0, abs(float(row.right.const))):
                kept.append(row)
        record["dropped_slack"] = len(chosen) - len(kept)
        chosen = kept
    record["added"] = len(chosen)
    return chosen, record
