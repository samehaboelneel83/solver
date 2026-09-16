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


def test_meta_schema_requires_auth():
    client = TestClient(app)
    response = client.get("/api/meta/schema")
    assert response.status_code == 401


def test_meta_schema_lists_all_31_tables(auth_headers):
    client = TestClient(app)
    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = response.json()
    assert len(tables) == 31


def test_meta_schema_flags_foreign_keys_and_readonly_id(auth_headers):
    client = TestClient(app)
    response = client.get("/api/meta/schema", headers=auth_headers)
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    entity = tables[("domain", "entity")]
    fields_by_name = {f["name"]: f for f in entity["fields"]}

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
    # Nullable column, optional on create because it's genuinely optional
    # input -- must remain writable (this is what the naive is_required()
    # fix would have incorrectly hidden from create forms).
    assert fields_by_name["description"]["writable"] is True
    # Required-on-create field -- sanity check that ordinary required
    # writable fields are unaffected by the nullability check.
    assert fields_by_name["is_active"]["writable"] is True
