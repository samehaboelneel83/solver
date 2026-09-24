"""A run told as GenUI events (app.genui.translate, GET /runs/{id}/genui)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.genui.translate import AGENT_STATES, COMPONENT_TYPES, EVENTS, STEPS, Translator
from app.main import app
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_run_events import _knapsack, _run
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _states(events):
    return [e["state"] for e in events if e["event"] == "agent.state"]


def _check(events):
    """Every event is the protocol's, every component type and state too."""
    for e in events:
        assert e["event"] in EVENTS, e
        if e["event"] == "agent.state":
            assert e["state"] in AGENT_STATES
        if e["event"] == "component.created":
            assert e["component"]["type"] in COMPONENT_TYPES and e["component"]["id"].startswith("run-")


def _whole(translator, record, *, extra=()):
    events = translator.opening()
    for kind, payload in [
        ("stage", {"stage": "started"}),
        ("stage", {"stage": "compiling", "model_class": "IP"}),
        ("stage", {"stage": "compiled", "model_class": "IP", "variables": 40, "rules": 1,
                   "fingerprint": {"rows_knapsack": 1}}),
        ("stage", {"stage": "chosen", "solver": "cp-sat", "why": "cp-sat is the highest-ranked solver for a IP model"}),
        ("stage", {"stage": "solving", "solver": "cp-sat", "time_limit_s": 10}),
        ("incumbent", {"t": 1.0, "objective": 90, "bound": 100}),
        ("bound", {"t": 2.0, "bound": 95}),
        *extra,
        ("stage", {"stage": "post_processing"}),
    ]:
        events += translator.feed(kind, payload)
    return events + translator.settle(record)


def test_an_optimal_run_walks_the_steps_and_hydrates_its_answer():
    events = _whole(Translator(7, status="queued", time_limit_s=10), {
        "status": "optimal", "objective": 95.0, "best_bound": 95.0, "gap": 0.0, "optimality": "global",
        "wall_time_s": 2.5, "solver": "cp-sat", "error": None})
    _check(events)
    assert _states(events) == [
        "submitting_job", "understanding", "building_model", "selecting_solver", "solving",
        "post_processing", "hydrating_ui", "complete"]
    assert set(STEPS) <= set(_states(events))
    created = [e["component"]["type"] for e in events if e["event"] == "component.created"]
    assert created == ["timeline", "model-summary", "solver-status", "solver-progress",
                       "optimization-summary", "metric", "metric", "metric"]
    # Progress: the gap from the solver's own numbers, the bound kept from
    # the last report, and the share of the time allowed -- nothing invented.
    progress = [e["data"] for e in events if e["event"] == "component.data" and e["id"] == "run-7-progress"]
    assert progress[0] == {"elapsed": 1.0, "objective": 90, "bound": 100, "gap": 10 / 90, "timeShare": 0.1}
    assert progress[1] == {"elapsed": 2.0, "objective": 90, "bound": 95, "gap": 5 / 90, "timeShare": 0.2}
    model = next(e["data"] for e in events if e["event"] == "component.data" and e["id"] == "run-7-model")
    assert model == {"modelClass": "IP", "variables": 40, "constraints": 1, "fingerprint": {"rows_knapsack": 1}}
    # Every component created is completed, each once.
    ids = {e["component"]["id"] for e in events if e["event"] == "component.created"}
    done = [e["id"] for e in events if e["event"] == "component.completed"]
    assert sorted(done) == sorted(ids)


def test_an_infeasible_run_ends_in_error_without_metric_cards():
    events = _whole(Translator(8, status="queued", time_limit_s=10), {
        "status": "infeasible", "objective": None, "best_bound": None, "gap": None, "optimality": None,
        "wall_time_s": 0.1, "solver": "cp-sat", "error": None})
    assert _states(events)[-1] == "error"
    assert "metric" not in [e["component"]["type"] for e in events if e["event"] == "component.created"]
    assert any(e["event"] == "agent.message" and "no answer satisfies every rule" in e["text"] for e in events)


