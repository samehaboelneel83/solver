"""People and their roles on one page (UX audit A-1): who holds what, a user
with no role is plain to see, and roles are given and taken in one call."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.main import app
from tests.test_api_runs import auth_headers, ensure_admin_seeded  # noqa: F401


@pytest.fixture
def planner():
    db = SessionLocal()
    name = f"planner-{uuid.uuid4().hex[:6]}"
    user_id = db.execute(text(
        "INSERT INTO iam.user_account (id, username, display_name, hashed_password, organization_id)"
        " SELECT :id, :n, 'Planner', 'x', organization_id FROM iam.user_account WHERE username = 'admin' RETURNING id"),
        {"id": str(uuid.uuid4()), "n": name}).scalar_one()
    db.commit()
    yield {"id": str(user_id), "username": name}
    db.execute(text("DELETE FROM iam.user_role WHERE user_id = :u"), {"u": user_id})
    db.execute(text("DELETE FROM iam.user_account WHERE id = :u"), {"u": user_id})
    db.commit()
    db.close()


def _role(client, headers, code):
    return next(r for r in client.get("/api/v1/people", headers=headers).json()["roles"] if r["code"] == code)


def test_users_come_with_their_roles_and_roles_with_what_they_allow(planner, auth_headers):  # noqa: F811
    client = TestClient(app)
    body = client.get("/api/v1/people", headers=auth_headers).json()
    me = next(u for u in body["users"] if u["username"] == "admin")
    assert "admin" in [r["code"] for r in me["roles"]]
    new = next(u for u in body["users"] if u["username"] == planner["username"])
    assert new["roles"] == [] and new["display_name"] == "Planner" and "token_version" not in new
    planner_role = next(r for r in body["roles"] if r["code"] == "planner")
    assert "run.submit" in planner_role["capabilities"] and planner_role["users"] >= 0


def test_roles_are_set_all_at_once_and_audited(planner, auth_headers):  # noqa: F811
    client = TestClient(app)
    role = _role(client, auth_headers, "planner")
    viewer = _role(client, auth_headers, "viewer")
    url = f"/api/v1/people/{planner['id']}/roles"
    response = client.put(url, json={"role_ids": [role["id"], viewer["id"]]}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert sorted(r["code"] for r in response.json()["roles"]) == ["planner", "viewer"]
    response = client.put(url, json={"role_ids": [role["id"]]}, headers=auth_headers)
    assert [r["code"] for r in response.json()["roles"]] == ["planner"]
    assert _role(client, auth_headers, "planner")["users"] == role["users"] + 1
    db = SessionLocal()
    try:
        logged = db.execute(text("SELECT count(*) FROM iam.audit_event WHERE action = 'user.roles' AND object_id = :o"),
                            {"o": planner["id"]}).scalar_one()
    finally:
        db.close()
    assert logged == 2
    assert client.put(url, json={"role_ids": [str(uuid.uuid4())]}, headers=auth_headers).status_code == 422


def test_an_administrator_cannot_lock_themself_out(auth_headers):  # noqa: F811
    client = TestClient(app)
    me = next(u for u in client.get("/api/v1/people", headers=auth_headers).json()["users"] if u["username"] == "admin")
    planner_role = _role(client, auth_headers, "planner")
    refused = client.put(f"/api/v1/people/{me['id']}/roles", json={"role_ids": [planner_role["id"]]}, headers=auth_headers)
    assert refused.status_code == 422 and "your own way to manage people" in refused.text
    assert client.patch(f"/api/v1/people/{me['id']}", json={"is_active": False}, headers=auth_headers).status_code == 422


def test_deactivating_ends_the_users_sessions(planner, auth_headers):  # noqa: F811
    client = TestClient(app)
    url = f"/api/v1/people/{planner['id']}"
    response = client.patch(url, json={"is_active": False}, headers=auth_headers)
    assert response.status_code == 200 and response.json()["is_active"] is False
    db = SessionLocal()
    try:
        assert db.execute(text("SELECT token_version FROM iam.user_account WHERE id = :u"), {"u": planner["id"]}).scalar_one() == 1
    finally:
        db.close()
    assert client.patch(url, json={"is_active": True}, headers=auth_headers).json()["is_active"] is True
