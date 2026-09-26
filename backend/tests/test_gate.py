"""The gate (queue R30): a problem with acceptance cases puts a new version into use only once it has
passed every one; checks never delay a planner's run."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import text

from app.solve.service import claim_next, enqueue_run, execute_run
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


def _with_case(db, client, auth_headers):
    """The two-day rota in use on version 1, solved, and made a case."""
    version, _ = _feasible(db)
    run = enqueue_run(db, _scenario_for(db, version), time_limit=10.0, reuse=False)
    assert claim_next(db) == run
    execute_run(db, run)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    made = client.post(f"/api/v1/problems/{problem}/suite-cases/from-run/{run}", headers=auth_headers, json={"name": "two shifts"})
    assert made.status_code == 201, made.text
    return problem, version


def _next_version(db, problem, version, weight=1):
    ir = copy.deepcopy(db.execute(text("SELECT ir FROM model_version WHERE id = :v"), {"v": version}).scalar_one())
    ir["objective"]["terms"][0]["weight"] = weight
    ir["constraints"][0]["note"] = f"reworded {weight}"  # a different version, whatever the weight
    made = make_model_version(db, problem, ir)
    db.commit()
    return made


def _point(client, auth_headers, problem, version, name):
    return client.post("/api/v1/scenarios", headers=auth_headers,
                       json={"problem_id": problem, "model_version_id": version, "name": name})


def _check(db, client, auth_headers, version):
    response = client.post(f"/api/v1/model-versions/{version}/check", headers=auth_headers)
    assert response.status_code == 201, response.text
    for _ in response.json()["run_ids"]:
        run = claim_next(db)
        execute_run(db, run)
    return client.get(f"/api/v1/model-versions/{version}/checks", headers=auth_headers).json()


def test_a_new_version_is_put_into_use_only_once_it_passes(db, empty_queue, client, auth_headers):
    problem, version = _with_case(db, client, auth_headers)
    second = _next_version(db, problem, version)
    refused = _point(client, auth_headers, problem, second, "next week")
    assert refused.status_code == 409
    assert refused.json()["detail"][0]["type"] == "version_not_checked"
    assert "two shifts: unchecked" in refused.json()["detail"][0]["msg"]

    checks = _check(db, client, auth_headers, second)
    assert checks["state"] == "passed" and [c["state"] for c in checks["cases"]] == ["passed"]
    assert _point(client, auth_headers, problem, second, "next week").status_code == 201


def test_a_version_that_fails_says_why_and_stays_out(db, empty_queue, client, auth_headers):
    problem, version = _with_case(db, client, auth_headers)
    dearer = _next_version(db, problem, version, weight=3)
    checks = _check(db, client, auth_headers, dearer)
    assert checks["state"] == "failed" and "the objective is 6, expected 2" in checks["cases"][0]["reasons"][0]
    refused = _point(client, auth_headers, problem, dearer, "next week")
    assert refused.status_code == 409 and "two shifts: failed (the objective is 6" in refused.json()["detail"][0]["msg"]


def test_a_version_already_in_use_is_not_held_back(db, empty_queue, client, auth_headers):
    """Softening rules on the version planners already use is not publishing anything."""
    problem, version = _with_case(db, client, auth_headers)
    assert _point(client, auth_headers, problem, version, "softened").status_code == 201


def test_the_gate_can_be_turned_off_and_a_problem_without_cases_has_none(db, empty_queue, client, auth_headers):
    problem, version = _with_case(db, client, auth_headers)
    second = _next_version(db, problem, version)
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'suite.required',"
                    " CAST('false' AS jsonb))"), {"p": problem})
    db.commit()
    assert _point(client, auth_headers, problem, second, "next week").status_code == 201

    fresh, _ = _feasible(db)
    fresh_problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": fresh}).scalar_one()
    newer = _next_version(db, fresh_problem, fresh)
    assert _point(client, auth_headers, fresh_problem, newer, "anything").status_code == 201


def test_repointing_a_scenario_is_gated_too(db, empty_queue, client, auth_headers):
    problem, version = _with_case(db, client, auth_headers)
    second = _next_version(db, problem, version)
    scenario = db.execute(text("SELECT id FROM scenario WHERE problem_id = :p AND name = 'base'"), {"p": problem}).scalar_one()
    response = client.patch(f"/api/v1/scenarios/{scenario}", headers=auth_headers, json={"model_version_id": second})
    assert response.status_code == 409


def test_checks_never_delay_a_planners_run(db, empty_queue, client, auth_headers):
    problem, version = _with_case(db, client, auth_headers)
    client.post(f"/api/v1/model-versions/{version}/check", headers=auth_headers)  # queued first
    base = db.execute(text("SELECT id FROM scenario WHERE problem_id = :p AND name = 'base'"), {"p": problem}).scalar_one()
    plan = enqueue_run(db, base, time_limit=10.0, reuse=False)
    assert claim_next(db) == plan
