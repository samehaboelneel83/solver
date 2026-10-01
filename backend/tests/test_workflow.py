"""A problem from one place: readiness names every missing value with what it
takes to fill it, and one solve keeps a "Base" scenario on the latest version."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.solve.missing import attribute_reads, missing_values
from tests.test_api_runs import auth_headers, ensure_admin_seeded  # noqa: F401
from tests.test_v1_problem_run import (  # noqa: F401
    db,
    make_domain,
    make_entity,
    make_entity_type,
    make_model_version,
    make_problem,
)

IR = {
    "version": 2, "sets": ["employee"], "parameters": {},
    "variables": {"pick": {"index": ["employee"], "domain": "binary"}},
    "constraints": [{"id": "c_one", "left": {"sum": {"var": "pick", "index": ["e"]}, "over": [{"index": "e", "set": "employee"}]},
                     "relation": "<=", "right": {"const": 1}, "severity": "hard"}],
    "objective": {"sense": "maximize", "terms": [{"id": "o_hours", "weight": 1, "expression": {
        "sum": {"mul": [{"attr": {"of": "e", "name": "hours_per_week"}}, {"var": "pick", "index": ["e"]}]},
        "over": [{"index": "e", "set": "employee"}]}}]},
}


def test_attribute_reads_are_items_numbers_not_links():
    ir = {"constraints": [{"forall": [{"index": "m", "set": "employee"}],
                           "left": {"sum": {"mul": [{"attr": {"of": "r", "name": "weight"}}, {"attr": {"of": "e", "name": "grade"}}]},
                                    "over": [{"index": "e", "set": "employee", "via": {"rel": "manages", "from": "m", "as": "r"}}]},
                           "right": {"attr": {"of": "m", "name": "cap"}}}]}
    assert attribute_reads(ir) == {("employee", "grade"), ("employee", "cap")}
    data = {"sets": {"employee": [{"id": "a", "grade": 1, "cap": 2}, {"id": "b", "cap": None}, {"id": "c", "grade": 3, "cap": 1}]}}
    assert missing_values(ir, data) == [
        {"set": "employee", "attribute": "cap", "records": ["b"]},
        {"set": "employee", "attribute": "grade", "records": ["b"]},
    ]


@pytest.fixture
def world(db):  # noqa: F811
    domain = make_domain(db, "workflow")
    employee = make_entity_type(db, domain, "employee", "agent")
    attribute = db.execute(text(
        "INSERT INTO attribute_def (entity_type_id, name, data_type, sort_order) VALUES (:t, 'hours_per_week', 'integer', 1) RETURNING id"),
        {"t": employee}).scalar_one()
    ahmed = make_entity(db, employee, "ahmed")
    make_entity(db, employee, "sara", attrs={"hours_per_week": 20})
    problem = make_problem(db, domain)
    db.commit()
    yield {"domain": domain, "problem": problem, "attribute": attribute, "ahmed": ahmed}
    db.execute(text("DELETE FROM run WHERE scenario_id IN (SELECT id FROM scenario WHERE problem_id = :p)"), {"p": problem})
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
    db.commit()


def test_readiness_walks_the_steps_and_names_every_missing_value(world, db, auth_headers):  # noqa: F811
    client = TestClient(app)
    url = f"/api/v1/problems/{world['problem']}/readiness"
    body = client.get(url, headers=auth_headers).json()
    assert body["latest_version"] is None and body["check"] is None and body["base_scenario"] is None and body["last_run"] is None

    make_model_version(db, world["problem"], IR)
    db.commit()
    body = client.get(url, headers=auth_headers).json()
    assert body["latest_version"]["version"] == 1
    assert body["check"]["ready"] is False and body["check"]["sets"] == {"employee": 2}
    (finding,) = body["check"]["findings"]
    assert finding["code"] == "missing_values" and finding["kind"] == "blocker"
    assert finding["says"] == "1 employee record has no hours_per_week, which the model reads as a number."
    gap = finding["missing"]
    assert gap["attribute_id"] == world["attribute"] and gap["data_type"] == "integer"
    assert [(r["id"], r["key"]) for r in gap["records"]] == [(world["ahmed"], "ahmed")]
    assert gap["records"][0]["updated_at"]

    # A default fills the gap (the attribute route writes it into the records without a value).
    response = client.patch(f"/api/v1/attributes/{world['attribute']}", json={"default_value": 40}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert client.get(url, headers=auth_headers).json()["check"] == {
        "ready": True, "findings": [], "model_class": "IP", "sets": {"employee": 2}}


def test_one_solve_keeps_a_base_scenario_on_the_latest_version(world, db, auth_headers):  # noqa: F811
    client = TestClient(app)
    solve = f"/api/v1/problems/{world['problem']}/solve"
    assert client.post(solve, headers=auth_headers).status_code == 422  # nothing published yet

    make_model_version(db, world["problem"], IR)
    db.commit()
    first = client.post(solve, headers=auth_headers)
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "queued"
    base = db.execute(text("SELECT id, model_version_id FROM scenario WHERE problem_id = :p"), {"p": world["problem"]}).all()
    assert len(base) == 1

    # A newer version: the same Base scenario moves to it; no second scenario.
    v2 = make_model_version(db, world["problem"], IR)
    db.commit()
    second = client.post(solve, headers=auth_headers)
    assert second.status_code == 201, second.text
    rows = db.execute(text("SELECT id, model_version_id, name FROM scenario WHERE problem_id = :p"), {"p": world["problem"]}).all()
    assert [(r.id, r.model_version_id, r.name) for r in rows] == [(base[0].id, v2, "Base")]
    body = client.get(f"/api/v1/problems/{world['problem']}/readiness", headers=auth_headers).json()
    assert body["base_scenario"] == {"id": base[0].id, "version": 2}
    assert body["last_run"]["id"] == second.json()["id"] and body["last_run"]["scenario"] == "Base"

    # A question asked of the plan (why-not) is a run too, but not the problem's latest result (UX audit C-2).
    db.execute(text("INSERT INTO run (scenario_id, dataset_id, status, purpose, parent_run_id, params, seed)"
                    " SELECT scenario_id, dataset_id, 'optimal', 'why_not', id, '{}', seed FROM run WHERE id = :r"),
               {"r": second.json()["id"]})
    db.commit()
    body = client.get(f"/api/v1/problems/{world['problem']}/readiness", headers=auth_headers).json()
    assert body["last_run"]["id"] == second.json()["id"]


def test_the_scenario_preflight_names_missing_values_in_place_of_the_compiler_refusal(world, db, auth_headers):  # noqa: F811
    version = make_model_version(db, world["problem"], IR)
    sid = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                     {"p": world["problem"], "v": version}).scalar_one()
    db.commit()
    body = TestClient(app).get(f"/api/v1/scenarios/{sid}/preflight", headers=auth_headers).json()
    assert [f["code"] for f in body["findings"]] == ["missing_values"]


def test_a_hard_rule_that_sums_over_nobody_and_so_cannot_hold_stops_the_solve(world, db, auth_headers):  # noqa: F811
    """feed_blend on a user's screen: c_protein was pointed at a set with no
    records, so its sum counted as 0 and "0 >= 20" could never hold. The check
    said "Ready to solve" with a warning, and every run came back infeasible."""
    make_entity_type(db, world["domain"], "em", "resource")
    ir = {**IR, "sets": ["employee", "em"], "constraints": [*IR["constraints"], {
        "id": "c_protein",
        "left": {"sum": {"mul": [{"const": 2}, {"var": "pick", "index": ["e"]}]}, "over": [{"index": "x", "set": "em"}, {"index": "e", "set": "employee"}]},
        "relation": ">=", "right": {"const": 20}, "severity": "hard"}]}
    make_model_version(db, world["problem"], ir)
    db.execute(text("UPDATE entity SET attrs = attrs || '{\"hours_per_week\": 30}' WHERE id = :id"), {"id": world["ahmed"]})
    db.commit()
    check = TestClient(app).get(f"/api/v1/problems/{world['problem']}/readiness", headers=auth_headers).json()["check"]
    assert check["ready"] is False
    blockers = [f for f in check["findings"] if f["kind"] == "blocker"]
    assert [f["code"] for f in blockers] == ["rule_never_holds"]
    assert blockers[0]["rule"] == "c_protein"
    assert "c_protein can never hold: on today's data it reads 0 >= 20" in blockers[0]["says"]
    # The warnings that were all it said before are still there.
    assert {"set_empty", "empty_range"} <= {f["code"] for f in check["findings"]}


def test_a_soft_rule_that_cannot_hold_is_only_paid_for_not_a_blocker(world, db, auth_headers):  # noqa: F811
    make_entity_type(db, world["domain"], "em", "resource")
    ir = {**IR, "sets": ["employee", "em"], "constraints": [*IR["constraints"], {
        "id": "c_soft", "left": {"sum": {"var": "pick", "index": ["e"]}, "over": [{"index": "x", "set": "em"}, {"index": "e", "set": "employee"}]},
        "relation": ">=", "right": {"const": 20}, "severity": "soft", "penalty": 5}]}
    make_model_version(db, world["problem"], ir)
    db.execute(text("UPDATE entity SET attrs = attrs || '{\"hours_per_week\": 30}' WHERE id = :id"), {"id": world["ahmed"]})
    db.commit()
    check = TestClient(app).get(f"/api/v1/problems/{world['problem']}/readiness", headers=auth_headers).json()["check"]
    assert "rule_never_holds" not in {f["code"] for f in check["findings"]}
