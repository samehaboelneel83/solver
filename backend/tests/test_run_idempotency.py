"""Run submit Idempotency-Key (OAAS S02)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.seed import seed_admin, seed_workforce_demo
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    session = SessionLocal()
    seed_admin(session)
    session.close()


@pytest.fixture
def auth_headers():
    settings = get_settings()
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def seeded(db):
    created = seed_workforce_demo(db)
    db.commit()
    yield created
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": created["domain_id"]})
    db.commit()


def test_idempotency_key_returns_same_run(seeded, auth_headers):
    client = TestClient(app)
    headers = {**auth_headers, "Idempotency-Key": "retry-abc-1"}
    first = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        headers=headers,
        json={"time_limit_s": 5, "reuse": False},
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        headers=headers,
        json={"time_limit_s": 5, "reuse": False},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_bad_idempotency_key_rejected(seeded, auth_headers):
    client = TestClient(app)
    response = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        headers={**auth_headers, "Idempotency-Key": "has space"},
        json={"time_limit_s": 5},
    )
    assert response.status_code == 422
