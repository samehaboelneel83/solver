"""Epic engine, E-2: IPOPT from several starting points.

IPOPT follows the slope from where it starts, so on a goal with several peaks
one start finds the nearest. `sin(x) + x/10` over [0, 20] has peaks near 1.7,
7.9 and 14.2 and its best value at the bound x = 20 (about 2.91); from the
middle of the range (x = 10) IPOPT climbs to the peak near 7.9 (about 1.78).
"""

from __future__ import annotations

import math

import pytest

from app.solve import compile_model
from app.solve.backends import IPOPT, by_name
from app.solve.ipopt import spread
from app.solve.params import check, parse_setting
from app.solve.service import solve_compiled
from tests.test_functions import NO_DATA, X, _ir, empty_queue, fn, plus  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401

pytestmark = pytest.mark.skipif(not IPOPT.is_available(), reason="casadi (IPOPT) is not installed in this image")

PEAKS = _ir(plus(fn("sin", X), {"mul": [{"const": 0.1}, X]}), "maximize", x=(0, 20))
BEST = math.sin(20) + 2.0


def _solve(starts: int | None, seed: int = 1):
    params = None if starts is None else {"starts": starts}
    return solve_compiled(by_name("ipopt"), compile_model(PEAKS, NO_DATA), time_limit=20, seed=seed,
                          solver_params=params)[0]


def test_one_start_finds_the_peak_nearest_the_middle():
    result = _solve(None)
    assert result.status == "optimal"
    assert result.objective == pytest.approx(math.sin(7.954) + 0.7954, abs=1e-2)
    assert "starts" not in result.solver


def test_several_starts_find_the_best_peak_and_say_how():
    result = _solve(8)
    assert result.status == "optimal"
    assert result.objective == pytest.approx(BEST, abs=1e-5)
    assert result.assignments[("x", ())] == pytest.approx(20, abs=1e-5)
    assert "from 8 starts" in result.solver


def test_multistart_is_reproducible_from_its_seed():
    a, b = _solve(4, seed=7), _solve(4, seed=7)
    assert a.objective == b.objective and a.assignments == b.assignments


def test_a_multistart_answer_is_still_only_local():
    # Several nearby optima are still nearby optima: the backend proves `local`.
    assert IPOPT.proves == "local"


def test_starts_are_spread_one_per_slice_of_each_range():
    points = spread([0.0, -1.0], [10.0, 1.0], 5, seed=3)
    assert len(points) == 5
    for column, (lo, hi) in zip(zip(*points), [(0.0, 10.0), (-1.0, 1.0)]):
        slices = sorted(int((v - lo) / (hi - lo) * 5) for v in column)
        assert slices == [0, 1, 2, 3, 4]
    assert spread([0.0], [1.0], 0, seed=1) == []


def test_an_unbounded_side_becomes_a_box_around_the_other():
    (point,) = spread([5.0], [float("inf")], 1, seed=1)
    assert 5.0 <= point[0] <= 1005.0


def test_starts_is_a_whitelisted_option_with_whitelisted_values():
    assert check("ipopt", {"starts": 8}) == {"starts": 8}
    assert parse_setting("ipopt.starts=16") == {"ipopt": {"starts": 16}}
    with pytest.raises(ValueError):
        check("ipopt", {"starts": 3})


# -- SCIP's global bound beside the best of several starts ---------------------------------------


def _bound(result):
    from app.solve.classify import classify
    from app.solve.service import _global_bound

    return _global_bound(compile_model(PEAKS, NO_DATA), classify(PEAKS, NO_DATA), result, time_limit=20, seed=1,
                         workers=2, should_stop=lambda: False)


@pytest.mark.skipif(not by_name("scip").is_available(), reason="SCIP is not installed in this image")
def test_scip_s_bound_proves_the_best_start_best():
    best = _solve(8)
    bounded, record = _bound(best)
    assert record["used"] is True and record["proven"] is True
    assert bounded.best_bound == pytest.approx(BEST, abs=1e-4) and record["gap"] <= 1e-4
    # The answer is IPOPT's still: SCIP only says how far any other could be.
    assert bounded.assignments == best.assignments and bounded.solver == best.solver


@pytest.mark.skipif(not by_name("scip").is_available(), reason="SCIP is not installed in this image")
def test_a_nearer_peak_is_shown_how_far_it_is_from_the_best():
    near = _solve(None)
    bounded, record = _bound(near)
    assert record["proven"] is False
    assert bounded.best_bound == pytest.approx(BEST, abs=1e-4)
    assert record["gap"] == pytest.approx((BEST - near.objective) / near.objective, rel=1e-3)


@pytest.mark.skipif(not by_name("scip").is_available(), reason="SCIP is not installed in this image")
def test_a_multistart_run_proven_by_scip_s_bound_claims_the_global_optimum(db, empty_queue):  # noqa: F811
    from sqlalchemy import text

    from app.solve.service import claim_next, enqueue_run, execute_run

    problem = make_problem(db, make_domain(db, "multistart-bound"))
    version = make_model_version(db, problem, PEAKS)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value)"
                    " VALUES ('problem', :p, 'solve.solver_params', to_jsonb('ipopt.starts=8'::text))"), {"p": problem})
    db.commit()
    try:
        run_id = enqueue_run(db, scenario, time_limit=20.0, reuse=False, solver="ipopt")
        claim_next(db)
        assert execute_run(db, run_id).status == "optimal"
        row = db.execute(text("SELECT optimality, best_bound, gap, params FROM run WHERE id = :r"),
                         {"r": run_id}).mappings().one()
        assert row["optimality"] == "global"
        assert float(row["best_bound"]) == pytest.approx(BEST, abs=1e-4)
        assert row["params"]["global_bound_run"]["proven"] is True
    finally:
        db.execute(text("DELETE FROM setting WHERE scope = 'problem' AND scope_id = :p"), {"p": problem})
        db.execute(text("DELETE FROM run"))
        db.commit()
