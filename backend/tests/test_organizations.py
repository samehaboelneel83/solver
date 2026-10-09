"""The operator lists organizations and starts a new one, with its first administrator, in the platform itself."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from app.seed import seed_admin
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_the_operator_starts_an_organization_whose_admin_can_sign_in(db, client, auth_headers):  # noqa: F811
    seed_admin(db)
    code = f"acme-{uuid4().hex[:6]}"
    made = client.post("/api/v1/organizations", headers=auth_headers, json={
        "code": code, "name": "Acme", "admin_username": f"{code}.admin", "admin_password": "a long first secret",
        "tier": "standard"})
    assert made.status_code == 201, made.text
    listed = client.get("/api/v1/organizations", headers=auth_headers).json()["items"]
    mine = next(o for o in listed if o["code"] == code)
    assert mine["users"] == 1 and mine["quota"] is not None and not mine["is_operator"]
    assert listed[0]["is_operator"]
    # The new administrator signs in, inside the new organization only.
    token = client.post("/api/auth/login", data={"username": f"{code}.admin", "password": "a long first secret"})
    assert token.status_code == 200, token.text
    theirs = {"Authorization": f"Bearer {token.json()['access_token']}"}
    assert client.get("/api/v1/organizations", headers=theirs).status_code == 403
    # Taken names are refused, not overwritten; and the operator's own session still works afterwards.
    again = client.post("/api/v1/organizations", headers=auth_headers, json={
        "code": code, "name": "Again", "admin_username": "someone.new", "admin_password": "another long secret"})
    assert again.status_code == 409
    assert client.get("/api/v1/organizations", headers=auth_headers).status_code == 200
    assert db.execute(text("SELECT count(*) FROM iam.organization WHERE code = :c"), {"c": code}).scalar_one() == 1
