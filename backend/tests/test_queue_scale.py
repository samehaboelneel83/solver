"""Worker scale-out and queue metrics (queue R33): per-org running count and oldest wait."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core import metrics
from app.seed import seed_admin, seed_workforce_demo
from app.solve.service import enqueue_run
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_queue_stats_include_running_and_oldest_wait_per_org(db, empty_queue):  # noqa: F811
    seeded = seed_workforce_demo(db)
    scenario = seeded["scenario_id"]
    org = db.execute(
        text("SELECT organization_id FROM scenario WHERE id = :s"), {"s": scenario}
    ).scalar_one()
    older = enqueue_run(db, scenario, time_limit=10.0)
    enqueue_run(db, scenario, time_limit=10.0)
    db.execute(
        text("UPDATE run SET status = 'running', started_at = now(), heartbeat_at = now() WHERE id = :r"),
        {"r": older},
    )
    db.execute(
        text("UPDATE run SET queued_at = :t WHERE status = 'queued' AND organization_id = :o"),
        {"t": datetime.now(timezone.utc) - timedelta(seconds=30), "o": org},
    )
    db.commit()

    families = {f.name: f for f in metrics.QueueDepth().collect()}
    depth = {s.labels["org"]: s.value for s in families["queue_depth"].samples}
    running = {s.labels["org"]: s.value for s in families["runs_running"].samples}
    wait = {s.labels["org"]: s.value for s in families["queue_oldest_wait_seconds"].samples}
    assert depth[str(org)] == 1
    assert running[str(org)] == 1
    assert wait[str(org)] >= 25


def test_operator_metrics_route_is_admin_only(db, empty_queue, client, auth_headers):  # noqa: F811
    seed_admin(db)
    assert client.get("/api/v1/metrics").status_code == 401
    seeded = seed_workforce_demo(db)
    enqueue_run(db, seeded["scenario_id"], time_limit=10.0)
    response = client.get("/api/v1/metrics", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.text
    assert "queue_depth" in body
    assert "runs_running" in body
    assert "queue_oldest_wait_seconds" in body
