"""The whole chain (spec §11):

  ProblemDefinition -> Geometry -> Grid (discretize) -> MathematicalModel (builder)
  -> Stage 0 start (heuristic) -> SolverAdapter -> values -> LayoutResult
  -> GeometryValidator + PathValidator -> report

The same problem runs on any adapter: `solve(problem, solver="cpsat")`,
`solver="scip"`, `"highs"`, `"cbc"`, or `solver="heuristic"` for Stage 0 alone.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .adapters import adapter
from .builder import ModelBuilder
from .discretize import Grid, discretize
from .geometry import Geometry
from .heuristic import Constructor, hint_values
from .model import MathematicalModel, violations
from .optimize import Outcome, lexicographic, weighted
from .problem import CampProblem
from .result import LayoutResult, layout_from_values
from .validate import Validation, validate


@dataclass
class Run:
    problem: CampProblem
    grid: Grid
    model: MathematicalModel
    start: list[float]
    outcome: Outcome | None
    layout: LayoutResult
    validation: Validation
    seconds: dict[str, float]


def solve(problem: CampProblem, solver: str = "cpsat", *, time_limit: float = 60.0, threads: int = 4,
          stage_limits: dict[str, float] | None = None, log=print) -> Run:
    faults = problem.check()
    if faults:
        raise ValueError("the problem definition is not consistent: " + "; ".join(faults))
    clock: dict[str, float] = {}
    t = time.time()
    grid = discretize(problem, Geometry(problem))
    clock["discretize"] = time.time() - t
    t = time.time()
    builder = ModelBuilder(grid)
    model = builder.build()
    clock["model"] = time.time() - t
    log(f"{problem.name}: {grid.stats()}")
    log(f"model: {model.size()['variables']} variables, {model.size()['constraints']} constraints")

    t = time.time()
    lay = Constructor(grid).best()
    start = hint_values(builder, lay)
    bad = violations(model, start)
    if bad:
        raise AssertionError(f"Stage 0 start breaks the model: {bad[:3]}")
    clock["stage0"] = time.time() - t
    log(f"stage 0: {len(lay.beds)} beds ({lay.label}), {clock['stage0']:.1f}s")

    outcome = None
    values = start
    if solver != "heuristic":
        t = time.time()
        spec = problem.objectives
        if spec.mode == "lexicographic":
            outcome = lexicographic(model, adapter(solver), spec.order, trade_beds=spec.trade_beds,
                                    tolerance=spec.tolerance, time_limit=time_limit, threads=threads, start=start,
                                    stage_limits=stage_limits, log=log)
        else:
            outcome = weighted(model, adapter(solver), spec.weights, time_limit=time_limit, threads=threads,
                               start=start, log=log)
        clock["solve"] = time.time() - t
        if outcome.ok:
            values = outcome.values
    objectives = {name: round(o.expr.value(values), 3) for name, o in model.objectives.items()}
    stages = [s.__dict__ for s in outcome.stages] if outcome else [{"objective": "stage 0", "status": "heuristic"}]
    layout = layout_from_values(grid, builder, values, objectives, stages, outcome.solver if outcome else "heuristic")
    layout.model_size = model.size()
    t = time.time()
    validation = validate(problem, layout)
    clock["validate"] = time.time() - t
    log(f"validation: {'VALID' if validation.ok else 'INVALID'} "
        f"({sum(c.ok for c in validation.checks)}/{len(validation.checks)} checks)")
    for c in validation.checks:
        if not c.ok:
            log(f"  FAILED {c.name}: {c.detail}")
    return Run(problem, grid, model, start, outcome, layout, validation, clock)
