"""Entity-valued parameters (queue R20b): `preferred_shift[employee, day] = shift`, set as a
dropdown per cell, used in a model as an index or in a filter, resolved from frozen data."""

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
def rota(tenants, db):  # noqa: F811
    """Two people, two days, two shifts; ana prefers late on mon, ben early on tue."""
    client, headers, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def call(method, path, body=None, ok=(200, 201, 204)):
        response = client.request(method, path, json=body, headers=headers)
        if ok:
            assert response.status_code in ok, response.text
        return response

    def post(path, body):
        return call("POST", path, body).json()

    types = {name: post("/api/v1/entity-types", {"domain_id": domain, "name": name, "role": role})
             for name, role in (("employee", "agent"), ("day", "time"), ("shift", "time"))}
    ids = {}
    for type_name, keys in (("employee", ["ana", "ben"]), ("day", ["mon", "tue"]), ("shift", ["early", "late"])):
        for k, key in enumerate(keys):
            ids[key] = post("/api/v1/entities", {"entity_type_id": types[type_name]["id"], "key": key, "sort_order": k})["id"]
    pref = post("/api/v1/parameters", {"domain_id": domain, "name": "preferred_shift",
                                       "index_type_ids": [types["employee"]["id"], types["day"]["id"]],
                                       "value_type_id": types["shift"]["id"]})
    call("PUT", f"/api/v1/parameters/{pref['id']}/values", {"cells": [
        {"entity_ids": [ids["ana"], ids["mon"]], "value_entity_id": ids["late"]},
        {"entity_ids": [ids["ben"], ids["tue"]], "value_entity_id": ids["early"]},
    ]})
    return {"call": call, "post": post, "domain": domain, "types": types, "ids": ids, "pref": pref}


def _solve(rota, db, ir, name="preferences"):  # noqa: F811
    post, call = rota["post"], rota["call"]
    problem = post("/api/problem/", {"domain_id": rota["domain"], "name": name})
    version = post(f"/api/v1/problems/{problem['id']}/versions", {"ir": ir})
    scenario = post("/api/v1/scenarios", {"problem_id": problem["id"], "model_version_id": version["id"], "name": "base"})
    run_id = post(f"/api/v1/scenarios/{scenario['id']}/runs", {"reuse": False, "time_limit_s": 10})["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    return call("GET", f"/api/v1/runs/{run_id}").json()


def _model(**parts):
    return {"version": 2, "sets": ["employee", "day", "shift"],
            "parameters": {"preferred_shift": {"index": ["employee", "day"], "entity": "shift"}},
            "variables": {"assign": {"index": ["employee", "day", "shift"], "domain": "binary"}},
            "constraints": [], **parts}


ED = [{"index": "e", "set": "employee"}, {"index": "d", "set": "day"}]
CELL = {"par": "preferred_shift", "index": ["e", "d"]}


def test_the_grid_holds_entities_and_says_their_keys(rota):
    grid = rota["call"]("GET", f"/api/v1/parameters/{rota['pref']['id']}/values").json()
    assert [(c["value_key"], c["value"]) for c in grid["cells"]] == [("late", None), ("early", None)]
    assert rota["pref"]["value_type_id"] == rota["types"]["shift"]["id"]
    wrong = rota["call"]("PUT", f"/api/v1/parameters/{rota['pref']['id']}/values",
                         {"cells": [{"entity_ids": [rota["ids"]["ana"], rota["ids"]["tue"]], "value": 3}]}, ok=None)
    assert wrong.status_code == 422 and "value_entity_id" in wrong.text
    not_a_shift = rota["call"]("PUT", f"/api/v1/parameters/{rota['pref']['id']}/values",
                               {"cells": [{"entity_ids": [rota["ids"]["ana"], rota["ids"]["tue"]],
                                           "value_entity_id": rota["ids"]["mon"]}]}, ok=None)
    assert not_a_shift.status_code == 422
    # Null clears a cell: an entity has no default.
    rota["call"]("PUT", f"/api/v1/parameters/{rota['pref']['id']}/values",
                 {"cells": [{"entity_ids": [rota["ids"]["ben"], rota["ids"]["tue"]], "value_entity_id": None}]})
    assert len(rota["call"]("GET", f"/api/v1/parameters/{rota['pref']['id']}/values").json()["cells"]) == 1


def test_deleting_the_entity_a_cell_holds_deletes_the_cell(rota):
    rota["call"]("DELETE", f"/api/v1/entities/{rota['ids']['late']}")
    cells = rota["call"]("GET", f"/api/v1/parameters/{rota['pref']['id']}/values").json()["cells"]
    assert [c["value_key"] for c in cells] == ["early"]


def test_a_filter_keeps_the_preferred_shift_and_an_empty_cell_keeps_none(rota, db, empty_queue):  # noqa: F811
    liked = {"sum": {"var": "assign", "index": ["e", "d", "s"]},
             "over": [*ED, {"index": "s", "set": "shift", "where": [{"attr": "id", "op": "=", "value": CELL}]}]}
    run = _solve(rota, db, _model(objective={"sense": "maximize", "terms": [{"id": "o_liked", "weight": 1, "expression": liked}]}))
    # Only the two preferred cells exist to be chosen.
    assert run["status"] == "optimal" and run["objective"] == 2
    assert sorted(map(tuple, run["assignments"]["assign"])) == [("ana", "mon", "late"), ("ben", "tue", "early")]


def test_as_an_index_it_reads_the_cell_and_an_empty_cell_is_refused_by_name(rota, db, empty_queue):  # noqa: F811
    one_cell = [{"index": "e", "set": "employee", "where": [{"attr": "id", "op": "=", "value": "ana"}]},
                {"index": "d", "set": "day", "where": [{"attr": "id", "op": "=", "value": "mon"}]}]
    rule = {"id": "c_pref", "forall": one_cell, "left": {"var": "assign", "index": ["e", "d", CELL]},
            "relation": "=", "right": {"const": 1}, "severity": "hard"}
    total = {"sense": "minimize", "terms": [{"id": "o_n", "weight": 1, "expression": {
        "sum": {"var": "assign", "index": ["e", "d", "s"]}, "over": [*ED, {"index": "s", "set": "shift"}]}}]}
    run = _solve(rota, db, _model(constraints=[rule], objective=total))
    assert run["status"] == "optimal" and run["assignments"]["assign"] == [["ana", "mon", "late"]]
    everyone = {**rule, "forall": ED}
    refused = _solve(rota, db, _model(constraints=[everyone], objective=total), name="everyone")
    assert refused["status"] == "error" and "preferred_shift[ana, tue] has no value" in (refused["error"] or "")


def test_the_model_must_say_what_the_parameter_holds(rota):
    ir = _model(objective={"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
        "sum": {"var": "assign", "index": ["e", "d", "s"]}, "over": [*ED, {"index": "s", "set": "shift"}]}}]})
    ir["parameters"]["preferred_shift"].pop("entity")
    problem = rota["post"]("/api/problem/", {"domain_id": rota["domain"], "name": "p"})
    refused = rota["call"]("POST", f"/api/v1/problems/{problem['id']}/versions", {"ir": ir}, ok=None)
    detail = refused.json()["detail"][0]
    assert refused.status_code == 422 and detail["loc"][-1] == "entity" and "entities of shift" in detail["msg"]
