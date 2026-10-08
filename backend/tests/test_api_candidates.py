"""Candidate data APIs: supplied records and exact-size map placements."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.seed import seed_admin
from app.core.db import SessionLocal

DRAWING = Path(__file__).parent / "fixtures" / "camp_layout_layers.dxf"


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    db = SessionLocal()
    seed_admin(db)
    db.close()


@pytest.fixture
def auth_headers():
    http = TestClient(app)
    settings = get_settings()
    response = http.post("/api/auth/login", data={"username": settings.admin_username,
                                                   "password": settings.admin_password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def domain_id(auth_headers):
    http = TestClient(app)
    response = http.post("/api/domain/", json={"name": f"candidate-test-{uuid.uuid4().hex[:8]}"},
                         headers=auth_headers)
    assert response.status_code == 201, response.text
    identity = response.json()["id"]
    try:
        yield identity
    finally:
        http.delete(f"/api/domain/{identity}", headers=auth_headers)


def test_supplied_candidates_are_created_as_queryable_domain_entities(auth_headers, domain_id):
    http = TestClient(app)
    created = http.post("/api/v1/candidate-sets", headers=auth_headers, json={
        "domain_id": domain_id,
        "name": "Warehouse shortlist",
        "attributes": [{"name": "daily_cost", "data_type": "number", "unit": "EGP/day"}],
        "candidates": [
            {"key": "north", "label": "North depot", "attrs": {"daily_cost": 240}},
            {"key": "south", "label": "South depot", "attrs": {"daily_cost": 190}},
        ],
    })
    assert created.status_code == 201, created.text
    assert created.json()["counts"]["candidates"] == 2
    records = http.get(created.json()["read_candidates"], headers=auth_headers)
    assert records.status_code == 200, records.text
    assert records.json()["total"] == 2
    assert {row["key"] for row in records.json()["items"]} == {"north", "south"}


def test_map_candidate_api_generates_records_and_occupancy_links(auth_headers, domain_id):
    http = TestClient(app)
    uploaded = http.post("/api/v1/gis/uploads", headers=auth_headers,
                         files={"file": ("camp_layout_layers.dxf", io.BytesIO(DRAWING.read_bytes()))},
                         data={"domain_id": str(domain_id)})
    assert uploaded.status_code == 201, uploaded.text

    generated = http.post("/api/v1/candidate-sets/from-map", headers=auth_headers, json={
        "domain_id": domain_id,
        "upload_id": uploaded.json()["upload_id"],
        "name": "camp west zone",
        "area_layers": ["BOUNDARY"],
        "blocked_layers": ["OBSTACLES", "DOORS_OBSTACLE"],
        "label_layer": "LABELS",
        # Within the API's own limits (150,000 records, 200,000 links): 1.5 m beds on the exact 0.5 m grid.
        "items": [{"name": "bed", "length": 1.5, "width": 0.5, "rotations": [0, 90]}],
        "aisle": 0.35,
        "aisle_side": "short",
        "step": 0.5,
        "area_indices": [0],
    })
    assert generated.status_code == 201, generated.text
    body = generated.json()
    assert body["counts"]["candidates"] > 0
    assert body["counts"]["occupies"] > 0
    assert body["grid_step_m"] == 0.5
    assert body["ir"]["sets"][0] == body["candidate_type"]
    assert body["ir"]["sets"][1] == body["cell_type"]

    records = http.get(body["read_candidates"], headers=auth_headers)
    assert records.status_code == 200, records.text
    assert records.json()["total"] == body["counts"]["candidates"]
