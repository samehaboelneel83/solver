"""Map data through the API: a CAD drawing uploaded, placed with a chosen CRS, previewed,
imported as layers of features, read back as GeoJSON, placed again and exported."""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.gis import store
from app.main import app
from tests.cad_fixtures import E0, N0, site_drawing
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture
def client(tenants):  # noqa: F811
    yield TestClient(app), tenants
    with SessionLocal() as session:
        session.execute(text("DELETE FROM gis_dataset"))
        session.execute(text("DELETE FROM gis_upload"))
        session.commit()


@pytest.fixture(scope="module")
def drawing_bytes(tmp_path_factory):
    path = tmp_path_factory.mktemp("gis") / "site.dxf"
    site_drawing(path)
    return path.read_bytes()


def _upload(http, t, data, name="Site plan.dxf"):
    got = http.post("/api/v1/gis/uploads", files={"file": (name, io.BytesIO(data))},
                    data={"domain_id": str(t["domain_a"])}, headers=t["a"])
    assert got.status_code == 201, got.text
    return got.json()


UTM36 = {"kind": "epsg", "code": 32636}


def test_an_upload_lists_layers_and_where_each_crs_would_put_it(client, drawing_bytes):
    http, t = client
    up = _upload(http, t, drawing_bytes)
    layers = {l["name"]: l for l in up["summary"]["layers"]}
    assert layers["Buildings"]["kinds"]["polygon"] == 3 and layers["Buildings"]["color"] == "#ff0000"
    assert up["summary"]["units_name"] == "metres"
    zone = next(z for z in up["utm_zones"] if z["zone"] == "36N")
    assert 31 < zone["centre"][0] < 32.5
    # Wrong coordinate system: the preview says so before anything is stored.
    wrong = http.post(f"/api/v1/gis/uploads/{up['upload_id']}/preview", json={"placement": {"kind": "epsg", "code": 4326}},
                      headers=t["a"]).json()
    assert wrong["warnings"] and "off the map" in wrong["warnings"][0]
    right = http.post(f"/api/v1/gis/uploads/{up['upload_id']}/preview", json={"placement": UTM36, "layers": ["Buildings"]},
                      headers=t["a"]).json()
    assert right["warnings"] == [] and len(right["features"]["features"]) == 3
    assert 31 < right["bbox"][0] < 32.5
    # Another organization cannot use the upload.
    assert http.post(f"/api/v1/gis/uploads/{up['upload_id']}/preview", json={"placement": UTM36},
                     headers=t["b"]).status_code == 404
    # Said to be in Egypt, the drawing's numbers name the UTM zones that put it there, one entry per place.
    egypt = http.post(f"/api/v1/gis/uploads/{up['upload_id']}/candidates", json={"region": "Egypt"}, headers=t["a"]).json()
    places = {c["placement"]["code"]: c for c in egypt["candidates"]}
    assert 32636 in places and 31 < places[32636]["centre"][0] < 32.5 and places[32636]["also"]
    assert all(24.4 < c["centre"][0] < 37.2 for c in egypt["candidates"])
    near = http.post(f"/api/v1/gis/uploads/{up['upload_id']}/candidates", json={"point": [31.3, 30.0]}, headers=t["a"]).json()
    assert near["candidates"][0]["placement"]["code"] == 32636 and "km from the position" in near["candidates"][0]["reason"]
    assert http.post(f"/api/v1/gis/uploads/{up['upload_id']}/candidates", json={"region": "Atlantis"},
                     headers=t["a"]).status_code == 422
    assert "Qatar" in [r["name"] for r in http.get("/api/v1/gis/regions", headers=t["a"]).json()["items"]]
    refused = http.post("/api/v1/gis/uploads", files={"file": ("plan.dwg", io.BytesIO(b"AC1032"))},
                        data={"domain_id": str(t["domain_a"])}, headers=t["a"])
    assert refused.status_code == 415 and "DXF" in refused.text


def test_previews_reuse_the_upload_parse(client, drawing_bytes, monkeypatch):
    http, t = client
    read = store.read_bytes
    parses = 0

    def counted(data, filename="drawing.dxf"):
        nonlocal parses
        parses += 1
        return read(data, filename)

    monkeypatch.setattr(store, "read_bytes", counted)
    up = _upload(http, t, drawing_bytes)
    assert parses == 1  # the upload request parses the DXF
    for _ in range(2):
        response = http.post(f"/api/v1/gis/uploads/{up['upload_id']}/preview",
                             json={"placement": UTM36, "layers": ["Buildings"]}, headers=t["a"])
        assert response.status_code == 200, response.text
    assert parses == 1  # previews reuse that parse instead of rereading the DXF


