import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    db = SessionLocal()
    seed_admin(db)
    db.close()


@pytest.fixture
def auth_headers():
    settings = get_settings()
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def organization_id(auth_headers):
    client = TestClient(app)
    response = client.get("/api/iam/organization/", headers=auth_headers)
    items = response.json()["items"]
    default_org = next(item for item in items if item["code"] == "default")
    return default_org["id"]


def test_get_domain_graph_returns_entity_as_node(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"unit-{suffix}", "name": "Unit"},
        headers=auth_headers,
    )
    assert et_response.status_code == 201
    entity_type_id = et_response.json()["id"]
    entity_type_code = et_response.json()["code"]

    entity_response = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "code": f"e1-{suffix}",
            "name": "Test Entity",
        },
        headers=auth_headers,
    )
    assert entity_response.status_code == 201
    entity_id = entity_response.json()["id"]

    graph_response = client.get(
        f"/api/graph/domain?organization_id={organization_id}", headers=auth_headers
    )
    assert graph_response.status_code == 200
    body = graph_response.json()

    node = next(n for n in body["nodes"] if n["id"] == entity_id)
    assert node["type"] == entity_type_code
    assert node["label"] == "Test Entity"
    assert node["parent"] is None
    assert node["attributes"]["code"] == f"e1-{suffix}"
    assert any(et["id"] == entity_type_id for et in body["entity_types"])


def test_get_domain_graph_requires_auth():
    client = TestClient(app)
    response = client.get(f"/api/graph/domain?organization_id={uuid.uuid4()}")
    assert response.status_code == 401
