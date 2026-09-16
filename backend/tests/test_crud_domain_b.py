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


@pytest.fixture
def entity_id(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    et_response = client.post(
        "/api/domain/entity_type/",
        json={
            "organization_id": organization_id,
            "code": f"unit-b-{suffix}",
            "name": "Unit",
            "is_abstract": False,
        },
        headers=auth_headers,
    )
    entity_type_id = et_response.json()["id"]
    entity_response = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "code": f"unit-1-{suffix}",
            "name": "Unit 1",
        },
        headers=auth_headers,
    )
    return entity_response.json()["id"]


def test_hierarchy_node_chain(auth_headers, organization_id, entity_id):
    client = TestClient(app)

    hierarchy_response = client.post(
        "/api/domain/hierarchy/",
        json={"organization_id": organization_id, "code": "org-chart", "name": "Org Chart"},
        headers=auth_headers,
    )
    assert hierarchy_response.status_code == 201
    hierarchy_id = hierarchy_response.json()["id"]

    node_response = client.post(
        "/api/domain/hierarchy_node/",
        json={"hierarchy_id": hierarchy_id, "entity_id": entity_id, "level": 0},
        headers=auth_headers,
    )
    assert node_response.status_code == 201


def test_entity_role_and_entity_state(auth_headers, entity_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    role_type_response = client.post(
        "/api/domain/role_type/",
        json={"code": f"supervisor-b-{suffix}", "name": "Supervisor"},
        headers=auth_headers,
    )
    assert role_type_response.status_code == 201
    role_type_id = role_type_response.json()["id"]

    entity_role_response = client.post(
        "/api/domain/entity_role/",
        json={"entity_id": entity_id, "role_type_id": role_type_id},
        headers=auth_headers,
    )
    assert entity_role_response.status_code == 201

    state_type_response = client.post(
        "/api/domain/state_type/",
        json={"code": f"availability-b-{suffix}", "name": "Availability"},
        headers=auth_headers,
    )
    assert state_type_response.status_code == 201
    state_type_id = state_type_response.json()["id"]

    entity_state_response = client.post(
        "/api/domain/entity_state/",
        json={
            "entity_id": entity_id,
            "state_type_id": state_type_id,
            "state_value": "AVAILABLE",
            "valid_from": "2026-01-01T00:00:00Z",
        },
        headers=auth_headers,
    )
    assert entity_state_response.status_code == 201
