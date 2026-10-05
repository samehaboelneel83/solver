"""The sample drawings in samples/map-data (what a person tries the workflow with) import as map data:
a CAD drawing in UTM metres with its layers, and the same site as GeoJSON landing at Mina by itself."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.main import app
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "map-data"
MINA = SAMPLES / "mina-camp-utm37n.dxf"
GEOJSON = SAMPLES / "mina-camp.geojson"

pytestmark = pytest.mark.skipif(not MINA.exists(), reason="the samples folder is not in this checkout")


@pytest.fixture
def client(tenants):  # noqa: F811
    yield TestClient(app), tenants
    with SessionLocal() as session:
        session.execute(text("DELETE FROM gis_dataset"))
        session.commit()


def test_the_dxf_sample_is_map_data_with_its_layers(client):
    http, t = client
    up = http.post("/api/v1/gis/uploads", files={"file": (MINA.name, io.BytesIO(MINA.read_bytes()))},
                   data={"domain_id": str(t["domain_a"])}, headers=t["a"])
    assert up.status_code in (200, 201), up.text
    ds = http.post("/api/v1/gis/datasets", json={"upload_id": up.json()["upload_id"], "domain_id": t["domain_a"],
                                                  "name": "Mina site", "placement": {"kind": "epsg", "code": 32637}},
                   headers=t["a"])
    assert ds.status_code in (200, 201), ds.text
    layers = {lay["name"] for lay in ds.json()["layers"]}
    assert {"CAMP_BOUNDARY", "DOORS", "OBSTACLES", "NO_BEDS", "ZONE_MEDICAL_AREA", "ROADS", "NOTES"} <= layers
    west, south, east, north = ds.json()["bbox"]
    assert 39.88 < west < east < 39.91 and 21.40 < south < north < 21.43  # Mina


def test_the_geojson_sample_lands_at_mina_by_itself(client):
    http, t = client
    up = http.post("/api/v1/gis/uploads", files={"file": (GEOJSON.name, io.BytesIO(GEOJSON.read_bytes()))},
                   data={"domain_id": str(t["domain_a"])}, headers=t["a"])
    assert up.status_code == 201, up.text
    best = up.json()["candidates"][0]
    assert best["placement"] == {"kind": "epsg", "code": 4326} and best["sure"]
    ds = http.post("/api/v1/gis/datasets", json={"upload_id": up.json()["upload_id"], "domain_id": t["domain_a"],
                                                  "name": "Mina site (GeoJSON)", "placement": best["placement"]},
                   headers=t["a"])
    assert ds.status_code == 201, ds.text
    assert ds.json()["source"]["format"] == "geojson"
    assert {"CAMP_BOUNDARY", "DOORS"} <= {lay["name"] for lay in ds.json()["layers"]}
