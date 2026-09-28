"""The goal's constant is part of its value, on every backend.

SCIP, CP-SAT and the MILP wrapper once reported the objective, and its bound,
without the goal's constant, while HiGHS counted it: the same model recorded
10 on one solver and 15 on another, and `run.objective` depended on which
solver the rules happened to choose. Blocks, the metaheuristics and the
partition start already counted it; now every backend does.
"""

from __future__ import annotations

import pytest

from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.service import solve_compiled


@pytest.mark.parametrize("backend", ["highs", "scip", "cp-sat", "milp"])
def test_every_backend_counts_the_goal_s_constant(backend):
    # Regression: SCIP, CP-SAT and the MILP wrapper once reported the goal
    # without its constant, so the same model recorded 10 on one solver and
    # 15 on another. A boosted model's `base` is such a constant.
    ir = {"version": 2, "sets": [], "parameters": {}, "constraints": [],
          "variables": {"x": {"index": [], "domain": "integer", "lower": 0, "upper": 10}},
          "objective": {"sense": "maximize", "terms": [
              {"id": "o", "weight": 1, "expression": {"add": [{"var": "x", "index": []}, {"const": 5}]}}]}}
    result, _ = solve_compiled(by_name(backend), compile_model(ir, {}), time_limit=10, seed=1)
    assert result.objective == 15
    assert float(result.best_bound) == pytest.approx(15)
