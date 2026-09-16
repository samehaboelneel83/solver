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


def test_create_edge_accepts_matching_types(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    employee_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    ).json()
    unit_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"unit-{suffix}", "name": "Unit"},
        headers=auth_headers,
    ).json()

    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={
            "code": f"works_for-{suffix}",
            "name": "Works For",
            "is_directed": True,
            "source_entity_type": employee_type["id"],
            "target_entity_type": unit_type["id"],
        },
        headers=auth_headers,
    ).json()

    employee = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": employee_type["id"], "name": "Ahmed"},
        headers=auth_headers,
    ).json()
    unit = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": unit_type["id"], "name": "Unit A"},
        headers=auth_headers,
    ).json()

    edge_response = client.post(
        "/api/graph/domain/edges",
        json={
            "relationship_type_id": rel_type["id"],
            "source_entity_id": employee["id"],
            "target_entity_id": unit["id"],
            "attributes": {"since": "2026"},
        },
        headers=auth_headers,
    )
    assert edge_response.status_code == 201
    body = edge_response.json()
    assert body["type"] == rel_type["code"]
    assert body["source"] == employee["id"]
    assert body["target"] == unit["id"]
    assert body["attributes"]["since"] == "2026"


def test_create_edge_rejects_type_mismatch(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    employee_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"employee-{suffix}", "name": "Employee"},
        headers=auth_headers,
    ).json()
    unit_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"unit-{suffix}", "name": "Unit"},
        headers=auth_headers,
    ).json()

    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={
            "code": f"works_for-{suffix}",
            "name": "Works For",
            "is_directed": True,
            "source_entity_type": employee_type["id"],
            "target_entity_type": unit_type["id"],
        },
        headers=auth_headers,
    ).json()

    employee_a = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": employee_type["id"], "name": "Ahmed"},
        headers=auth_headers,
    ).json()
    employee_b = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": employee_type["id"], "name": "Sara"},
        headers=auth_headers,
    ).json()

    # target should be a Unit, not an Employee -- must be rejected
    edge_response = client.post(
        "/api/graph/domain/edges",
        json={
            "relationship_type_id": rel_type["id"],
            "source_entity_id": employee_a["id"],
            "target_entity_id": employee_b["id"],
            "attributes": {},
        },
        headers=auth_headers,
    )
    assert edge_response.status_code == 422


def test_create_edge_allows_unconstrained_relationship_type(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    any_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"thing-{suffix}", "name": "Thing"},
        headers=auth_headers,
    ).json()
    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={"code": f"related_to-{suffix}", "name": "Related To", "is_directed": False},
        headers=auth_headers,
    ).json()

    a = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "A"},
        headers=auth_headers,
    ).json()
    b = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "B"},
        headers=auth_headers,
    ).json()

    edge_response = client.post(
        "/api/graph/domain/edges",
        json={
            "relationship_type_id": rel_type["id"],
            "source_entity_id": a["id"],
            "target_entity_id": b["id"],
            "attributes": {},
        },
        headers=auth_headers,
    )
    assert edge_response.status_code == 201


def test_update_edge_replaces_attributes(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    any_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"thing-{suffix}", "name": "Thing"},
        headers=auth_headers,
    ).json()
    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={"code": f"related_to-{suffix}", "name": "Related To", "is_directed": False},
        headers=auth_headers,
    ).json()
    a = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "A"},
        headers=auth_headers,
    ).json()
    b = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "B"},
        headers=auth_headers,
    ).json()
    edge = client.post(
        "/api/graph/domain/edges",
        json={
            "relationship_type_id": rel_type["id"],
            "source_entity_id": a["id"],
            "target_entity_id": b["id"],
            "attributes": {"weight": 1},
        },
        headers=auth_headers,
    ).json()

    update_response = client.patch(
        f"/api/graph/domain/edges/{edge['id']}",
        json={"attributes": {"weight": 2}},
        headers=auth_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["attributes"]["weight"] == 2


def test_delete_edge_succeeds(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    any_type = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": f"thing-{suffix}", "name": "Thing"},
        headers=auth_headers,
    ).json()
    rel_type = client.post(
        "/api/domain/relationship_type/",
        json={"code": f"related_to-{suffix}", "name": "Related To", "is_directed": False},
        headers=auth_headers,
    ).json()
    a = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "A"},
        headers=auth_headers,
    ).json()
    b = client.post(
        "/api/graph/domain/nodes",
        json={"organization_id": organization_id, "entity_type_id": any_type["id"], "name": "B"},
        headers=auth_headers,
    ).json()
    edge = client.post(
        "/api/graph/domain/edges",
        json={
            "relationship_type_id": rel_type["id"],
            "source_entity_id": a["id"],
            "target_entity_id": b["id"],
            "attributes": {},
        },
        headers=auth_headers,
    ).json()

    delete_response = client.delete(f"/api/graph/domain/edges/{edge['id']}", headers=auth_headers)
    assert delete_response.status_code == 204
