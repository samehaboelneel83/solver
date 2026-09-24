"""POST /domains/{id}/grids: one transaction, caps, and a replace that says what it replaces (GIS 3)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from shapely.geometry import box
from sqlalchemy import text

from app.main import app
from tests.test_spatial_grid import _drawn
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db, make_model_version, make_problem  # noqa: F401

SQUARE_KM = _drawn(box(0, 0, 1000, 1000))


def _post(client, tenants, domain, **body):
    return client.post(f"/api/v1/domains/{domain}/grids", json=body, headers=tenants["a"])


def test_a_grid_is_cells_and_adjacency_in_the_domain(tenants, db):  # noqa: F811
    client = TestClient(app)
    domain = tenants["domain_a"]
    inside = [3.001, 0.001]
    report = _post(client, tenants, domain, boundary=SQUARE_KM, shape="square", size_m=500, entity_type="cell",
                   layers=[{"lon": inside[0], "lat": inside[1], "population": 40}, {"lon": 9.0, "lat": 9.0, "population": 5}])
    assert report.status_code == 201, report.text
    r = report.json()
    assert (r["cells"], r["edges"], r["dropped"]) == (4, 4, 0)
    assert r["layer_totals"] == {"population": 40} and r["layer_outside"] == {"population": 5}
    keys = db.execute(text("SELECT key FROM entity WHERE entity_type_id = :t ORDER BY key"),
                      {"t": r["entity_type_id"]}).scalars().all()
    assert keys == ["c_r0_c0", "c_r0_c1", "c_r1_c0", "c_r1_c1"]
    attrs = db.execute(text("SELECT attrs FROM entity WHERE entity_type_id = :t AND key = 'c_r0_c0'"),
                       {"t": r["entity_type_id"]}).scalar_one()
    assert attrs["geometry"]["type"] == "Polygon" and attrs["centroid"]["type"] == "Point"
    assert round(attrs["area_m2"]) == 250_000 and attrs["population"] == 40 and attrs["coverage"] == 1.0
    edges = db.execute(text("SELECT count(*), min((attrs->>'shared_m')::float) FROM relationship WHERE relationship_type_id = :r"),
                       {"r": r["relationship_type_id"]}).one()
    assert edges[0] == 4 and round(edges[1]) == 500
    kinds = dict(db.execute(text("SELECT name, data_type::text FROM attribute_def WHERE entity_type_id = :t"),
                            {"t": r["entity_type_id"]}).all())
    assert kinds == {"geometry": "geometry", "centroid": "geometry", "area_m2": "number", "row": "integer",
                     "col": "integer", "coverage": "number", "population": "number"}


def test_a_grid_over_an_entity_s_own_shape(tenants, db):  # noqa: F811
    client = TestClient(app)
    domain = tenants["domain_a"]
    area = client.post("/api/v1/entity-types", json={"domain_id": domain, "name": "area"}, headers=tenants["a"]).json()["id"]
    client.post(f"/api/v1/entity-types/{area}/attributes", json={"name": "outline", "data_type": "geometry"}, headers=tenants["a"])
    region = client.post("/api/v1/entities", json={"entity_type_id": area, "key": "region", "attrs": {"outline": SQUARE_KM}},
                         headers=tenants["a"]).json()["id"]
    report = _post(client, tenants, domain, boundary_entity_id=region, shape="hex", size_m=300, entity_type="cell")
    assert report.status_code == 201, report.text
    assert report.json()["cells"] > 4 and report.json()["edges"] > 0


def test_regenerating_a_grid_in_use_is_refused_until_replace(tenants, db):  # noqa: F811
    """Review Focus 4."""
    client = TestClient(app)
    domain = tenants["domain_a"]
    first = _post(client, tenants, domain, boundary=SQUARE_KM, shape="square", size_m=500, entity_type="cell").json()
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, {"version": 2, "sets": ["cell"], "parameters": {}, "variables": {},
                                               "constraints": []})
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 'grid') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.commit()
    again = _post(client, tenants, domain, boundary=SQUARE_KM, shape="square", size_m=250, entity_type="cell")
    assert again.status_code == 409
    detail = again.json()["detail"]
    assert detail["cells"] == 4 and scenario in detail["scenarios"]
    count = db.execute(text("SELECT count(*) FROM entity WHERE entity_type_id = :t"), {"t": first["entity_type_id"]}).scalar_one()
    assert count == 4  # nothing changed
    replaced = _post(client, tenants, domain, boundary=SQUARE_KM, shape="square", size_m=250, entity_type="cell", replace=True)
    assert replaced.status_code == 201 and replaced.json()["cells"] == 16 and replaced.json()["edges"] == 24
    assert replaced.json()["entity_type_id"] == first["entity_type_id"]
    left = db.execute(text("SELECT count(*) FROM relationship WHERE relationship_type_id = :r"),
                      {"r": replaced.json()["relationship_type_id"]}).scalar_one()
    assert left == 24  # the old grid's edges went with its cells


def test_caps_and_bad_input_are_named(tenants, db):  # noqa: F811
    client = TestClient(app)
    domain = tenants["domain_a"]
    too_many = _post(client, tenants, domain, boundary=_drawn(box(0, 0, 10_000, 10_000)), shape="square", size_m=50, entity_type="cell")
    assert too_many.status_code == 422 and "40000 cells" in too_many.text
    open_ring = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]}
    bad = _post(client, tenants, domain, boundary=open_ring, shape="square", size_m=500, entity_type="cell")
    assert bad.status_code == 422 and "ring 0" in bad.text
    point = _post(client, tenants, domain, boundary={"type": "Point", "coordinates": [3, 0]}, shape="square", size_m=500, entity_type="cell")
    assert point.status_code == 422 and "a point has no area" in point.text
    wide = _post(client, tenants, domain, boundary={"type": "Polygon", "coordinates": [[[0, 0], [8, 0], [8, 1], [0, 1], [0, 0]]]},
                 shape="square", size_m=5000, entity_type="cell")
    assert wide.status_code == 422 and "degrees of longitude wide" in wide.text
    clash = _post(client, tenants, domain, boundary=SQUARE_KM, shape="square", size_m=500, entity_type="cell",
                  layers=[{"lon": 3.001, "lat": 0.001, "area_m2": 1}])
    assert clash.status_code == 422 and "already carries" in clash.text


def test_another_organization_cannot_grid_this_domain(tenants, db):  # noqa: F811
    client = TestClient(app)
    other = client.post(f"/api/v1/domains/{tenants['domain_a']}/grids", headers=tenants["b"],
                        json={"boundary": SQUARE_KM, "shape": "square", "size_m": 500, "entity_type": "cell"})
    assert other.status_code == 404


def _tiles_index(db, domain):
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('domain', :d, 'spatial.tiles_index',"
                    " CAST('\"http://localhost:8080/index.json\"' AS jsonb))"), {"d": domain})
    db.commit()


def test_cells_take_their_elevation_and_slope_from_the_terrain(tenants, db, monkeypatch):  # noqa: F811
    """GIS 10: a plane rising 1000 m per degree east; at the equator a degree is 111,320 m, so 0.898 %."""
    from app.spatial import terrain
    from tests.test_terrain import _server

    client = TestClient(app)
    domain = tenants["domain_a"]
    _tiles_index(db, domain)
    monkeypatch.setattr(terrain, "fetch_bytes", _server(lambda lon, lat: 50 + 1000 * (lon - 3.0)))
    report = _post(client, tenants, domain, boundary=SQUARE_KM, shape="square", size_m=500, entity_type="cell", elevation=True)
    assert report.status_code == 201, report.text
    r = report.json()
    assert r["elevation_missing"] == 0 and r["elevation_range"][0] < r["elevation_range"][1]
    rows = db.execute(text("SELECT attrs FROM entity WHERE entity_type_id = :t"), {"t": r["entity_type_id"]}).scalars().all()
    assert all(abs(a["slope_pct"] - 1000 / 111_320 * 100) < 0.1 for a in rows)
    west = min(rows, key=lambda a: a["col"] * 10 + a["row"])
    assert abs(west["elevation_m"] - (50 + 1000 * (west["centroid"]["coordinates"][0] - 3.0))) < 1.5
    kinds = dict(db.execute(text("SELECT name, data_type::text FROM attribute_def WHERE entity_type_id = :t"),
                            {"t": r["entity_type_id"]}).all())
    assert kinds["elevation_m"] == kinds["slope_pct"] == "number"


def test_elevation_without_a_tile_index_is_refused_by_name(tenants, db):  # noqa: F811
    report = _post(TestClient(app), tenants, tenants["domain_a"], boundary=SQUARE_KM, shape="square", size_m=500,
                   entity_type="cell", elevation=True)
    assert report.status_code == 422 and "spatial.tiles_index" in report.text
    assert db.execute(text("SELECT count(*) FROM entity_type WHERE domain_id = :d AND name = 'cell'"),
                      {"d": tenants["domain_a"]}).scalar_one() == 0  # nothing written


def test_cells_the_terrain_does_not_reach_get_no_value_and_are_counted(tenants, db, monkeypatch):  # noqa: F811
    from app.spatial import terrain
    from tests.test_terrain import _server

    domain = tenants["domain_a"]
    _tiles_index(db, domain)
    monkeypatch.setattr(terrain, "fetch_bytes", _server(lambda lon, lat: 5.0, covered=lambda x, y: False))
    r = _post(TestClient(app), tenants, domain, boundary=SQUARE_KM, shape="square", size_m=500, entity_type="cell",
              elevation=True).json()
    assert r["elevation_missing"] == 4 and r["elevation_range"] is None
    rows = db.execute(text("SELECT attrs FROM entity WHERE entity_type_id = :t"), {"t": r["entity_type_id"]}).scalars().all()
    assert not any("elevation_m" in a for a in rows)
