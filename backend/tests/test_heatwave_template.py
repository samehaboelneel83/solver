"""The heatwave_cooling template (user trial): reach, hospital reach and outage areas computed from the
map when it is applied; seats, teams and a budget; goals in order."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.heatwave import BUDGET, HEATWAVE_COOLING
from app.main import app
from app.showcase import ensure_showcase_templates
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_the_template_opens_cooling_centres_from_the_map(tenants, db, empty_queue):  # noqa: F811
    client = TestClient(app)
    template_id = ensure_showcase_templates(db)[HEATWAVE_COOLING]
    applied = client.post(f"/api/v1/templates/{template_id}/apply", json={"domain_name": "heatwave"}, headers=tenants["a"])
    assert applied.status_code == 201, applied.text
    applied = applied.json()
    d = applied["domain_id"]
    reach = db.execute(text("SELECT name, source FROM parameter_def WHERE domain_id = :d ORDER BY name"), {"d": d}).all()
    assert [r.name for r in reach] == ["covers", "hosp_reach"]
    assert all(r.source["kind"] == "within" and r.source["pairs"] > 0 for r in reach)
    inside = db.execute(text("SELECT source FROM relationship_type WHERE domain_id = :d AND name = 'in_outage_area'"),
                        {"d": d}).scalar_one()
    assert inside["kind"] == "inside"
    teams = db.execute(text("SELECT count(*) FROM relationship r JOIN relationship_type t ON t.id = r.relationship_type_id"
                            " WHERE t.domain_id = :d AND t.name = 'base_hospital'"), {"d": d}).scalar_one()
    assert teams == 8  # each team linked to its hospital through the reference field

    run_id = client.post(f"/api/v1/scenarios/{applied['scenario_id']}/runs", json={"time_limit_s": 30, "reuse": False},
                         headers=tenants["a"]).json()["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    run = client.get(f"/api/v1/runs/{run_id}", headers=tenants["a"]).json()
    assert run["status"] == "optimal", (run["status"], run.get("error"))
    assert all(c["satisfied"] for c in run["constraints"] if c["hard"])
    answer = db.execute(text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": run_id}).scalar_one()
    opened = {k[0] for k in answer["open"]}
    assert opened and len({k[1] for k in answer["assign"]}) == len(opened)  # a team at every open site
    costs = dict(db.execute(text("SELECT e.key, (e.attrs ->> 'cost_egp_day')::int FROM entity e JOIN entity_type t"
                                 " ON t.id = e.entity_type_id WHERE t.domain_id = :d AND t.name = 'site'"), {"d": d}).all())
    assert sum(costs[k] for k in opened) <= BUDGET