def test_a_feasible_run_is_a_warning_and_the_solver_log_hydrates():
    events = _whole(Translator(9, status="queued", time_limit_s=10), {
        "status": "feasible", "objective": 90.0, "best_bound": 95.0, "gap": 0.05, "optimality": None,
        "wall_time_s": 10, "solver": "cp-sat", "error": None}, extra=[("log", {"line": "presolve done"})])
    assert _states(events)[-1] == "warning"
    log = [e for e in events if e["event"] == "component.data" and e["id"] == "run-9-log"]
    assert log == [{"event": "component.data", "id": "run-9-log", "data": {"append": ["presolve done"]}}]


def _read(response):
    out = []
    for block in response.text.split("\n\n"):
        data = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if data:
            out.append(json.loads(data[0]))
    return out


def test_the_stream_tells_a_real_run(tenants, db):  # noqa: F811
    run_id = _run(db, _knapsack(), "genui-stream")
    with TestClient(app).stream("GET", f"/api/v1/runs/{run_id}/genui", headers=tenants["a"]) as response:
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        response.read()
    events = _read(response)
    _check(events)
    assert _states(events)[:5] == ["submitting_job", "understanding", "building_model", "selecting_solver", "solving"]
    assert _states(events)[-1] == "complete"
    summary = next(e["data"] for e in events if e["event"] == "component.data" and e["id"] == f"run-{run_id}-summary")
    assert summary["status"] == "optimal" and summary["solver"] == "cp-sat" and summary["objective"] is not None
    assert any(e["event"] == "component.data" and e["id"] == f"run-{run_id}-progress" for e in events)


def test_another_organization_cannot_watch_the_genui_stream(tenants, db):  # noqa: F811
    run_id = _run(db, _knapsack(10), "genui-private")
    with TestClient(app).stream("GET", f"/api/v1/runs/{run_id}/genui", headers=tenants["b"]) as response:
        assert response.status_code == 404


def test_a_probe_race_is_told_as_trying_the_solvers():
    t = Translator(10, status="queued", time_limit_s=10)
    t.opening()
    events = t.feed("stage", {"stage": "probing", "solvers": ["cp-sat", "highs"], "seconds": 1.0})
    assert {"event": "agent.message", "text": "Trying cp-sat, highs for 1 s each; the best goes on."} in events
    assert _states(events) == ["selecting_solver"]


def test_a_spatial_run_that_ended_well_also_shows_its_map():
    """GIS 7: the partition, hydrated from the stored answer; never for a run without one."""
    record = {"status": "optimal", "objective": 0, "best_bound": 0, "gap": 0.0, "optimality": "global",
              "wall_time_s": 0.1, "solver": "cp-sat", "error": None}
    events = _whole(Translator(11, status="queued", time_limit_s=10, spatial=True), record)
    _check(events)
    maps = [e["component"] for e in events if e["event"] == "component.created" and e["component"]["type"] == "spatial-map"]
    assert maps == [{"id": "run-11-map", "type": "spatial-map", "state": "hydrated",
                     "props": {"title": "The partition", "runId": 11}, "data": {"source": "run", "runId": 11}}]
    assert {"event": "component.completed", "id": "run-11-map"} in events

    plain = _whole(Translator(12, status="queued", time_limit_s=10), record)
    failed = _whole(Translator(13, status="queued", time_limit_s=10, spatial=True), {**record, "status": "infeasible"})
    for stream in (plain, failed):
        assert not any(e["event"] == "component.created" and e["component"]["type"] == "spatial-map" for e in stream)


def test_an_approximate_optimum_is_never_said_to_be_proven():
    """PDLP (queue R1): optimal to a tolerance -- the stream warns rather than completing."""
    record = {"status": "optimal", "objective": 12.5, "best_bound": None, "gap": None, "optimality": "approximate",
              "wall_time_s": 0.2, "solver": "pdlp", "error": None}
    events = _whole(Translator(14, status="queued", time_limit_s=10), record)
    said = [e["text"] for e in events if e["event"] == "agent.message"]
    assert any("not proven the best" in text for text in said)
    assert not any("proven the best (" in text for text in said)
    assert _states(events)[-1] == "warning"
