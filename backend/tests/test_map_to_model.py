"""From a map file to data a model reads, inside the app (improvement plan, phases 1 and 2).

The user test had to compute drive times, "within 15 minutes", "near a hospital" and
"which district" outside the app and type them back in. This walks the same road
through the API, on a small made-up town with nothing flood-specific about it:
layers -> records with shapes -> spatial measures -> parameters and links.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.main import app
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

WGS84 = {"kind": "epsg", "code": 4326}


def _f(layer, geometry, **props):
    return {"type": "Feature", "properties": {"layer": layer, **props}, "geometry": geometry}


def _pt(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


def _box(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


TOWN = {"type": "FeatureCollection", "features": [
    _f("ZONES", _box(30.00, 31.20, 30.02, 31.22), name="North"),
    _f("ZONES", _box(30.02, 31.20, 30.04, 31.22), name="South"),
    _f("DEPOTS", _pt(30.001, 31.201), name="D1", capacity=4),
    _f("DEPOTS", _pt(30.039, 31.201), name="D2", capacity=6),
    _f("SITES", _pt(30.005, 31.205), name="S1", risk=3),
    _f("SITES", _pt(30.030, 31.205), name="S2", risk=9),
    _f("SITES", _pt(30.035, 31.215), name="S3", risk=5),
    _f("CLINICS", _pt(30.0302, 31.2052), name="C1"),
    # One straight road along 31.201 at 60 km/h, then up the east side at 20 km/h.
    _f("ROADS", {"type": "LineString", "coordinates": [[30.0, 31.201], [30.02, 31.201], [30.04, 31.201]]}, speed=60),
    _f("ROADS", {"type": "LineString", "coordinates": [[30.04, 31.201], [30.04, 31.215]]}, speed=20),
]}


@pytest.fixture
def town(tenants, db):  # noqa: F811
    http, t = TestClient(app), tenants
    up = http.post("/api/v1/gis/uploads", files={"file": ("town.geojson", io.BytesIO(json.dumps(TOWN).encode()))},
                   data={"domain_id": str(t["domain_a"])}, headers=t["a"])
    assert up.status_code == 201, up.text
    ds = http.post("/api/v1/gis/datasets", json={"upload_id": up.json()["upload_id"], "domain_id": t["domain_a"],
                                                  "name": "Town", "placement": WGS84}, headers=t["a"])
    assert ds.status_code == 201, ds.text
    yield http, t, ds.json()
    with SessionLocal() as session:
        session.execute(text("DELETE FROM gis_dataset"))
        session.execute(text("DELETE FROM gis_upload"))
        session.commit()


def _make(http, t, ds, layer, **edit):
    plan = http.post(f"/api/v1/gis/datasets/{ds['id']}/records/propose", json={"layers": [layer]}, headers=t["a"])
    assert plan.status_code == 200, plan.text
    body = {**plan.json(), **edit}
    made = http.post(f"/api/v1/gis/datasets/{ds['id']}/records", json={"layers": [layer], "plan": body}, headers=t["a"])
    assert made.status_code == 201, made.text
    return plan.json(), made.json()


def test_layers_become_records_with_shapes_fields_and_measures(town, db):  # noqa: F811
    http, t, ds = town
    plan, made = _make(http, t, ds, "DEPOTS")
    assert plan["name"] == "depot" and plan["key"] == "name"
    # The key is listed too, left out (benchmark, October 2026: a changed key kept the old one as a field).
    assert {f["name"]: f["data_type"] for f in plan["fields"] if not f["skip"]} == {"capacity": "integer"}
    assert made["made"] == 2 and made["updated"] == 0
    rows = dict(db.execute(text("SELECT e.key, e.attrs FROM entity e WHERE e.entity_type_id = :t"),
                           {"t": made["entity_type_id"]}).all())
    assert rows["D2"]["capacity"] == 6 and rows["D2"]["shape"] == _pt(30.039, 31.201)
    _, zones = _make(http, t, ds, "ZONES")
    area = db.execute(text("SELECT (attrs->>'area_m2')::float FROM entity WHERE entity_type_id = :t AND key = 'North'"),
                      {"t": zones["entity_type_id"]}).scalar_one()
    assert 3_500_000 < area < 4_500_000  # about 1.9 km x 2.2 km
    # Again: nothing new, the existing records refreshed by key.
    _, again = _make(http, t, ds, "DEPOTS")
    assert again["made"] == 0 and again["updated"] == 2
    # Another organization cannot read the layers.
    assert http.post(f"/api/v1/gis/datasets/{ds['id']}/records/propose", json={"layers": ["DEPOTS"]},
                     headers=t["b"]).status_code == 404


def test_shapes_attach_to_records_that_came_from_a_spreadsheet(town, db):  # noqa: F811
    http, t, ds = town
    kind = http.post("/api/v1/entity-types", json={"domain_id": t["domain_a"], "name": "site"}, headers=t["a"]).json()
    for key in ("S1", "S2", "S9"):
        assert http.post("/api/v1/entities", json={"entity_type_id": kind["id"], "key": key}, headers=t["a"]).status_code == 201
    got = http.post(f"/api/v1/gis/datasets/{ds['id']}/records/attach",
                    json={"layers": ["SITES"], "type": "site", "match": "name"}, headers=t["a"])
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["attached"] == 2 and body["records_without_shape"] == ["S9"] and body["unmatched_features"] == ["S3"]


def test_spatial_measures_are_written_as_data_a_model_reads(town, db):  # noqa: F811
    http, t, ds = town
    _, depots = _make(http, t, ds, "DEPOTS")
    _, sites = _make(http, t, ds, "SITES")
    _, zones = _make(http, t, ds, "ZONES")
    _, clinics = _make(http, t, ds, "CLINICS")
    d = t["domain_a"]

    def post(path, body):
        got = http.post(f"/api/v1/domains/{d}/{path}", json=body, headers=t["a"])
        assert got.status_code == 201, got.text
        return got.json()

    inside = post("spatial/inside", {"name": "zone_of", "from_type_id": sites["entity_type_id"], "to_type_id": zones["entity_type_id"]})
    pairs = dict(db.execute(text("SELECT a.key, b.key FROM relationship r JOIN entity a ON a.id = r.from_entity_id"
                                 " JOIN entity b ON b.id = r.to_entity_id WHERE r.relationship_type_id = :r"),
                            {"r": inside["relationship_type_id"]}).all())
    assert pairs == {"S1": "North", "S2": "South", "S3": "South"}

    count = post("spatial/count", {"name": "clinics_300m", "from_type_id": sites["entity_type_id"],
                                   "to_type_id": clinics["entity_type_id"], "max_m": 300})
    assert count["with_any"] == 1
    near = dict(db.execute(text("SELECT key, (attrs->>'clinics_300m')::int FROM entity WHERE entity_type_id = :t"),
                           {"t": sites["entity_type_id"]}).all())
    assert near == {"S1": 0, "S2": 1, "S3": 0}

    nearest = post("spatial/nearest", {"name": "closest_depot", "from_type_id": sites["entity_type_id"],
                                       "to_type_id": depots["entity_type_id"], "k": 1})
    assert nearest["links"] == 3

    touching = post("spatial/touching", {"name": "next_to", "type_id": zones["entity_type_id"]})
    assert touching["links"] == 2

    # "Within 4 minutes along my own roads", as a 0/1 parameter a rule multiplies by.
    reach = post("within", {"name": "reach", "from_type_id": depots["entity_type_id"], "to_type_id": sites["entity_type_id"],
                            "metric": "network_time", "max_min": 4, "output": "parameter",
                            "network": {"dataset_id": ds["id"], "layer": "ROADS", "speed_field": "speed", "default_kmh": 30}})
    ones = {(a, b) for a, b in db.execute(text(
        "SELECT a.key, b.key FROM parameter_value pv JOIN entity a ON a.id = pv.entity_ids[1]"
        " JOIN entity b ON b.id = pv.entity_ids[2] WHERE pv.parameter_def_id = :p AND pv.value = 1"),
        {"p": reach["parameter_id"]}).all()}
    assert ("D1", "S1") in ones and ("D2", "S2") in ones and ("D1", "S3") not in ones
    assert reach["source"]["metric"].startswith("along layer 'ROADS'")

    minutes = post("distances", {"name": "drive_min", "from_type_id": depots["entity_type_id"],
                                 "to_type_id": sites["entity_type_id"], "metric": "network_time", "unit": "min",
                                 "network": {"dataset_id": ds["id"], "layer": "ROADS", "speed_field": "speed"}})
    assert minutes["pairs"] == 6


def test_a_spreadsheet_with_longitude_and_latitude_makes_places(tenants, db):  # noqa: F811
    http, t = TestClient(app), tenants
    csv_file = "yard_id,lon,lat,max_trucks\nY1,29.90,31.18,6\nY2,29.94,31.18,12\n"
    files = {"file": ("yards.csv", io.BytesIO(csv_file.encode()), "text/csv")}
    proposal = http.post(f"/api/v1/domains/{t['domain_a']}/spreadsheet/propose", files=files, headers=t["a"])
    assert proposal.status_code == 200, proposal.text
    kind = proposal.json()["kinds"][0]
    assert kind["location"] == {"name": "location", "lon": "lon", "lat": "lat", "wkt": None, "skip": False}
    made = http.post(f"/api/v1/domains/{t['domain_a']}/spreadsheet/import",
                     files={"file": ("yards.csv", io.BytesIO(csv_file.encode()), "text/csv")},
                     data={"proposal": json.dumps(proposal.json())}, headers=t["a"])
    assert made.status_code == 200, made.text
    shape = db.execute(text("SELECT e.attrs->'location' FROM entity e JOIN entity_type k ON k.id = e.entity_type_id"
                            " WHERE k.domain_id = :d AND k.name = 'yard' AND e.key = 'Y2'"), {"d": t["domain_a"]}).scalar_one()
    assert shape == {"type": "Point", "coordinates": [29.94, 31.18]}
