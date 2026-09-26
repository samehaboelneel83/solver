"""A problem's acceptance cases (queue R29, app.solve.suite): a question with a known answer, asked
again of any version on its own frozen data, judged passed or failed with the reasons."""

from __future__ import annotations

import copy
import uuid

import pytest
from sqlalchemy import text

from app.core.db import engine
from app.solve import suite
from app.solve.service import claim_next, execute_run
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_diagnose import _scenario_for
from tests.test_solve import _feasible
from tests.test_v1_problem_run import db, make_model_version  # noqa: F401


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _plan(db):
    """The two-day rota solved: optimal, 2 shifts."""
    from app.solve.service import enqueue_run

    version, _ = _feasible(db)
    run = enqueue_run(db, _scenario_for(db, version), time_limit=10.0, reuse=False)
    assert claim_next(db) == run
    execute_run(db, run)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    return problem, version, run


def _ask(client, auth_headers, db, case_id, version=None):
    response = client.post(f"/api/v1/suite-cases/{case_id}/runs", headers=auth_headers,
                           json={} if version is None else {"model_version_id": version})
    assert response.status_code == 201, response.text
    run = response.json()["run_id"]
    assert claim_next(db) == run
    execute_run(db, run)
    return client.get(f"/api/v1/runs/{run}", headers=auth_headers).json()


def _make(client, auth_headers, problem, run, name="two shifts"):
    response = client.post(f"/api/v1/problems/{problem}/suite-cases/from-run/{run}", headers=auth_headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_case_made_from_a_run_passes_on_the_same_version(db, empty_queue, client, auth_headers):
    problem, _, run = _plan(db)
    case = _make(client, auth_headers, problem, run)
    assert case["expect"]["status"] == "optimal" and case["expect"]["objective"] == 2
    read = _ask(client, auth_headers, db, case["id"])
    assert read["purpose"] == "suite" and read["verdict"]["passed"] is True and read["verdict"]["reasons"] == []
    listed = client.get(f"/api/v1/problems/{problem}/suite-cases", headers=auth_headers).json()["items"]
    assert [c["last"]["verdict"]["passed"] for c in listed] == [True]
    # Case runs are not plans: the runs list leaves them out.
    assert read["id"] not in [r["id"] for r in client.get("/api/v1/runs", headers=auth_headers).json()["items"]]


def test_a_version_whose_answer_moves_fails_and_says_by_how_much(db, empty_queue, client, auth_headers):
    problem, version, run = _plan(db)
    case = _make(client, auth_headers, problem, run)
    ir = copy.deepcopy(db.execute(text("SELECT ir FROM model_version WHERE id = :v"), {"v": version}).scalar_one())
    ir["objective"]["terms"][0]["weight"] = 3  # the same plan, three times the cost
    second = make_model_version(db, problem, ir)
    db.commit()
    read = _ask(client, auth_headers, db, case["id"], second)
    assert read["verdict"]["passed"] is False
    assert read["verdict"]["reasons"] == ["the objective is 6, expected 2 within 2e-06"]

    # Loosened: a change of goal the case accepts.
    loosened = client.patch(f"/api/v1/suite-cases/{case['id']}", headers=auth_headers,
                            json={"expect": {**case["expect"], "tolerance_abs": 5}})
    assert loosened.status_code == 200
    assert _ask(client, auth_headers, db, case["id"], second)["verdict"]["passed"] is True


def test_a_cell_that_must_hold_is_named_when_it_does_not(db, empty_queue, client, auth_headers):
    problem, _, run = _plan(db)
    case = _make(client, auth_headers, problem, run)
    roster = db.execute(text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": run}).scalar_one()["assign"]
    off = [e for e in ("ahmed", "sara") if [e, "mon", "morning"] not in roster][0]
    client.patch(f"/api/v1/suite-cases/{case['id']}", headers=auth_headers,
                 json={"expect": {**case["expect"], "must_hold": [{"var": "assign", "index": [off, "mon", "morning"], "value": 1}]}})
    reasons = _ask(client, auth_headers, db, case["id"])["verdict"]["reasons"]
    assert reasons == [f"assign['{off}', 'mon', 'morning'] is off, expected on"]


def test_a_case_asks_its_own_frozen_question_not_todays(db, empty_queue, client, auth_headers):
    """Demand raised after the case was made: the case still asks the question it froze."""
    problem, _, run = _plan(db)
    case = _make(client, auth_headers, problem, run)
    db.execute(text("UPDATE parameter_def SET default_value = 2 WHERE name = 'demand'"
                    " AND domain_id = (SELECT domain_id FROM problem WHERE id = :p)"), {"p": problem})
    db.commit()
    assert _ask(client, auth_headers, db, case["id"])["verdict"]["passed"] is True


def test_the_verdict_names_each_reason():
    expect = {"status": "optimal", "objective": 10, "tolerance_rel": 0.01, "max_seconds": 5}
    assert suite.judge(expect, "optimal", 10.05, None, 1.0, {})["passed"] is True
    got = suite.judge(expect, "optimal", 11, None, 9.0, {})
    assert got["reasons"] == ["the objective is 11, expected 10 within 0.1", "took 9.0 s, allowed 5 s"]
    assert suite.judge(expect, "infeasible", None, None, 1.0, {})["reasons"] == ["said infeasible, expected optimal"]


def test_a_plan_that_is_a_question_is_not_made_a_case(db, empty_queue, client, auth_headers):
    problem, _, run = _plan(db)
    db.execute(text("UPDATE run SET purpose = 'why_not', parent_run_id = id WHERE id = :r"), {"r": run})
    db.commit()
    response = client.post(f"/api/v1/problems/{problem}/suite-cases/from-run/{run}", headers=auth_headers, json={"name": "x"})
    assert response.status_code == 409 and response.json()["detail"][0]["type"] == "case_not_a_plan"


def test_another_organization_sees_no_case(db, empty_queue, client, auth_headers):
    problem, _, run = _plan(db)
    _make(client, auth_headers, problem, run)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET ROLE solver_app"))
            connection.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": str(uuid.uuid4())})
            assert connection.execute(text("SELECT count(*) FROM suite_case")).scalar_one() == 0
        finally:
            transaction.rollback()
