"""Watching a run: what is recorded, and what the stream sends.

Migration 0036 and `GET /api/v1/runs/{id}/events` (target roadmap Phase 8).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.solve.service import RunEvents, enqueue_run
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import IR, tenants  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401


def _events(db, run_id: int) -> list[tuple[str, dict]]:
    rows = db.execute(
        text("SELECT kind, payload FROM run_event WHERE run_id = :r ORDER BY seq"), {"r": run_id}
    ).all()
    return [(kind, payload) for kind, payload in rows]


def _run(db, ir: dict, name: str) -> int:
    version = make_model_version(db, make_problem(db, make_domain(db, name)), ir)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 'base') RETURNING id"),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=10.0)
    # The queue is shared and claimed fairly, so a worker turn may take
    # another organization's run first (the `tenants` fixture leaves one
    # queued). Work until this one has settled.
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() != "queued":
            break
        work_once(db)
    return run_id


# The knapsack from the honesty tests: big enough that CP-SAT reports
# several better answers on its way to the best one.
def _knapsack(items: int = 40) -> dict:
    import random

    rnd = random.Random(7)
    weights = {f"x{i}": rnd.randint(10, 99) for i in range(items)}
    values = {f"x{i}": rnd.randint(10, 99) for i in range(items)}
    return {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {name: {"index": [], "domain": "binary"} for name in weights},
        "constraints": [
            {
                "id": "cap",
                "left": {"add": [{"mul": [{"const": w}, {"var": n, "index": []}]} for n, w in weights.items()]},
                "relation": "<=",
                "right": {"const": sum(weights.values()) // 3},
                "severity": "hard",
            }
        ],
        "objective": {
            "sense": "maximize",
            "terms": [
                {
                    "id": "o",
                    "weight": 1,
                    "expression": {"add": [{"mul": [{"const": v}, {"var": n, "index": []}]} for n, v in values.items()]},
                }
            ],
        },
    }


# -- what a run records --------------------------------------------------------------


def test_a_run_records_its_stages(db):
    run_id = _run(db, IR, "events-stages")

    stages = [(kind, payload) for kind, payload in _events(db, run_id) if kind == "stage"]
    names = [payload["stage"] for _, payload in stages]
    assert names == ["started", "compiling", "compiled", "chosen", "solving", "post_processing", "settled"]
    by_name = {payload["stage"]: payload for _, payload in stages}
    compiled = by_name["compiled"]
    assert compiled["model_class"] == "IP" and compiled["variables"] == 1
    # The model's numbers ride along, as stored on the run.
    assert compiled["fingerprint"]["variables"] == 1 and compiled["fingerprint"]["version"] == 2
    assert by_name["chosen"]["solver"] == "cp-sat" and "cp-sat" in by_name["chosen"]["why"]
    assert by_name["solving"]["solver"] == "cp-sat"
    assert by_name["settled"]["status"] == "optimal"


def test_a_solver_reports_the_answer_and_the_bound_as_it_works(db):
    run_id = _run(db, _knapsack(), "events-progress")

    progress = [payload for kind, payload in _events(db, run_id) if kind in ("incumbent", "bound")]
    assert progress, "no progress recorded"
    for payload in progress:
        assert set(payload) == {"t", "objective", "bound"}
        assert payload["t"] >= 0
    # The best answer recorded is the one the run ended with.
    objective = db.execute(text("SELECT objective FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    best = max(payload["objective"] for payload in progress if payload["objective"] is not None)
    assert float(objective) == pytest.approx(best)


def test_events_are_throttled_rather_than_written_by_the_thousand(db):
    run_id = _run(db, _knapsack(60), "events-throttle")
    rows = len(_events(db, run_id))
    seconds = db.execute(text("SELECT wall_time_s FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    # Two a second for progress, plus the seven stages, and a little slack.
    assert rows <= 7 + 2 * (float(seconds) + 2)


def test_the_recorder_keeps_the_latest_of_what_it_held_back(db):
    run_id = _run(db, IR, "events-latest")
    # Only what this test records: the solve of its own has already been.
    db.execute(text("DELETE FROM run_event WHERE run_id = :r"), {"r": run_id})
    db.commit()
    events = RunEvents(run_id)
    try:
        events.progress("incumbent", {"t": 0.1, "objective": 1.0, "bound": 9.0})  # written: first
        events.progress("incumbent", {"t": 0.2, "objective": 2.0, "bound": 8.0})  # held
        events.progress("bound", {"t": 0.3, "objective": 2.0, "bound": 7.0})  # replaces it
    finally:
        events.close()  # flushes what was held

    kept = [payload for kind, payload in _events(db, run_id) if kind in ("incumbent", "bound")]
    assert [payload["bound"] for payload in kept] == [9.0, 7.0]


def test_events_belong_to_the_run_and_go_with_it(db):
    run_id = _run(db, IR, "events-cascade")
    assert _events(db, run_id)
    db.execute(text("DELETE FROM run WHERE id = :r"), {"r": run_id})
    db.commit()
    assert _events(db, run_id) == []


# -- the stream --------------------------------------------------------------------------


def _read(response) -> list[dict]:
    """The events in an SSE body, ignoring comments (heartbeats)."""
    out = []
    for block in response.text.split("\n\n"):
        data = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if data:
            out.append(json.loads(data[0]))
    return out


def test_the_stream_replays_a_finished_run_and_closes(tenants, db):
    run_id = _run(db, _knapsack(), "events-stream")
    with TestClient(app).stream("GET", f"/api/v1/runs/{run_id}/events", headers=tenants["a"]) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        response.read()
    events = _read(response)

    assert [event["seq"] for event in events] == sorted(event["seq"] for event in events)
    # The whole run, in order: what it compiled to, the solving, the answers
    # and bounds along the way, and the status it ended with.
    assert (events[0]["kind"], events[0]["stage"]) == ("stage", "started")
    assert (events[-1]["kind"], events[-1]["stage"]) == ("stage", "settled")
    assert any(event["kind"] in ("incumbent", "bound") for event in events)


def test_the_stream_sends_only_what_was_missed(tenants, db):
    run_id = _run(db, _knapsack(), "events-resume")
    client = TestClient(app)
    with client.stream("GET", f"/api/v1/runs/{run_id}/events", headers=tenants["a"]) as first:
        first.read()
    all_events = _read(first)
    half = all_events[len(all_events) // 2]["seq"]

    with client.stream(
        "GET", f"/api/v1/runs/{run_id}/events", headers={**tenants["a"], "Last-Event-ID": str(half)}
    ) as second:
        second.read()
    assert [event["seq"] for event in _read(second)] == [
        event["seq"] for event in all_events if event["seq"] > half
    ]


def test_another_organization_cannot_watch_a_run(tenants, db):
    run_id = _run(db, IR, "events-private")
    with TestClient(app).stream("GET", f"/api/v1/runs/{run_id}/events", headers=tenants["b"]) as response:
        assert response.status_code == 404


def test_a_run_settled_in_presolve_still_has_a_point_to_show(db):
    """A model small enough to be decided before the search begins reports
    nothing as it solves -- there is no "while". Its answer is recorded as
    one point, so every solved run has a curve rather than an empty box."""
    run_id = _run(db, IR, "events-presolve")

    progress = [payload for kind, payload in _events(db, run_id) if kind == "incumbent"]
    objective = db.execute(text("SELECT objective FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    assert progress[-1]["objective"] == float(objective)


def test_watching_a_queued_run_never_holds_up_the_server(db, monkeypatch):
    # A run nobody has picked up yet: the stream waits for news. That wait,
    # and the closing when the viewer leaves, happen off the event loop, so
    # every other request keeps being served (a blocking wait once hung the
    # whole API).
    import asyncio
    import time

    from app.api import run_events

    version = make_model_version(db, make_problem(db, make_domain(db, "events-waiting")), IR)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 'base') RETURNING id"),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=10.0)
    monkeypatch.setattr(run_events, "HEARTBEAT_SECONDS", 3.0)

    async def watch() -> tuple[int, float]:
        stream = run_events.records(run_id, 0)
        waiting = asyncio.ensure_future(stream.__anext__())
        ticks = 0
        for _ in range(20):
            await asyncio.sleep(0.02)
            ticks += 1
        started = time.monotonic()
        waiting.cancel()
        try:
            await waiting
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
        return ticks, time.monotonic() - started

    ticks, closing = asyncio.run(watch())
    assert ticks == 20
    assert closing < 1.0
