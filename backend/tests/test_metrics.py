"""Prometheus metrics (target roadmap Phase 8), read back from the registry
and from the port Prometheus would scrape."""

from __future__ import annotations

import socket
import urllib.request

from prometheus_client import REGISTRY
from sqlalchemy import text

from app.core import metrics
from app.seed import seed_workforce_demo
from app.solve.service import enqueue_run
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _value(name: str, labels: dict | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def test_a_worker_run_is_counted_timed_and_its_wait_and_gap_recorded(db, empty_queue):  # noqa: F811
    seeded = seed_workforce_demo(db)
    run_id = enqueue_run(db, seeded["scenario_id"], time_limit=10.0)
    before = {
        "runs": sum(
            _value("runs_total", {"solver": "cp-sat", "status": s}) for s in ("optimal", "feasible", "infeasible")
        ),
        "waits": _value("queue_wait_seconds_count"),
        "gaps": _value("run_gap_count", {"solver": "cp-sat"}),
    }

    assert work_once(db) == run_id

    row = db.execute(
        text("SELECT status, solver, params->>'classified_as' AS c, gap FROM run WHERE id = :r"), {"r": run_id}
    ).mappings().one()
    assert row["solver"] == "cp-sat"
    assert _value("runs_total", {"solver": "cp-sat", "status": row["status"]}) >= 1
    after_runs = sum(
        _value("runs_total", {"solver": "cp-sat", "status": s}) for s in ("optimal", "feasible", "infeasible")
    )
    assert after_runs == before["runs"] + 1
    assert _value(
        "solve_seconds_count", {"solver": "cp-sat", "model_class": row["c"], "status": row["status"]}
    ) >= 1
    assert _value("queue_wait_seconds_count") == before["waits"] + 1
    if row["gap"] is not None:
        assert _value("run_gap_count", {"solver": "cp-sat"}) == before["gaps"] + 1
    assert _value("worker_busy") == 0


def test_queue_depth_counts_queued_runs_per_organization(db, empty_queue):  # noqa: F811
    seeded = seed_workforce_demo(db)
    enqueue_run(db, seeded["scenario_id"], time_limit=10.0)
    enqueue_run(db, seeded["scenario_id"], time_limit=10.0)
    org = db.execute(
        text("SELECT organization_id FROM scenario WHERE id = :s"), {"s": seeded["scenario_id"]}
    ).scalar_one()

    (family,) = list(metrics.QueueDepth().collect())
    by_org = {sample.labels["org"]: sample.value for sample in family.samples}
    assert by_org == {str(org): 2}


def test_metrics_are_served_on_their_own_port(monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv("TEST_METRICS_PORT", str(port))
    assert metrics.serve("TEST_METRICS_PORT", 0) == port
    body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics").read().decode()
    assert "# TYPE worker_busy gauge" in body
    assert "# TYPE solve_seconds histogram" in body
    # Taken already: reported, not fatal. And 0 turns it off.
    assert metrics.serve("TEST_METRICS_PORT", 0) is None
    monkeypatch.setenv("TEST_METRICS_PORT", "0")
    assert metrics.serve("TEST_METRICS_PORT", 0) is None
