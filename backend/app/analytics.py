"""One `run_fact` row in ClickHouse for every settled run (target roadmap Phase 8).

The facts Phase 17's learned selector will train on, and what an analyst
queries without touching the transactional database: which solver took
which class of model, how it ended, the gap, how long it waited and ran,
how big the model was, its fingerprint (`app.solve.fingerprint`, JSON --
empty for a run that never compiled, e.g. cancelled before a worker took
it), and the trace to follow when a number looks wrong.

Written by the worker from an outbox (`run.fact_written_at`, migration
0040), not at the moment a run settles: runs settle in more than one place,
and ClickHouse can be down. `publish_facts` takes a batch of settled,
unwritten runs (`FOR UPDATE SKIP LOCKED`, so two workers never write the
same one), inserts them, and stamps them. The table is a
`ReplacingMergeTree` keyed by run, so a run written twice -- a crash between
the insert and the stamp -- is still one row once merged (`FINAL` reads it
so now).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TABLE = "run_fact"

COLUMNS = [
    "run_id", "organization_id", "domain_id", "problem_id", "scenario_id", "model_version_id",
    "solver", "model_class", "status", "optimality",
    "objective", "best_bound", "gap", "wall_time_s", "time_limit_s", "workers", "seed",
    "variables", "rules", "fingerprint", "trace_id",
    "queued_at", "started_at", "finished_at", "queue_wait_s", "written_at",
]

_PENDING = text(
    """
    SELECT r.id AS run_id, r.organization_id, p.domain_id, s.problem_id, r.scenario_id,
           s.model_version_id, r.solver, coalesce(r.params->>'classified_as', '') AS model_class,
           r.status::text AS status, coalesce(r.optimality, '') AS optimality,
           r.objective::float8 AS objective, r.best_bound, r.gap, r.wall_time_s,
           coalesce((r.params->>'time_limit_s')::float8, 0) AS time_limit_s,
           coalesce((r.params->>'workers')::int, 0) AS workers, r.seed,
           compiled.variables, compiled.rules,
           coalesce((r.params->'fingerprint')::text, '') AS fingerprint,
           coalesce(split_part(r.params->'trace'->>'traceparent', '-', 2), '') AS trace_id,
           r.queued_at, r.started_at, r.finished_at,
           extract(epoch FROM r.started_at - r.queued_at)::float8 AS queue_wait_s,
           now() AS written_at
      FROM run r
      JOIN scenario s ON s.id = r.scenario_id
      JOIN problem p ON p.id = s.problem_id
      LEFT JOIN LATERAL (
            SELECT (e.payload->>'variables')::int AS variables, (e.payload->>'rules')::int AS rules
              FROM run_event e
             WHERE e.run_id = r.id AND e.kind = 'stage' AND e.payload->>'stage' = 'compiled'
             ORDER BY e.seq DESC LIMIT 1
      ) compiled ON true
     WHERE r.fact_written_at IS NULL AND r.status NOT IN ('queued', 'running')
     ORDER BY r.id
     LIMIT :n
     FOR UPDATE OF r SKIP LOCKED
    """
)


def publish_facts(db: Session, client=None, *, batch: int = 500, raise_errors: bool = False) -> int:
    """Write up to `batch` settled runs' facts; return how many. A ClickHouse
    failure is logged and leaves them for the next sweep -- or, with
    `raise_errors`, is raised for a caller that backs off (the worker)."""
    rows = db.execute(_PENDING, {"n": batch}).mappings().all()
    if not rows:
        db.rollback()
        return 0
    try:
        if client is None:
            from app.core.db import get_clickhouse_client

            client = get_clickhouse_client()
        client.insert(TABLE, [_values(row) for row in rows], column_names=COLUMNS)
    except Exception:
        db.rollback()
        if raise_errors:
            raise
        logger.warning("could not write %d run fact(s); they wait for the next sweep", len(rows), exc_info=True)
        return 0
    db.execute(
        text("UPDATE run SET fact_written_at = now() WHERE id = ANY(:ids)"),
        {"ids": [row["run_id"] for row in rows]},
    )
    db.commit()
    return len(rows)


def _values(row: Any) -> list:
    return [row[column] for column in COLUMNS]
