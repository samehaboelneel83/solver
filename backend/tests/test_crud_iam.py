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


def test_unauthenticated_request_is_rejected():
    client = TestClient(app)
    response = client.get("/api/iam/organization/")
    assert response.status_code == 401


def test_list_rejects_out_of_bounds_pagination_params(auth_headers):
    client = TestClient(app)

    negative_limit = client.get("/api/iam/organization/?limit=-1", headers=auth_headers)
    assert negative_limit.status_code == 422

    negative_offset = client.get("/api/iam/organization/?offset=-1", headers=auth_headers)
    assert negative_offset.status_code == 422

    too_large_limit = client.get("/api/iam/organization/?limit=501", headers=auth_headers)
    assert too_large_limit.status_code == 422


def test_organization_crud_lifecycle(auth_headers):
    client = TestClient(app)
    code = f"acme-{uuid.uuid4().hex[:8]}"

    create_response = client.post(
        "/api/iam/organization/",
        json={"code": code, "name": "Acme Corp", "is_active": True},
        headers=auth_headers,
    )
    assert create_response.status_code == 201
    org = create_response.json()
    org_id = org["id"]
    assert org["code"] == code

    list_response = client.get("/api/iam/organization/", headers=auth_headers)
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] >= 1
    assert any(item["id"] == org_id for item in body["items"])

    get_response = client.get(f"/api/iam/organization/{org_id}", headers=auth_headers)
    assert get_response.status_code == 200
    assert get_response.json()["code"] == code

    update_response = client.put(
        f"/api/iam/organization/{org_id}",
        json={"name": "Acme Corporation"},
        headers=auth_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Acme Corporation"

    delete_response = client.delete(f"/api/iam/organization/{org_id}", headers=auth_headers)
    assert delete_response.status_code == 204

    get_after_delete = client.get(f"/api/iam/organization/{org_id}", headers=auth_headers)
    assert get_after_delete.status_code == 404


def test_organization_omitting_client_default_applies_orm_default(auth_headers):
    """is_active has a client-side ORM default of True. Omitting it must
    create an ACTIVE organization -- before the client-default fix the
    field was required on create, and the generic form's unchecked
    checkbox silently created every org as inactive."""
    client = TestClient(app)
    code = f"defaults-{uuid.uuid4().hex[:8]}"

    response = client.post(
        "/api/iam/organization/",
        json={"code": code, "name": "Defaults Corp"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["is_active"] is True

    client.delete(f"/api/iam/organization/{response.json()['id']}", headers=auth_headers)


def test_user_account_never_exposes_hashed_password(auth_headers):
    """hashed_password is `hidden`, so it must not appear in list or get
    responses -- the seeded admin's bcrypt hash was previously returned to
    any authenticated caller and rendered in the admin table."""
    client = TestClient(app)

    list_response = client.get("/api/iam/user_account/", headers=auth_headers)
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert items, "expected at least the seeded admin user"
    for item in items:
        assert "hashed_password" not in item
    assert any(item["username"] == "admin" for item in items)

    get_response = client.get(f"/api/iam/user_account/{items[0]['id']}", headers=auth_headers)
    assert get_response.status_code == 200
    assert "hashed_password" not in get_response.json()


def test_user_account_cannot_be_created_with_a_raw_hash(auth_headers):
    """`hidden` drops hashed_password from the Create schema, so Pydantic
    ignores it and the NOT NULL column rejects the insert at the database
    level. Task 1 (generic CRUD hardening) wraps that IntegrityError and
    returns a 409 with a helpful detail message instead of the raw 500
    that used to surface here."""
    client = TestClient(app)

    response = client.post(
        "/api/iam/user_account/",
        json={
            "username": f"probe-{uuid.uuid4().hex[:8]}",
            "display_name": "Probe",
            "hashed_password": "plaintext-oops",
        },
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert "required" in response.json()["detail"]
