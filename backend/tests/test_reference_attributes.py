"""Reference attributes (queue R20a): an entity as an attribute's value, mirrored as a
many-to-one relationship so `via` and the relationship checks apply (migration 0067)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture
def org(tenants, db):  # noqa: F811
    """unit (rate) <- employee.home_unit (optional); employee.mentor_unit (required) added per test."""
    client, headers, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def call(method, path, body=None, ok=(200, 201, 204)):
        response = client.request(method, path, json=body, headers=headers)
        if ok:
            assert response.status_code in ok, response.text
        return response

    def post(path, body):
        return call("POST", path, body).json()

    unit = post("/api/v1/entity-types", {"domain_id": domain, "name": "unit", "role": "org"})
    post(f"/api/v1/entity-types/{unit['id']}/attributes", {"name": "rate", "data_type": "number", "default_value": 1})
    employee = post("/api/v1/entity-types", {"domain_id": domain, "name": "employee", "role": "agent"})
    home = post(f"/api/v1/entity-types/{employee['id']}/attributes",
                {"name": "home_unit", "data_type": "reference", "target_type_id": unit["id"]})
    u1 = post("/api/v1/entities", {"entity_type_id": unit["id"], "key": "u1", "attrs": {"rate": 3}})
    u2 = post("/api/v1/entities", {"entity_type_id": unit["id"], "key": "u2", "attrs": {"rate": 5}})
    return {"client": client, "call": call, "post": post, "domain": domain, "unit": unit, "employee": employee,
            "home": home, "u1": u1, "u2": u2}


def _edges(db, rel_id):  # noqa: F811
    return sorted(db.execute(text(
        "SELECT a.key, b.key FROM relationship r JOIN entity a ON a.id = r.from_entity_id "
        "JOIN entity b ON b.id = r.to_entity_id WHERE r.relationship_type_id = :t"), {"t": rel_id}).all())


def test_declaring_a_reference_makes_its_many_to_one_relationship(org):
    home = org["home"]
    assert home["data_type"] == "reference" and home["target_type_id"] == org["unit"]["id"]
    rel = org["call"]("GET", f"/api/v1/relationship-types/{home['references_id']}").json()
    assert (rel["name"], rel["from_type_id"], rel["to_type_id"], rel["cardinality"]) == (
        "home_unit", org["employee"]["id"], org["unit"]["id"], "many_to_one")


def test_the_value_is_a_key_and_the_edge_follows_it(org, db):  # noqa: F811
    post, call = org["post"], org["call"]
    e1 = post("/api/v1/entities", {"entity_type_id": org["employee"]["id"], "key": "e1", "attrs": {"home_unit": "u1"}})
    assert e1["attrs"] == {"home_unit": "u1"}
    assert _edges(db, org["home"]["references_id"]) == [("e1", "u1")]
    call("PATCH", f"/api/v1/entities/{e1['id']}", {"attrs": {"home_unit": "u2"}})
    assert _edges(db, org["home"]["references_id"]) == [("e1", "u2")]
    # A renamed target is followed into whoever refers to it.
    call("PATCH", f"/api/v1/entities/{org['u2']['id']}", {"key": "u9"})
    assert call("GET", f"/api/v1/entities/{e1['id']}").json()["attrs"] == {"home_unit": "u9"}
    call("PATCH", f"/api/v1/entities/{e1['id']}", {"attrs": {}})
    assert _edges(db, org["home"]["references_id"]) == []


def test_a_key_naming_no_entity_of_the_type_is_refused(org):
    bad = org["call"]("POST", "/api/v1/entities", {"entity_type_id": org["employee"]["id"], "key": "e1",
                                                   "attrs": {"home_unit": "nowhere"}}, ok=None)
    assert bad.status_code == 422 and "reference_unknown" in bad.text


def test_the_mirror_relationship_is_not_written_directly(org):
    e1 = org["post"]("/api/v1/entities", {"entity_type_id": org["employee"]["id"], "key": "e1"})
    direct = org["call"]("POST", "/api/v1/relationships", {"relationship_type_id": org["home"]["references_id"],
                                                           "from_entity_id": e1["id"], "to_entity_id": org["u1"]["id"]},
                         ok=None)
    assert direct.status_code == 422 and "set it on the entity" in direct.text


def test_deleting_a_target_clears_an_optional_reference_and_refuses_a_required_one(org):
    post, call = org["post"], org["call"]
    e1 = post("/api/v1/entities", {"entity_type_id": org["employee"]["id"], "key": "e1", "attrs": {"home_unit": "u1"}})
    call("DELETE", f"/api/v1/entities/{org['u1']['id']}")
    assert call("GET", f"/api/v1/entities/{e1['id']}").json()["attrs"] == {}
    post(f"/api/v1/entity-types/{org['employee']['id']}/attributes",
         {"name": "cost_unit", "data_type": "reference", "target_type_id": org["unit"]["id"], "required": True})
    post("/api/v1/entities", {"entity_type_id": org["employee"]["id"], "key": "e2", "attrs": {"cost_unit": "u2"}})
    refused = call("DELETE", f"/api/v1/entities/{org['u2']['id']}", ok=None)
    assert refused.status_code == 422 and "required" in refused.text


def test_deleting_the_attribute_takes_its_values_and_its_relationship(org, db):  # noqa: F811
    post, call = org["post"], org["call"]
    e1 = post("/api/v1/entities", {"entity_type_id": org["employee"]["id"], "key": "e1", "attrs": {"home_unit": "u1"}})
    call("DELETE", f"/api/v1/attributes/{org['home']['id']}")
    assert call("GET", f"/api/v1/entities/{e1['id']}").json()["attrs"] == {}
    assert call("GET", f"/api/v1/relationship-types/{org['home']['references_id']}", ok=None).status_code == 404


def test_a_reference_has_no_default_and_an_edge_attribute_is_never_one(org):
    call = org["call"]
    no_default = call("POST", f"/api/v1/entity-types/{org['employee']['id']}/attributes",
                      {"name": "x_unit", "data_type": "reference", "target_type_id": org["unit"]["id"],
                       "default_value": "u1"}, ok=None)
    assert no_default.status_code == 422
    no_target = call("POST", f"/api/v1/entity-types/{org['employee']['id']}/attributes",
                     {"name": "y_unit", "data_type": "reference"}, ok=None)
    assert no_target.status_code == 422 and "target_type_id" in no_target.text
    on_edge = call("POST", f"/api/v1/relationship-types/{org['home']['references_id']}/attributes",
                   {"name": "z", "data_type": "reference", "target_type_id": org["unit"]["id"]}, ok=None)
    assert on_edge.status_code == 422


def test_filters_offer_a_reference_by_key(org):
    post, call = org["post"], org["call"]
    post("/api/v1/entities", {"entity_type_id": org["employee"]["id"], "key": "e1", "attrs": {"home_unit": "u1"}})
    post("/api/v1/entities", {"entity_type_id": org["employee"]["id"], "key": "e2", "attrs": {"home_unit": "u2"}})
    import json
    expr = json.dumps({"version": 1, "query": {"combinator": "and", "rules": [
        {"field": f"attr:{org['employee']['id']}:home_unit", "operator": "=", "value": "u2"}]}})
    listed = call("GET", f"/api/v1/entities?entity_type_id={org['employee']['id']}&expr={expr}").json()
    assert [e["key"] for e in listed["items"]] == ["e2"]


def test_a_rule_walks_the_reference_to_the_unit_it_names(org, db, empty_queue):  # noqa: F811
    post, call = org["post"], org["call"]
    post("/api/v1/entities", {"entity_type_id": org["employee"]["id"], "key": "e1", "attrs": {"home_unit": "u1"}})
    post("/api/v1/entities", {"entity_type_id": org["employee"]["id"], "key": "e2", "attrs": {"home_unit": "u2"}})
    pick = {"var": "pick", "index": ["e"]}
    # Each employee costs its home unit's rate; pick one, cheapest.
    ir = {"version": 2, "sets": ["employee", "unit"], "parameters": {}, "relationships": ["home_unit"],
          "variables": {"pick": {"index": ["employee"], "domain": "binary"}},
          "constraints": [{"id": "c_one", "left": {"sum": pick, "over": [{"index": "e", "set": "employee"}]},
                           "relation": "=", "right": {"const": 1}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": [{"id": "o_rate", "weight": 1, "expression": {
              "sum": {"mul": [{"attr": {"of": "u", "name": "rate"}}, pick]},
              "over": [{"index": "e", "set": "employee"},
                       {"index": "u", "set": "unit", "via": {"rel": "home_unit", "from": "e"}}]}}]}}
    problem = post("/api/problem/", {"domain_id": org["domain"], "name": "cheapest"})
    version = post(f"/api/v1/problems/{problem['id']}/versions", {"ir": ir})
    scenario = post("/api/v1/scenarios", {"problem_id": problem["id"], "model_version_id": version["id"], "name": "base"})
    run_id = post(f"/api/v1/scenarios/{scenario['id']}/runs", {"reuse": False, "time_limit_s": 10})["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    run = call("GET", f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "optimal" and run["objective"] == 3 and run["assignments"]["pick"] == [["e1"]]


def test_the_mirror_relationship_type_follows_its_attribute(org):
    call, rel_id = org["call"], org["home"]["references_id"]
    renamed = call("PATCH", f"/api/v1/relationship-types/{rel_id}", {"name": "base_unit"}, ok=None)
    deleted = call("DELETE", f"/api/v1/relationship-types/{rel_id}", ok=None)
    assert renamed.status_code == deleted.status_code == 409 and "through that attribute" in deleted.text
    call("PATCH", f"/api/v1/relationship-types/{rel_id}", {"colour": "#123456"})  # its colour is its own
    # Renaming the attribute renames its relationship.
    call("PATCH", f"/api/v1/attributes/{org['home']['id']}", {"name": "base_unit"})
    assert call("GET", f"/api/v1/relationship-types/{rel_id}").json()["name"] == "base_unit"
