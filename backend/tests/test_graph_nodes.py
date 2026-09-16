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


def test_create_node_writes_attributes_and_hierarchy_placement(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    )
    entity_type_id = et_response.json()["id"]

    attr_response = client.post(
        "/api/domain/attribute_definition/",
        json={
            "entity_type_id": entity_type_id,
            "code": "rank",
            "name": "Rank",
            "data_type": "string",
            "is_required": False,
            "is_multi_value": False,
        },
        headers=auth_headers,
    )
    assert attr_response.status_code == 201

    hierarchy_response = client.post(
        "/api/domain/hierarchy/",
        json={"organization_id": organization_id, "code": f"org-chart-{suffix}", "name": "Org Chart"},
        headers=auth_headers,
    )
    hierarchy_id = hierarchy_response.json()["id"]

    node_response = client.post(
        "/api/graph/domain/nodes",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "name": "Ahmed",
            "code": f"ahmed-{suffix}",
            "attributes": {"rank": "Captain"},
            "hierarchy_id": hierarchy_id,
        },
        headers=auth_headers,
    )
    assert node_response.status_code == 201
    body = node_response.json()
    assert body["label"] == "Ahmed"
    assert body["attributes"]["rank"] == "Captain"
    assert body["parent"] is None

    entity_id = body["id"]

    child_node_response = client.post(
        "/api/graph/domain/nodes",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "name": "Sara",
            "hierarchy_id": hierarchy_id,
            "parent_entity_id": entity_id,
        },
        headers=auth_headers,
    )
    assert child_node_response.status_code == 201
    assert child_node_response.json()["parent"] == entity_id


def test_update_node_edits_fields(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    )
    entity_type_id = et_response.json()["id"]

    node_response = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": entity_type_id, "name": "Ahmed"},
        headers=auth_headers,
    )
    entity_id = node_response.json()["id"]

    update_response = client.patch(
        f"/api/graph/domain/nodes/{entity_id}",
        json={"name": "Ahmed Updated", "status": "ACTIVE"},
        headers=auth_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["label"] == "Ahmed Updated"
    assert update_response.json()["attributes"]["status"] == "ACTIVE"


def test_update_node_returns_404_for_missing_entity(auth_headers):
    client = TestClient(app)
    response = client.patch(
        f"/api/graph/domain/nodes/{uuid.uuid4()}",
        json={"name": "Nope"},
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_delete_node_returns_409_when_still_referenced(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    )
    entity_type_id = et_response.json()["id"]

    rel_type_response = client.post(
        "/api/domain/relationship_type/",
        json={"code": f"reports_to-{suffix}", "name": "Reports To", "is_directed": True},
        headers=auth_headers,
    )
    relationship_type_id = rel_type_response.json()["id"]

    node_a = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": entity_type_id, "name": "A"},
        headers=auth_headers,
    ).json()
    node_b = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": entity_type_id, "name": "B"},
        headers=auth_headers,
    ).json()

    relationship_response = client.post(
        "/api/domain/relationship/",
        json={
            "relationship_type_id": relationship_type_id,
            "source_entity_id": node_a["id"],
            "target_entity_id": node_b["id"],
        },
        headers=auth_headers,
    )
    assert relationship_response.status_code == 201

    delete_response = client.delete(f"/api/graph/domain/nodes/{node_a['id']}", headers=auth_headers)
    assert delete_response.status_code == 409
    assert "relationship" in delete_response.json()["detail"].lower()


def test_delete_node_succeeds_when_unreferenced(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    )
    entity_type_id = et_response.json()["id"]

    node_response = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": entity_type_id, "name": "Solo"},
        headers=auth_headers,
    )
    entity_id = node_response.json()["id"]

    delete_response = client.delete(f"/api/graph/domain/nodes/{entity_id}", headers=auth_headers)
    assert delete_response.status_code == 204
