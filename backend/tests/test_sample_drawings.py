"""The sample drawings in samples/map-data (what a person tries the workflow with) read as intended:
straight into a camp, and as map data whose layers make a camp."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.camp.engine import camp_layout  # noqa: F401 -- the engine on the path
from app.core.db import SessionLocal
from app.main import app
from tests.camp_records import clear_camps
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "map-data"
MINA = SAMPLES / "mina-camp-utm37n.dxf"
ROOM = SAMPLES / "small-room-mm.dxf"

pytestmark = pytest.mark.skipif(not MINA.exists(), reason="the samples folder is not in this checkout")


@pytest.fixture
def client(tenants):  # noqa: F811
    yield TestClient(app), tenants
    with SessionLocal() as session:
        clear_camps(session)
        session.execute(text("DELETE FROM gis_dataset"))
        session.commit()


def test_the_samples_import_straight_into_camps(client):
    http, t = client
    got = http.post("/api/v1/camps/import", files={"file": (MINA.name, io.BytesIO(MINA.read_bytes()))},
                    data={"crs": "EPSG:32637"}, headers=t["a"]).json()
    p = got["problem"]
    assert got["check"]["ok"], got["check"]
    assert [d["id"] for d in p["doors"]] == ["D1-south", "D2-east", "D3-north", "D4-west"]
    assert len(p["obstacles"]) == 5 and len(p["prohibited"]) == 2 and [z["id"] for z in p["placement_zones"]] == ["medical-area"]
    lon, lat = p["origin_lonlat"]
    assert lon == pytest.approx(39.893, abs=0.002) and lat == pytest.approx(21.413, abs=0.002)  # Mina

    room = http.post("/api/v1/camps/import", files={"file": (ROOM.name, io.BytesIO(ROOM.read_bytes()))},
                     headers=t["a"]).json()["problem"]
    xs = [q[0] for q in room["boundary"]]
    assert (min(xs), max(xs)) == (0, 14)  # millimetres read as metres
    (door,) = room["doors"]
    assert door["id"] == "D1" and door["b"][0] - door["a"][0] == pytest.approx(1.5, abs=0.01)


def test_the_mina_sample_is_map_data_whose_layers_make_a_camp(client):
    http, t = client
    up = http.post("/api/v1/gis/uploads", files={"file": (MINA.name, io.BytesIO(MINA.read_bytes()))},
                   data={"domain_id": str(t["domain_a"])}, headers=t["a"])
    assert up.status_code in (200, 201), up.text
    ds = http.post("/api/v1/gis/datasets", json={"upload_id": up.json()["upload_id"], "domain_id": t["domain_a"],
                                                  "name": "Mina camp", "placement": {"kind": "epsg", "code": 32637}},
                   headers=t["a"])
    assert ds.status_code in (200, 201), ds.text
    layer = {lay["name"]: lay["id"] for lay in ds.json()["layers"]}
    assert {"CAMP_BOUNDARY", "DOORS", "OBSTACLES", "NO_BEDS", "ZONE_MEDICAL_AREA", "ROADS", "NOTES"} <= set(layer)
    made = http.post("/api/v1/camps/from-map", json={
        "domain_id": t["domain_a"], "name": "Mina camp", "dataset_id": ds.json()["id"],
        "boundary": layer["CAMP_BOUNDARY"], "doors": [layer["DOORS"]], "obstacles": [layer["OBSTACLES"]],
        "prohibited": [layer["NO_BEDS"]], "zones": [layer["ZONE_MEDICAL_AREA"]]}, headers=t["a"])
    assert made.status_code == 201, made.text
    camp = made.json()
    assert camp["check"]["ok"], camp["check"]["faults"]
    p = camp["problem"]
    assert len(p["doors"]) == 4 and len(p["obstacles"]) == 5 and len(p["prohibited"]) == 2
    assert len(p["placement_zones"]) == 1


GEOJSON = SAMPLES / "mina-camp.geojson"


def test_the_geojson_sample_is_map_data_whose_layers_make_a_camp(client):
    """Not only DXF: the same camp as GeoJSON lands at Mina by itself (WGS 84) and makes the same camp."""
    http, t = client
    up = http.post("/api/v1/gis/uploads", files={"file": (GEOJSON.name, io.BytesIO(GEOJSON.read_bytes()))},
                   data={"domain_id": str(t["domain_a"])}, headers=t["a"])
    assert up.status_code == 201, up.text
    best = up.json()["candidates"][0]
    assert best["placement"] == {"kind": "epsg", "code": 4326} and best["sure"]
    ds = http.post("/api/v1/gis/datasets", json={"upload_id": up.json()["upload_id"], "domain_id": t["domain_a"],
                                                  "name": "Mina camp (GeoJSON)", "placement": best["placement"]},
                   headers=t["a"])
    assert ds.status_code == 201, ds.text
    assert ds.json()["source"]["format"] == "geojson"
    layer = {lay["name"]: lay["id"] for lay in ds.json()["layers"]}
    made = http.post("/api/v1/camps/from-map", json={
        "domain_id": t["domain_a"], "name": "Mina camp", "dataset_id": ds.json()["id"],
        "boundary": layer["CAMP_BOUNDARY"], "doors": [layer["DOORS"]], "obstacles": [layer["OBSTACLES"]],
        "prohibited": [layer["NO_BEDS"]], "zones": [layer["ZONE_MEDICAL_AREA"]]}, headers=t["a"])
    assert made.status_code == 201, made.text
    camp = made.json()
    assert camp["check"]["ok"], camp["check"]["faults"]
    p = camp["problem"]
    assert [d["id"] for d in p["doors"]] == ["D1-south", "D2-east", "D3-north", "D4-west"]
    assert {o["id"] for o in p["obstacles"]} == {"latrines", "generator", "water-tank", "trees", "medical-store"}
    assert [z["id"] for z in p["placement_zones"]] == ["medical-area"]
    # Laid out on the camp's own grid: 40 x 26 m, turned from north by the UTM grid's convergence at Mina.
    xs, ys = [q[0] for q in p["boundary"]], [q[1] for q in p["boundary"]]
    assert (max(xs) - min(xs), max(ys) - min(ys)) == (pytest.approx(40, abs=0.02), pytest.approx(26, abs=0.02))
    assert 0.2 < abs(p["bearing"]) < 0.5
