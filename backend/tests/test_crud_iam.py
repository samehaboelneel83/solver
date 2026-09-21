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


def test_user_account_is_created_with_a_password(auth_headers):
    """The admin form sends `password`. The factory hashes it; neither the
    plaintext nor hashed_password comes back."""
    client = TestClient(app)
    username = f"planner-{uuid.uuid4().hex[:8]}"
    password = "change-me-planner"

    response = client.post(
        "/api/iam/user_account/",
        json={"username": username, "display_name": "Planner", "password": password},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == username
    assert "password" not in body
    assert "hashed_password" not in body

    login = client.post("/api/auth/login", data={"username": username, "password": password})
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]

    client.delete(f"/api/iam/user_account/{body['id']}", headers=auth_headers)


def test_user_account_create_without_password_is_422(auth_headers):
    client = TestClient(app)
    response = client.post(
        "/api/iam/user_account/",
        json={"username": f"nopw-{uuid.uuid4().hex[:8]}", "display_name": "No Password"},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
    locs = [tuple(err.get("loc", ())) for err in response.json()["detail"]]
    assert any("password" in loc for loc in locs), response.text


def test_user_account_empty_password_is_422(auth_headers):
    client = TestClient(app)
    response = client.post(
        "/api/iam/user_account/",
        json={"username": f"blank-{uuid.uuid4().hex[:8]}", "password": "   "},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
    locs = [tuple(err.get("loc", ())) for err in response.json()["detail"]]
    assert any("password" in loc for loc in locs), response.text


def test_user_account_cannot_be_created_with_a_raw_hash(auth_headers):
    """hashed_password stays hidden. Sending it does not create a user, and
    a create that also carries password hashes that password -- the raw
    string is never stored as the hash."""
    client = TestClient(app)
    username = f"probe-{uuid.uuid4().hex[:8]}"
    password = "the-real-password"

    ignored = client.post(
        "/api/iam/user_account/",
        json={
            "username": username,
            "display_name": "Probe",
            "hashed_password": "plaintext-oops",
        },
        headers=auth_headers,
    )
    assert ignored.status_code == 422, ignored.text

    created = client.post(
        "/api/iam/user_account/",
        json={
            "username": username,
            "display_name": "Probe",
            "password": password,
            "hashed_password": "plaintext-oops",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert client.post(
        "/api/auth/login", data={"username": username, "password": password}
    ).status_code == 200
    assert client.post(
        "/api/auth/login", data={"username": username, "password": "plaintext-oops"}
    ).status_code == 401

    client.delete(f"/api/iam/user_account/{created.json()['id']}", headers=auth_headers)


def test_user_account_patch_password_changes_login(auth_headers):
    client = TestClient(app)
    username = f"reset-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/iam/user_account/",
        json={"username": username, "password": "first-password"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    changed = client.put(
        f"/api/iam/user_account/{user_id}",
        json={"password": "second-password"},
        headers=auth_headers,
    )
    assert changed.status_code == 200, changed.text
    assert "password" not in changed.json()
    assert client.post(
        "/api/auth/login", data={"username": username, "password": "second-password"}
    ).status_code == 200
    assert client.post(
        "/api/auth/login", data={"username": username, "password": "first-password"}
    ).status_code == 401

    client.delete(f"/api/iam/user_account/{user_id}", headers=auth_headers)


def test_user_account_patch_without_password_keeps_login(auth_headers):
    client = TestClient(app)
    username = f"keep-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/iam/user_account/",
        json={"username": username, "display_name": "Keep", "password": "same-password"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    renamed = client.put(
        f"/api/iam/user_account/{user_id}",
        json={"display_name": "Kept"},
        headers=auth_headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["display_name"] == "Kept"
    assert client.post(
        "/api/auth/login", data={"username": username, "password": "same-password"}
    ).status_code == 200

    client.delete(f"/api/iam/user_account/{user_id}", headers=auth_headers)
