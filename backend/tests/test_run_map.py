"""A spatial run's partition as GeoJSON, per cell and dissolved by zone (GIS 7)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from shapely.geometry import box, shape
from sqlalchemy import text

from app.main import app
from app.solve.service import enqueue_run
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_run_events import _knapsack, _run
from tests.test_spatial_grid import _drawn
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db, make_model_version, make_problem  # noqa: F401

#: A 1 km square: 2 x 2 cells of 500 m.
SQUARE_KM = _drawn(box(0, 0, 1000, 1000))


def _ir(extra: list[dict] | None = None) -> dict:
    return {
        "version": 2,
        "sets": ["cell", "district"],
        "relationships": ["adjacent"],
        "parameters": {},
        "variables": {"assign": {"index": ["cell", "district"], "domain": "binary"}},
        "constraints": [
            {"id": "c_one_each", "forall": [{"index": "u", "set": "cell"}],
             "left": {"sum": {"var": "assign", "index": ["u", "z"]}, "over": [{"index": "z", "set": "district"}]},
             "relation": "=", "right": {"const": 1}, "severity": "hard"},
            {"id": "c_two_each", "forall": [{"index": "z", "set": "district"}],
             "left": {"sum": {"var": "assign", "index": ["u", "z"]}, "over": [{"index": "u", "set": "cell"}]},
             "relation": "=", "right": {"const": 2}, "severity": "hard"},
            {"id": "c_connected", "severity": "hard",
             "connected": {"assign": {"var": "assign", "index": ["u", "z"]}, "units": {"index": "u", "set": "cell"},
                           "groups": {"index": "z", "set": "district"}, "via": "adjacent"}},
            *(extra or []),
        ],
    }


def _solved_grid_run(client, tenants, db, ir: dict | None = None) -> int:
    headers, domain = tenants["a"], tenants["domain_a"]
    # A population point in the south-west cell, which the dissolved totals must carry.
    grid = client.post(f"/api/v1/domains/{domain}/grids", headers=headers, json={
        "boundary": SQUARE_KM, "shape": "square", "size_m": 500, "entity_type": "cell",
        "layers": [{"lon": 3.001, "lat": 0.001, "population": 40}]})
    assert grid.status_code == 201, grid.text
    district = client.post("/api/v1/entity-types", json={"domain_id": domain, "name": "district"}, headers=headers).json()
    for key in ("d0", "d1"):
        assert client.post("/api/v1/entities", json={"entity_type_id": district["id"], "key": key}, headers=headers).status_code == 201
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, ir or _ir())
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 'map') RETURNING id"),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=10.0)
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    assert db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() == "optimal"
    return run_id


def test_a_partition_comes_back_per_cell_and_per_zone(tenants, db, empty_queue):  # noqa: F811
    client = TestClient(app)
    run_id = _solved_grid_run(client, tenants, db)
    cells = client.get(f"/api/v1/runs/{run_id}/map", headers=tenants["a"])
    assert cells.status_code == 200, cells.text
    features = cells.json()["features"]
    assert cells.json()["type"] == "FeatureCollection" and len(features) == 4
    assert sorted(f["properties"]["key"] for f in features) == ["c_r0_c0", "c_r0_c1", "c_r1_c0", "c_r1_c1"]
    assert sorted(f["properties"]["group"] for f in features) == ["d0", "d0", "d1", "d1"]
    assert all(f["properties"]["subgroup"] is None and f["geometry"]["type"] == "Polygon" for f in features)
    assert {f["properties"]["key"]: f["properties"]["population"] for f in features}["c_r0_c0"] == 40

    zones = client.get(f"/api/v1/runs/{run_id}/map?dissolve=true", headers=tenants["a"]).json()["features"]
    assert [(z["properties"]["group"], z["properties"]["cells"]) for z in zones] == [("d0", 2), ("d1", 2)]
    # Two adjacent squares dissolve into one rectangle, not two touching polygons.
    assert all(z["geometry"]["type"] == "Polygon" and len(shape(z["geometry"]).exterior.coords) == 5 for z in zones)
    assert sorted(z["properties"]["population"] for z in zones) == [0, 40]
    assert all(round(z["properties"]["area_m2"]) == 500_000 for z in zones)
    assert all("row" not in z["properties"] and "coverage" not in z["properties"] for z in zones)


def test_a_nested_rule_gives_each_cell_a_subgroup(tenants, db, empty_queue):  # noqa: F811
    """A second connected rule over the same cells: its groups are the sub-groups."""
    client = TestClient(app)
    ir = _ir()
    ir["sets"].append("ward")
    ir["variables"]["sub"] = {"index": ["cell", "ward"], "domain": "binary"}
    ir["constraints"] += [
        {"id": "c_one_ward", "forall": [{"index": "u", "set": "cell"}],
         "left": {"sum": {"var": "sub", "index": ["u", "w"]}, "over": [{"index": "w", "set": "ward"}]},
         "relation": "=", "right": {"const": 1}, "severity": "hard"},
        {"id": "c_wards", "severity": "hard",
         "connected": {"assign": {"var": "sub", "index": ["u", "w"]}, "units": {"index": "u", "set": "cell"},
                       "groups": {"index": "w", "set": "ward"}, "via": "adjacent", "empty": "allowed"}},
    ]
    ward = client.post("/api/v1/entity-types", json={"domain_id": tenants["domain_a"], "name": "ward"}, headers=tenants["a"]).json()
    client.post("/api/v1/entities", json={"entity_type_id": ward["id"], "key": "w0"}, headers=tenants["a"])
    run_id = _solved_grid_run(client, tenants, db, ir)
    features = client.get(f"/api/v1/runs/{run_id}/map", headers=tenants["a"]).json()["features"]
    assert {f["properties"]["subgroup"] for f in features} == {"w0"}
    zones = client.get(f"/api/v1/runs/{run_id}/map?dissolve=true", headers=tenants["a"]).json()["features"]
    assert [(z["properties"]["group"], z["properties"]["subgroup"]) for z in zones] == [("d0", "w0"), ("d1", "w0")]


def test_a_run_without_a_map_says_so(tenants, db, empty_queue):  # noqa: F811
    run_id = _run(db, _knapsack(10), "no-map")
    missing = TestClient(app).get(f"/api/v1/runs/{run_id}/map", headers=tenants["a"])
    assert missing.status_code == 404 and "no connected rule" in missing.text
    # Asked quietly, as the run page does, it is an empty answer with why, not an error (F7).
    quiet = TestClient(app).get(f"/api/v1/runs/{run_id}/map?quiet=true", headers=tenants["a"])
    assert quiet.status_code == 200 and quiet.json()["features"] == [] and "no connected rule" in quiet.json()["none"]
    assert TestClient(app).get("/api/v1/runs/999999999/map?quiet=true", headers=tenants["a"]).status_code == 404


def test_another_organization_cannot_read_the_map(tenants, db, empty_queue):  # noqa: F811
    client = TestClient(app)
    run_id = _solved_grid_run(client, tenants, db)
    assert client.get(f"/api/v1/runs/{run_id}/map", headers=tenants["b"]).status_code == 404


def test_two_stacked_cells_dissolve_to_a_rectangle():
    """A union of cells one above the other started its outline where they met, and simplifying never drops a
    ring's first point: a sixth corner in a straight edge (found when queue R13's start paired the cells that way)."""
    from app.api.run_map import dissolve

    def cell(key, x0, y0, x1, y1):
        return {"type": "Feature", "properties": {"key": key, "group": "d0", "subgroup": None},
                "geometry": {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}}

    below = cell("a", 3.0000000000000004, 0.0, 3.004493373765469, 0.004523656847896722)
    above = cell("b", 3.0000000000000004, 0.004523656847896722, 3.0044933738211133, 0.009047313695227132)
    [zone] = dissolve([below, above])
    assert zone["geometry"]["type"] == "Polygon" and len(shape(zone["geometry"]).exterior.coords) == 5


def test_each_place_carries_its_amounts_and_what_it_got_most_of():
    """Benchmark re-test, October 2026: a parcel's planted area by crop was lost -- its value was 1."""
    from app.api.answer_map import answer_map

    box = {"type": "Polygon", "coordinates": [[[30, 31], [30.01, 31], [30.01, 31.01], [30, 31.01], [30, 31]]]}
    ir = {"sets": ["parcel", "crop"], "variables": {"area": {"index": ["parcel", "crop"], "domain": "continuous"}}}
    data = {"sets": {"parcel": [{"id": "p1", "shape": box}], "crop": [{"id": "wheat"}, {"id": "maize"}]}}
    amounts = {"area": [{"index": ["p1", "wheat"], "value": 12.5}, {"index": ["p1", "maize"], "value": 3}]}
    found = answer_map(ir, data, {}, amounts, [])
    p1 = next(f for f in found["features"] if f["properties"].get("key") == "p1" and f["properties"]["layer"] == "area")
    assert p1["properties"]["value"] == 15.5 and p1["properties"]["largest"] == "wheat"
    assert p1["properties"]["by"] == {"wheat": 12.5, "maize": 3}
    assert "wheat 12.5, maize 3" in p1["properties"]["title"]
