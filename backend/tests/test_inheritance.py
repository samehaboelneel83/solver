"""Entity-type inheritance (queue R18): abstract types, inherited attributes, and sets over a whole family."""

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
def fleet(tenants, db):  # noqa: F811
    """vehicle (abstract: capacity, default 10) <- truck (+ refrigerated) <- reefer; vehicle <- van."""
    client, headers, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def call(method, path, body=None, ok=(200, 201)):
        response = client.request(method, path, json=body, headers=headers)
        if ok:
            assert response.status_code in ok, response.text
        return response

    def post(path, body):
        return call("POST", path, body).json()

    vehicle = post("/api/v1/entity-types", {"domain_id": domain, "name": "vehicle", "role": "resource", "is_abstract": True})
    post(f"/api/v1/entity-types/{vehicle['id']}/attributes", {"name": "capacity", "data_type": "integer", "default_value": 10})
    truck = post("/api/v1/entity-types", {"domain_id": domain, "name": "truck", "role": "resource", "inherited_from": vehicle["id"]})
    post(f"/api/v1/entity-types/{truck['id']}/attributes", {"name": "refrigerated", "data_type": "boolean", "default_value": False})
    reefer = post("/api/v1/entity-types", {"domain_id": domain, "name": "reefer", "role": "resource", "inherited_from": truck["id"]})
    van = post("/api/v1/entity-types", {"domain_id": domain, "name": "van", "role": "resource", "inherited_from": vehicle["id"]})
    return {"client": client, "call": call, "post": post, "domain": domain,
            "vehicle": vehicle, "truck": truck, "reefer": reefer, "van": van}


def test_a_type_reads_back_its_lineage_and_inherited_attributes(fleet):
    reefer = fleet["call"]("GET", f"/api/v1/entity-types/{fleet['reefer']['id']}").json()
    assert reefer["inherited_from"] == fleet["truck"]["id"] and reefer["is_abstract"] is False
    assert [a["name"] for a in reefer["inherited_attributes"]] == ["refrigerated", "capacity"]  # nearest first
    assert reefer["attributes"] == []
    vehicle = fleet["call"]("GET", f"/api/v1/entity-types/{fleet['vehicle']['id']}").json()
    assert vehicle["is_abstract"] is True and vehicle["inherited_attributes"] == []


def test_an_entity_takes_its_ancestors_attributes_and_defaults(fleet, db):  # noqa: F811
    cold = fleet["post"]("/api/v1/entities", {"entity_type_id": fleet["reefer"]["id"], "key": "r1", "attrs": {"refrigerated": True}})
    assert cold["attrs"] == {"refrigerated": True, "capacity": 10}
    bad = fleet["call"]("POST", "/api/v1/entities", {"entity_type_id": fleet["van"]["id"], "key": "v1", "attrs": {"refrigerated": True}}, ok=None)
    assert bad.status_code == 422  # a van is not a truck


def test_an_abstract_type_holds_no_entities_of_its_own(fleet):
    refused = fleet["call"]("POST", "/api/v1/entities", {"entity_type_id": fleet["vehicle"]["id"], "key": "x"}, ok=None)
    assert refused.status_code == 422 and "abstract" in refused.text
    fleet["post"]("/api/v1/entities", {"entity_type_id": fleet["van"]["id"], "key": "v1"})
    made_abstract = fleet["call"]("PATCH", f"/api/v1/entity-types/{fleet['van']['id']}", {"is_abstract": True}, ok=None)
    assert made_abstract.status_code == 422 and "cannot be abstract" in made_abstract.text


def test_no_cycles_and_one_meaning_per_attribute_name(fleet):
    cycle = fleet["call"]("PATCH", f"/api/v1/entity-types/{fleet['vehicle']['id']}", {"inherited_from": fleet["reefer"]["id"]}, ok=None)
    assert cycle.status_code == 422 and "descendants" in cycle.text
    clash = fleet["call"]("POST", f"/api/v1/entity-types/{fleet['van']['id']}/attributes", {"name": "capacity", "data_type": "integer"}, ok=None)
    assert clash.status_code == 422 and "inheritance" in clash.text
    # A type leaves its lineage with an explicit null.
    left = fleet["call"]("PATCH", f"/api/v1/entity-types/{fleet['van']['id']}", {"inherited_from": None}).json()
    assert left["inherited_from"] is None and left["inherited_attributes"] == []


def test_a_relationship_and_a_parameter_over_an_ancestor_take_its_descendants(fleet):
    post = fleet["post"]
    depot = post("/api/v1/entity-types", {"domain_id": fleet["domain"], "name": "depot", "role": "location"})
    d1 = post("/api/v1/entities", {"entity_type_id": depot["id"], "key": "d1"})
    r1 = post("/api/v1/entities", {"entity_type_id": fleet["reefer"]["id"], "key": "r1"})
    based = post("/api/v1/relationship-types", {"domain_id": fleet["domain"], "name": "based_at",
                                                "from_type_id": fleet["vehicle"]["id"], "to_type_id": depot["id"]})
    post("/api/v1/relationships", {"relationship_type_id": based["id"], "from_entity_id": r1["id"], "to_entity_id": d1["id"]})
    cost = post("/api/v1/parameters", {"domain_id": fleet["domain"], "name": "day_cost",
                                        "index_type_ids": [fleet["vehicle"]["id"]], "default_value": 0})
    put = fleet["call"]("PUT", f"/api/v1/parameters/{cost['id']}/values", {"cells": [{"entity_ids": [r1["id"]], "value": 120}]})
    assert put.status_code == 200


def test_a_set_over_an_abstract_type_ranges_over_its_whole_family(fleet, db, empty_queue):  # noqa: F811
    post = fleet["post"]
    post("/api/v1/entities", {"entity_type_id": fleet["truck"]["id"], "key": "t1", "attrs": {"capacity": 30}})
    post("/api/v1/entities", {"entity_type_id": fleet["reefer"]["id"], "key": "r1", "attrs": {"capacity": 20}})
    post("/api/v1/entities", {"entity_type_id": fleet["van"]["id"], "key": "v1"})  # capacity 10 by default
    use = {"var": "use", "index": ["v"]}
    each = [{"index": "v", "set": "vehicle"}]
    ir = {"version": 2, "sets": ["vehicle"], "parameters": {},
          "variables": {"use": {"index": ["vehicle"], "domain": "binary"}},
          "constraints": [{"id": "c_carry", "left": {"sum": {"mul": [{"attr": {"of": "v", "name": "capacity"}}, use]}, "over": each},
                           "relation": ">=", "right": {"const": 25}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": [{"id": "o_used", "weight": 1, "expression": {"sum": use, "over": each}}]}}
    problem = post("/api/problem/", {"domain_id": fleet["domain"], "name": "fleet"})
    version = post(f"/api/v1/problems/{problem['id']}/versions", {"ir": ir})
    scenario = post("/api/v1/scenarios", {"problem_id": problem["id"], "model_version_id": version["id"], "name": "base"})
    run_id = post(f"/api/v1/scenarios/{scenario['id']}/runs", {"reuse": False, "time_limit_s": 10})["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    run = fleet["call"]("GET", f"/api/v1/runs/{run_id}").json()
    # Every vehicle is in the set, whatever its own type: one truck of 30 carries 25.
    assert set(run["set_order"]["vehicle"]) == {"t1", "r1", "v1"}
    assert run["status"] == "optimal" and run["objective"] == 1 and run["assignments"]["use"] == [["t1"]]
