"""FK-dropdown options endpoint and /api/meta/schema labelling.

Like test_crud_hardening.py, these exercise generic machinery rather than
any particular table, and were re-expressed against the four untouched
`iam` tables after migration 0006 dropped the domain.*/problem.* tables
they originally used. Cases with no `iam` equivalent are deleted rather
than weakened -- see the task report for the list.
"""

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
def admin_user_id(auth_headers):
    settings = get_settings()
    client = TestClient(app)
    response = client.get(
        f"/api/iam/user_account/?q={settings.admin_username}", headers=auth_headers
    )
    items = response.json()["items"]
    return next(item for item in items if item["username"] == settings.admin_username)["id"]


def _make_role(client, auth_headers, code: str, name: str | None = None) -> str:
    response = client.post(
        "/api/iam/role/",
        json={"code": code, "name": name if name is not None else code},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_options_route_matches_before_item_id_route(auth_headers):
    """Regression guard for router registration order: the options router
    must be included before crud_router in main.py, otherwise
    GET /api/{schema}/{table}/{item_id} matches "options" as a UUID
    path param first and this returns 422 instead of 200."""
    client = TestClient(app)

    response = client.get("/api/iam/role/options?q=x", headers=auth_headers)

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_options_search_returns_code_and_name_label(auth_headers):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    code = f"opt-{suffix}"

    _make_role(client, auth_headers, code, "Opt Name")

    response = client.get(f"/api/iam/role/options?q={code}", headers=auth_headers)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["label"] == f"{code} — Opt Name"


def test_options_ids_resolves_exact_rows(auth_headers):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    ids = [
        _make_role(client, auth_headers, f"opt-ids-{i}-{suffix}", f"Opt Ids {i}")
        for i in range(2)
    ]

    response = client.get(
        f"/api/iam/role/options?ids={ids[0]},{ids[1]}", headers=auth_headers
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

    ids = [
        _make_role(client, auth_headers, f"opt-bulk-{i}-{suffix}", f"Opt Bulk {i}")
        for i in range(60)
    ]

    response = client.get(
        f"/api/iam/role/options?ids={','.join(ids)}", headers=auth_headers
    )
    assert response.status_code == 200
    items = response.json()
    assert {item["id"] for item in items} == set(ids)
    assert len(items) == 60


def test_options_too_many_ids_returns_422(auth_headers):
    client = TestClient(app)
    ids = [str(uuid.uuid4()) for _ in range(201)]

    response = client.get(
        f"/api/iam/role/options?ids={','.join(ids)}", headers=auth_headers
    )
    assert response.status_code == 422


def test_options_invalid_id_returns_422(auth_headers):
    client = TestClient(app)

    response = client.get("/api/iam/role/options?ids=not-a-uuid", headers=auth_headers)
    assert response.status_code == 422


def test_user_role_label_uses_username_and_role_code(auth_headers, admin_user_id):
    """LABEL_OVERRIDES coverage: a join row with no code/name of its own
    must resolve to a composed label rather than falling back to its id.
    (Replaces the equivalent domain.hierarchy_node case, whose table
    migration 0006 dropped.)"""
    settings = get_settings()
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    role_code = f"lbl-role-{suffix}"

    role_id = _make_role(client, auth_headers, role_code, "Label Role")
    create_response = client.post(
        "/api/iam/user_role/",
        json={"user_id": admin_user_id, "role_id": role_id},
        headers=auth_headers,
    )
    assert create_response.status_code == 201
    user_role_id = create_response.json()["id"]

    options_response = client.get(
        f"/api/iam/user_role/options?ids={user_role_id}", headers=auth_headers
    )
    assert options_response.status_code == 200
    items = options_response.json()
    assert len(items) == 1
    assert items[0]["label"] == f"{settings.admin_username} / {role_code}"


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


def test_meta_reports_scalar_defaults_and_no_spurious_choices(auth_headers):
    """The positive `choices` half of this test is gone with its tables: no
    field on the four remaining registered tables matches meta.py's CHOICES
    map. What is still checked is the `default` reporting and that plain
    text fields report neither a default nor choices."""
    client = TestClient(app)

    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    organization_fields = {f["name"]: f for f in tables[("iam", "organization")]["fields"]}

    # Client-side ORM default=True is reported as a scalar default.
    assert organization_fields["is_active"]["default"] is True

    name_field = organization_fields["name"]
    assert not name_field.get("default")
    assert not name_field.get("choices")


def test_schema_reports_table_labels(auth_headers):
    client = TestClient(app)

    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    organization_table = tables[("iam", "organization")]
    assert organization_table["label"] == "Organization"
    assert organization_table["label_plural"] == "Organizations"

    user_account_table = tables[("iam", "user_account")]
    assert user_account_table["label"] == "User account"
    assert user_account_table["label_plural"] == "User accounts"


def test_schema_reports_field_label_overrides(auth_headers):
    client = TestClient(app)

    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    # FIELD_LABELS[(None, "organization_id")] -- would otherwise humanise to
    # "Organization" anyway, but this pins that the override is consulted.
    user_account_fields = {f["name"]: f for f in tables[("iam", "user_account")]["fields"]}
    assert user_account_fields["organization_id"]["label"] == "Organization"


def test_schema_field_label_falls_back_to_humanised_name(auth_headers):
    """Fields with no override in FIELD_LABELS still get a sensible label
    from humanise(): a single trailing "_id" is dropped, underscores
    become spaces, and only the first letter is capitalised."""
    client = TestClient(app)

    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    user_account_fields = {f["name"]: f for f in tables[("iam", "user_account")]["fields"]}
    assert user_account_fields["display_name"]["label"] == "Display name"
    assert user_account_fields["created_at"]["label"] == "Created at"

    user_role_fields = {f["name"]: f for f in tables[("iam", "user_role")]["fields"]}
    assert user_role_fields["user_id"]["label"] == "User"
    assert user_role_fields["role_id"]["label"] == "Role"

    organization_fields = {f["name"]: f for f in tables[("iam", "organization")]["fields"]}
    assert organization_fields["code"]["label"] == "Code"
    assert organization_fields["parent_id"]["label"] == "Parent"


def test_schema_field_label_drops_is_prefix(auth_headers):
    """A boolean column should read as the thing it describes ("Active"),
    not as a question ("Is active")."""
    client = TestClient(app)

    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    organization_fields = {f["name"]: f for f in tables[("iam", "organization")]["fields"]}
    assert organization_fields["is_active"]["label"] == "Active"

    user_account_fields = {f["name"]: f for f in tables[("iam", "user_account")]["fields"]}
    assert user_account_fields["is_active"]["label"] == "Active"


def test_schema_field_keeps_all_existing_keys(auth_headers):
    """Adding `label` must not disturb any key the frontend already
    depends on."""
    client = TestClient(app)

    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    code_field = next(
        f for f in tables[("iam", "organization")]["fields"] if f["name"] == "code"
    )
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
    role_before = by_table[("iam", "role")]
    assert isinstance(role_before["total"], int)
    assert role_before["label_plural"] == "Roles"

    suffix = uuid.uuid4().hex[:8]
    _make_role(client, auth_headers, f"cnt-{suffix}", f"Count Test {suffix}")

    response_after = client.get("/api/meta/counts", headers=auth_headers)
    assert response_after.status_code == 200
    by_table_after = {(c["schema"], c["table"]): c for c in response_after.json()}
    assert by_table_after[("iam", "role")]["total"] == role_before["total"] + 1
