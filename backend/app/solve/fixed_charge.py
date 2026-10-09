"""A start for any model with fixed charges: slope scaling read off the compiled model (9 October 2026).

A fixed charge is a yes/no decision that costs something to switch on and lets other quantities be non-zero
only while it is on -- a rule of the shape `a1*x1 + a2*x2 + ... <= M * open` with every `a > 0` and every `x >= 0`.
Facility location (a site's shipments within its capacity once it opens), lot sizing (production only in a
period with a set-up), network design (flow only on a link that is built), unit commitment (output only from a
unit that is on), machine set-ups, opening a route, renting a vehicle: nothing here knows which. Branching on such
models is slow because the relaxation opens every charge a little -- `open = usage / M` -- and so pays almost
nothing for it.

Slope scaling (Kim and Pardalos, 1999) turns that around:

1. every charge is set aside, and its cost is spread over what it switches on instead: each quantity it limits
   costs `charge / estimate` more per unit (the estimate: M at first, then what the last round used);
   the model is then a relaxation with nothing to open, and solved;
2. a charge is switched on exactly when that solution uses what it limits; with every charge fixed so, the
   model is solved again as it is (its other whole-number decisions too, for a few seconds), which mends every
   other rule -- or says those charges cannot work;
3. the estimates become what each charge now carries, and the rounds repeat while they find new designs;
4. the dearest charges of the best design are then switched off one at a time while that still solves for less.

The best design's full answer is the start: every rule holds, since it came from the model itself. The
solver begins there, and a run never ends with less (`fixed_charge_start_run`).
"""
from __future__ import annotations

import time
from dataclasses import replace
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, Constraint, Linear, Variable, VarKey

SHARE, CEILING = 0.2, 30.0
#: A quantity counts as used above this.
USED = 1e-6


def _normal(c: Constraint):
    """(coefficients, relation, right-hand side) of `left - right relation rhs`, or None for a rule that is not
    a plain linear row."""
    if c.when is not None or c.quadratic or getattr(c, "schedule", None) is not None:
        return None
    coeffs: dict[VarKey, Decimal] = {}
    for k, v in c.left.coeffs.items():
        coeffs[k] = coeffs.get(k, Decimal(0)) + v
    for k, v in c.right.coeffs.items():
        coeffs[k] = coeffs.get(k, Decimal(0)) - v
    return {k: v for k, v in coeffs.items() if v}, c.relation, c.right.const - c.left.const


def _charges(compiled: Compiled):
    """{charge: [(row number, {quantity: a}, M)]} -- every rule `sum(a*x) <= M*charge` whose charge costs to
    switch on -- and the charge's cost (in the goal's direction: minimizing)."""
    sign = Decimal(1) if compiled.sense != "maximize" else Decimal(-1)
    rows: dict[VarKey, list[tuple[int, dict[VarKey, Decimal], Decimal]]] = {}
    for i, c in enumerate(compiled.constraints):
        normal = _normal(c)
        if normal is None:
            continue
        coeffs, relation, rhs = normal
        if relation == ">=":
            coeffs, rhs, relation = {k: -v for k, v in coeffs.items()}, -rhs, "<="
        if relation != "<=" or rhs != 0 or len(coeffs) < 2:
            continue
        negative = [k for k, v in coeffs.items() if v < 0]
        if len(negative) != 1:
            continue
        y = negative[0]
        spec = compiled.variables.get(y)
        if spec is None or spec.domain != "binary":
            continue
        limited = {k: v for k, v in coeffs.items() if k != y}
        if any(compiled.variables[k].lower < 0 for k in limited):
            continue
        rows.setdefault(y, []).append((i, limited, -coeffs[y]))
    cost = {y: sign * compiled.objective.coeffs.get(y, Decimal(0)) for y in rows}
    return {y: r for y, r in rows.items() if cost[y] > 0}, cost


def applies(compiled: Compiled) -> str | None:
    if compiled.objective_mode == "lex":
        return "goals ranked in order are left to the solver"
    if compiled.objective_quadratic:
        return "the goal is not linear"
    if compiled.pwl or compiled.functions or compiled.intervals or compiled.placements or compiled.predictions:
        return "the model has curves, functions, schedules, placements or predictions"
    if not any(v.is_integral for v in compiled.variables.values()):
        return "the model has no yes/no decisions"
    charges, _ = _charges(compiled)
    if not charges:
        return "no yes/no decision with a cost switches other quantities on (no rule sum(a*x) <= M*decision)"
    return None


