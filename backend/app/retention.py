"""Pruning what is not kept for ever (target roadmap Phase 8; queue R37).

`prune_run_events` deletes the progress events of runs that settled more
than `run.event_retention_days` ago (migration 0041).

`prune_runs` deletes settled runs past `run.retention_days` (default 365),
with their events, solutions and constraint results (queue R37).

The days are resolved per run -- problem, then domain, then platform, then
the key's default. 0 at the level that applies keeps them for ever. Queued
or running runs are never touched.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

KEY = "run.event_retention_days"
RUNS_KEY = "run.retention_days"

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


def prune_runs(db: Session, *, batch: int = 500) -> int:
    """Delete settled runs past ``run.retention_days``; return how many runs."""
    total = 0
    while True:
        doomed = db.execute(
            text(
                """
                WITH kept AS (
                    SELECT r.id AS run_id, r.finished_at,
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
                )
                SELECT run_id FROM kept
                 WHERE days > 0 AND finished_at < now() - make_interval(secs => days * 86400)
                 LIMIT :n
                """
            ),
            {"key": RUNS_KEY, "n": batch},
        ).scalars().all()
        if not doomed:
            break
        ids = list(doomed)
        db.execute(text("DELETE FROM run_event WHERE run_id = ANY(:ids)"), {"ids": ids})
        db.execute(text("DELETE FROM constraint_result WHERE run_id = ANY(:ids)"), {"ids": ids})
        db.execute(text("DELETE FROM solution WHERE run_id = ANY(:ids)"), {"ids": ids})
        deleted = db.execute(text("DELETE FROM run WHERE id = ANY(:ids)"), {"ids": ids}).rowcount
        db.commit()
        total += deleted
        if deleted < batch:
            break
    if total:
        logger.info("pruned %d run(s) past their retention", total)
    return total
