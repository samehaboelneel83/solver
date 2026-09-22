"""API keys and the rate limit (migration 0035, target roadmap Phase 7).

Uses `test_tenancy`'s two organizations: A (the operator, with a queued run)
and B (a tenant whose administrator holds every capability).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _make_key(headers, **body) -> dict:
    response = TestClient(app).post("/api/v1/api-keys", json={"name": "ci", **body}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _as(key: dict) -> dict:
    return {"Authorization": f"Bearer {key['token']}"}


def test_a_key_acts_as_its_maker_and_its_token_is_shown_once(tenants):
    key = _make_key(tenants["b"])
    assert key["token"].startswith(f"sk_{key['prefix']}_")

    me = TestClient(app).get("/api/v1/me", headers=_as(key))
    assert me.status_code == 200, me.text
    assert me.json()["username"].startswith("admin-b-")

    listed = TestClient(app).get("/api/v1/api-keys", headers=tenants["b"]).json()["items"]
    assert [item["prefix"] for item in listed] == [key["prefix"]]
    assert "token" not in listed[0]


def test_a_key_can_do_only_what_it_was_given(tenants):
    key = _make_key(tenants["b"], capabilities=["run.submit"])
    client = TestClient(app)

    assert client.get("/api/v1/me", headers=_as(key)).json()["capabilities"] == ["run.submit"]
    assert client.post("/api/domain/", json={"name": "by-key"}, headers=_as(key)).status_code == 403
    assert client.get("/api/v1/runs", headers=_as(key)).status_code == 200


def test_a_key_cannot_have_a_capability_its_maker_lacks(tenants):
    response = TestClient(app).post(
        "/api/v1/api-keys", json={"name": "greedy", "capabilities": ["run.submit", "rule.everything"]}, headers=tenants["b"]
    )
    assert response.status_code == 403
    assert "rule.everything" in response.json()["detail"]


def test_a_key_cannot_make_or_revoke_keys(tenants):
    key = _make_key(tenants["b"])
    client = TestClient(app)
    assert client.post("/api/v1/api-keys", json={"name": "child"}, headers=_as(key)).status_code == 403
    assert client.delete(f"/api/v1/api-keys/{key['id']}", headers=_as(key)).status_code == 403


def test_a_key_loses_a_capability_the_moment_its_maker_does(tenants, db):
    key = _make_key(tenants["b"])
    client = TestClient(app)
    assert client.post("/api/domain/", json={"name": "before"}, headers=_as(key)).status_code == 201

    db.execute(
        text("DELETE FROM iam.user_role WHERE user_id = (SELECT user_id FROM iam.api_key WHERE id = :k)"),
        {"k": key["id"]},
    )
    db.commit()
    assert client.post("/api/domain/", json={"name": "after"}, headers=_as(key)).status_code == 403


def test_a_revoked_expired_or_wrong_key_is_refused(tenants, db):
    client = TestClient(app)
    revoked = _make_key(tenants["b"])
    assert client.delete(f"/api/v1/api-keys/{revoked['id']}", headers=tenants["b"]).status_code == 204
    assert client.get("/api/v1/me", headers=_as(revoked)).status_code == 401

    expired = _make_key(tenants["b"], expires_in_days=1)
    db.execute(
        text("UPDATE iam.api_key SET created_at = now() - interval '3 days', expires_at = now() - interval '1 day' WHERE id = :k"),
        {"k": expired["id"]},
    )
    db.commit()
    assert client.get("/api/v1/me", headers=_as(expired)).status_code == 401

    good = _make_key(tenants["b"])
    wrong = {**good, "token": good["token"][:-4] + "AAAA"}
    assert client.get("/api/v1/me", headers=_as(wrong)).status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer sk_nonsense"}).status_code == 401


def test_a_key_sees_only_its_organization(tenants):
    key = _make_key(tenants["b"])
    client = TestClient(app)
    assert client.get(f"/api/v1/runs/{tenants['run_a']}", headers=_as(key)).status_code == 404
    assert client.get("/api/v1/runs", headers=_as(key)).json()["total"] == 0
    # ... and A cannot see B's keys.
    assert client.get("/api/v1/api-keys", headers=tenants["a"]).json()["items"] == []


def test_using_a_key_is_recorded(tenants, db):
    key = _make_key(tenants["b"])
    TestClient(app).get("/api/v1/me", headers=_as(key))
    used = db.execute(text("SELECT last_used_at FROM iam.api_key WHERE id = :k"), {"k": key["id"]}).scalar_one()
    assert used is not None


# -- the rate limit ------------------------------------------------------------------------


def test_over_the_rate_limit_is_a_429_with_retry_after(tenants, db):
    client = TestClient(app)
    assert client.put(
        f"/api/v1/organizations/{tenants['org_b']}/quota", json={"requests_per_minute": 2}, headers=tenants["a"]
    ).status_code == 200
    key = _make_key(tenants["b"])

    assert client.get("/api/v1/me", headers=_as(key)).status_code == 200
    assert client.get("/api/v1/me", headers=_as(key)).status_code == 200
    limited = client.get("/api/v1/me", headers=_as(key))
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["Retry-After"]) <= 30

    # Refused requests spend nothing: once the bucket has refilled, the
    # next request goes through however often the caller retried.
    client.get("/api/v1/me", headers=_as(key))
    db.execute(
        text("UPDATE iam.rate_bucket SET refilled_at = now() - interval '31 seconds' WHERE caller = :c"),
        {"c": f"key:{key['id']}"},
    )
    db.commit()
    assert client.get("/api/v1/me", headers=_as(key)).status_code == 200


def test_the_limit_is_per_caller_and_absent_without_a_quota(tenants):
    client = TestClient(app)
    # A has no quota row: no limit however many requests.
    for _ in range(5):
        assert client.get("/api/v1/me", headers=tenants["a"]).status_code == 200
    first, second = _make_key(tenants["b"]), _make_key(tenants["b"])
    client.put(
        f"/api/v1/organizations/{tenants['org_b']}/quota", json={"requests_per_minute": 1}, headers=tenants["a"]
    )
    assert client.get("/api/v1/me", headers=_as(first)).status_code == 200
    assert client.get("/api/v1/me", headers=_as(second)).status_code == 200
    assert client.get("/api/v1/me", headers=_as(first)).status_code == 429
