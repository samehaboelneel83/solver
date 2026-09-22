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
import time
from types import FrameType

from sqlalchemy import text

from app.core import logs
from app.core.db import SessionLocal
from app.solve.service import claim_next, execute_run

logger = logging.getLogger("solver.worker")

POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))
# Silence longer than this means the worker is gone. Short enough that a
# crashed solve is noticed; long enough that a slow heartbeat is not a theft.
STALE_AFTER_SECONDS = int(os.environ.get("WORKER_STALE_AFTER_SECONDS", "20"))

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
    org_id = db.execute(
        text("SELECT organization_id FROM run WHERE id = :r"), {"r": run_id}
    ).scalar_one_or_none()
    logs.bind(run_id=run_id, org_id=str(org_id) if org_id else None)
    log = logs.get("solver.worker")
    log.info("run claimed")
    try:
        outcome = execute_run(db, run_id)
        log.info("run settled", status=outcome.status, objective=outcome.objective)
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
        logs.clear()
    return run_id


def main() -> None:  # pragma: no cover -- the loop itself
    logs.configure("worker")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    db = SessionLocal()
    try:
        reclaim_stale(db)
        logger.info("worker ready; polling every %ss", POLL_SECONDS)
        while not _stop:
            if work_once(db) is None:
                time.sleep(POLL_SECONDS)
    finally:
        db.close()
        logger.info("worker stopped")


if __name__ == "__main__":  # pragma: no cover
    main()
