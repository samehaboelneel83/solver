"""Prometheus metrics for the API and the worker (target roadmap Phase 8).

Each process serves its own on an internal port -- the worker on
`WORKER_METRICS_PORT` (9100), the API on `API_METRICS_PORT` (9101) -- that
docker-compose does not publish. A Prometheus server on the compose network
scrapes both. Not on the API's public port: `queue_depth` is labelled by
organization, and a tenant's ids are not for anonymous readers.

What there is, and who writes it:

* `solve_seconds{solver, model_class, status}` -- histogram, worker: how
  long each run took, by the solver that took it, the class it was, and
  how it ended.
* `run_gap{solver}` -- histogram, worker: the gap each run ended with (0 =
  proven). A distribution rather than the roadmap's gauge: the last run's
  gap alone says nothing about the hundred before it.
* `runs_total{solver, status}` -- counter, worker.
* `queue_wait_seconds` -- histogram, worker: from `queued_at` to the claim.
* `worker_busy` -- gauge, worker: 1 while it holds a run.
* `queue_depth{org}` -- gauge, API: queued runs per organization, counted
  from the database when scraped, so it is right however many workers
  there are.
"""

from __future__ import annotations

import logging
import os

from prometheus_client import Counter, Gauge, Histogram, start_http_server
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import REGISTRY, Collector

logger = logging.getLogger(__name__)

SOLVE_SECONDS = Histogram(
    "solve_seconds",
    "Seconds a run took, by solver, model class and how it ended",
    ["solver", "model_class", "status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600),
)
RUN_GAP = Histogram(
    "run_gap",
    "Relative gap between a run's answer and its proven bound when it ended (0 = proven)",
    ["solver"],
    buckets=(0.0, 1e-6, 1e-4, 1e-3, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0),
)
RUNS = Counter("runs_total", "Runs settled, by solver and status", ["solver", "status"])
QUEUE_WAIT = Histogram(
    "queue_wait_seconds",
    "Seconds from a run being queued to a worker claiming it",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 300, 900, 3600),
)
WORKER_BUSY = Gauge("worker_busy", "1 while this worker holds a run, else 0")


class QueueDepth(Collector):
    """`queue_depth{org}`, read from the database at scrape time. Registered
    by the API only (`serve(..., queue_depth=True)`)."""

    def collect(self):
        from sqlalchemy import text

        from app.core.db import SessionLocal

        family = GaugeMetricFamily("queue_depth", "Queued runs per organization", labels=["org"])
        db = SessionLocal()
        try:
            rows = db.execute(
                text(
                    "SELECT organization_id, count(*) FROM run"
                    " WHERE status = 'queued' GROUP BY organization_id"
                )
            ).all()
        except Exception:  # pragma: no cover -- a scrape must not take the process down
            logger.warning("could not count the queue", exc_info=True)
            rows = []
        finally:
            db.close()
        for org, count in rows:
            family.add_metric([str(org)], count)
        yield family


_QUEUE_DEPTH: QueueDepth | None = None


def register_queue_depth() -> None:
    global _QUEUE_DEPTH
    if _QUEUE_DEPTH is None:
        _QUEUE_DEPTH = QueueDepth()
        REGISTRY.register(_QUEUE_DEPTH)


def serve(port_env: str, default: int) -> int | None:
    """Serve this process's metrics on the port named by `port_env`; `0`
    turns it off. Returns the port, or None when off or already taken (a
    second process in the same container must not fail to start over it)."""
    port = int(os.environ.get(port_env, default))
    if port == 0:
        return None
    try:
        start_http_server(port, addr="0.0.0.0")
    except OSError:
        logger.warning("metrics port %s is taken; not serving metrics here", port)
        return None
    return port


def record_run(solver: str | None, model_class: str | None, status: str, seconds: float, gap) -> None:
    solver = solver or "none"
    SOLVE_SECONDS.labels(solver, model_class or "unknown", status).observe(max(0.0, seconds))
    RUNS.labels(solver, status).inc()
    if gap is not None:
        RUN_GAP.labels(solver).observe(float(gap))
