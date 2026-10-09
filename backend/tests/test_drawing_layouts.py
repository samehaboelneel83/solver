"""Lay items out on a drawing through the platform's own API, without the Assistant (owner, 9 October 2026)."""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.test_layout import DRAWING
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

BED = {"name": "bed", "length": 1.5, "width": 0.5, "rotations": [0, 90]}


def _upload(client, headers):
    got = client.post("/api/v1/layouts/drawings", headers=headers,
                      files={"file": (DRAWING.name, DRAWING.read_bytes(), "application/dxf")})
    assert got.status_code == 200, got.text
    return got.json()


def test_a_drawing_names_its_layers_and_a_layout_previews_in_both_forms(tenants):  # noqa: F811
    from app.main import app

    client = TestClient(app)
    drawing = _upload(client, tenants["a"])
    layers = {layer["name"]: layer for layer in drawing["layers"]}
    assert {"BOUNDARY", "OBSTACLES", "LABELS"} <= set(layers) and layers["BOUNDARY"]["features"] > 0
    options = {"upload_id": drawing["upload_id"], "area_layers": ["BOUNDARY"], "blocked_layers": ["OBSTACLES"],
               "label_layer": "LABELS", "items": [BED], "aisle": 0.35, "aisle_side": "any"}
    placed = client.post("/api/v1/layouts/preview", headers=tenants["a"], json=options).json()
    assert placed["form"] == "place" and placed["grid_step_m"] == 0.05 and placed["upper_bound"]["items"] > 2000
    assert any("place" in c for c in placed["model"]["constraints"])
    listed = client.post("/api/v1/layouts/preview", headers=tenants["a"], json={**options, "form": "candidates"}).json()
    assert listed["form"] == "generated" and listed["candidates"] > 40_000 and listed["stored"]["links"] == 0
    assert listed["model"]["generate"][0]["kind"] == "positions"
    # A layer the drawing has not is named, not guessed.
    bad = client.post("/api/v1/layouts/preview", headers=tenants["a"], json={**options, "blocked_layers": ["WALLS"]})
    assert bad.status_code == 422 and "WALLS" in bad.text
    # Another organisation cannot use the upload.
    assert client.post("/api/v1/layouts/preview", headers=tenants["b"], json=options).status_code == 404


def test_a_layout_builds_a_problem_through_from_spec(tenants):  # noqa: F811
    from app.main import app

    client = TestClient(app)
    drawing = _upload(client, tenants["a"])
    body = {"upload_id": drawing["upload_id"], "area_layers": ["BOUNDARY"], "blocked_layers": ["OBSTACLES"],
            "items": [BED], "aisle": 0.35, "aisle_side": "any", "form": "candidates", "step": 0.5,
            "domain_name": f"camp {uuid4().hex[:6]}", "problem_name": "beds"}
    checked = client.post("/api/v1/layouts/build", headers=tenants["a"], json={**body, "dry_run": True})
    assert checked.status_code == 200, checked.text[:500]
    built = client.post("/api/v1/layouts/build", headers=tenants["a"], json=body)
    assert built.status_code == 200, built.text[:500]
    out = built.json()
    assert out["scenario_id"] and out["layout"]["candidates"] > 40_000
    versions = client.get(f"/api/v1/problems/{out['problem_id']}/versions", headers=tenants["a"])
    assert versions.status_code == 200 and versions.json()["items"]
