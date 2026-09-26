"""Nightly model CI (queue R32): every problem's cases re-asked of its published version with the
result cache off, so a solver or library change that moves an answer is caught."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.solve import suite
from app.solve.result import Solution
from app.solve.service import claim_next, execute_run
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_diagnose import _scenario_for
from tests.test_solve import _feasible
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _plan(db):
    from app.solve.service import enqueue_run

    version, _ = _feasible(db)
    run = enqueue_run(db, _scenario_for(db, version), time_limit=10.0, reuse=False)
    assert claim_next(db) == run
    execute_run(db, run)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    return problem, version, run


def _case(db, problem, run, name="two shifts"):
    return suite.from_run(db, run, name, "test")


def _worse_sandbox(target, kwargs, **opts):
    compiled = kwargs["compiled"]
    return (
        Solution(
            status="optimal",
            optimal=True,
            objective=99,
            assignments={k: 1 for k in compiled.variables},
            wall_seconds=0.01,
            solver="fake-upgrade",
        ),
        None,
    )


def test_nightly_reasks_every_case_of_the_published_version(db, empty_queue):
    problem, version, run = _plan(db)
    case_id = _case(db, problem, run)
    db.commit()

    rows = suite.nightly(db, night=date(2026, 9, 26))
    assert len(rows) == 1
    assert rows[0]["case_id"] == case_id and rows[0]["model_version_id"] == version
    assert rows[0]["passed"] is True and rows[0]["status"] == "optimal"
    stored = db.execute(
        text("SELECT passed, status FROM suite_nightly WHERE night = :n AND case_id = :c"),
        {"n": date(2026, 9, 26), "c": case_id},
    ).mappings().one()
    assert stored["passed"] is True and stored["status"] == "optimal"


def test_a_fake_upgrade_that_moves_the_objective_fails_the_night(db, empty_queue):
    """A monkeypatched sandbox that returns a worse objective is what a library upgrade looks like."""
    problem, version, run = _plan(db)
    _case(db, problem, run)
    db.commit()

    with patch("app.solve.sandbox.run", side_effect=_worse_sandbox):
        rows = suite.nightly(db, night=date(2026, 9, 26))
    assert rows[0]["passed"] is False
    assert any("objective is 99" in r for r in rows[0]["reasons"])
    # Nightly never puts a version into use or takes one out of use.
    assert db.execute(
        text("SELECT count(*) FROM scenario WHERE problem_id = :p AND name NOT LIKE 'checks:%'"),
        {"p": problem},
    ).scalar_one() >= 1


def test_a_case_that_passed_yesterday_and_fails_today_is_a_red_row(db, empty_queue, client, auth_headers):
    problem, version, run = _plan(db)
    case_id = _case(db, problem, run)
    db.commit()
    yesterday = date(2026, 9, 25)
    today = date(2026, 9, 26)
    suite.nightly(db, night=yesterday)

    with patch("app.solve.sandbox.run", side_effect=_worse_sandbox):
        suite.nightly(db, night=today)

    checks = suite.version_checks(db, version)
    row = next(c for c in checks["cases"] if c["case_id"] == case_id)
    assert row["nightly_regressed"] is True
    assert any("objective is 99" in r for r in row["reasons"])
    body = client.get(f"/api/v1/model-versions/{version}/checks", headers=auth_headers).json()
    assert next(c for c in body["cases"] if c["case_id"] == case_id)["nightly_regressed"] is True


def test_nightly_does_not_reuse_a_cached_answer(db, empty_queue):
    """A suite run that would otherwise hit the result cache still solves: the night is the check."""
    problem, version, run = _plan(db)
    _case(db, problem, run)
    db.commit()
    suite.nightly(db, night=date(2026, 9, 25))
    suite.nightly(db, night=date(2026, 9, 26))
    suite_runs = db.execute(
        text(
            "SELECT id, reused_from FROM run WHERE purpose = 'suite'"
            "  AND (params ->> 'model_version_id')::bigint = :v ORDER BY id"
        ),
        {"v": version},
    ).mappings().all()
    assert len(suite_runs) >= 2
    assert all(r["reused_from"] is None for r in suite_runs)


def test_fast_subset_caps_the_time_allowance(db, empty_queue):
    problem, version, run = _plan(db)
    case_id = _case(db, problem, run)
    db.execute(
        text("UPDATE suite_case SET expect = expect || CAST(:e AS jsonb) WHERE id = :c"),
        {"c": case_id, "e": '{"max_seconds": 120}'},
    )
    db.commit()
    rows = suite.nightly(db, night=date(2026, 9, 26), max_seconds=5)
    assert rows[0]["passed"] is True
    limit = db.execute(
        text(
            "SELECT (params ->> 'time_limit_s')::float FROM run"
            " WHERE purpose = 'suite' AND (params ->> 'case_id')::bigint = :c"
            " ORDER BY id DESC LIMIT 1"
        ),
        {"c": case_id},
    ).scalar_one()
    assert limit == 5.0
