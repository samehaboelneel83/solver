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
            "code": f"shift-scheduling-a-{suffix}",
            "name": "Shift Scheduling",
            "version": 1,
            "status": "DRAFT",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_scenario_create(auth_headers, problem_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    response = client.post(
        "/api/problem/scenario/",
        json={"problem_id": problem_id, "code": f"baseline-a-{suffix}", "name": "Baseline"},
        headers=auth_headers,
    )
    assert response.status_code == 201


def test_variable_definition_and_dimension(auth_headers, problem_id):
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]

    var_response = client.post(
        "/api/problem/variable_definition/",
        json={
            "problem_id": problem_id,
            "code": f"employee_shift-{suffix}",
            "name": "Employee Shift Assignment",
            "variable_type": "BOOLEAN",
        },
        headers=auth_headers,
    )
    assert var_response.status_code == 201
    variable_id = var_response.json()["id"]

    dimension_response = client.post(
        "/api/problem/variable_dimension/",
        json={"variable_id": variable_id, "dimension_order": 0, "dimension_type": "ENTITY"},
        headers=auth_headers,
    )
    assert dimension_response.status_code == 201


def test_problem_create_without_client_defaults(auth_headers, organization_id):
    """version (default=1) and status (default="DRAFT") are NOT NULL columns
    with client-side ORM defaults. Omitting them must succeed and apply
    those defaults -- previously they were required on create, so the
    generic form (which omits empty inputs) could not create a Problem at
    all and returned 422."""
    client = TestClient(app)
    code = f"minimal-problem-{uuid.uuid4().hex[:8]}"

    response = client.post(
        "/api/problem/problem/",
        json={
            "organization_id": organization_id,
            "code": code,
            "name": "Minimal Problem",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 1
    assert body["status"] == "DRAFT"
