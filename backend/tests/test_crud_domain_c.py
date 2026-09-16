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


@pytest.fixture
def organization_id(auth_headers):
    client = TestClient(app)
    response = client.get("/api/iam/organization/", headers=auth_headers)
    items = response.json()["items"]
    default_org = next(item for item in items if item["code"] == "default")
    return default_org["id"]


def test_event_type_and_event(auth_headers):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    event_type_response = client.post(
        "/api/domain/event_type/",
        json={"code": f"leave-taken-c-{suffix}", "name": "Leave Taken"},
        headers=auth_headers,
    )
    assert event_type_response.status_code == 201
    event_type_id = event_type_response.json()["id"]

    event_response = client.post(
        "/api/domain/event/",
        json={"event_type_id": event_type_id, "occurred_at": "2026-01-05T09:00:00Z"},
        headers=auth_headers,
    )
    assert event_response.status_code == 201


def test_resource_type_and_resource(auth_headers):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    resource_type_response = client.post(
        "/api/domain/resource_type/",
        json={"code": f"room-c-{suffix}", "name": "Room"},
        headers=auth_headers,
    )
    assert resource_type_response.status_code == 201
    resource_type_id = resource_type_response.json()["id"]

    resource_response = client.post(
        "/api/domain/resource/",
        json={"resource_type_id": resource_type_id, "capacity": 30, "unit": "seats"},
        headers=auth_headers,
    )
    assert resource_response.status_code == 201


def test_time_calendar_and_time_period(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    calendar_response = client.post(
        "/api/domain/time_calendar/",
        json={
            "organization_id": organization_id,
            "code": f"main-c-{suffix}",
            "name": "Main Calendar",
        },
        headers=auth_headers,
    )
    assert calendar_response.status_code == 201
    calendar_id = calendar_response.json()["id"]

    period_response = client.post(
        "/api/domain/time_period/",
        json={
            "calendar_id": calendar_id,
            "name": "Week 1",
            "start_time": "2026-01-05T00:00:00Z",
            "end_time": "2026-01-11T23:59:59Z",
            "metadata_": {"note": "first week"},
        },
        headers=auth_headers,
    )
    assert period_response.status_code == 201
    assert period_response.json()["metadata_"] == {"note": "first week"}
    period_id = period_response.json()["id"]

    get_response = client.get(
        f"/api/domain/time_period/{period_id}",
        headers=auth_headers,
    )
    assert get_response.status_code == 200
    assert get_response.json()["metadata_"] == {"note": "first week"}
