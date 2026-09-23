"""The feed-blend, load-balance and workshop templates, applied and solved.

These are the product's only demonstrations of linear and quadratic solving,
so what they must show is pinned here end to end: applying each builds a
domain and a model the validator accepts, and solving it lands on the class,
the solver and the answer worked out by hand in `app.showcase`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.showcase import FEED_BLEND, LOAD_BALANCE, WORKSHOP, ensure_showcase_templates
from app.solve.service import enqueue_run
from app.worker import work_once
from tests.test_api_templates import auth_headers, ensure_admin_seeded  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture(autouse=True)
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


@pytest.fixture
def applied(db, auth_headers):
    """Apply a showcase template into a fresh domain; clean the domain up."""
    domains: list[int] = []

    def apply(name: str) -> dict:
        template = ensure_showcase_templates(db)[name]
        response = TestClient(app).post(
            f"/api/v1/templates/{template}/apply",
            json={"domain_name": f"{name}-{uuid.uuid4().hex[:8]}"},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        domains.append(body["domain_id"])
        return body

    yield apply
    db.execute(text("DELETE FROM run"))
    for domain in domains:
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
    db.commit()


def _solve(db, scenario: int) -> dict:
    run_id = enqueue_run(db, scenario, time_limit=20.0)
    work_once(db)
    return dict(
        db.execute(
            text("SELECT status, solver, optimality, objective, error, params FROM run WHERE id = :r"),
            {"r": run_id},
        ).mappings().one()
    )


def test_ensuring_the_templates_twice_keeps_one_row_each(db):
    first = ensure_showcase_templates(db)
    second = ensure_showcase_templates(db)

    assert first == second
    count = db.execute(
        text("SELECT count(*) FROM template WHERE name IN (:a, :b, :c)"),
        {"a": FEED_BLEND, "b": LOAD_BALANCE, "c": WORKSHOP},
    ).scalar_one()
    assert count == 3


def test_feed_blend_is_a_linear_program_with_a_fractional_answer(db, applied):
    body = applied(FEED_BLEND)

    row = _solve(db, body["scenario_id"])

    assert row["status"] == "optimal", row["error"]
    assert row["solver"] == "glop"
    assert row["optimality"] == "global"
    # Bran is cheapest but fibrous and soy is protein-rich but dear; the
    # optimum sits where both the protein floor and the fibre cap bind:
    # soy = 8.375 / 0.315 kg, bran = 37.5 - soy / 2, maize the rest.
    assert abs(row["objective"] - Decimal("43.5317")) < Decimal("0.001")


def test_load_balance_is_a_convex_qp_solved_to_its_global_optimum(db, applied):
    body = applied(LOAD_BALANCE)

    row = _solve(db, body["scenario_id"])

    assert row["status"] == "optimal", row["error"]
    assert row["solver"] == "highs"
    assert row["optimality"] == "global"
    # Chloe is capped at 15 and Dev at 30; Ana and Ben share the other 75.
    assert abs(row["objective"] - Decimal("3937.5")) < Decimal("0.01")


def test_workshop_is_scheduled_on_cp_sat_in_the_makespan_worked_by_hand(db, applied):
    body = applied(WORKSHOP)

    row = _solve(db, body["scenario_id"])

    assert row["status"] == "optimal", row["error"]
    assert row["solver"] == "cp-sat"
    # Johnson's rule: B first (cut 1 < weld 4), then A and C; welding's 8
    # hours cannot start before B's 1-hour cut, so 9 is also a bound.
    assert row["objective"] == 9
    version = db.execute(
        text("SELECT ir_version FROM template WHERE name = :n"), {"n": WORKSHOP}
    ).scalar_one()
    assert version == "2"


def test_workshop_welds_no_job_before_it_is_cut(db, applied):
    """The route is a relationship the rule walks: were it lost in the
    snapshot, the welder alone would bound the makespan at 8, not 9."""
    body = applied(WORKSHOP)
    run_id = enqueue_run(db, body["scenario_id"], time_limit=20.0)
    work_once(db)
    rows = db.execute(
        text("SELECT constraint_id, satisfied FROM constraint_result WHERE run_id = :r ORDER BY constraint_id"),
        {"r": run_id},
    ).all()
    assert [tuple(r) for r in rows] == [("c_makespan", True), ("c_one_at_a_time", True), ("c_route", True)]
    objective = db.execute(text("SELECT objective FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    assert objective == 9
