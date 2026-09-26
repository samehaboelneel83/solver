"""OIDC SSO (queue R35)."""

from __future__ import annotations

from sqlalchemy import text

from app import sso
from app.core.security import create_access_token, decode_access_token
from app.seed import seed_admin
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_put_provider_encrypts_secret_and_begin_login(db, client, auth_headers):
    seed_admin(db)
    org = db.execute(text("SELECT id FROM iam.organization WHERE code = 'default'")).scalar_one()
    response = client.put(
        "/api/v1/sso/provider",
        headers=auth_headers,
        json={
            "issuer": "https://idp.example.com",
            "client_id": "solver-app",
            "client_secret": "super-secret",
            "role_map": {"Admins": "admin"},
            "sso_required": False,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is True
    assert body["issuer"] == "https://idp.example.com"
    assert "client_secret" not in body
    enc = db.execute(
        text("SELECT client_secret_enc FROM iam.oidc_provider WHERE organization_id = :o"),
        {"o": org},
    ).scalar_one()
    assert enc and enc != "super-secret"
    assert sso.decrypt_secret(enc) == "super-secret"

    start = client.get(
        f"/api/v1/sso/login/{org}",
        params={"redirect_uri": "http://localhost/callback"},
    )
    assert start.status_code == 200, start.text
    assert "authorization_url" in start.json()
    assert "code_challenge" in start.json()["authorization_url"]


def test_sso_required_blocks_password_login(db, client, auth_headers):
    seed_admin(db)
    from app.core.config import get_settings

    client.put(
        "/api/v1/sso/provider",
        headers=auth_headers,
        json={
            "issuer": "https://idp.example.com",
            "client_id": "solver-app",
            "client_secret": "x",
            "sso_required": True,
        },
    )
    settings = get_settings()
    refused = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    assert refused.status_code == 401
    assert "single sign-on" in refused.json()["detail"]
    # Restore password login for later tests in this session — auth_headers re-logins.
    db.execute(text("UPDATE iam.oidc_provider SET sso_required = false"))
    db.commit()
    settings = get_settings()
    assert (
        client.post(
            "/api/auth/login",
            data={"username": settings.admin_username, "password": settings.admin_password},
        ).status_code
        == 200
    )


def test_callback_jit_user_with_stubbed_exchange(db, client, auth_headers, monkeypatch):
    seed_admin(db)
    org = db.execute(text("SELECT id FROM iam.organization WHERE code = 'default'")).scalar_one()
    client.put(
        "/api/v1/sso/provider",
        headers=auth_headers,
        json={
            "issuer": "https://idp.example.com",
            "client_id": "solver-app",
            "client_secret": "x",
            "role_map": {"Admins": "admin"},
        },
    )
    start = client.get(
        f"/api/v1/sso/login/{org}",
        params={"redirect_uri": "http://localhost/callback"},
    )
    state = start.json()["state"]

    def fake_exchange(provider, *, code, redirect_uri, code_verifier, http_post=None):
        return {
            "token": {"access_token": "t"},
            "claims": {
                "sub": "oidc-sub-1",
                "email": "alice@example.com",
                "preferred_username": "alice",
                "name": "Alice",
                "groups": ["Admins"],
            },
        }

    monkeypatch.setattr(sso, "exchange_code", fake_exchange)
    # Re-insert pending state consumed by begin? begin already stored it; callback uses it.
    # The TestClient call to login already put state in _pending.
    from app.api import sso as sso_api

    assert state in sso_api._pending
    cb = client.get("/api/v1/sso/callback", params={"code": "abc", "state": state})
    assert cb.status_code == 200, cb.text
    token = cb.json()["access_token"]
    payload = decode_access_token(token)
    assert payload["sub"] == "alice" or payload["sub"].startswith("alice")
    user = db.execute(
        text("SELECT external_sub, is_active FROM iam.user_account WHERE external_sub = 'oidc-sub-1'")
    ).mappings().one()
    assert user["is_active"] is True
