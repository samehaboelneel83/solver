"""The solver worker: claim a queued run, solve it, repeat.

Run it with `python -m app.worker`. Several may run at once — `claim_next`
uses `FOR UPDATE SKIP LOCKED`, so each takes a different run and none waits
on another.

**Why a worker at all.** Solving used to happen inside the HTTP request,
which capped a model at whatever a request may take and held a web worker for
the duration. A run row has carried `queued_at`, `started_at` and
`finished_at` since migration 0007, so the shape was always meant for this;
this is the process that fills them in.

**What it does not do yet**, stated so nobody assumes otherwise: no
back-off beyond a fixed poll, no heartbeat, no cancellation. A run whose
worker dies mid-solve stays `running` until `reclaim_stale()` puts it back —
which happens at start-up, not continuously.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from types import FrameType

from sqlalchemy import text

from app.core.db import SessionLocal
from app.solve.service import claim_next, execute_run

logger = logging.getLogger("solver.worker")

POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))
# A run still `running` after this long has lost its worker. Generous, because
# reclaiming one that is merely slow would solve it twice.
STALE_AFTER_MINUTES = int(os.environ.get("WORKER_STALE_AFTER_MINUTES", "30"))

_stop = False


def _request_stop(signum: int, _frame: FrameType | None) -> None:
    """Finish the run in hand, then exit. Killing mid-solve would leave a row
    `running` with nothing working on it."""
    global _stop
    _stop = True
    logger.info("signal %s received; stopping after the current run", signum)


def reclaim_stale(db) -> int:
    """Put runs whose worker died back in the queue.

    At start-up only: a crash leaves `running` rows nobody owns, and without
    this they are invisible work that never completes. The run keeps its
    dataset, so re-solving answers the same frozen question.
    """
    reclaimed = db.execute(
        text(
            "UPDATE run SET status = 'queued', started_at = NULL"
            " WHERE status = 'running'"
            "   AND started_at < now() - make_interval(mins => :mins)"
            " RETURNING id"
        ),
        {"mins": STALE_AFTER_MINUTES},
    ).scalars().all()
    db.commit()
    if reclaimed:
        logger.warning("requeued %d run(s) left running by a stopped worker: %s",
                       len(reclaimed), reclaimed)
    return len(reclaimed)


def work_once(db) -> int | None:
    """Claim and solve one run. Returns its id, or None when the queue is
    empty."""
    run_id = claim_next(db)
    if run_id is None:
        return None
    logger.info("run %s: solving", run_id)
    try:
        outcome = execute_run(db, run_id)
        logger.info("run %s: %s (objective %s)", run_id, outcome.status, outcome.objective)
    except Exception:
        # A claimed run that raises would otherwise stay `running` for ever,
        # and the next worker would skip it. Record the failure on the run.
        db.rollback()
        logger.exception("run %s: failed", run_id)
        db.execute(
            text(
                "UPDATE run SET status = 'error', error = :e, finished_at = now()"
                " WHERE id = :r"
            ),
            {"e": "the worker failed while solving; see the worker log", "r": run_id},
        )
        db.commit()
    return run_id


def main() -> None:  # pragma: no cover -- the loop itself
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
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
