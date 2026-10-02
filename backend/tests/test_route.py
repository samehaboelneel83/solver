"""The `route` rule (queue R15b): exact rows checked against every set of routes, and the routing start."""

from __future__ import annotations

import itertools
import math

import pytest

from app.ir.validate import check_shape
from app.solve import compile_model, routing
from app.solve.backends import by_name
from app.solve.compile import Unsupported
from app.solve.evolve import holds
from bench.routing import vrp
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _brute(ir, data) -> float:
    """The least distance over every way to split the stops among the vehicles and order each share."""
    vehicles = [row["id"] for row in data["sets"]["vehicle"]]
    rows = {row["id"]: row for row in data["sets"]["stop"]}
    route = ir["constraints"][0]["route"]
    depot = route["depot"]
    stops = [s for s in rows if s != depot]
    dist = {(r["0"], r["1"]): r["value"] for r in data["parameters"]["distance"]}
    load = "demand" in route
    cap = {row["id"]: row["capacity"] for row in data["sets"]["vehicle"]}
    best = math.inf
    for owner in itertools.product(range(len(vehicles)), repeat=len(stops)):
        total = 0
        for k, v in enumerate(vehicles):
            mine = [s for s, o in zip(stops, owner) if o == k]
            if load and sum(rows[s]["demand"] for s in mine) > cap[v]:
                break
            if not mine:
                continue
            total += min(sum(dist[(a, b)] for a, b in zip((depot, *order), (*order, depot)))
                         for order in itertools.permutations(mine))
        else:
            best = min(best, total)
    return best


