"""The result cache: a question already answered is not solved again (migration 0042).

The same model, the same frozen data, the same scenario patch and the same
deciding settings, proven globally optimal once, answer every later submit
of that question: a new run is recorded already finished, pointing at the
one that was solved, with its answer and its rules' results -- and nothing
is queued. Anything that could change the answer changes the key; anything
short of a proven optimum is never reused.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.api.runs import _read
from app.solve.service import claim_next, enqueue_run
from app.worker import work_once
from tests.test_diagnose import _scenario_for
from tests.test_solve import _feasible  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture(autouse=True)
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _row(db, run_id: int) -> dict:
    return dict(
        db.execute(
            text(
                "SELECT status, optimality, objective, wall_time_s, reused_from, cache_key, params"
                "  FROM run WHERE id = :r"
            ),
            {"r": run_id},
        ).mappings().one()
    )


def _solved(db, scenario: int, **kwargs) -> int:
    run_id = enqueue_run(db, scenario, time_limit=20.0, **kwargs)
    work_once(db)
    assert _row(db, run_id)["status"] == "optimal"
    return run_id


def test_a_proven_optimum_answers_the_same_question_without_a_solve(db):
    version, _ = _feasible(db)
    scenario = _scenario_for(db, version)
    first = _solved(db, scenario)

    # A different time limit is the same question: a proven optimum does
    # not depend on how long it was given.
    second = enqueue_run(db, scenario, time_limit=5.0)

    row, original = _row(db, second), _row(db, first)
    assert second != first
    assert row["status"] == "optimal" and row["optimality"] == "global"
    assert row["reused_from"] == first and row["cache_key"] == original["cache_key"]
    assert row["objective"] == original["objective"] and row["wall_time_s"] == 0
    assert row["params"]["reused_from"] == first and row["params"]["time_limit_s"] == 5.0
    # Nothing was queued: no worker will solve it.
    assert claim_next(db) is None
    # The answer and the rules' results came with it.
    solutions = db.execute(
        text("SELECT run_id, assignments FROM solution WHERE run_id IN (:a, :b)"), {"a": first, "b": second}
    ).all()
    assert len(solutions) == 2 and solutions[0][1] == solutions[1][1]
    results = [
        db.execute(
            text("SELECT constraint_id, satisfied, slack FROM constraint_result WHERE run_id = :r ORDER BY 1"),
            {"r": run},
        ).all()
        for run in (first, second)
    ]
    assert results[0] and results[0] == results[1]
    # And the API says so.
    assert _read(db, second).reused_from == first
    assert _read(db, first).reused_from is None


def test_a_different_seed_or_no_reuse_is_solved(db):
    version, _ = _feasible(db)
    scenario = _scenario_for(db, version)
    _solved(db, scenario, seed=1)

    other_seed = enqueue_run(db, scenario, time_limit=20.0, seed=2)
    asked_fresh = enqueue_run(db, scenario, time_limit=20.0, seed=1, reuse=False)

    for run_id in (other_seed, asked_fresh):
        assert _row(db, run_id)["status"] == "queued" and _row(db, run_id)["reused_from"] is None


def test_a_different_patch_is_a_different_question(db):
    version, _ = _feasible(db)
    _solved(db, _scenario_for(db, version))
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    relaxed = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name, patch)"
            " VALUES (:p, :v, 'relaxed', CAST('{\"disable\": [\"c_max_hours\"]}' AS jsonb)) RETURNING id"
        ),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()

    run_id = enqueue_run(db, relaxed, time_limit=20.0)

    assert _row(db, run_id)["status"] == "queued"


def test_an_infeasible_verdict_is_never_reused(db):
    """A "no answer" is derived again, with its explanation, not copied."""
    version, _ = _feasible(db, demand_value=2, hours=8)
    scenario = _scenario_for(db, version)
    first = enqueue_run(db, scenario, time_limit=20.0)
    work_once(db)
    assert _row(db, first)["status"] == "infeasible"

    second = enqueue_run(db, scenario, time_limit=20.0)

    assert _row(db, second)["status"] == "queued" and _row(db, second)["reused_from"] is None


def test_run_scenario_returns_a_reused_answer_rather_than_solving_it(db):
    from app.solve.service import run_scenario

    version, _ = _feasible(db)
    scenario = _scenario_for(db, version)
    first = run_scenario(db, scenario, time_limit=15.0)
    second = run_scenario(db, scenario, time_limit=15.0)

    assert second.run_id != first.run_id and second.dataset_id == first.dataset_id
    assert (second.status, second.objective, second.assignments) == (first.status, first.objective, first.assignments)
    assert _row(db, second.run_id)["reused_from"] == first.run_id
