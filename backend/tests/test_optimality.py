"""What an answer may claim (migration 0028).

`optimal` from a local solver and `optimal` from a global one are different
claims, and on a nonconvex model the difference is whether a better answer
exists. These tests pin that the claim comes from what each backend
*declares*, never from a guess, and that the database refuses a claim with no
answer behind it.
"""

from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.solve.backends import CP_SAT, REGISTRY, optimality_of
from app.solve.service import enqueue_run
from app.worker import work_once
from tests.test_solve import _feasible  # noqa: F401
from tests.test_v1_problem_run import (  # noqa: F401
    _data,
    _snapshot,
    db,
    make_attribute_def,
    make_domain,
    make_entity,
    make_entity_type,
    make_model_version,
    make_parameter_def,
    make_parameter_value,
    make_problem,
)


@pytest.fixture(autouse=True)
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _scenario(db, version: int) -> int:
    problem = db.execute(
        text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}
    ).scalar_one()
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name)"
            " VALUES (:p, :v, 'base') RETURNING id"
        ),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    return scenario


# -- the declaration ----------------------------------------------------------


def test_every_backend_declares_what_its_optimum_proves():
    """Required, not defaulted: a backend added without saying would be a
    local solver reporting "optimal" with nothing to tell it apart."""
    for backend in REGISTRY:
        assert backend.proves in ("global", "local", "approximate"), backend.name
    field = next(f for f in dataclasses.fields(CP_SAT) if f.name == "proves")
    assert field.default is dataclasses.MISSING


def test_every_backend_today_proves_the_global_optimum_but_pdlp():
    """They solve convex models exactly, so the optimum each proves is the
    global one -- except PDLP, whose optimum holds to a tolerance (migration
    0051). A local solver joining the registry changes this test on purpose."""
    assert {backend.name: backend.proves for backend in REGISTRY} == {
        **{backend.name: "global" for backend in REGISTRY}, "pdlp": "approximate"
    }


def test_the_claim_follows_the_status_and_the_backend():
    local = dataclasses.replace(CP_SAT, proves="local")
    assert optimality_of(CP_SAT, "optimal") == "global"
    assert optimality_of(local, "optimal") == "local"
    # Found before the clock ran out: an answer, but no claim to be best.
    assert optimality_of(CP_SAT, "feasible") == "none"
    # No answer, no claim.
    for status in ("infeasible", "unknown", "error"):
        assert optimality_of(CP_SAT, status) is None


# -- through a run ------------------------------------------------------------


def test_an_optimal_run_records_that_its_answer_is_the_global_best(db):
    version, _ = _feasible(db, demand_value=1)
    run_id = enqueue_run(db, _scenario(db, version), time_limit=20.0)

    work_once(db)

    row = db.execute(
        text("SELECT status, optimality FROM run WHERE id = :r"), {"r": run_id}
    ).mappings().one()
    assert row["status"] == "optimal"
    assert row["optimality"] == "global"


def test_an_infeasible_run_makes_no_claim(db):
    version, _ = _feasible(db, demand_value=2, hours=8)
    run_id = enqueue_run(db, _scenario(db, version), time_limit=20.0)

    work_once(db)

    row = db.execute(
        text("SELECT status, optimality FROM run WHERE id = :r"), {"r": run_id}
    ).mappings().one()
    assert row["status"] == "infeasible"
    assert row["optimality"] is None


# -- what the database refuses -----------------------------------------------


def test_the_database_refuses_a_claim_with_no_answer_behind_it(db):
    """A run that errored cannot be "the global optimum" of anything, whoever
    writes the row."""
    version, _ = _feasible(db, demand_value=1)
    run_id = enqueue_run(db, _scenario(db, version), time_limit=20.0)
    db.execute(text("UPDATE run SET status = 'error' WHERE id = :r"), {"r": run_id})
    db.commit()

    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE run SET optimality = 'global' WHERE id = :r"), {"r": run_id})
        db.commit()
    db.rollback()


def test_the_database_refuses_a_claim_it_has_no_word_for(db):
    version, _ = _feasible(db, demand_value=1)
    run_id = enqueue_run(db, _scenario(db, version), time_limit=20.0)
    work_once(db)

    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE run SET optimality = 'probably' WHERE id = :r"), {"r": run_id})
        db.commit()
    db.rollback()
