"""Expired run events are pruned (migration 0041, app.retention)."""

from __future__ import annotations

from sqlalchemy import text

from app.retention import prune_run_events
from app.seed import seed_workforce_demo
from app.solve.service import enqueue_run
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _run(db, scenario_id: int, *, status: str, days_ago: float | None, events: int = 3) -> int:
    run_id = enqueue_run(db, scenario_id, time_limit=5.0)
    db.execute(
        text(
            "UPDATE run SET status = CAST(:st AS run_status),"
            "               finished_at = CASE WHEN CAST(:d AS float8) IS NULL THEN NULL"
            "                                  ELSE now() - make_interval(secs => CAST(:d AS float8) * 86400) END"
            " WHERE id = :r"
        ),
        {"st": status, "d": days_ago, "r": run_id},
    )
    for seq in range(1, events + 1):
        db.execute(
            text("INSERT INTO run_event (run_id, seq, kind, payload) VALUES (:r, :s, 'stage', '{}')"),
            {"r": run_id, "s": seq},
        )
    db.commit()
    return run_id


def _events(db, run_id: int) -> int:
    return db.execute(text("SELECT count(*) FROM run_event WHERE run_id = :r"), {"r": run_id}).scalar_one()


def _set(db, scope: str, scope_id, value: str) -> None:
    db.execute(
        text(
            "INSERT INTO setting (scope, scope_id, key, value)"
            " VALUES (CAST(:s AS setting_scope), :i, 'run.event_retention_days', CAST(:v AS jsonb))"
            " ON CONFLICT (scope, scope_id, key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"s": scope, "i": scope_id, "v": value},
    )
    db.commit()


def test_events_go_thirty_days_after_the_run_settles_by_default(db, empty_queue):  # noqa: F811
    seeded = seed_workforce_demo(db)
    old = _run(db, seeded["scenario_id"], status="optimal", days_ago=31)
    recent = _run(db, seeded["scenario_id"], status="optimal", days_ago=29)
    running = _run(db, seeded["scenario_id"], status="running", days_ago=None)

    assert prune_run_events(db) >= 3
    assert _events(db, old) == 0
    assert _events(db, recent) == 3
    assert _events(db, running) == 3
    # The run itself stays: only its curve goes.
    assert db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": old}).scalar_one() == "optimal"


def test_a_domain_can_keep_its_curves_for_a_shorter_or_longer_time(db, empty_queue):  # noqa: F811
    seeded = seed_workforce_demo(db)
    week_old = _run(db, seeded["scenario_id"], status="infeasible", days_ago=8)
    try:
        _set(db, "domain", seeded["domain_id"], "7")
        prune_run_events(db)
        assert _events(db, week_old) == 0

        forty = _run(db, seeded["scenario_id"], status="optimal", days_ago=40)
        _set(db, "problem", seeded["problem_id"], "0")  # the problem keeps them for ever
        prune_run_events(db)
        assert _events(db, forty) == 3
    finally:
        db.execute(text("DELETE FROM setting WHERE key = 'run.event_retention_days'"))
        db.commit()


def test_pruning_deletes_in_batches_until_nothing_is_left(db, empty_queue):  # noqa: F811
    seeded = seed_workforce_demo(db)
    runs = [_run(db, seeded["scenario_id"], status="optimal", days_ago=60, events=4) for _ in range(3)]
    assert prune_run_events(db, batch=5) == 12
    assert all(_events(db, run) == 0 for run in runs)
    assert prune_run_events(db) == 0
