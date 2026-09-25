"""What a run's views are drawn from (queue R17): amounts, decision kinds, set roles, set order."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_a_run_carries_its_amounts_and_the_shape_of_its_sets(tenants, db, empty_queue):  # noqa: F811
    client, headers, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body):
        response = client.post(path, json=body, headers=headers)
        assert response.status_code in (200, 201), response.text
        return response.json()

    day = post("/api/v1/entity-types", {"domain_id": domain, "name": "day", "role": "time"})
    plant = post("/api/v1/entity-types", {"domain_id": domain, "name": "plant", "role": "location"})
    # Days entered out of alphabetical order: the answer keeps the dataset's order.
    for key in ("mon", "tue", "wed"):
        post("/api/v1/entities", {"entity_type_id": day["id"], "key": key})
    for key in ("north", "south"):
        post("/api/v1/entities", {"entity_type_id": plant["id"], "key": key})
    make = {"var": "make", "index": ["p", "d"]}
    both = [{"index": "p", "set": "plant"}, {"index": "d", "set": "day"}]
    ir = {"version": 2, "sets": ["plant", "day"], "parameters": {},
          "variables": {"make": {"index": ["plant", "day"], "domain": "integer", "lower": 0, "upper": 50},
                        "run": {"index": ["plant"], "domain": "binary"}},
          "constraints": [
              {"id": "c_need", "forall": [{"index": "d", "set": "day"}], "left": {"sum": make, "over": [{"index": "p", "set": "plant"}]},
               "relation": ">=", "right": {"const": 30}, "severity": "hard"},
              {"id": "c_only_running", "forall": both, "left": make, "relation": "<=",
               "right": {"mul": [{"const": 50}, {"var": "run", "index": ["p"]}]}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": [
              {"id": "o_make", "weight": 1, "expression": {"sum": make, "over": both}},
              {"id": "o_run", "weight": 100, "expression": {"sum": {"var": "run", "index": ["p"]}, "over": [{"index": "p", "set": "plant"}]}}]}}
    problem = post("/api/problem/", {"domain_id": domain, "name": "shapes"})
    version = post(f"/api/v1/problems/{problem['id']}/versions", {"ir": ir})
    scenario = post("/api/v1/scenarios", {"problem_id": problem["id"], "model_version_id": version["id"], "name": "base"})
    run_id = post(f"/api/v1/scenarios/{scenario['id']}/runs", {"reuse": False, "time_limit_s": 10})["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    run = client.get(f"/api/v1/runs/{run_id}", headers=headers).json()
    assert run["status"] == "optimal"
    assert run["variable_kinds"] == {"make": "integer", "run": "binary"}
    assert run["set_roles"] == {"day": "time", "plant": "location"}
    assert run["set_order"]["day"] == ["mon", "tue", "wed"]
    # 30 a day from one running plant: amounts carry how much, not only where.
    made = {tuple(a["index"]): a["value"] for a in run["amounts"]["make"]}
    assert sum(made.values()) == 90 and set(v for v in made.values()) == {30}
    assert "run" not in run["amounts"]  # a yes-or-no answer is in `assignments`
    # And a reused answer carries them too.
    again = post(f"/api/v1/scenarios/{scenario['id']}/runs", {"time_limit_s": 10})
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": again["id"]}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    reused = client.get(f"/api/v1/runs/{again['id']}", headers=headers).json()
    assert reused["amounts"] == run["amounts"]


def test_an_interval_run_names_the_start_and_end_its_gantt_draws(tenants, db, empty_queue):  # noqa: F811
    """Queue R17b: an interval decision reports its start, end (and presence) decisions."""
    from tests.test_scheduling import NO_OVERLAP, _ir

    client, headers, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body):
        response = client.post(path, json=body, headers=headers)
        assert response.status_code in (200, 201), response.text
        return response.json()

    job = post("/api/v1/entity-types", {"domain_id": domain, "name": "job", "role": "task"})
    ids = [post("/api/v1/entities", {"entity_type_id": job["id"], "key": key})["id"] for key in ("j1", "j2")]
    duration = post("/api/v1/parameters", {"domain_id": domain, "name": "duration", "index_type_ids": [job["id"]]})
    client.put(f"/api/v1/parameters/{duration['id']}/values", headers=headers,
               json={"cells": [{"entity_ids": [ids[0]], "value": 3}, {"entity_ids": [ids[1]], "value": 4}]})
    problem = post("/api/problem/", {"domain_id": domain, "name": "gantt"})
    version = post(f"/api/v1/problems/{problem['id']}/versions", {"ir": _ir(NO_OVERLAP, horizon=20)})
    scenario = post("/api/v1/scenarios", {"problem_id": problem["id"], "model_version_id": version["id"], "name": "base"})
    run_id = post(f"/api/v1/scenarios/{scenario['id']}/runs", {"reuse": False, "time_limit_s": 10})["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    run = client.get(f"/api/v1/runs/{run_id}", headers=headers).json()
    assert run["status"] == "optimal" and run["objective"] == 7
    assert run["intervals"] == {"task": {"start": "begin", "end": "finish"}}
    ends = {tuple(a["index"]): a["value"] for a in run["amounts"]["finish"]}
    assert sorted(ends.values()) in ([3, 7], [4, 7])


def test_a_run_says_where_each_located_member_stood(tenants, db, empty_queue):  # noqa: F811
    """Queue R17b's answer maps: a point per member of each located set, a shape at its centroid."""
    client, headers, domain = TestClient(app), tenants["a"], tenants["domain_a"]

    def post(path, body):
        response = client.post(path, json=body, headers=headers)
        assert response.status_code in (200, 201), response.text
        return response.json()

    site = post("/api/v1/entity-types", {"domain_id": domain, "name": "site", "role": "location"})
    post(f"/api/v1/entity-types/{site['id']}/attributes", {"name": "place", "data_type": "geometry"})
    post("/api/v1/entities", {"entity_type_id": site["id"], "key": "a", "attrs": {"place": {"type": "Point", "coordinates": [31.2, 30.0]}}})
    square = {"type": "Polygon", "coordinates": [[[31, 29], [32, 29], [32, 30], [31, 30], [31, 29]]]}
    post("/api/v1/entities", {"entity_type_id": site["id"], "key": "b", "attrs": {"place": square}})
    post("/api/v1/entities", {"entity_type_id": site["id"], "key": "c"})  # nowhere: not placed
    ir = {"version": 2, "sets": ["site"], "parameters": {},
          "variables": {"open": {"index": ["site"], "domain": "binary"}}, "constraints": [],
          "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
              "sum": {"var": "open", "index": ["s"]}, "over": [{"index": "s", "set": "site"}]}}]}}
    problem = post("/api/problem/", {"domain_id": domain, "name": "where"})
    version = post(f"/api/v1/problems/{problem['id']}/versions", {"ir": ir})
    scenario = post("/api/v1/scenarios", {"problem_id": problem["id"], "model_version_id": version["id"], "name": "base"})
    run_id = post(f"/api/v1/scenarios/{scenario['id']}/runs", {"reuse": False, "time_limit_s": 10})["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    places = client.get(f"/api/v1/runs/{run_id}/places", headers=headers).json()
    assert places == {"site": {"a": [31.2, 30.0], "b": [31.5, 29.5]}}
