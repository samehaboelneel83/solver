"""OR-Tools CP-SAT: every variable integer, every coefficient an integer.

Coefficients here are multiples of the grid pitch and its square (0.5, 0.25),
zone areas and the area-per-bed rule: each row and the objective are scaled
by the least common denominator of its coefficients (exactly, through
fractions) so nothing is rounded away. Relaxable variables stay integer:
CP-SAT has no continuous variables, and the model is exact with them integer.
"""
from __future__ import annotations

import math
import time
from fractions import Fraction

from ortools.sat.python import cp_model

from ..model import Constraint, Expr, MathematicalModel
from .base import SolveResult, SolverAdapter


def _integral(coefs: list[float], rhs: float) -> tuple[list[int], int, int]:
    fr = [Fraction(c).limit_denominator(10_000) for c in coefs] + [Fraction(rhs).limit_denominator(10_000)]
    scale = 1
    for f in fr:
        scale = scale * f.denominator // math.gcd(scale, f.denominator)
    ints = [int(f * scale) for f in fr]
    return ints[:-1], ints[-1], scale


class CpSatAdapter(SolverAdapter):
    name = "cp-sat"

    def solve(self, model: MathematicalModel, objective: Expr, sense, *, extra=(), time_limit=60.0, hint=None,
              threads=4, relative_gap=0.0) -> SolveResult:
        start = time.time()
        cp = cp_model.CpModel()
        xs = []
        for v in model.vars:
            lb, ub = int(math.floor(v.lb)), int(math.ceil(v.ub))
            xs.append(cp.NewBoolVar(v.name) if v.kind == "binary" else cp.NewIntVar(lb, ub, v.name))
        for c in [*model.constraints, *extra]:
            self._row(cp, xs, c)
        idx = list(objective.terms)
        coefs, _, scale = _integral([objective.terms[k] for k in idx], 0.0)
        expr = sum(cf * xs[k] for cf, k in zip(coefs, idx))
        (cp.Maximize if sense == "max" else cp.Minimize)(expr)
        if hint:
            for k, x in enumerate(xs):
                cp.AddHint(x, int(round(hint[k])))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit)
        solver.parameters.num_workers = int(threads)
        if relative_gap:
            solver.parameters.relative_gap_limit = float(relative_gap)
        status = solver.Solve(cp)
        seconds = time.time() - start
        name = {cp_model.OPTIMAL: "optimal", cp_model.FEASIBLE: "feasible", cp_model.INFEASIBLE: "infeasible",
                cp_model.MODEL_INVALID: "error"}.get(status, "unknown")
        if name not in ("optimal", "feasible"):
            return SolveResult(name, seconds=seconds, solver=self.name, message=solver.StatusName(status))
        values = [float(solver.Value(x)) for x in xs]
        return SolveResult(name, values, objective.value(values), solver.BestObjectiveBound() / scale + objective.constant,
                           seconds, self.name, solver.StatusName(status))

    @staticmethod
    def _row(cp, xs, c: Constraint) -> None:
        idx = list(c.expr.terms)
        coefs, rhs, _ = _integral([c.expr.terms[k] for k in idx], c.rhs)
        lhs = sum(cf * xs[k] for cf, k in zip(coefs, idx))
        if c.sense == "<=":
            cp.Add(lhs <= rhs)
        elif c.sense == ">=":
            cp.Add(lhs >= rhs)
        else:
            cp.Add(lhs == rhs)
