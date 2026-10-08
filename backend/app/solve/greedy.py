"""A greedy start for packing-shaped integer models: an answer in a moment that every rule keeps.

A model is packing-shaped when every decision is a whole number from 0, every rule reads "a sum of decisions
with coefficients >= 0 is at most a capacity >= 0", and the goal rewards decisions (maximize) or charges for
them (minimize). Knapsacks, set packing, multi-dimensional knapsacks and layouts that place items on cells are
all of this shape. Nothing chosen is always an answer there, and adding a decision only uses up capacity, so a
greedy pass -- best reward per share of capacity first, each as large as still fits -- is an answer too.

It is the run's start: a solver that takes one starts from it, and a solver that ends with less, or with
nothing (the camp test, October 2026: CP-SAT on one thread found no answer for a block of 13,000 positions in
100 s, and the run ended "feasible 0"), leaves the start as the answer -- feasible, no claim of best.
"""
from __future__ import annotations

import time
from decimal import Decimal
from math import floor
from typing import Any

from app.solve.compile import Compiled, VarKey

#: Above this many coefficients the pass itself would take too long to be a start.
MAX_NNZ = 20_000_000
SHARE, CEILING = 0.1, 20.0
TOLERANCE = 1e-9


def applies(compiled: Compiled) -> str | None:
    """None when the model is packing-shaped, else why the greedy start does not apply."""
    if compiled.objective_mode == "lex":
        return "the goal is ranked, not one weighted sum"
    if compiled.objective_quadratic or compiled.penalty_objective.coeffs or compiled.violations:
        return "the goal is not a plain sum of decisions"
    if compiled.pwl or compiled.functions or compiled.intervals or compiled.routes or compiled.connectivity \
            or compiled.predictions:
        return "the model has curves, functions, intervals, routes or connectivity rules"
    for v in compiled.variables.values():
        if not v.is_integral or v.lower != 0:
            return "some decision is not a whole number from 0"
    nnz = 0
    for c in compiled.constraints:
        if c.when is not None or c.schedule is not None or c.quadratic or getattr(c, "chance", None):
            return "some rule is conditional, a schedule, quadratic or a chance rule"
        if c.relation not in ("<=", ">="):
            return "some rule is an equation"
        sign = 1 if c.relation == "<=" else -1
        if any(sign * (c.left.coeffs.get(k, Decimal(0)) - c.right.coeffs.get(k, Decimal(0))) < 0
               for k in set(c.left.coeffs) | set(c.right.coeffs)):
            return "some rule asks for a decision to be at least something"
        if sign * (c.right.const - c.left.const) < 0:
            return "some rule cannot hold with nothing chosen"
        nnz += len(c.left.coeffs) + len(c.right.coeffs)
    if nnz > MAX_NNZ:
        return f"the model is too large for a greedy pass ({nnz:,} coefficients)"
    return None


def start(compiled: Compiled) -> tuple[dict[VarKey, int], dict[str, Any]]:
    """Every decision's greedy value, and what was found. Call only when `applies` is None."""
    from app.solve.evolve import holds

    began = time.monotonic()
    caps: list[float] = []
    uses: dict[VarKey, list[tuple[int, float]]] = {}
    for c in compiled.constraints:
        sign = 1 if c.relation == "<=" else -1
        row = len(caps)
        caps.append(float(sign * (c.right.const - c.left.const)))
        for key in set(c.left.coeffs) | set(c.right.coeffs):
            coeff = float(sign * (c.left.coeffs.get(key, Decimal(0)) - c.right.coeffs.get(key, Decimal(0))))
            if coeff > 0:
                uses.setdefault(key, []).append((row, coeff))
    direction = 1.0 if compiled.sense == "maximize" else -1.0
    gain = {k: direction * float(c) for k, c in compiled.objective.coeffs.items()}

    def share(key: VarKey) -> float:
        return sum(coeff / caps[row] if caps[row] > 0 else float("inf") for row, coeff in uses.get(key, ()))

    order = sorted((k for k in compiled.variables if gain.get(k, 0.0) > 0), key=lambda k: -gain[k] / (1e-12 + share(k)))
    slack = list(caps)
    hint: dict[VarKey, int] = {k: 0 for k in compiled.variables}
    for key in order:
        most = float(compiled.variables[key].upper)
        for row, coeff in uses.get(key, ()):
            most = min(most, (slack[row] + TOLERANCE) / coeff)
            if most < 1:
                break
        value = int(floor(most + TOLERANCE)) if most >= 1 else 0
        if value <= 0:
            continue
        hint[key] = value
        for row, coeff in uses.get(key, ()):
            slack[row] -= coeff * value
    objective = float(compiled.objective.const) + sum(float(compiled.objective.coeffs.get(k, 0)) * v
                                                       for k, v in hint.items() if v)
    return hint, {"method": "greedy packing", "chosen": sum(1 for v in hint.values() if v),
                  "objective": round(objective, 6), "feasible": holds(compiled, hint),
                  "seconds": round(time.monotonic() - began, 3)}
