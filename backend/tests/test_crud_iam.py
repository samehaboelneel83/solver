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

    create_response = client.post(
        "/api/iam/organization/",
        json={"code": "acme", "name": "Acme Corp", "is_active": True},
        headers=auth_headers,
    )
    assert create_response.status_code == 201
    org = create_response.json()
    org_id = org["id"]
    assert org["code"] == "acme"

    list_response = client.get("/api/iam/organization/", headers=auth_headers)
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] >= 1
    assert any(item["id"] == org_id for item in body["items"])

    get_response = client.get(f"/api/iam/organization/{org_id}", headers=auth_headers)
    assert get_response.status_code == 200
    assert get_response.json()["code"] == "acme"

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
