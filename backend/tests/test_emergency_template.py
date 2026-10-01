"""The emergency_coverage template (improvement plan 5.8): reach from the map, goals in order, a backup rule."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.emergency_coverage import EMERGENCY_COVERAGE, MAX_OPEN, REACH_M
from app.main import app
from app.showcase import ensure_showcase_templates
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_the_template_covers_from_the_map_with_goals_in_order(tenants, db, empty_queue):  # noqa: F811
    client = TestClient(app)
    template_id = ensure_showcase_templates(db)[EMERGENCY_COVERAGE]
    applied = client.post(f"/api/v1/templates/{template_id}/apply", json={"domain_name": "cover"}, headers=tenants["a"])
    assert applied.status_code == 201, applied.text
    applied = applied.json()
    reach = db.execute(text("SELECT source FROM relationship_type WHERE domain_id = :d AND name = 'reaches'"),
                       {"d": applied["domain_id"]}).scalar_one()
    assert reach["kind"] == "within" and reach["max_m"] == REACH_M and reach["edges"] > 60
    run_id = client.post(f"/api/v1/scenarios/{applied['scenario_id']}/runs", json={"time_limit_s": 30, "reuse": False},
                         headers=tenants["a"]).json()["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    run = client.get(f"/api/v1/runs/{run_id}", headers=tenants["a"]).json()
    assert run["status"] in ("optimal", "feasible"), (run["status"], run.get("error"))
    assert run["params"]["objective_mode"] == "lex"
    opened = db.execute(text("SELECT assignments -> 'open' FROM solution WHERE run_id = :r"), {"r": run_id}).scalar_one()
    assert 1 <= len(opened) <= MAX_OPEN
    mapped = client.get(f"/api/v1/runs/{run_id}/answer-map", headers=tenants["a"]).json()
    assert {l["id"] for l in mapped["layers"]} >= {"open", "covered"}
