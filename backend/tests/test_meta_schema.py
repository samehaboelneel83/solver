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


def test_meta_schema_requires_auth():
    client = TestClient(app)
    response = client.get("/api/meta/schema")
    assert response.status_code == 401


def test_meta_schema_lists_exactly_the_registered_tables(auth_headers):
    """Was "lists all 31 tables". Schema v1 dropped the 27 domain.*/problem.*
    tables (migration 0006/0007) and replaced them with the four untouched
    `iam` tables plus three flat v1 tables driven through the generic
    factory (`domain`, `template`, `problem`); every other v1 table gets a
    purpose-built router or (for the four IMMUTABLE_TABLES) none at all.
    Pinning the exact set is stronger than pinning the count."""
    client = TestClient(app)
    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = response.json()

    assert len(tables) == len(TABLE_REGISTRY)
    assert {(t["schema"], t["table"]) for t in tables} == {
        ("iam", "organization"),
        ("iam", "user_account"),
        ("iam", "role"),
        ("iam", "user_role"),
        ("iam", "role_capability"),
        ("public", "domain"),
        ("public", "template"),
        ("public", "problem"),
    }


def test_meta_schema_flags_foreign_keys_and_readonly_id(auth_headers):
    client = TestClient(app)
    response = client.get("/api/meta/schema", headers=auth_headers)
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    user_account = tables[("iam", "user_account")]
    fields_by_name = {f["name"]: f for f in user_account["fields"]}

    assert fields_by_name["id"]["writable"] is False
    assert fields_by_name["organization_id"]["is_fk"] is True
    assert fields_by_name["organization_id"]["fk_table"] == "iam.organization"


def test_meta_schema_writable_distinguishes_server_default_from_nullable(auth_headers):
    client = TestClient(app)
    response = client.get("/api/meta/schema", headers=auth_headers)
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    organization = tables[("iam", "organization")]
    fields_by_name = {f["name"]: f for f in organization["fields"]}

    # NOT NULL column, optional on create only because it's server-generated
    # (server_default, Task 11) -- must not be writable, or the frontend
    # would render an editable timestamp input on create.
    assert fields_by_name["created_at"]["writable"] is False
    # Migration 0023: same demotion as created_at — the form must not
    # render a timestamp control; EntityDetail attaches the loaded value.
    assert "updated_at" in fields_by_name
    assert fields_by_name["updated_at"]["writable"] is False
    # Nullable column, optional on create because it's genuinely optional
    # input -- must remain writable (this is what the naive is_required()
    # fix would have incorrectly hidden from create forms).
    assert fields_by_name["description"]["writable"] is True
    # Writable field -- sanity check that ordinary writable fields are
    # unaffected by the nullability check.
    assert fields_by_name["is_active"]["writable"] is True


def test_meta_schema_keeps_client_default_fields_writable(auth_headers):
    """A NOT NULL column with a client-side ORM default (is_active) is
    optional on create -- but unlike a server-generated column it must stay
    writable, or the form could never set it. Regression guard for the
    interaction between the generator's client-default handling and
    meta.py's server-generated demotion."""
    client = TestClient(app)
    response = client.get("/api/meta/schema", headers=auth_headers)
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    fields_by_name = {f["name"]: f for f in tables[("iam", "organization")]["fields"]}

    # default=True on the ORM column -> optional on create, still writable.
    assert fields_by_name["is_active"]["required"] is False
    assert fields_by_name["is_active"]["writable"] is True
    # server_default=func.now() -> optional on create AND not writable.
    # (unchanged behaviour: this is the case meta.py must still demote)
    assert fields_by_name["created_at"]["writable"] is False


def test_meta_schema_hides_hidden_fields_entirely(auth_headers):
    """hashed_password is passed as `hidden`, so it must not appear in the
    metadata at all -- the form offers `password` instead, write-only."""
    client = TestClient(app)
    response = client.get("/api/meta/schema", headers=auth_headers)
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    user_account = tables[("iam", "user_account")]
    field_names = {f["name"] for f in user_account["fields"]}
    fields_by_name = {f["name"]: f for f in user_account["fields"]}

    assert "hashed_password" not in field_names
    assert "username" in field_names
    password = fields_by_name["password"]
    assert password["writable"] is True
    assert password["write_only"] is True
    assert password["required"] is True
    assert password["type"] == "password"
