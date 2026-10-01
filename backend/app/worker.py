"""The solver worker: claim a queued run, solve it, repeat.

Run it with `python -m app.worker`. Several may run at once — `claim_next`
uses `FOR UPDATE SKIP LOCKED`, so each takes a different run and none waits
on another.

**Why a worker at all.** Solving used to happen inside the HTTP request,
which capped a model at whatever a request may take and held a web worker for
the duration. A run row has carried `queued_at`, `started_at` and
`finished_at` since migration 0007, so the shape was always meant for this;
this is the process that fills them in.

A live worker heartbeats on the run it is solving. Reclaim looks at that
clock, not at `started_at`, and it runs between jobs rather than only at
start-up. A run whose worker died is queued again — unless it had already
been asked to stop, in which case it is `cancelled` rather than solved twice.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
import uuid
from types import FrameType

from sqlalchemy import text

from app.analytics import publish_facts
from app.retention import prune_run_events, prune_runs
from app.core import logs, metrics, tracing
from app.core.db import SessionLocal
from app.solve.service import claim_next, execute_run

logger = logging.getLogger("solver.worker")

POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))
# Silence longer than this means the worker is gone. Short enough that a
# crashed solve is noticed; long enough that a slow heartbeat is not a theft.
STALE_AFTER_SECONDS = int(os.environ.get("WORKER_STALE_AFTER_SECONDS", "20"))
# How often expired run events are pruned (app.retention). Retention is in
# days, so hourly is plenty.
PRUNE_EVERY_SECONDS = float(os.environ.get("WORKER_PRUNE_EVERY_SECONDS", "3600"))

_stop = False


def _request_stop(signum: int, _frame: FrameType | None) -> None:
    """Finish the run in hand, then exit. Killing mid-solve would leave a row
    `running` with nothing working on it."""
    global _stop
    _stop = True
    logger.info("signal %s received; stopping after the current run", signum)


def reclaim_stale(db) -> int:
    """Put runs whose worker died back in the queue.

    Looks at `heartbeat_at`, falling back to `started_at` for a row written
    before the column existed. A slow run that is still heartbeating is left
    alone. A dead worker that had already been asked to stop is marked
    cancelled: solving it again would ignore the stop.
    """
    cancelled = db.execute(
        text(
            "UPDATE run SET status = 'cancelled', finished_at = now()"
            " WHERE status = 'running' AND cancel_requested"
            "   AND COALESCE(heartbeat_at, started_at) < now() - make_interval(secs => :secs)"
            " RETURNING id"
        ),
        {"secs": STALE_AFTER_SECONDS},
    ).scalars().all()
    reclaimed = db.execute(
        text(
            "UPDATE run SET status = 'queued', started_at = NULL, heartbeat_at = NULL"
            " WHERE status = 'running' AND NOT cancel_requested"
            "   AND COALESCE(heartbeat_at, started_at) < now() - make_interval(secs => :secs)"
            " RETURNING id"
        ),
        {"secs": STALE_AFTER_SECONDS},
    ).scalars().all()
    db.commit()
    if cancelled:
        logger.info("marked %d abandoned cancelled run(s): %s", len(cancelled), cancelled)
    if reclaimed:
        logger.warning("requeued %d run(s) left running by a stopped worker: %s",
                       len(reclaimed), reclaimed)
    return len(reclaimed)


def work_once(db) -> int | None:
    """Claim and solve one run. Returns its id, or None when the queue is
    empty."""
    reclaim_stale(db)
    run_id = claim_next(db)
    if run_id is None:
        return None
    # Every line about this run, here and in the solve, carries its id and
    # organization; the solver is added once one is chosen (`_execute`).
    claimed = db.execute(
        text(
            "SELECT organization_id,"
            "       extract(epoch FROM coalesce(started_at, now()) - queued_at) AS waited"
            "  FROM run WHERE id = :r"
        ),
        {"r": run_id},
    ).mappings().one()
    org_id = claimed["organization_id"]
    logs.bind(run_id=run_id, org_id=str(org_id) if org_id else None)
    log = logs.get("solver.worker")
    log.info("run claimed", waited_s=round(float(claimed["waited"] or 0), 3))
    metrics.QUEUE_WAIT.observe(max(0.0, float(claimed["waited"] or 0)))
    metrics.WORKER_BUSY.set(1)
    started = time.monotonic()
    try:
        outcome = execute_run(db, run_id)
        log.info("run settled", status=outcome.status, objective=outcome.objective)
        _record(db, run_id, time.monotonic() - started)
    except Exception:
        # A claimed run that raises would otherwise stay `running` for ever,
        # and the next worker would skip it. Record the failure on the run.
        db.rollback()
        log.exception("run failed")
        db.execute(
            text(
                "UPDATE run SET status = 'error', error = :e, finished_at = now()"
                " WHERE id = :r"
            ),
            {"e": "the worker failed while solving; see the worker log", "r": run_id},
        )
        db.commit()
    finally:
        metrics.WORKER_BUSY.set(0)
        logs.clear()
    return run_id


def _record(db, run_id: int, seconds: float) -> None:
    """The settled run, into the metrics: its solver, class, status and gap."""
    row = db.execute(
        text(
            "SELECT status, solver, gap, params->>'classified_as' AS model_class"
            "  FROM run WHERE id = :r"
        ),
        {"r": run_id},
    ).mappings().one()
    metrics.record_run(row["solver"], row["model_class"], row["status"], seconds, row["gap"])


def _analytics_client(backoff: "Backoff | None" = None):
    """A ClickHouse client with the analytics tables in place, or None while
    ClickHouse cannot be reached (tried again once the backoff allows)."""
    from app.clickhouse_schema import create_analytics_schema
    from app.core.db import get_clickhouse_client

    try:
        client = get_clickhouse_client()
        create_analytics_schema(client)
        if backoff is not None:
            backoff.succeeded()
        return client
    except Exception as exc:
        if backoff is None:
            logger.warning("ClickHouse is not reachable; run facts will wait", exc_info=True)
        else:
            backoff.failed(exc)
        return None


class Backoff:
    """Try ClickHouse again after a growing wait, and say so once, not every pass (operator trial F32).

    The first failure is logged with its traceback; later ones are one line each,
    as often as the wait allows (doubling up to `ceiling` seconds). Recovery is logged too.
    """

    def __init__(self, what: str, *, first: float = 5.0, ceiling: float = 300.0, clock=time.monotonic) -> None:
        self.what, self.first, self.ceiling, self.clock = what, first, ceiling, clock
        self.wait = 0.0
        self.next_at = 0.0
        self.failures = 0

    def due(self) -> bool:
        return self.clock() >= self.next_at

    def failed(self, exc: BaseException) -> None:
        self.failures += 1
        self.wait = self.first if self.wait == 0 else min(self.ceiling, self.wait * 2)
        self.next_at = self.clock() + self.wait
        if self.failures == 1:
            logger.warning("%s is not reachable; run facts will wait (next try in %.0fs)", self.what, self.wait,
                           exc_info=exc)
        else:
            logger.warning("%s is still not reachable (%d tries): %s; next try in %.0fs", self.what, self.failures,
                           str(exc).splitlines()[0] if str(exc) else type(exc).__name__, self.wait)

    def succeeded(self) -> None:
        if self.failures:
            logger.info("%s is reachable again after %d failed tries", self.what, self.failures)
        self.wait, self.next_at, self.failures = 0.0, 0.0, 0


#: How often a worker says it is alive, and how long after its last word it counts as gone.
BEAT_SECONDS = 15
ONLINE_WITHIN_SECONDS = 90


def beat(db, worker_id: str) -> None:
    """Say this worker is alive (Epic UX, U-5): `GET /api/v1/workers` counts the recent ones."""
    db.execute(text(
        "INSERT INTO worker_heartbeat (worker_id, host, pid) VALUES (:w, :h, :p)"
        " ON CONFLICT (worker_id) DO UPDATE SET last_seen = now()"),
        {"w": worker_id, "h": socket.gethostname()[:200], "p": os.getpid()})
    db.commit()


def main() -> None:  # pragma: no cover -- the loop itself
    logs.configure("worker")
    tracing.configure("worker")
    metrics.serve("WORKER_METRICS_PORT", 9100)
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    clickhouse = Backoff("ClickHouse")
    client = _analytics_client(clickhouse)
    db = SessionLocal()
    try:
        reclaim_stale(db)
        logger.info("worker ready; polling every %ss", POLL_SECONDS)
        pruned_at = 0.0
        worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        beaten_at = 0.0
        while not _stop:
            if time.monotonic() - beaten_at >= BEAT_SECONDS:
                try:
                    beat(db, worker_id)
                except Exception:
                    db.rollback()
                    logger.warning("could not record the worker heartbeat", exc_info=True)
                beaten_at = time.monotonic()
            if time.monotonic() - pruned_at >= PRUNE_EVERY_SECONDS:
                try:
                    prune_run_events(db)
                    prune_runs(db)
                except Exception:
                    db.rollback()
                    logger.warning("could not prune run events", exc_info=True)
                pruned_at = time.monotonic()
            solved = work_once(db)
            if solved is None:
                # Camp layouts (app.camp.jobs) when no run is waiting.
                try:
                    from app.camp import jobs as camp_jobs
                    solved = camp_jobs.work_once(db, heartbeat=lambda: beat(db, worker_id))
                except Exception:
                    db.rollback()
                    logger.warning("could not take a camp solve", exc_info=True)
            # Every settled run's fact, whoever settled it; a ClickHouse
            # outage leaves them for the next pass (app.analytics).
            if client is None and clickhouse.due():
                client = _analytics_client(clickhouse)
            if client is not None and clickhouse.due():
                try:
                    publish_facts(db, client, raise_errors=True)
                    clickhouse.succeeded()
                except Exception as exc:
                    clickhouse.failed(exc)
            if solved is None:
                time.sleep(POLL_SECONDS)
    finally:
        db.close()
        logger.info("worker stopped")


if __name__ == "__main__":  # pragma: no cover
    main()
