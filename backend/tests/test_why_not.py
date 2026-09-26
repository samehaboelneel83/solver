""""Why not?" probes (queue R26, app.solve.whynot): a question about a plan, answered on its own data."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.solve import whynot
from app.solve.service import claim_next, enqueue_run, execute_run
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


def _plan(db, hours=40):
    """The two-person, two-day rota, one person a day, solved: cost 2."""
    version, _ = _feasible(db, hours=hours)
    run = enqueue_run(db, _scenario_for(db, version), time_limit=10.0, reuse=False)
    assert claim_next(db) == run
    assert execute_run(db, run).status == "optimal"
    roster = db.execute(text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": run}).scalar_one()["assign"]
    return run, roster


def _ask(client, auth_headers, run, force):
    return client.post(f"/api/v1/runs/{run}/why-not", json={"force": force}, headers=auth_headers)


def _answer(db, client, auth_headers, run, force):
    response = _ask(client, auth_headers, run, force)
    assert response.status_code == 201, response.text
    probe = response.json()["run_id"]
    assert claim_next(db) == probe
    execute_run(db, probe)
    return probe, client.get(f"/api/v1/runs/{probe}", headers=auth_headers).json()


def _cell(employee, day, value=1):
    return {"var": "assign", "index": [employee, day, "morning"], "value": value}


def test_what_no_plan_allows_is_blocked_by_named_rules_and_the_asked_cells(db, empty_queue, client, auth_headers):
    """Eight hours a week is one shift: ahmed on both days breaks c_max_hours whatever else moves."""
    run, _ = _plan(db, hours=8)
    probe, read = _answer(db, client, auth_headers, run, [_cell("ahmed", "mon"), _cell("ahmed", "tue")])
    verdict = read["verdict"]
    assert read["purpose"] == "why_not" and read["parent_run_id"] == run
    assert verdict["kind"] == "blocked" and verdict["forced"] == ["lock:1", "lock:2"]
    assert {item["constraint_id"] for item in verdict["conflict"]} == {"lock:1", "lock:2", "c_max_hours"}


def test_what_a_plan_allows_says_its_cost_and_the_least_that_moves(db, empty_queue, client, auth_headers):
    """One shift each: to put a person on the other day, the two swap -- four cells, the same cost."""
    run, roster = _plan(db, hours=8)
    person, day = roster[0][0], roster[0][1]
    other_day = "tue" if day == "mon" else "mon"
    _, read = _answer(db, client, auth_headers, run, [_cell(person, other_day)])
    verdict = read["verdict"]
    assert verdict["kind"] == "possible" and verdict["proven"] is True
    assert verdict["delta"] == 0 and verdict["change"] == 4
    assert [person, other_day, "morning"] in [c[1:] for c in verdict["turned_on"]]
    assert len(verdict["turned_on"]) == 2 and len(verdict["turned_off"]) == 2


def test_an_extra_shift_costs_what_it_costs(db, empty_queue, client, auth_headers):
    """Both on Monday: one shift more than the plan's two, so the cost rises by exactly 1."""
    run, _ = _plan(db)
    _, read = _answer(db, client, auth_headers, run, [_cell("ahmed", "mon"), _cell("sara", "mon")])
    assert read["verdict"]["kind"] == "possible" and read["verdict"]["delta"] == 1 and read["verdict"]["objective"] == 3


def test_what_the_plan_already_does_is_answered_at_once(db, empty_queue, client, auth_headers):
    run, roster = _plan(db)
    response = _ask(client, auth_headers, run, [{"var": "assign", "index": roster[0], "value": 1}])
    assert response.status_code == 201
    assert response.json() == {"run_id": None,
                               "verdict": {"kind": "already", "cells": [{"var": "assign", "index": roster[0], "value": 1.0}]}}
    assert db.execute(text("SELECT count(*) FROM run WHERE purpose = 'why_not'")).scalar_one() == 0


def test_a_probe_is_kept_out_of_the_plans_and_is_not_itself_asked_about(db, empty_queue, client, auth_headers):
    run, _ = _plan(db)
    probe, _ = _answer(db, client, auth_headers, run, [_cell("ahmed", "mon"), _cell("sara", "mon")])
    plans = client.get("/api/v1/runs", headers=auth_headers).json()["items"]
    assert probe not in [r["id"] for r in plans] and run in [r["id"] for r in plans]
    asked = client.get(f"/api/v1/runs?purpose=why_not&parent_run_id={run}", headers=auth_headers).json()["items"]
    assert [r["id"] for r in asked] == [probe]
    again = _ask(client, auth_headers, probe, [_cell("ahmed", "tue")])
    assert again.status_code == 409 and again.json()["detail"][0]["type"] == "why_not_of_a_probe"


@pytest.mark.parametrize("force, code", [
    ([], "why_not_empty"),
    ([{"var": "nope", "index": ["a"], "value": 1}], "why_not_unknown"),
    ([{"var": "assign", "index": ["ahmed"], "value": 1}], "why_not_index_arity"),
])
def test_a_question_that_cannot_be_asked_is_refused_by_name(db, empty_queue, client, auth_headers, force, code):
    run, _ = _plan(db)
    response = _ask(client, auth_headers, run, force)
    assert response.status_code == 422 and response.json()["detail"][0]["type"] == code


def test_questions_have_their_own_allowance(db, empty_queue, client, auth_headers, monkeypatch):
    run, _ = _plan(db)
    monkeypatch.setattr(whynot, "OPEN_PROBES", 1)
    assert _ask(client, auth_headers, run, [_cell("ahmed", "mon"), _cell("sara", "mon")]).status_code == 201
    refused = _ask(client, auth_headers, run, [_cell("ahmed", "tue"), _cell("sara", "tue")])
    assert refused.status_code == 429 and refused.json()["detail"][0]["type"] == "why_not_open"
