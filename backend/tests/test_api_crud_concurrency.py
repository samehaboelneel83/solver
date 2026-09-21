"""Ruling 42 on the generic CRUD factory -- a stale PUT is refused.

The factory tables (`domain`, `template`, `problem`, and the five
`iam` tables) share one PUT. The generic form sends every filled writable
field, so two clients opening the same row is the same silent overwrite
0010 closed for purpose-built forms. Migration 0023 gives each table an
`updated_at`; the factory compares it when the payload carries it.
`role_capability` joined them in 0026.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.concurrency import STALE_PREFIX
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin

CRUD_TABLES = (
    ("iam", "organization"),
    ("iam", "user_account"),
    ("iam", "role"),
    ("iam", "user_role"),
    ("iam", "role_capability"),
    ("public", "domain"),
    ("public", "template"),
    ("public", "problem"),
)


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


def _assert_stale_conflict(response) -> str:
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, str), response.text
    assert STALE_PREFIX in detail, detail
    return detail


def test_every_generic_crud_table_has_updated_at():
    db = SessionLocal()
    try:
        for schema, table in CRUD_TABLES:
            row = db.execute(
                text(
                    "SELECT data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t "
                    "AND column_name = 'updated_at'"
                ),
                {"s": schema, "t": table},
            ).first()
            assert row is not None, f"{schema}.{table}.updated_at is missing"
            assert row[0] == "timestamp with time zone", (schema, table, row[0])
            assert row[1] == "NO", (schema, table, row[1])
    finally:
        db.close()


def test_a_trigger_maintains_it_on_every_generic_crud_table():
    db = SessionLocal()
    try:
        for schema, table in CRUD_TABLES:
            reg = f"{schema}.{table}" if schema != "public" else table
            row = db.execute(
                text(
                    "SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger "
                    "WHERE tgrelid = cast(:t AS regclass) AND NOT tgisinternal "
                    "AND tgname = :name"
                ),
                {"t": reg, "name": f"{table}_set_updated_at"},
            ).first()
            assert row is not None, f"{reg} has no set_updated_at trigger"
            definition = row[1]
            assert "BEFORE INSERT OR UPDATE" in definition, definition
            assert "FOR EACH ROW" in definition, definition
    finally:
        db.close()


def test_the_domain_read_routes_carry_updated_at(auth_headers):
    client = TestClient(app)
    created = client.post(
        "/api/domain/",
        json={"name": f"crud-conc-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    domain_id = created.json()["id"]
    try:
        assert isinstance(created.json()["updated_at"], str)
        one = client.get(f"/api/domain/{domain_id}", headers=auth_headers)
        assert one.status_code == 200, one.text
        assert one.json()["updated_at"] == created.json()["updated_at"]
        listed = client.get("/api/domain/", headers=auth_headers)
        assert listed.status_code == 200, listed.text
        match = next(item for item in listed.json()["items"] if item["id"] == domain_id)
        assert match["updated_at"] == created.json()["updated_at"]
    finally:
        client.delete(f"/api/domain/{domain_id}", headers=auth_headers)


def test_a_stale_domain_save_is_refused(auth_headers):
    client = TestClient(app)
    created = client.post(
        "/api/domain/",
        json={"name": f"crud-stale-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    loaded = created.json()
    domain_id = loaded["id"]
    try:
        other = client.put(
            f"/api/domain/{domain_id}",
            json={"name": "changed by B"},
            headers=auth_headers,
        )
        assert other.status_code == 200, other.text

        refused = client.put(
            f"/api/domain/{domain_id}",
            json={"name": loaded["name"], "updated_at": loaded["updated_at"]},
            headers=auth_headers,
        )
        detail = _assert_stale_conflict(refused)
        assert "domain" in detail
        current = client.get(f"/api/domain/{domain_id}", headers=auth_headers).json()
        assert current["name"] == "changed by B"
    finally:
        client.delete(f"/api/domain/{domain_id}", headers=auth_headers)


def test_a_stale_organization_save_is_refused(auth_headers):
    """iam tables live in a schema and use UUID keys; the factory must
    lock and compare the same way as the public bigint tables."""
    client = TestClient(app)
    code = f"stale-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/iam/organization/",
        json={"code": code, "name": "Original", "is_active": True},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    loaded = created.json()
    org_id = loaded["id"]
    try:
        other = client.put(
            f"/api/iam/organization/{org_id}",
            json={"name": "changed by B"},
            headers=auth_headers,
        )
        assert other.status_code == 200, other.text

        refused = client.put(
            f"/api/iam/organization/{org_id}",
            json={"name": loaded["name"], "updated_at": loaded["updated_at"]},
            headers=auth_headers,
        )
        detail = _assert_stale_conflict(refused)
        assert "organization" in detail
        current = client.get(f"/api/iam/organization/{org_id}", headers=auth_headers).json()
        assert current["name"] == "changed by B"
    finally:
        client.delete(f"/api/iam/organization/{org_id}", headers=auth_headers)


def test_omitting_updated_at_on_a_generic_put_keeps_last_save_wins(auth_headers):
    client = TestClient(app)
    created = client.post(
        "/api/domain/",
        json={"name": f"crud-omit-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    domain_id = created.json()["id"]
    try:
        other = client.put(
            f"/api/domain/{domain_id}",
            json={"name": "first writer"},
            headers=auth_headers,
        )
        assert other.status_code == 200, other.text
        response = client.put(
            f"/api/domain/{domain_id}",
            json={"name": "second writer"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "second writer"
    finally:
        client.delete(f"/api/domain/{domain_id}", headers=auth_headers)


def test_updated_at_on_a_generic_put_is_compared_never_stored(auth_headers):
    client = TestClient(app)
    created = client.post(
        "/api/domain/",
        json={"name": f"crud-ts-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    loaded = created.json()
    domain_id = loaded["id"]
    try:
        saved = client.put(
            f"/api/domain/{domain_id}",
            json={"name": "renamed", "updated_at": loaded["updated_at"]},
            headers=auth_headers,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["name"] == "renamed"
        assert saved.json()["updated_at"] != loaded["updated_at"]
    finally:
        client.delete(f"/api/domain/{domain_id}", headers=auth_headers)
