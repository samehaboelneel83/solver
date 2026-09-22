"""OpenTelemetry traces (target roadmap Phase 8): the request that queues a
run and the worker that solves it are one trace, through `run.params.trace`."""

from __future__ import annotations

import io
import json
import logging

import pytest
import structlog
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import text

from app.core import logs, tracing
from app.core.config import get_settings
from app.main import app
from app.seed import seed_workforce_demo
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    tracing.configure("test", exporter=exporter)
    yield exporter
    tracing.configure("test", exporter=InMemorySpanExporter())


def _token() -> str:
    settings = get_settings()
    return TestClient(app).post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    ).json()["access_token"]


def test_a_run_is_one_trace_from_the_request_to_the_worker(db, empty_queue, spans):  # noqa: F811
    seeded = seed_workforce_demo(db)
    db.commit()
    client = TestClient(app)
    response = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        json={"time_limit_s": 10},
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    stored = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    assert stored["trace"]["traceparent"].startswith("00-")

    assert work_once(db) == run_id

    finished = {s.name: s for s in spans.get_finished_spans()}
    request = finished[f"POST /api/v1/scenarios/{seeded['scenario_id']}/runs"]
    trace_id = request.context.trace_id
    for name in ("enqueue_run", "run", "compile", "choose", "solve", "persist"):
        assert finished[name].context.trace_id == trace_id, name
    # The parent chain crosses the queue: request -> enqueue -> run -> stages.
    assert finished["enqueue_run"].parent.span_id == request.context.span_id
    assert finished["run"].parent.span_id == finished["enqueue_run"].context.span_id
    for stage in ("compile", "choose", "solve", "persist"):
        assert finished[stage].parent.span_id == finished["run"].context.span_id, stage
    assert f"{trace_id:032x}" in stored["trace"]["traceparent"]
    assert finished["choose"].attributes["solver"] == "cp-sat"
    assert finished["compile"].attributes["variables"] > 0


def test_an_infeasible_run_has_a_diagnose_span(db, empty_queue, spans):  # noqa: F811
    """The demo's own model, with coverage hard, is infeasible (weekly_rota's
    staff cannot meet its demand): the worker explains it, under `diagnose`."""
    from app.solve.service import enqueue_run

    seeded = seed_workforce_demo(db)
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name)"
            " VALUES (:p, :v, 'as modelled for tracing') RETURNING id"
        ),
        {"p": seeded["problem_id"], "v": seeded["model_version_id"]},
    ).scalar_one()
    db.commit()
    with tracing.span("test root"):
        run_id = enqueue_run(db, scenario, time_limit=10.0)
    assert work_once(db) == run_id

    finished = {s.name: s for s in spans.get_finished_spans()}
    assert finished["solve"].attributes["status"] == "infeasible"
    assert finished["diagnose"].context.trace_id == finished["test root"].context.trace_id
    assert finished["diagnose"].parent.span_id == finished["run"].context.span_id


def test_the_log_exporter_writes_each_span_as_a_json_line_and_logs_carry_the_trace():
    root = logging.getLogger()
    saved = (list(root.handlers), root.level, structlog.get_config())
    stream = io.StringIO()
    logs.clear()
    try:
        logs.configure("worker", stream=stream)
        tracing.configure("worker", exporter=tracing.LogExporter())
        with tracing.span("outer", run_id=5) as outer:
            logs.get("t").info("inside")
            trace_id = format(outer.get_span_context().trace_id, "032x")
        lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    finally:
        root.handlers, root.level = saved[0], saved[1]
        structlog.configure(**saved[2])
        tracing.configure("test", exporter=InMemorySpanExporter())

    inside = next(line for line in lines if line["event"] == "inside")
    span = next(line for line in lines if line["event"] == "span")
    assert inside["trace_id"] == trace_id
    assert span["name"] == "outer" and span["trace_id"] == trace_id
    assert span["attr.run_id"] == 5 and span["parent_id"] is None and span["duration_ms"] >= 0


def test_an_unknown_exporter_is_refused(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "jaeger-please")
    with pytest.raises(ValueError, match="log, otlp or none"):
        tracing.configure("test")
