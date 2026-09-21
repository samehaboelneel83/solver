"""Relationship-type attribute definitions -- the same `attribute_def` object.

A relationship's `attrs` JSONB had no declared type, so the graph panel
edited it as a raw JSON box. Migration 0024 lets `attribute_def` belong to
a `relationship_type` instead of an `entity_type` (exactly one owner).
When a type has no defs, attrs stay free-form -- concurrency tests and the
snapshot fixture that send `{"weight": 1}` keep working. Once a def exists,
the same trigger kinds as `entity_validate` refuse a bad write.
"""

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
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def domain_id(auth_headers):
    client = TestClient(app)
    response = client.post(
        "/api/domain/",
        json={"name": f"rel-attr-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    created_id = response.json()["id"]
    try:
        yield created_id
    finally:
        client.delete(f"/api/domain/{created_id}", headers=auth_headers)


@pytest.fixture
def types(auth_headers, domain_id):
    client = TestClient(app)
    made = {}
    for name, role in (("unit", "org"), ("employee", "agent")):
        response = client.post(
            "/api/v1/entity-types",
            json={"domain_id": domain_id, "name": name, "role": role},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        made[name] = response.json()["id"]
    return made


def _rel_type(client, auth_headers, domain_id, types) -> int:
    response = client.post(
        "/api/v1/relationship-types",
        json={
            "domain_id": domain_id,
            "name": "works_in",
            "from_type_id": types["employee"],
            "to_type_id": types["unit"],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _entity(client, auth_headers, entity_type_id, key) -> int:
    response = client.post(
        "/api/v1/entities",
        json={"entity_type_id": entity_type_id, "key": key, "attrs": {}},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _trigger_error(response) -> dict:
    assert response.status_code == 422, response.text
    detail = response.json().get("detail")
    assert isinstance(detail, list) and len(detail) == 1, response.text
    entry = detail[0]
    assert set(entry) == {"type", "loc", "msg", "kind"}, entry
    loc = [str(part) for part in entry["loc"]]
    assert loc[0] == "body", entry
    return {"message": entry["msg"], "field": loc[1] if len(loc) > 1 else None, "kind": entry["kind"]}


def test_a_relationship_type_read_carries_attributes(auth_headers, domain_id, types):
    client = TestClient(app)
    rel_type_id = _rel_type(client, auth_headers, domain_id, types)
    created = client.get(f"/api/v1/relationship-types/{rel_type_id}", headers=auth_headers)
    assert created.status_code == 200, created.text
    assert created.json()["attributes"] == []

    added = client.post(
        f"/api/v1/relationship-types/{rel_type_id}/attributes",
        json={"name": "weight", "data_type": "integer"},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["name"] == "weight"
    assert body["data_type"] == "integer"
    assert body["relationship_type_id"] == rel_type_id
    assert body["entity_type_id"] is None

    listed = client.get(f"/api/v1/relationship-types/{rel_type_id}", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    names = [a["name"] for a in listed.json()["attributes"]]
    assert names == ["weight"]


def test_a_relationship_attribute_is_not_an_entity_attribute(auth_headers, domain_id, types):
    client = TestClient(app)
    rel_type_id = _rel_type(client, auth_headers, domain_id, types)
    client.post(
        f"/api/v1/relationship-types/{rel_type_id}/attributes",
        json={"name": "weight", "data_type": "integer"},
        headers=auth_headers,
    )
    entity_type = client.get(f"/api/v1/entity-types/{types['employee']}", headers=auth_headers)
    assert entity_type.status_code == 200, entity_type.text
    assert entity_type.json()["attributes"] == []


def test_free_form_attrs_stay_legal_until_a_def_exists(auth_headers, domain_id, types):
    client = TestClient(app)
    rel_type_id = _rel_type(client, auth_headers, domain_id, types)
    frm = _entity(client, auth_headers, types["employee"], "ahmed")
    to = _entity(client, auth_headers, types["unit"], "hq")
    created = client.post(
        "/api/v1/relationships",
        json={
            "relationship_type_id": rel_type_id,
            "from_entity_id": frm,
            "to_entity_id": to,
            "attrs": {"weight": 1, "note": "anything"},
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["attrs"] == {"weight": 1, "note": "anything"}


def test_unknown_relationship_attribute_is_422_once_a_def_exists(auth_headers, domain_id, types):
    client = TestClient(app)
    rel_type_id = _rel_type(client, auth_headers, domain_id, types)
    added = client.post(
        f"/api/v1/relationship-types/{rel_type_id}/attributes",
        json={"name": "weight", "data_type": "integer"},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text
    frm = _entity(client, auth_headers, types["employee"], "ahmed")
    to = _entity(client, auth_headers, types["unit"], "hq")
    refused = client.post(
        "/api/v1/relationships",
        json={
            "relationship_type_id": rel_type_id,
            "from_entity_id": frm,
            "to_entity_id": to,
            "attrs": {"nope": 1},
        },
        headers=auth_headers,
    )
    detail = _trigger_error(refused)
    assert detail["kind"] == "unknown_attribute"
    assert detail["field"] == "nope"


def test_a_typed_relationship_attr_round_trips_and_materialises_a_default(
    auth_headers, domain_id, types
):
    client = TestClient(app)
    rel_type_id = _rel_type(client, auth_headers, domain_id, types)
    added = client.post(
        f"/api/v1/relationship-types/{rel_type_id}/attributes",
        json={"name": "weight", "data_type": "integer", "default_value": 1},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text
    frm = _entity(client, auth_headers, types["employee"], "ahmed")
    to = _entity(client, auth_headers, types["unit"], "hq")
    created = client.post(
        "/api/v1/relationships",
        json={"relationship_type_id": rel_type_id, "from_entity_id": frm, "to_entity_id": to, "attrs": {}},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["attrs"] == {"weight": 1}

    saved = client.patch(
        f"/api/v1/relationships/{created.json()['id']}",
        json={"attrs": {"weight": 5}},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["attrs"] == {"weight": 5}


def test_a_wrong_type_on_a_relationship_attr_is_422(auth_headers, domain_id, types):
    client = TestClient(app)
    rel_type_id = _rel_type(client, auth_headers, domain_id, types)
    client.post(
        f"/api/v1/relationship-types/{rel_type_id}/attributes",
        json={"name": "weight", "data_type": "integer"},
        headers=auth_headers,
    )
    frm = _entity(client, auth_headers, types["employee"], "ahmed")
    to = _entity(client, auth_headers, types["unit"], "hq")
    refused = client.post(
        "/api/v1/relationships",
        json={
            "relationship_type_id": rel_type_id,
            "from_entity_id": frm,
            "to_entity_id": to,
            "attrs": {"weight": "heavy"},
        },
        headers=auth_headers,
    )
    detail = _trigger_error(refused)
    assert detail["kind"] == "attribute_type"
    assert detail["field"] == "weight"
