"""Structured logs (target roadmap Phase 8): one JSON object per line, from
the API and the worker, with the run, organization and solver bound."""

from __future__ import annotations

import io
import json
import logging

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import logs
from app.core.config import get_settings
from app.main import app
from app.seed import seed_workforce_demo
from app.solve.service import enqueue_run
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture
def captured():
    """Configure logging into a buffer; put the process back afterwards."""
    root = logging.getLogger()
    saved = (list(root.handlers), root.level, structlog.get_config())
    stream = io.StringIO()

    def lines() -> list[dict]:
        return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]

    yield stream, lines
    logs.clear()
    root.handlers, root.level = saved[0], saved[1]
    structlog.configure(**saved[2])


def test_every_line_is_json_with_the_service_and_what_is_bound(captured):
    stream, lines = captured
    logs.configure("worker", stream=stream)
    logs.bind(run_id=7, org_id="org-1", solver=None)
    logs.get("t").info("hello", answer=42)
    # An old-style standard-library call goes through the same renderer.
    logging.getLogger("t.stdlib").warning("plain %s", "text")
    logs.clear()
    logs.get("t").info("after")

    first, second, third = lines()
    assert first["event"] == "hello" and first["answer"] == 42
    assert first["service"] == "worker" and first["run_id"] == 7 and first["org_id"] == "org-1"
    assert "solver" not in first  # None is not bound
    assert first["level"] == "info" and "timestamp" in first
    assert second["event"] == "plain text" and second["level"] == "warning" and second["run_id"] == 7
    assert "run_id" not in third


def test_a_worker_run_is_logged_with_its_run_organization_and_solver(db, empty_queue, captured):  # noqa: F811
    stream, lines = captured
    logs.configure("worker", stream=stream)
    seeded = seed_workforce_demo(db)
    run_id = enqueue_run(db, seeded["scenario_id"], time_limit=10.0)
    org = db.execute(text("SELECT organization_id FROM run WHERE id = :r"), {"r": run_id}).scalar_one()

    assert work_once(db) == run_id

    about = [line for line in lines() if line.get("run_id") == run_id]
    events = [line["event"] for line in about]
    assert events[0] == "run claimed" and events[-1] == "run settled"
    assert all(line["org_id"] == str(org) for line in about)
    settled = about[-1]
    assert settled["solver"] == "cp-sat" and settled["status"] in ("optimal", "feasible", "infeasible")
    # Nothing leaks into the next thing the worker does.
    logs.get("t").info("idle")
    assert "run_id" not in lines()[-1]


def test_each_request_is_one_line_with_its_organization(captured):
    stream, lines = captured
    settings = get_settings()
    with TestClient(app) as client:
        logs.configure("api", stream=stream)
        token = client.post(
            "/api/auth/login",
            data={"username": settings.admin_username, "password": settings.admin_password},
        ).json()["access_token"]
        client.get("/api/health")
        client.get("/api/v1/runs?limit=1", headers={"Authorization": f"Bearer {token}"})

    requests = {line["path"]: line for line in lines() if line.get("event") == "request"}
    runs = requests["/api/v1/runs"]
    assert runs["status"] == 200 and runs["method"] == "GET" and runs["service"] == "api"
    assert runs["org_id"] and runs["user"] == settings.admin_username
    assert runs["duration_ms"] >= 0
    assert requests["/api/health"]["org_id"] is None
