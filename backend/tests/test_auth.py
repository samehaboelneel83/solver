import pytest
from starlette.requests import Request
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.main import app
from app.seed import seed_admin


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    db = SessionLocal()
    seed_admin(db)
    db.close()


def test_login_with_seeded_admin_returns_token():
    settings = get_settings()
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_with_wrong_password_returns_401():
    settings = get_settings()
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": "wrong"},
    )
    assert response.status_code == 401


def test_get_current_user_accepts_valid_token():
    settings = get_settings()
    token = create_access_token(subject=settings.admin_username)
    db = SessionLocal()
    request = Request({"type": "http"})
    user = get_current_user(request, token=token, db=db)
    db.close()
    assert user.username == settings.admin_username
    # For the request's log line (`app.main.log_request`).
    assert request.state.org_id == str(user.organization_id)


def test_get_current_user_rejects_invalid_token():
    db = SessionLocal()
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(Request({"type": "http"}), token="garbage", db=db)
    db.close()
    assert exc_info.value.status_code == 401
