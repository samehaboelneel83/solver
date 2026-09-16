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


def test_entity_type_create(auth_headers, organization_id):
    client = TestClient(app)
    response = client.post(
        "/api/domain/entity_type/",
        json={
            "organization_id": organization_id,
            "code": "employee-a",
            "name": "Employee",
            "is_abstract": False,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["code"] == "employee-a"


def test_entity_attribute_and_relationship_chain(auth_headers, organization_id):
    client = TestClient(app)

    et_response = client.post(
        "/api/domain/entity_type/",
        json={
            "organization_id": organization_id,
            "code": "vehicle-a",
            "name": "Vehicle",
            "is_abstract": False,
        },
        headers=auth_headers,
    )
    assert et_response.status_code == 201
    entity_type_id = et_response.json()["id"]

    entity_response = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "code": "veh-1",
            "name": "Truck 1",
        },
        headers=auth_headers,
    )
    assert entity_response.status_code == 201
    entity_id = entity_response.json()["id"]

    attr_def_response = client.post(
        "/api/domain/attribute_definition/",
        json={
            "entity_type_id": entity_type_id,
            "code": "capacity_kg",
            "name": "Capacity (kg)",
            "data_type": "number",
            "is_required": False,
            "is_multi_value": False,
        },
        headers=auth_headers,
    )
    assert attr_def_response.status_code == 201
    attribute_id = attr_def_response.json()["id"]

    entity_attr_response = client.post(
        "/api/domain/entity_attribute/",
        json={"entity_id": entity_id, "attribute_id": attribute_id, "value_number": 1200},
        headers=auth_headers,
    )
    assert entity_attr_response.status_code == 201

    rel_type_response = client.post(
        "/api/domain/relationship_type/",
        json={
            "code": "assigned_to-a",
            "name": "Assigned To",
            "is_directed": True,
            "metadata_": {"note": "test-tag"},
        },
        headers=auth_headers,
    )
    assert rel_type_response.status_code == 201
    assert rel_type_response.json()["metadata_"] == {"note": "test-tag"}
    relationship_type_id = rel_type_response.json()["id"]

    rel_type_get_response = client.get(
        f"/api/domain/relationship_type/{relationship_type_id}", headers=auth_headers
    )
    assert rel_type_get_response.status_code == 200
    assert rel_type_get_response.json()["metadata_"] == {"note": "test-tag"}

    other_entity_response = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "code": "veh-2",
            "name": "Truck 2",
        },
        headers=auth_headers,
    )
    other_entity_id = other_entity_response.json()["id"]

    relationship_response = client.post(
        "/api/domain/relationship/",
        json={
            "relationship_type_id": relationship_type_id,
            "source_entity_id": entity_id,
            "target_entity_id": other_entity_id,
        },
        headers=auth_headers,
    )
    assert relationship_response.status_code == 201
