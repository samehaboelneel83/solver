"""One `run_fact` row in ClickHouse per settled run (target roadmap Phase 8).

Written to `analytics_test` (conftest), never the live `analytics`."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.analytics import publish_facts
from app.clickhouse_schema import create_analytics_schema
from app.core.db import get_clickhouse_client
from app.seed import seed_workforce_demo
from app.solve.service import cancel_run, enqueue_run
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture
def clickhouse():
    client = get_clickhouse_client()
    assert client.database.endswith("_test"), client.database
    create_analytics_schema(client)
    create_analytics_schema(client)  # twice: the added column's ALTER is idempotent
    client.command("TRUNCATE TABLE run_fact")
    return client


def _facts(client, run_id: int) -> list[dict]:
    result = client.query(f"SELECT * FROM run_fact FINAL WHERE run_id = {int(run_id)}")
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


def _written(db, run_id: int):
    return db.execute(text("SELECT fact_written_at FROM run WHERE id = :r"), {"r": run_id}).scalar_one()


def test_a_settled_run_becomes_one_fact(db, empty_queue, clickhouse):  # noqa: F811
    seeded = seed_workforce_demo(db)
    run_id = enqueue_run(db, seeded["scenario_id"], time_limit=10.0)
    assert work_once(db) == run_id
    run = db.execute(
        text("SELECT status, solver, organization_id, objective, gap FROM run WHERE id = :r"), {"r": run_id}
    ).mappings().one()

    assert publish_facts(db, clickhouse) >= 1
    assert _written(db, run_id) is not None

    (fact,) = _facts(clickhouse, run_id)
    assert fact["status"] == run["status"] and fact["solver"] == run["solver"] == "cp-sat"
    assert str(fact["organization_id"]) == str(run["organization_id"])
    assert fact["problem_id"] == seeded["problem_id"] and fact["scenario_id"] == seeded["scenario_id"]
    assert fact["model_class"] == "IP" and fact["variables"] > 0 and fact["rules"] > 0
    assert len(fact["trace_id"]) == 32 and fact["time_limit_s"] == 10.0
    assert fact["queue_wait_s"] is not None and fact["queue_wait_s"] >= 0
    if run["objective"] is not None:
        assert fact["objective"] == pytest.approx(float(run["objective"]))

    # The fingerprint the run stored, as JSON, readable in ClickHouse.
    import json

    stored = db.execute(text("SELECT params->'fingerprint' FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    assert json.loads(fact["fingerprint"]) == stored and stored["version"] == 1
    assert stored["variables"] == fact["variables"] and stored["rows"] == fact["rules"]
    (rows,) = clickhouse.query(
        f"SELECT JSONExtractInt(fingerprint, 'rows') FROM run_fact FINAL WHERE run_id = {int(run_id)}"
    ).result_rows[0]
    assert rows == stored["rows"]

    # Written once: the next sweep has nothing of it to do.
    publish_facts(db, clickhouse)
    assert len(_facts(clickhouse, run_id)) == 1


def test_a_fact_written_twice_is_still_one_row(db, empty_queue, clickhouse):  # noqa: F811
    """A crash between the insert and the stamp writes it again next time."""
    seeded = seed_workforce_demo(db)
    run_id = enqueue_run(db, seeded["scenario_id"], time_limit=10.0)
    work_once(db)
    publish_facts(db, clickhouse)
    db.execute(text("UPDATE run SET fact_written_at = NULL WHERE id = :r"), {"r": run_id})
    db.commit()
    publish_facts(db, clickhouse)
    assert len(_facts(clickhouse, run_id)) == 1


def test_a_run_cancelled_before_any_worker_took_it_has_a_fact_too(db, empty_queue, clickhouse):  # noqa: F811
    seeded = seed_workforce_demo(db)
    run_id = enqueue_run(db, seeded["scenario_id"], time_limit=10.0)
    assert cancel_run(db, run_id) == "cancelled"
    publish_facts(db, clickhouse)
    (fact,) = _facts(clickhouse, run_id)
    assert fact["status"] == "cancelled" and fact["started_at"] is None and fact["variables"] is None


def test_a_clickhouse_failure_leaves_the_run_for_the_next_sweep(db, empty_queue, clickhouse):  # noqa: F811
    class Down:
        def insert(self, *_args, **_kwargs):
            raise ConnectionError("clickhouse is down")

    seeded = seed_workforce_demo(db)
    run_id = enqueue_run(db, seeded["scenario_id"], time_limit=10.0)
    work_once(db)
    assert publish_facts(db, Down()) == 0
    assert _written(db, run_id) is None
    assert publish_facts(db, clickhouse) >= 1
    assert len(_facts(clickhouse, run_id)) == 1
