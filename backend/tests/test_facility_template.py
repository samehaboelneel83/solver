"""The facility_coverage template (queue R16a): applied, its distances come from the map, and it solves."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.facilities import FACILITY_COVERAGE, REACH_M
from app.main import app
from app.showcase import ensure_showcase_templates
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_the_template_solves_on_distances_nobody_typed_in(tenants, db, empty_queue):  # noqa: F811
    client = TestClient(app)
    template_id = ensure_showcase_templates(db)[FACILITY_COVERAGE]
    applied = client.post(f"/api/v1/templates/{template_id}/apply", json={"domain_name": "sites"}, headers=tenants["a"])
    assert applied.status_code == 201, applied.text
    applied = applied.json()
    domain = applied["domain_id"]
    source = db.execute(text("SELECT source FROM parameter_def WHERE domain_id = :d AND name = 'distance'"), {"d": domain}).scalar_one()
    assert source["kind"] == "distance" and source["pairs"] == 8 * 40
    reach = db.execute(text("SELECT source FROM relationship_type WHERE domain_id = :d AND name = 'reaches'"), {"d": domain}).scalar_one()
    assert reach["kind"] == "within" and reach["max_m"] == REACH_M and reach["edges"] > 40

    # Applied again: the computed data is left as it is, like every other name in a seed.
    again = client.post(f"/api/v1/templates/{template_id}/apply", json={"domain_id": domain, "name": "again"}, headers=tenants["a"])
    assert again.status_code == 201, again.text
    assert db.execute(text("SELECT count(*) FROM parameter_def WHERE domain_id = :d"), {"d": domain}).scalar_one() == 1

    run_id = client.post(f"/api/v1/scenarios/{applied['scenario_id']}/runs", json={"time_limit_s": 30, "reuse": False},
                         headers=tenants["a"]).json()["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    run = client.get(f"/api/v1/runs/{run_id}", headers=tenants["a"]).json()
    assert run["status"] == "optimal", (run["status"], run.get("error"))
    assert {c["name"] for c in run["params"]["computed_inputs"]} == {"distance", "reaches"}