def _small(load: bool, seed: int):
    ir, data = vrp("S", seed, load=load)
    # Five stops: every split and order can be counted.
    keep = {"depot", "s1", "s2", "s3", "s4", "s5"}
    data["sets"]["stop"] = [r for r in data["sets"]["stop"] if r["id"] in keep]
    data["parameters"]["distance"] = [r for r in data["parameters"]["distance"] if r["0"] in keep and r["1"] in keep]
    for row in data["sets"]["vehicle"]:
        row["capacity"] = max(9, sum(r["demand"] for r in data["sets"]["stop"]) // 2 + 3)
    return ir, data


@pytest.mark.parametrize("load", [True, False])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_the_rows_hold_exactly_the_routes(load, seed):
    ir, data = _small(load, seed)
    assert check_shape(ir) is None
    result = by_name("cp-sat").solve(compile_model(ir, data), time_limit=30, workers=8, seed=1)
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(_brute(ir, data))


def test_a_loop_away_from_the_depot_is_not_a_route():
    """Without the load flow, two stops visiting each other would satisfy in-once and out-once."""
    ir, data = _small(False, 0)
    compiled = compile_model(ir, data)
    v = data["sets"]["vehicle"][0]["id"]
    loop = {k: 0 for k in compiled.variables}
    # Vehicle 0 does depot -> s1 -> s2 -> depot; vehicle 1 circles s3 -> s4 -> s5 -> s3 and never leaves the depot.
    w = data["sets"]["vehicle"][1]["id"]
    for a, b in (("depot", "s1"), ("s1", "s2"), ("s2", "depot")):
        loop[("visit", (v, a, b))] = 1
    for a, b in (("s3", "s4"), ("s4", "s5"), ("s5", "s3")):
        loop[("visit", (w, a, b))] = 1
    assert not holds(compiled, loop)


def test_a_stop_with_no_demand_is_refused_with_its_reason():
    ir, data = vrp("S", 0)
    data["sets"]["stop"][2]["demand"] = 0
    with pytest.raises(Unsupported, match="no positive 'demand'"):
        compile_model(ir, data)


def test_a_depot_missing_from_the_data_is_refused():
    ir, data = vrp("S", 0)
    ir["constraints"][0]["route"]["depot"] = "hq"
    with pytest.raises(Unsupported, match="the depot 'hq'"):
        compile_model(ir, data)


@pytest.mark.parametrize("size", ["S", "M", "L"])
def test_the_routing_start_holds_every_row(size):
    ir, data = vrp(size, 0)
    compiled = compile_model(ir, data)
    assert routing.applies(ir, compiled) is None
    hint, record = routing.start(ir, data, compiled, seconds=2)
    assert record["feasible"] and set(hint) == set(compiled.variables)
    assert holds(compiled, hint)


def test_from_the_start_cp_sat_proves_the_optimum():
    ir, data = _small(True, 1)
    compiled = compile_model(ir, data)
    hint, _ = routing.start(ir, data, compiled, seconds=1)
    result = by_name("cp-sat").solve(compiled, time_limit=30, workers=8, seed=1, hint=hint)
    assert result.status == "optimal" and float(result.objective) == pytest.approx(_brute(ir, data))


def test_the_routing_start_says_why_it_cannot_run():
    ir, data = vrp("S", 0)
    ir["objective"]["sense"] = "maximize"
    assert "minimises" in routing.applies(ir, compile_model(ir, data))


def test_a_route_run_through_the_api_starts_from_the_routing_search(tenants, db, empty_queue):  # noqa: F811
    """Vehicles and stops as entities, distances as a parameter, a route rule: the run records its start and
    is answered -- proven here, where CP-SAT closes six stops."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.main import app
    from app.worker import work_once

    client, headers, domain = TestClient(app), tenants["a"], tenants["domain_a"]
    ir, data = _small(True, 0)

    def post(path, body):
        response = client.post(path, json=body, headers=headers)
        assert response.status_code in (200, 201), response.text
        return response.json()

    vehicle = post("/api/v1/entity-types", {"domain_id": domain, "name": "vehicle", "role": "resource"})
    stop = post("/api/v1/entity-types", {"domain_id": domain, "name": "stop", "role": "location"})
    post(f"/api/v1/entity-types/{vehicle['id']}/attributes", {"name": "capacity", "data_type": "integer"})
    post(f"/api/v1/entity-types/{stop['id']}/attributes", {"name": "demand", "data_type": "integer"})
    for row in data["sets"]["vehicle"]:
        post("/api/v1/entities", {"entity_type_id": vehicle["id"], "key": row["id"], "attrs": {"capacity": row["capacity"]}})
    ids = {row["id"]: post("/api/v1/entities", {"entity_type_id": stop["id"], "key": row["id"],
                                                "attrs": {"demand": row["demand"]}})["id"]
           for row in data["sets"]["stop"]}
    distance = post("/api/v1/parameters", {"domain_id": domain, "name": "distance", "index_type_ids": [stop["id"], stop["id"]],
                                            "default_value": 0})
    cells = [{"entity_ids": [ids[r["0"]], ids[r["1"]]], "value": r["value"]} for r in data["parameters"]["distance"]]
    assert client.put(f"/api/v1/parameters/{distance['id']}/values", json={"cells": cells}, headers=headers).status_code == 200
    problem = post("/api/problem/", {"domain_id": domain, "name": "rounds"})
    version = post(f"/api/v1/problems/{problem['id']}/versions", {"ir": ir, "note": "six stops"})
    scenario = post("/api/v1/scenarios", {"problem_id": problem["id"], "model_version_id": version["id"], "name": "as drawn"})
    run_id = post(f"/api/v1/scenarios/{scenario['id']}/runs", {"reuse": False, "time_limit_s": 20})["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    run = client.get(f"/api/v1/runs/{run_id}", headers=headers).json()
    assert run["status"] == "optimal" and run["optimality"] == "global"
    assert float(run["objective"]) == pytest.approx(_brute(ir, data))
    start = run["params"]["routing_start_run"]
    assert start["used"] and start["feasible"] and start["objective"] >= float(run["objective"])
    assert "connected_start_run" not in run["params"]  # no connected rule, nothing said about one


def _two_depots():
    """Benchmark, October 2026: two depots, each truck from its own, and distances in fractions of a km."""
    ir, _ = vrp("S", 0, load=True)
    body = ir["constraints"][0]["route"]
    del body["depot"]
    body["depot_of"] = "home"
    at = {"north": 0.0, "n1": 1.0, "n2": 2.0, "south": 10.0, "s1": 11.0, "s2": 12.5}
    data = {
        "sets": {"vehicle": [{"id": "t_north", "capacity": 10, "home": "north"}, {"id": "t_south", "capacity": 10, "home": "south"}],
                 "stop": [{"id": k, "demand": 0 if k in ("north", "south") else 1} for k in at]},
        "parameters": {"distance": [{"0": a, "1": b, "value": round(abs(at[a] - at[b]) * 1.5, 2)} for a in at for b in at]},
        "parameter_defaults": {"distance": 0},
    }
    return ir, data


def test_each_vehicle_starts_from_its_own_depot_and_distances_may_be_fractional():
    ir, data = _two_depots()
    assert check_shape(ir) is None
    compiled = compile_model(ir, data)
    result = by_name("highs").solve(compiled, time_limit=30, workers=1, seed=1)
    assert result.status == "optimal"
    # Each truck out and back to its own two stops: 2 x 1.5 x 2 + 2 x 1.5 x 2.5 = 13.5.
    assert float(result.objective) == pytest.approx(13.5)
    used = {k[1] for k, v in result.assignments.items() if k[0] == "visit" and round(float(v)) == 1}
    assert all(("north" not in arc and "n1" not in arc) for v, *arc in used if v == "t_south")


def test_the_routing_start_takes_several_depots_and_fractional_distances():
    ir, data = _two_depots()
    compiled = compile_model(ir, data)
    assert routing.applies(ir, compiled) is None
    hint, record = routing.start(ir, data, compiled, seconds=2)
    assert record["feasible"] is True and float(record["objective"]) == pytest.approx(13.5)


def test_a_vehicle_whose_depot_is_not_a_stop_is_named():
    ir, data = _two_depots()
    data["sets"]["vehicle"][1]["home"] = "nowhere"
    with pytest.raises(Unsupported, match="t_south's home 'nowhere'"):
        compile_model(ir, data)
