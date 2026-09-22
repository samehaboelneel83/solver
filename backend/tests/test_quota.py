"""Quotas, metered usage and fair claiming (migration 0034, Phase 7).

Uses `test_tenancy`'s two organizations: A (the operator, with one queued
run) and B (a tenant whose administrator holds every capability).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.solve.service import claim_next, enqueue_run, variable_count
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import IR, tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _set_quota(tenants, **limits):
    response = TestClient(app).put(
        f"/api/v1/organizations/{tenants['org_b']}/quota", json=limits, headers=tenants["a"]
    )
    assert response.status_code == 200, response.text
    return response.json()


def _scenario_b(tenants) -> int:
    client, headers = TestClient(app), tenants["b"]
    domain = client.post("/api/domain/", json={"name": "quota"}, headers=headers).json()["id"]
    problem = client.post("/api/problem/", json={"domain_id": domain, "name": "p"}, headers=headers).json()["id"]
    version = client.post(f"/api/v1/problems/{problem}/versions", json={"ir": IR}, headers=headers).json()["id"]
    return client.post(
        "/api/v1/scenarios", json={"problem_id": problem, "model_version_id": version, "name": "s"}, headers=headers
    ).json()["id"]


def _submit(tenants, scenario: int, **body):
    return TestClient(app).post(f"/api/v1/scenarios/{scenario}/runs", json=body, headers=tenants["b"])


def _refused(response, quota: str) -> str:
    assert response.status_code == 422, response.text
    (item,) = response.json()["detail"]
    assert item["loc"] == ["quota", quota]
    return item["msg"]


# -- reading and setting -----------------------------------------------------------


def test_an_organization_without_a_quota_row_is_unlimited(tenants):
    body = TestClient(app).get("/api/v1/quota", headers=tenants["b"]).json()
    assert body["limits"] == dict.fromkeys(body["limits"])
    assert body["this_month"] == {"cpu_seconds": 0.0, "runs": 0}


def test_only_an_operator_sets_a_quota(tenants):
    response = TestClient(app).put(
        f"/api/v1/organizations/{tenants['org_b']}/quota", json={"max_vars": 5}, headers=tenants["b"]
    )
    assert response.status_code == 403
    assert "operator" in response.json()["detail"]

    set_ = _set_quota(tenants, max_vars=5)
    assert set_["limits"]["max_vars"] == 5
    seen = TestClient(app).get("/api/v1/quota", headers=tenants["b"]).json()
    assert seen["limits"]["max_vars"] == 5


# -- refused at submit -------------------------------------------------------------------


def test_a_time_limit_over_the_quota_is_refused_naming_it(tenants):
    scenario = _scenario_b(tenants)
    _set_quota(tenants, max_time_limit_s=5)

    assert "quota of 5 s" in _refused(_submit(tenants, scenario, time_limit_s=30), "max_time_limit_s")
    assert _submit(tenants, scenario, time_limit_s=5).status_code == 201


def test_a_full_queue_is_refused(tenants):
    scenario = _scenario_b(tenants)
    _set_quota(tenants, max_queued_runs=1)

    assert _submit(tenants, scenario).status_code == 201
    _refused(_submit(tenants, scenario), "max_queued_runs")


def test_too_many_decisions_is_refused_and_nothing_is_kept(tenants, db):
    scenario = _scenario_b(tenants)
    _set_quota(tenants, max_vars=1)
    many = {**IR, "variables": {"x": IR["variables"]["x"], "y": IR["variables"]["x"]}}
    assert variable_count(many, {"sets": {}}) == 2

    client, headers = TestClient(app), tenants["b"]
    problem = db.execute(text("SELECT problem_id FROM scenario WHERE id = :s"), {"s": scenario}).scalar_one()
    version = client.post(f"/api/v1/problems/{problem}/versions", json={"ir": many}, headers=headers).json()["id"]
    wide = client.post(
        "/api/v1/scenarios", json={"problem_id": problem, "model_version_id": version, "name": "wide"}, headers=headers
    ).json()["id"]

    assert "2 decisions" in _refused(_submit(tenants, wide), "max_vars")
    runs = db.execute(text("SELECT count(*) FROM run WHERE scenario_id = :s"), {"s": wide}).scalar_one()
    assert runs == 0


def test_a_month_of_cpu_used_up_is_refused(tenants, db):
    scenario = _scenario_b(tenants)
    _set_quota(tenants, cpu_seconds_month=100)
    db.execute(
        text(
            "INSERT INTO iam.usage_month (organization_id, month, cpu_seconds, runs)"
            " VALUES (:o, date_trunc('month', now() AT TIME ZONE 'UTC')::date, 100, 3)"
        ),
        {"o": tenants["org_b"]},
    )
    db.commit()

    assert "100 of its 100" in _refused(_submit(tenants, scenario), "cpu_seconds_month")


# -- metered --------------------------------------------------------------------------


def test_a_settled_run_is_metered_as_wall_time_times_threads(tenants, db):
    scenario = _scenario_b(tenants)
    run = _submit(tenants, scenario).json()["id"]
    work_once(db)  # A's queued run, which is older ...
    work_once(db)  # ... but B has none running either, so either order is fair.

    wall, workers = db.execute(
        text("SELECT wall_time_s, (params ->> 'workers')::int FROM run WHERE id = :r"), {"r": run}
    ).one()
    used = TestClient(app).get("/api/v1/quota", headers=tenants["b"]).json()["this_month"]
    assert used["runs"] == 1
    assert abs(used["cpu_seconds"] - wall * workers) < 1e-9


# -- fair claim ----------------------------------------------------------------------------


def test_the_next_run_is_from_the_organization_with_fewest_in_progress(tenants, db):
    """A has a run in progress and more waiting, all older than B's one run.
    Oldest-first would make B wait behind all of A's; fair claim takes B's."""
    db.execute(text("UPDATE run SET status = 'running', started_at = now() WHERE id = :r"), {"r": tenants["run_a"]})
    db.commit()
    older_a = enqueue_run(db, tenants["scenario_a"], time_limit=5.0)
    run_b = _submit(tenants, _scenario_b(tenants)).json()["id"]

    assert claim_next(db) == run_b
    assert claim_next(db) == older_a


def test_an_organization_at_its_concurrency_quota_waits(tenants, db):
    _set_quota(tenants, max_concurrent_runs=1)
    scenario = _scenario_b(tenants)
    first = _submit(tenants, scenario).json()["id"]
    second = _submit(tenants, scenario).json()["id"]
    db.execute(text("UPDATE run SET status = 'running', started_at = now() WHERE id = :r"), {"r": first})
    db.commit()

    # B is at its one concurrent run: A's queued run is taken, then nothing.
    assert claim_next(db) == tenants["run_a"]
    assert claim_next(db) is None

    db.execute(text("UPDATE run SET status = 'optimal', finished_at = now() WHERE id = :r"), {"r": first})
    db.commit()
    assert claim_next(db) == second