def start(compiled: Compiled, *, seconds: float = CEILING,
          bound: float | None = None) -> tuple[dict[VarKey, Any], dict[str, Any]]:
    """The best design slope scaling finds, as a complete answer of the model, and what it did. Runs in the
    HiGHS worker process (`app.solve.highs_worker`), one HiGHS model changed in place between solves."""
    from app.solve import highs

    began = time.monotonic()
    if not highs.available():
        return {}, {"why": "HiGHS is not in this build", "seconds": 0.0}
    try:
        hint, record = highs._in_child({"mode": "fixed_charge", "compiled": compiled, "seconds": float(seconds),
                                        "bound": bound},
                                       time_limit=float(seconds))
    except RuntimeError as failed:
        return {}, {"why": str(failed)[:300], "seconds": round(time.monotonic() - began, 3)}
    record["seconds"] = round(time.monotonic() - began, 3)
    return hint, record


def start_in_process(compiled: Compiled, *, seconds: float,
                     bound: float | None = None) -> tuple[dict[VarKey, Any], dict[str, Any]]:
    import highspy
    import numpy as np

    from app.solve.highs import _add_columns, _add_rows, _set_objective

    began = time.monotonic()
    deadline = began + max(1.0, seconds)
    charges, cost = _charges(compiled)
    sense = 1.0 if compiled.sense != "maximize" else -1.0
    record: dict[str, Any] = {"charges": len(charges), "rows": sum(len(r) for r in charges.values()), "rounds": 0,
                              "designs": 0}
    solver = highspy.Highs()
    solver.setOptionValue("output_flag", False)
    solver.setOptionValue("threads", 1)
    solver.setOptionValue("random_seed", 1)
    keys = list(compiled.variables)
    position = {k: i for i, k in enumerate(keys)}
    _add_columns(highspy, solver, compiled, keys)
    _add_rows(highspy, solver, compiled.constraints, position)
    _set_objective(highspy, solver, compiled, position, 1.0)
    base_cost = np.zeros(len(keys))
    for k, v in compiled.objective.coeffs.items():
        base_cost[position[k]] = float(v)
    integral = np.array([i for i, k in enumerate(keys) if compiled.variables[k].is_integral], dtype=np.int32)
    charge_cols = np.array([position[y] for y in charges], dtype=np.int32)
    lower0 = np.array([float(compiled.variables[y].lower) for y in charges])
    upper0 = np.array([float(compiled.variables[y].upper) for y in charges])

    def left() -> float:
        return deadline - time.monotonic()

    def run(limit: float):
        solver.setOptionValue("time_limit", float(solver.getRunTime() + max(0.05, limit)))
        solver.solve()
        status = solver.getModelStatus()
        if status != highspy.HighsModelStatus.kOptimal and not (
                solver.getInfo().primal_solution_status == 2 and status == highspy.HighsModelStatus.kTimeLimit):
            return None
        return np.array(solver.allVariableValues()), float(solver.getInfo().objective_function_value)

    def integrality(on: bool):
        if len(integral):
            kind = highspy.HighsVarType.kInteger if on else highspy.HighsVarType.kContinuous
            solver.changeColsIntegrality(len(integral), integral, np.array([kind] * len(integral)))

    def costs(values: np.ndarray):
        solver.changeColsCost(len(keys), np.arange(len(keys), dtype=np.int32), values)

    def relaxed(estimate: dict[tuple[VarKey, int], float]):
        """Every charge set aside (free to open, costing nothing) and its cost spread over what it limits."""
        integrality(False)
        solver.changeColsBounds(len(charge_cols), charge_cols, lower0, upper0)
        c = base_cost.copy()
        for y, rows in charges.items():
            c[position[y]] = 0.0
            share = float(cost[y]) / len(rows)
            for i, limited, m in rows:
                per = share / max(estimate.get((y, i), float(m)), 1e-9)
                for k, a in limited.items():
                    c[position[k]] += sense * per * float(a)
        costs(c)
        return run(min(10.0, left()))

    def design_value(design: set[VarKey]):
        """The model itself, every charge on or off as `design` says: (objective as minimized, values)."""
        if left() < 0.2:
            return None
        integrality(True)
        on = np.array([1.0 if y in design else 0.0 for y in charges])
        solver.changeColsBounds(len(charge_cols), charge_cols, on, on)
        costs(base_cost)
        outcome = run(min(5.0, left()))
        record["designs"] += 1
        if outcome is None:
            return None
        values, objective = outcome
        return sense * objective, values

    estimate: dict[tuple[VarKey, int], float] = {}
    best = None
    best_design: set[VarKey] = set()
    seen: set[frozenset] = set()
    for _ in range(20):
        if left() < 0.5:
            break
        outcome = relaxed(estimate)
        if outcome is None:
            break
        record["rounds"] += 1
        values, _ = outcome
        usage = {(y, i): sum(float(a) * values[position[k]] for k, a in limited.items())
                 for y, rows in charges.items() for i, limited, _m in rows}
        design = {y for y, rows in charges.items() if any(usage[(y, i)] > USED for i, _, _ in rows)}
        key = frozenset(design)
        if key in seen:
            break
        seen.add(key)
        found = design_value(design)
        if found is not None and (best is None or found[0] < best[0]):
            best, best_design = found, design
        estimate = {k: (v if v > USED else estimate.get(k, 0.0) or float(next(m for i, _, m in charges[k[0]]
                                                                          if i == k[1])))
                    for k, v in usage.items()}
    if best is None:
        # No design from the relaxations completes: every charge on, then the dearest switched off below.
        found = design_value(set(charges))
        if found is None:
            return {}, {**record, "why": "no design completes into an answer, not even with every charge on"}
        best, best_design = found, set(charges)
    # Local search over the design: a charge off, a charge on, or one of each -- the first that solves for less
    # is kept, and the search starts again from it, until none does or the time is spent.
    dropped = added = swapped = 0

    def better(design: set[VarKey]) -> bool:
        nonlocal best, best_design
        found = design_value(design)
        if found is not None and found[0] < best[0] - 1e-9:
            best, best_design = found, design
            return True
        return False

    def ordered():
        on = sorted(best_design, key=lambda y: (-cost[y], str(y)))
        off = sorted((y for y in charges if y not in best_design), key=lambda y: (cost[y], str(y)))
        return on, off

    def drop_pass() -> bool:
        """Every charge on, dearest first, switched off when that solves for less -- the whole pass."""
        nonlocal dropped
        any_ = False
        for y in ordered()[0]:
            if left() < 0.3:
                break
            if y in best_design and better(best_design - {y}):
                dropped += 1
                any_ = True
        return any_

    def add_one() -> bool:
        nonlocal added
        for z in ordered()[1]:
            if left() < 0.3:
                return False
            if better(best_design | {z}):
                added += 1
                return True
        return False

    def swap_one() -> bool:
        nonlocal swapped
        on, off = ordered()
        for y in on:
            for z in off[:40]:
                if left() < 0.3:
                    return False
                if better((best_design - {y}) | {z}):
                    swapped += 1
                    return True
        # Two off and one on: fewer, larger charges (two small sites for one big one).
        for i, y1 in enumerate(on[:12]):
            for y2 in on[i + 1:12]:
                for z in off[:12]:
                    if left() < 0.3:
                        return False
                    if better((best_design - {y1, y2}) | {z}):
                        swapped += 1
                        return True
        return False

    def near() -> bool:
        """Within 0.2% of a known bound on the optimum: no start could be much better."""
        if bound is None:
            return False
        close = best[0] - sense * float(bound) <= 0.002 * max(1.0, abs(best[0]))
        record["near_bound"] = record.get("near_bound") or close
        return close

    while left() > 0.3 and not near() and (drop_pass() or add_one() or swap_one()):
        pass
    values = best[1]
    hint: dict[VarKey, Any] = {}
    for k, i in position.items():
        v = float(values[i])
        hint[k] = int(round(v)) if compiled.variables[k].is_integral else v
    record.update(open=len(best_design), dropped=dropped, added=added, swapped=swapped,
                  objective=round(best[0] * sense, 6), feasible=True)
    return hint, record


def holds(compiled: Compiled, hint: dict[VarKey, Any]) -> bool:
    """Whether a complete start keeps every linear rule and bound of the model (to a small tolerance)."""
    if not hint or any(k not in hint for k in compiled.variables):
        return False
    for c in compiled.constraints:
        if _normal(c) is None:
            continue
        gap = float(c.left.evaluated_at(hint)) - float(c.right.evaluated_at(hint))
        if (c.relation == "<=" and gap > 1e-6) or (c.relation == ">=" and gap < -1e-6) or (
                c.relation in ("=", "==") and abs(gap) > 1e-6):
            return False
    return all(float(v.lower) - 1e-9 <= float(hint[k]) <= float(v.upper) + 1e-9 for k, v in compiled.variables.items())


def better_of(compiled: Compiled, ours: dict[VarKey, Any], theirs: dict[VarKey, Any] | None) -> bool:
    """Whether `ours` is the better start: it holds and `theirs` does not, or both hold and ours is better."""
    if not holds(compiled, ours):
        return False
    if not theirs or not holds(compiled, theirs):
        return True
    a, b = float(compiled.objective.evaluated_at(ours)), float(compiled.objective.evaluated_at(theirs))
    return a < b if compiled.sense != "maximize" else a > b
