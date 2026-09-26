"""Execution-attempt fencing (OAAS S03)."""

from __future__ import annotations

from sqlalchemy import text

from app.solve.service import _owns_attempt, claim_next, enqueue_run, run_attempt
from tests.test_v1_problem_run import (  # noqa: F401
    db,
    make_domain,
    make_model_version,
    make_problem,
    make_scenario,
)


def test_claim_bumps_execution_attempt(db):
    domain = make_domain(db, "fence")
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, ir={"version": 1, "sets": [], "parameters": {}, "variables": {}, "constraints": [], "objective": {"sense": "minimize", "terms": []}})
    scenario = make_scenario(db, problem, version)
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=1, reuse=False)
    assert run_attempt(db, run_id) == 0
    assert claim_next(db) == run_id
    assert run_attempt(db, run_id) == 1
    assert _owns_attempt(db, run_id, 1)
    assert not _owns_attempt(db, run_id, 0)
    # Simulate reclaim then re-claim.
    db.execute(
        text(
            "UPDATE run SET status = 'queued', started_at = NULL, heartbeat_at = NULL WHERE id = :r"
        ),
        {"r": run_id},
    )
    db.commit()
    assert claim_next(db) == run_id
    assert run_attempt(db, run_id) == 2
    assert not _owns_attempt(db, run_id, 1)
