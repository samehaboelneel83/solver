"""The queue: submitting a run, claiming it, and solving it elsewhere.

The properties worth pinning are the ones that only show up with two workers
or a crash:

- **two workers never take the same run**, and neither waits on the other —
  `FOR UPDATE SKIP LOCKED`, tested with two real connections rather than by
  reading the SQL;
- **a run whose worker died is reclaimed**, or it is invisible work that
  never completes;
- **the data is frozen at submit**, not at solve, so a run answers the
  question as it was asked even if the domain changes while it waits.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.seed import seed_workforce_demo
from app.solve.service import claim_next, enqueue_run, execute_run
from app.worker import reclaim_stale, work_once
from tests.test_v1_problem_run import db  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def empty_queue(db):
    """Submitting commits -- it has to, or a worker in another process could
    not see the run -- so the usual rollback does not undo it. Each test here
    starts from an empty queue, otherwise one test's leftovers are the next
    one's claim.
    """
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _status(db, run_id: int) -> str:
    return db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one()


def test_a_submitted_run_is_queued_with_its_data_already_frozen(db):
    seeded = seed_workforce_demo(db)

    run_id = enqueue_run(db, seeded["scenario_id"], time_limit=15.0)

    row = db.execute(
        text("SELECT status, dataset_id, started_at, finished_at FROM run WHERE id = :r"),
        {"r": run_id},
    ).mappings().one()
    assert row["status"] == "queued"
    # Frozen at submit: the answer must be about the data the person was
    # looking at, not whatever it becomes while the run waits.
    assert row["dataset_id"] is not None
    assert row["started_at"] is None and row["finished_at"] is None


def test_the_worker_solves_a_queued_run_and_records_the_answer(db):
    seeded = seed_workforce_demo(db)
    run_id = enqueue_run(db, seeded["scenario_id"], time_limit=30.0)

    claimed = work_once(db)

    assert claimed == run_id
    row = db.execute(
        text("SELECT status, objective, started_at, finished_at FROM run WHERE id = :r"),
        {"r": run_id},
    ).mappings().one()
    assert row["status"] in ("optimal", "feasible")
    assert row["objective"] is not None
    assert row["started_at"] is not None and row["finished_at"] is not None
    assert db.execute(
        text("SELECT count(*) FROM solution WHERE run_id = :r"), {"r": run_id}
    ).scalar_one() == 1


def test_an_empty_queue_is_not_an_error(db):
    assert work_once(db) is None


def test_runs_are_taken_oldest_first(db):
    seeded = seed_workforce_demo(db)
    first = enqueue_run(db, seeded["scenario_id"])
    second = enqueue_run(db, seeded["scenario_id"])

    assert claim_next(db) == first
    assert claim_next(db) == second


def test_two_workers_never_take_the_same_run(db):
    """The property `SKIP LOCKED` exists for, tested with two connections:
    a second worker takes the *next* run rather than waiting on the one
    already claimed, so neither blocks and neither duplicates."""
    seeded = seed_workforce_demo(db)
    first = enqueue_run(db, seeded["scenario_id"])
    second = enqueue_run(db, seeded["scenario_id"])

    worker_a = SessionLocal()
    worker_b = SessionLocal()
    try:
        claimed_a = claim_next(worker_a)
        claimed_b = claim_next(worker_b)

        assert {claimed_a, claimed_b} == {first, second}
        assert claimed_a != claimed_b
        # And a third worker finds nothing rather than re-taking one.
        worker_c = SessionLocal()
        try:
            assert claim_next(worker_c) is None
        finally:
            worker_c.close()
    finally:
        worker_a.close()
        worker_b.close()


def test_a_run_left_running_by_a_dead_worker_is_requeued(db):
    seeded = seed_workforce_demo(db)
    run_id = enqueue_run(db, seeded["scenario_id"])
    claim_next(db)
    assert _status(db, run_id) == "running"
    # Pretend the worker died an hour ago.
    db.execute(
        text("UPDATE run SET started_at = now() - interval '1 hour' WHERE id = :r"), {"r": run_id}
    )
    db.commit()

    assert reclaim_stale(db) == 1

    assert _status(db, run_id) == "queued"
    # It keeps its dataset, so re-solving answers the same frozen question.
    assert db.execute(
        text("SELECT dataset_id FROM run WHERE id = :r"), {"r": run_id}
    ).scalar_one() is not None


def test_a_run_still_solving_is_left_alone(db):
    """Reclaiming a slow run would solve it twice."""
    seeded = seed_workforce_demo(db)
    enqueue_run(db, seeded["scenario_id"])
    run_id = claim_next(db)

    assert reclaim_stale(db) == 0
    assert _status(db, run_id) == "running"


def test_a_run_the_compiler_cannot_express_is_recorded_not_retried(db):
    """A pre-contract model: the worker must record the reason and move on,
    or the queue would hand the same impossible run to every worker."""
    domain = db.execute(text("INSERT INTO domain (name) VALUES ('wq') RETURNING id")).scalar_one()
    problem = db.execute(
        text("INSERT INTO problem (domain_id, name) VALUES (:d, 'p') RETURNING id"), {"d": domain}
    ).scalar_one()
    version = db.execute(
        text("INSERT INTO model_version (problem_id, ir) VALUES (:p, :ir) RETURNING id"),
        {
            "p": problem,
            "ir": '{"version": 1, "sets": [], "parameters": {}, "variables": {},'
            ' "constraints": [{"id": "c_old", "note": "never expressed"}]}',
        },
    ).scalar_one()
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name)"
            " VALUES (:p, :v, 's') RETURNING id"
        ),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    run_id = enqueue_run(db, scenario)

    work_once(db)

    row = db.execute(
        text("SELECT status, error FROM run WHERE id = :r"), {"r": run_id}
    ).mappings().one()
    assert row["status"] == "error"
    assert "no expression" in row["error"]
    # And the queue is empty: a failed run is finished, not retried for ever.
    assert work_once(db) is None


def test_execute_uses_the_dataset_frozen_at_submit_not_todays_data(db):
    """The point of freezing at submit. An entity added after submitting must
    not appear in the answer -- the run was asked about the data as it was."""
    seeded = seed_workforce_demo(db)
    run_id = enqueue_run(db, seeded["scenario_id"], time_limit=30.0)

    employee_type = db.execute(
        text(
            "SELECT id FROM entity_type WHERE domain_id = :d AND name = 'employee'"
        ),
        {"d": seeded["domain_id"]},
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO entity (entity_type_id, key, label, attrs)"
            " VALUES (:t, 'zz_late', 'Added after submitting',"
            "         '{\"full_name\": \"Added Late\", \"hours_per_week\": 40}')"
        ),
        {"t": employee_type},
    )
    db.commit()

    claim_next(db)
    outcome = execute_run(db, run_id)

    roster = outcome.assignments.get("assign", [])
    assert roster, "the run should still have an answer"
    assert not any(entry[0] == "zz_late" for entry in roster)
