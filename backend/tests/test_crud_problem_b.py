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


@pytest.fixture
def problem_id(auth_headers, organization_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    response = client.post(
        "/api/problem/problem/",
        json={
            "organization_id": organization_id,
            "code": f"shift-scheduling-b-{suffix}",
            "name": "Shift Scheduling",
            "version": 1,
            "status": "DRAFT",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_constraint_definition_and_scope(auth_headers, problem_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    constraint_response = client.post(
        "/api/problem/constraint_definition/",
        json={
            "problem_id": problem_id,
            "code": f"max-weekly-hours-{suffix}",
            "name": "Max Weekly Hours",
            "is_hard": True,
        },
        headers=auth_headers,
    )
    assert constraint_response.status_code == 201
    constraint_id = constraint_response.json()["id"]

    scope_response = client.post(
        "/api/problem/constraint_scope/",
        json={"constraint_id": constraint_id, "scope_type": "GLOBAL"},
        headers=auth_headers,
    )
    assert scope_response.status_code == 201


def test_objective_and_component(auth_headers, problem_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    objective_response = client.post(
        "/api/problem/objective/",
        json={
            "problem_id": problem_id,
            "code": f"minimize-cost-{suffix}",
            "name": "Minimize Cost",
            "objective_type": "MINIMIZE",
        },
        headers=auth_headers,
    )
    assert objective_response.status_code == 201
    objective_id = objective_response.json()["id"]

    component_response = client.post(
        "/api/problem/objective_component/",
        json={"objective_id": objective_id, "code": f"overtime-penalty-{suffix}", "weight": 10},
        headers=auth_headers,
    )
    assert component_response.status_code == 201


def test_parameter_create(auth_headers, problem_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    response = client.post(
        "/api/problem/parameter/",
        json={
            "problem_id": problem_id,
            "code": f"max_overtime_hours-{suffix}",
            "data_type": "number",
            "value": 10,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
