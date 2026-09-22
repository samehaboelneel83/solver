"""Pruning what is not kept for ever (target roadmap Phase 8).

`prune_run_events` deletes the progress events of runs that settled more
than `run.event_retention_days` ago (migration 0041). The days are resolved
per run, at every level of migration 0014 -- the run's problem, then its
domain, then the platform, then the key's default -- in one statement, so
a domain that keeps its curves longer is honoured without a query per run.
0 at the level that applies keeps them for ever. A queued or running run's
events are never touched, however old the run.

Deleted in batches, so pruning a large backlog does not hold one long
transaction on a table the live chart reads.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

KEY = "run.event_retention_days"

_BATCH = text(
    """
    WITH kept AS (
        SELECT r.id AS run_id,
               r.finished_at,
               coalesce(
                   (SELECT (st.value #>> '{}')::numeric FROM setting st
                     WHERE st.scope = 'problem' AND st.scope_id = s.problem_id AND st.key = :key),
                   (SELECT (st.value #>> '{}')::numeric FROM setting st
                     WHERE st.scope = 'domain' AND st.scope_id = p.domain_id AND st.key = :key),
                   (SELECT (st.value #>> '{}')::numeric FROM setting st
                     WHERE st.scope = 'platform' AND st.key = :key),
                   (SELECT (k.default_value #>> '{}')::numeric FROM setting_key k WHERE k.key = :key)
               ) AS days
          FROM run r
          JOIN scenario s ON s.id = r.scenario_id
          JOIN problem p ON p.id = s.problem_id
         WHERE r.status NOT IN ('queued', 'running') AND r.finished_at IS NOT NULL
    ),
    doomed AS (
        SELECT e.run_id, e.seq
          FROM run_event e
          JOIN kept ON kept.run_id = e.run_id
         WHERE kept.days > 0
           AND kept.finished_at < now() - make_interval(secs => kept.days * 86400)
         LIMIT :n
    )
    DELETE FROM run_event e USING doomed
     WHERE e.run_id = doomed.run_id AND e.seq = doomed.seq
    """
)


def prune_run_events(db: Session, *, batch: int = 5000) -> int:
    """Delete expired events; return how many."""
    total = 0
    while True:
        deleted = db.execute(_BATCH, {"key": KEY, "n": batch}).rowcount
        db.commit()
        total += deleted
        if deleted < batch:
            break
    if total:
        logger.info("pruned %d run event(s) past their retention", total)
    return total
