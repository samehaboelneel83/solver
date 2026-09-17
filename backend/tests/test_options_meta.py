import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.crud.registry import TABLE_REGISTRY
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


def test_options_route_matches_before_item_id_route(auth_headers):
    """Regression guard for router registration order: the options router
    must be included before crud_router in main.py, otherwise
    GET /api/{schema}/{table}/{item_id} matches "options" as a UUID
    path param first and this returns 422 instead of 200."""
    client = TestClient(app)

    response = client.get("/api/domain/entity_type/options?q=x", headers=auth_headers)

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_options_search_returns_code_and_name_label(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    code = f"opt-{suffix}"

    create_response = client.post(
        "/api/domain/entity_type/",
        json={
            "organization_id": organization_id,
            "code": code,
            "name": "Opt Name",
            "is_abstract": False,
        },
        headers=auth_headers,
    )
    assert create_response.status_code == 201

    response = client.get(f"/api/domain/entity_type/options?q={code}", headers=auth_headers)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["label"] == f"{code} — Opt Name"


def test_options_ids_resolves_exact_rows(auth_headers):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    ids = []
    for i in range(2):
        response = client.post(
            "/api/domain/role_type/",
            json={"code": f"opt-ids-{i}-{suffix}", "name": f"Opt Ids {i}"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])

    response = client.get(
        f"/api/domain/role_type/options?ids={ids[0]},{ids[1]}", headers=auth_headers
    )
    assert response.status_code == 200
    items = response.json()
    assert {item["id"] for item in items} == set(ids)


def test_options_ids_over_default_limit_returns_all(auth_headers):
    """`ids` must return exactly the requested rows, not just the first
    `limit` (default 50) of them -- Task 3's frontend batches every
    distinct FK id on a page into one `ids=` call, so silently truncating
    at 50 would leave later rows showing raw UUIDs instead of labels."""
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    ids = []
    for i in range(60):
        response = client.post(
            "/api/domain/role_type/",
            json={"code": f"opt-bulk-{i}-{suffix}", "name": f"Opt Bulk {i}"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])

    response = client.get(
        f"/api/domain/role_type/options?ids={','.join(ids)}", headers=auth_headers
    )
    assert response.status_code == 200
    items = response.json()
    assert {item["id"] for item in items} == set(ids)
    assert len(items) == 60


def test_options_too_many_ids_returns_422(auth_headers):
    client = TestClient(app)
    ids = [str(uuid.uuid4()) for _ in range(201)]

    response = client.get(
        f"/api/domain/role_type/options?ids={','.join(ids)}", headers=auth_headers
    )
    assert response.status_code == 422


def test_options_invalid_id_returns_422(auth_headers):
    client = TestClient(app)

    response = client.get(
        "/api/domain/role_type/options?ids=not-a-uuid", headers=auth_headers
    )
    assert response.status_code == 422


def test_hierarchy_node_label_uses_entity_and_hierarchy_names(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    et_response = client.post(
        "/api/domain/entity_type/",
        json={
            "organization_id": organization_id,
            "code": f"hn-type-{suffix}",
            "name": "HN Type",
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
            "code": f"hn-entity-{suffix}",
            "name": f"HN Entity {suffix}",
        },
        headers=auth_headers,
    )
    assert entity_response.status_code == 201
    entity_id = entity_response.json()["id"]

    hierarchy_response = client.post(
        "/api/domain/hierarchy/",
        json={
            "organization_id": organization_id,
            "code": f"hn-hier-{suffix}",
            "name": f"HN Hierarchy {suffix}",
        },
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
    node_id = node_response.json()["id"]

    options_response = client.get(
        f"/api/domain/hierarchy_node/options?ids={node_id}", headers=auth_headers
    )
    assert options_response.status_code == 200
    items = options_response.json()
    assert len(items) == 1
    assert items[0]["label"] == f"HN Entity {suffix} in HN Hierarchy {suffix}"


def test_user_account_label_is_username(auth_headers):
    # hashed_password is `hidden=` on UserAccount's create schema (by
    # design -- see test_list_filter_and_order_reject_hidden_columns in
    # test_crud_hardening.py), so it can't be set through the CRUD POST
    # endpoint. Insert the row directly to get a user with no code/name,
    # to exercise label_for()'s username fallback.
    from app.models.iam import UserAccount

    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    username = f"opt-user-{suffix}"

    db = SessionLocal()
    try:
        user = UserAccount(username=username, hashed_password="not-a-real-hash")
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = str(user.id)
    finally:
        db.close()

    options_response = client.get(
        f"/api/iam/user_account/options?ids={user_id}", headers=auth_headers
    )
    assert options_response.status_code == 200
    items = options_response.json()
    assert len(items) == 1
    assert items[0]["label"] == username


def test_meta_reports_defaults_and_choices(auth_headers):
    client = TestClient(app)

    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    problem_fields = {f["name"]: f for f in tables[("problem", "problem")]["fields"]}
    status_field = problem_fields["status"]
    assert status_field["default"] == "DRAFT"
    assert "ACTIVE" in status_field["choices"]

    attribute_definition_fields = {
        f["name"]: f for f in tables[("domain", "attribute_definition")]["fields"]
    }
    data_type_field = attribute_definition_fields["data_type"]
    assert "boolean" in data_type_field["choices"]

    name_field = problem_fields["name"]
    assert not name_field.get("default")
    assert not name_field.get("choices")


def test_schema_reports_table_labels(auth_headers):
    client = TestClient(app)

    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    entity_type_table = tables[("domain", "entity_type")]
    assert entity_type_table["label"] == "Entity type"
    assert entity_type_table["label_plural"] == "Entity types"

    # Irregular plurals must not just tack an "s" on.
    entity_table = tables[("domain", "entity")]
    assert entity_table["label"] == "Entity"
    assert entity_table["label_plural"] == "Entities"

    hierarchy_table = tables[("domain", "hierarchy")]
    assert hierarchy_table["label"] == "Hierarchy"
    assert hierarchy_table["label_plural"] == "Hierarchies"


def test_schema_reports_field_label_overrides(auth_headers):
    client = TestClient(app)

    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    relationship_fields = {f["name"]: f for f in tables[("domain", "relationship")]["fields"]}
    assert relationship_fields["source_entity_id"]["label"] == "From"
    assert relationship_fields["target_entity_id"]["label"] == "To"

    entity_fields = {f["name"]: f for f in tables[("domain", "entity")]["fields"]}
    assert entity_fields["entity_type_id"]["label"] == "Type"
    assert entity_fields["organization_id"]["label"] == "Organization"

    entity_type_fields = {f["name"]: f for f in tables[("domain", "entity_type")]["fields"]}
    assert entity_type_fields["is_abstract"]["label"] == "Abstract type"


def test_schema_field_label_falls_back_to_humanised_name(auth_headers):
    """Fields with no override in FIELD_LABELS still get a sensible label
    from humanise(): a single trailing "_id" is dropped, underscores
    become spaces, and only the first letter is capitalised."""
    client = TestClient(app)

    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    relationship_fields = {f["name"]: f for f in tables[("domain", "relationship")]["fields"]}
    assert relationship_fields["valid_from"]["label"] == "Valid from"
    assert relationship_fields["valid_to"]["label"] == "Valid to"

    entity_type_fields = {f["name"]: f for f in tables[("domain", "entity_type")]["fields"]}
    assert entity_type_fields["parent_type_id"]["label"] == "Parent type"
    assert entity_type_fields["code"]["label"] == "Code"


def test_schema_field_keeps_all_existing_keys(auth_headers):
    """Adding `label` must not disturb any key the frontend already
    depends on."""
    client = TestClient(app)

    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    code_field = next(f for f in tables[("domain", "entity_type")]["fields"] if f["name"] == "code")
    expected_keys = {
        "name",
        "type",
        "required",
        "writable",
        "is_fk",
        "fk_table",
        "default",
        "choices",
        "label_field",
        "label",
    }
    assert set(code_field.keys()) == expected_keys


def test_meta_counts_requires_auth():
    client = TestClient(app)

    response = client.get("/api/meta/counts")

    assert response.status_code == 401


def test_meta_counts_reports_one_entry_per_table_and_increments(auth_headers):
    client = TestClient(app)

    response = client.get("/api/meta/counts", headers=auth_headers)
    assert response.status_code == 200
    counts = response.json()
    assert len(counts) == len(TABLE_REGISTRY)

    by_table = {(c["schema"], c["table"]): c for c in counts}
    role_type_before = by_table[("domain", "role_type")]
    assert isinstance(role_type_before["total"], int)
    assert role_type_before["label_plural"] == "Role types"

    suffix = uuid.uuid4().hex[:8]
    create_response = client.post(
        "/api/domain/role_type/",
        json={"code": f"cnt-{suffix}", "name": f"Count Test {suffix}"},
        headers=auth_headers,
    )
    assert create_response.status_code == 201

    response_after = client.get("/api/meta/counts", headers=auth_headers)
    assert response_after.status_code == 200
    by_table_after = {(c["schema"], c["table"]): c for c in response_after.json()}
    assert by_table_after[("domain", "role_type")]["total"] == role_type_before["total"] + 1