def test_an_import_stores_layers_and_features_that_read_back_as_geojson(client, drawing_bytes):
    http, t = client
    up = _upload(http, t, drawing_bytes)
    made = http.post("/api/v1/gis/datasets", json={"upload_id": up["upload_id"], "domain_id": t["domain_a"],
                                                    "name": "Site plan", "placement": UTM36}, headers=t["a"])
    assert made.status_code == 201, made.text
    ds = made.json()
    assert ds["placement"]["name"] == "WGS 84 / UTM zone 36N"
    layers = {l["name"]: l for l in ds["layers"]}
    assert layers["Trees"]["color"] == "#00ff00" and layers["Labels"]["kinds"] == {"text": 2}
    fc = http.get(f"/api/v1/gis/datasets/{ds['id']}/features", params={"layers": str(layers["Labels"]["id"])},
                  headers=t["a"]).json()
    assert {f["properties"]["text"] for f in fc["features"]} >= {"Main gate"}
    assert all(31 < f["geometry"]["coordinates"][0] < 32.5 for f in fc["features"])
    # A window in degrees returns what lies in it.
    w, s, e, n = ds["bbox"]
    half = http.get(f"/api/v1/gis/datasets/{ds['id']}/features", params={"bbox": f"{w},{s},{(w + e) / 2},{n}"},
                    headers=t["a"]).json()
    everything = http.get(f"/api/v1/gis/datasets/{ds['id']}/features", headers=t["a"]).json()
    assert 0 < len(half["features"]) < len(everything["features"])
    # The upload is used up; B sees nothing.
    assert http.get("/api/v1/gis/datasets", params={"domain_id": t["domain_a"]}, headers=t["a"]).json()["items"][0]["name"] == "Site plan"
    assert http.get(f"/api/v1/gis/datasets/{ds['id']}", headers=t["b"]).status_code == 404
    with SessionLocal() as session:
        if session.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name = 'gis_feature'"
                                " AND column_name = 'geom'")).scalar_one_or_none():
            # PostGIS keeps a real geometry beside the GeoJSON.
            n_geom = session.execute(text("SELECT count(*) FROM gis_feature WHERE dataset_id = :d AND geom IS NOT NULL"
                                          " AND ST_SRID(geom) = 4326"), {"d": ds["id"]}).scalar_one()
            assert n_geom == len(everything["features"])


def test_a_dataset_is_placed_again_without_the_file_and_exports(client, drawing_bytes):
    http, t = client
    up = _upload(http, t, drawing_bytes)
    ds = http.post("/api/v1/gis/datasets", json={"upload_id": up["upload_id"], "domain_id": t["domain_a"],
                                                  "name": "Site", "placement": UTM36, "layers": ["Buildings", "Labels"]},
                   headers=t["a"]).json()
    assert {l["name"] for l in ds["layers"]} == {"Buildings", "Labels"}
    # Local engineering coordinates: the drawing's (E0, N0) at a surveyed point.
    local = {"kind": "local", "anchor": [E0, N0], "lonlat": [29.9, 31.2], "rotation": 0, "scale": 1}
    moved = http.put(f"/api/v1/gis/datasets/{ds['id']}/placement", json={"placement": local}, headers=t["a"]).json()
    assert moved["placement"]["kind"] == "local"
    w, s, e, n = moved["bbox"]
    assert 29.89 < w < 29.91 and 31.19 < s < 31.21
    layer = moved["layers"][0]
    patched = http.patch(f"/api/v1/gis/layers/{layer['id']}", json={"color": "#123ABC", "visible": False}, headers=t["a"])
    assert patched.json()["color"] == "#123abc" and patched.json()["visible"] is False
    gj = http.get(f"/api/v1/gis/datasets/{ds['id']}/export", params={"format": "geojson"}, headers=t["a"])
    assert gj.status_code == 200 and json.loads(gj.content)["features"]
    table = http.get(f"/api/v1/gis/datasets/{ds['id']}/export", params={"format": "csv"}, headers=t["a"]).text
    assert table.splitlines()[0].startswith("id,layer,kind") and "POLYGON" in table
    assert http.get("/api/v1/gis/crs", params={"q": "Purple Belt"}, headers=t["a"]).json()["items"]
    assert http.delete(f"/api/v1/gis/datasets/{ds['id']}", headers=t["a"]).status_code == 204
