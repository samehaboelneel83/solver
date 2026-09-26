"""Shadow runs (queue R31, app.solve.shadow): a candidate version answers a share of real runs beside
the one in use, compared once both settle, never shown to the planner."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import text

from app.solve import shadow
from app.solve.service import cancel_run, claim_next, enqueue_run, execute_run
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_diagnose import _scenario_for
from tests.test_solve import _feasible
from tests.test_v1_problem_run import db, make_model_version  # noqa: F401


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _setting(db, problem, key, value):
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, :k, CAST(:v AS jsonb))"
                    " ON CONFLICT (scope, scope_id, key) DO UPDATE SET value = EXCLUDED.value"),
               {"p": problem, "k": key, "v": str(value)})
    db.commit()


def _shadowed(db, weight=1, rate=1):
    """The two-day rota on version 1, and version 2 (the goal times `weight`) as the shadow."""
    version, _ = _feasible(db)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    ir = copy.deepcopy(db.execute(text("SELECT ir FROM model_version WHERE id = :v"), {"v": version}).scalar_one())
    ir["objective"]["terms"][0]["weight"] = weight
    ir["constraints"][0]["note"] = f"candidate {weight}"
    candidate = make_model_version(db, problem, ir)
    db.commit()
    _setting(db, problem, "shadow.version", candidate)
    _setting(db, problem, "shadow.rate", rate)
    return problem, version, candidate, _scenario_for(db, version)


def _drain(db):
    while (run := claim_next(db)) is not None:
        execute_run(db, run)


def test_each_real_run_gets_one_twin_and_they_are_compared(db, empty_queue, client, auth_headers):
    problem, _, candidate, scenario = _shadowed(db, weight=3)
    real = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": real}).scalar_one()
    twin = params["shadow_run"]
    row = db.execute(text("SELECT purpose, parent_run_id, dataset_id FROM run WHERE id = :t"), {"t": twin}).mappings().one()
    assert row["purpose"] == "shadow" and row["parent_run_id"] == real
    _drain(db)
    verdict = db.execute(text("SELECT verdict FROM run WHERE id = :t"), {"t": twin}).scalar_one()
    # Three times the cost for the same two shifts: 6 against 2, worse for a minimised goal.
    assert verdict["real"] == {"status": "optimal", "objective": 2} and verdict["shadow"]["objective"] == 6
    assert verdict["delta"] == 4 and verdict["at_least_as_good"] is False and "moved" in verdict
    # Not the planner's: the runs list and its events leave it out.
    listed = [r["id"] for r in client.get("/api/v1/runs", headers=auth_headers).json()["items"]]
    assert real in listed and twin not in listed
    report = client.get(f"/api/v1/problems/{problem}/shadow", headers=auth_headers).json()["candidates"]
    assert report[0]["model_version_id"] == candidate and report[0]["runs"] == 1
    assert report[0]["share_at_least_as_good"] == 0 and report[0]["worst"]["delta"] == 4


def test_the_share_shadowed_is_the_rate_and_reproducible():
    assert not any(shadow.picked(i, 0) for i in range(1, 500))
    assert all(shadow.picked(i, 1) for i in range(1, 500))
    half = sum(shadow.picked(i, 0.5) for i in range(1, 201))
    assert 70 <= half <= 130  # a binomial(200, 0.5) band, well past three deviations
    assert [shadow.picked(i, 0.3) for i in range(1, 50)] == [shadow.picked(i, 0.3) for i in range(1, 50)]


def test_rate_zero_makes_no_twin(db, empty_queue):
    _, _, _, scenario = _shadowed(db, rate=0)
    real = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    assert db.execute(text("SELECT count(*) FROM run WHERE parent_run_id = :r"), {"r": real}).scalar_one() == 0


def test_a_candidate_that_fails_is_a_failed_shadow_not_a_failed_run(db, empty_queue):
    problem, version, _, scenario = _shadowed(db)
    ir = copy.deepcopy(db.execute(text("SELECT ir FROM model_version WHERE id = :v"), {"v": version}).scalar_one())
    ir["constraints"][0]["right"] = {"par": "demand", "index": ["d", "s"]}
    ir["constraints"][0]["relation"] = ">="
    ir["constraints"].append({"id": "c_impossible", "left": {"const": 1}, "relation": "<=", "right": {"const": 0},
                              "severity": "hard"})
    broken = make_model_version(db, problem, ir)
    db.commit()
    _setting(db, problem, "shadow.version", broken)
    real = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    _drain(db)
    assert db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": real}).scalar_one() == "optimal"
    twin = db.execute(text("SELECT id, verdict FROM run WHERE parent_run_id = :r"), {"r": real}).mappings().one()
    assert twin["verdict"]["shadow"]["status"] == "infeasible" and twin["verdict"]["same_status"] is False


def test_cancelling_the_real_run_cancels_its_twin(db, empty_queue):
    _, _, _, scenario = _shadowed(db)
    real = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    cancel_run(db, real)
    statuses = db.execute(text("SELECT status FROM run WHERE id = :r OR parent_run_id = :r ORDER BY id"), {"r": real}).scalars().all()
    assert statuses == ["cancelled", "cancelled"]


def test_a_candidate_that_has_not_passed_its_cases_is_not_shadowed(db, empty_queue, client, auth_headers):
    problem, version, _, scenario = _shadowed(db)
    first = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    _drain(db)
    made = client.post(f"/api/v1/problems/{problem}/suite-cases/from-run/{first}", headers=auth_headers, json={"name": "two shifts"})
    assert made.status_code == 201
    real = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": real}).scalar_one()
    assert "shadow_run" not in params and "acceptance cases (unchecked)" in params["shadow_skipped"]
