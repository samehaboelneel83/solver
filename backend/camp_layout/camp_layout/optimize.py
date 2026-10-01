"""Objective driver: lexicographic stages or one normalised weighted sum.

Lexicographic (spec §8): solve for the first objective; keep what it
reached as a constraint (beds exactly -- never given back unless the problem
says `trade_beds`; the others within their `tolerance`); solve for the next,
starting from the previous answer. A stage that runs out of time keeps the
best answer it found and says so: its value, and the bound, are reported,
never an "optimal" it did not prove.

Weighted: Σ w_i · s_i · obj_i / scale_i, where s_i is +1 for a maximised and
-1 for a minimised objective and scale_i the objective's typical size (the
builder's estimate), so no objective dominates merely by its units.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .adapters.base import SolveResult, SolverAdapter
from .model import Constraint, Expr, MathematicalModel


@dataclass
class Stage:
    objective: str
    status: str
    value: float | None
    bound: float | None
    seconds: float
    kept: str  # the constraint this stage leaves for the next


@dataclass
class Outcome:
    values: list[float] | None
    stages: list[Stage] = field(default_factory=list)
    solver: str = ""

    @property
    def ok(self) -> bool:
        return self.values is not None


def lexicographic(model: MathematicalModel, solver: SolverAdapter, order, *, trade_beds=False, tolerance=None,
                  time_limit=60.0, threads=4, start: list[float] | None = None, stage_limits=None, log=print) -> Outcome:
    tolerance = tolerance or {}
    extra: list[Constraint] = []
    hint: list[float] | None = start
    out = Outcome(None, solver=solver.name)
    for name in order:
        obj = model.objectives[name]
        limit = (stage_limits or {}).get(name, time_limit)
        result: SolveResult = solver.solve(model, obj.expr, obj.sense, extra=extra, time_limit=limit,
                                           hint=hint, threads=threads)
        if not result.has_solution:
            out.stages.append(Stage(name, result.status, None, None, result.seconds, "stopped"))
            log(f"  {name}: {result.status} after {result.seconds:.1f}s ({result.message})")
            if out.values is None:
                return out
            break
        out.values, hint = result.values, result.values
        value = result.objective
        if name == "beds" and not trade_beds:
            keep, text = math.floor(value + 1e-6), "exactly"
            extra.append(Constraint(Expr(dict(obj.expr.terms)), ">=", keep - obj.expr.constant, f"keep:{name}"))
        else:
            slack = tolerance.get(name, 0.0)
            if obj.sense == "max":
                keep = value - abs(value) * slack
                extra.append(Constraint(Expr(dict(obj.expr.terms)), ">=", keep - obj.expr.constant, f"keep:{name}"))
            else:
                keep = value + abs(value) * slack + 1e-6
                extra.append(Constraint(Expr(dict(obj.expr.terms)), "<=", keep - obj.expr.constant, f"keep:{name}"))
            text = f"within {slack:.0%}" if slack else "exactly"
        out.stages.append(Stage(name, result.status, value, result.bound, result.seconds,
                                f"{name} {'≥' if obj.sense == 'max' else '≤'} {keep:g} ({text})"))
        log(f"  {name}: {value:g} {obj.unit} ({result.status}, bound {result.bound:g}, {result.seconds:.1f}s)")
    return out


def weighted(model: MathematicalModel, solver: SolverAdapter, weights, *, time_limit=60.0, threads=4,
             start: list[float] | None = None, log=print) -> Outcome:
    total = Expr()
    for name, w in weights.items():
        if not w:
            continue
        obj = model.objectives[name]
        sign = 1.0 if obj.sense == "max" else -1.0
        total = total.plus(obj.expr, sign * w / obj.scale)
    # Integer-friendly: CP-SAT scales exactly, but keep the numbers sane.
    total = Expr({k: round(c, 6) for k, c in total.terms.items()}, total.constant)
    result = solver.solve(model, total, "max", time_limit=time_limit, threads=threads, hint=start)
    out = Outcome(result.values if result.has_solution else None, solver=solver.name)
    out.stages.append(Stage("weighted", result.status, result.objective, result.bound, result.seconds, ""))
    log(f"  weighted: {result.status} ({result.seconds:.1f}s)")
    return out
