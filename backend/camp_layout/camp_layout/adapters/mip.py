"""MILP solvers through OR-Tools' MPSolver: SCIP, CBC or HiGHS.

Relaxable variables (the flows) become continuous: integral optimal flows
exist, so the MILP branches only on beds, tiles, cells and zone depths.
One adapter serves three solvers; which one is the backend's name.
"""
from __future__ import annotations

import time

from ortools.linear_solver import pywraplp

from ..model import MathematicalModel
from .base import SolveResult, SolverAdapter

BACKENDS = {"scip": "SCIP", "cbc": "CBC", "highs": "HIGHS"}


class MipAdapter(SolverAdapter):
    def __init__(self, backend: str = "scip"):
        if backend not in BACKENDS:
            raise ValueError(f"unknown MILP backend {backend!r}: {', '.join(BACKENDS)}")
        self.backend = backend
        self.name = f"mip:{backend}"

    def solve(self, model: MathematicalModel, objective, sense, *, extra=(), time_limit=60.0, hint=None,
              threads=4, relative_gap=0.0) -> SolveResult:
        start = time.time()
        s = pywraplp.Solver.CreateSolver(BACKENDS[self.backend])
        if s is None:
            return SolveResult("error", solver=self.name, message=f"{self.backend} is not in this OR-Tools build")
        s.SetTimeLimit(int(time_limit * 1000))
        s.SetNumThreads(int(threads))
        inf = s.infinity()
        xs = []
        for v in model.vars:
            integral = v.kind != "continuous" and not v.relaxable
            xs.append(s.IntVar(v.lb, v.ub, v.name) if integral else s.NumVar(v.lb, v.ub, v.name))
        for c in [*model.constraints, *extra]:
            lo = c.rhs if c.sense in (">=", "==") else -inf
            hi = c.rhs if c.sense in ("<=", "==") else inf
            row = s.RowConstraint(lo, hi, "")
            for k, coef in c.expr.terms.items():
                row.SetCoefficient(xs[k], coef)
        obj = s.Objective()
        for k, coef in objective.terms.items():
            obj.SetCoefficient(xs[k], coef)
        obj.SetMaximization() if sense == "max" else obj.SetMinimization()
        if hint:
            s.SetHint(xs, [float(h) for h in hint])
        params = pywraplp.MPSolverParameters()
        if relative_gap:
            params.SetDoubleParam(params.RELATIVE_MIP_GAP, float(relative_gap))
        status = s.Solve(params)
        seconds = time.time() - start
        name = {s.OPTIMAL: "optimal", s.FEASIBLE: "feasible", s.INFEASIBLE: "infeasible"}.get(status, "unknown")
        if name not in ("optimal", "feasible"):
            return SolveResult(name, seconds=seconds, solver=self.name, message=f"status {status}")
        values = [x.solution_value() for x in xs]
        for k, v in enumerate(model.vars):
            if v.kind != "continuous" and not v.relaxable:
                values[k] = float(round(values[k]))
        bound = obj.BestBound() + objective.constant
        return SolveResult(name, values, objective.value(values), bound, seconds, self.name, f"status {status}")
