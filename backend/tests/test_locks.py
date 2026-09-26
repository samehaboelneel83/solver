"""Locks: parts of a plan held fixed while the rest is solved again (queue R24, app.solve.locks)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.solve.compile import Compiled, Linear, Variable
from app.solve.locks import Base, LockRefused, apply
from app.solve.service import claim_next, enqueue_run, execute_run
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_diagnose import _scenario_for
from tests.test_solve import _feasible
from tests.test_v1_problem_run import db  # noqa: F401


def _model() -> Compiled:
    """assign[employee, day] binary, hours[employee] whole 0..40, and a route arc over [stop, stop]."""
    variables = {}
    for e in ("ann", "bob"):
        for d in ("mon", "tue"):
            key = ("assign", (e, d))
            variables[key] = Variable(key, "binary", Decimal(0), Decimal(1))
        variables[("hours", (e,))] = Variable(("hours", (e,)), "integer", Decimal(0), Decimal(40))
    for a in ("x", "y"):
        for b in ("x", "y"):
            variables[("arc", (a, b))] = Variable(("arc", (a, b)), "binary", Decimal(0), Decimal(1))
    return Compiled(variables=variables, constraints=[], objective=Linear(), sense="minimize",
                    var_index_sets={"assign": ["employee", "day"], "hours": ["employee"], "arc": ["stop", "stop"]},
                    symmetry=[("employee", ("ann", "bob"))])


BASE = {7: Base({"assign": [["ann", "mon"], ["bob", "tue"]], "hours": [["ann"]], "arc": [["x", "y"]]},
                {"hours": [{"index": ["ann"], "value": 8}]})}
DAYS = {"day": [{"id": "mon", "date": "2026-10-05"}, {"id": "tue", "date": "2026-10-06"}]}


def _fixed(compiled: Compiled) -> dict:
    return {next(iter(c.left.coeffs)): c.right.const for c in compiled.constraints}


def test_a_cell_lock_is_one_named_row_and_symmetry_ordering_is_given_up():
    locked = apply(_model(), [{"var": "assign", "index": ["bob", "mon"], "value": 1}], {}, {})
    (row,) = locked.constraints
    assert row.id == "lock:1" and row.relation == "="
    assert row.index == {"var": "assign", "employee": "bob", "day": "mon"}
    assert _fixed(locked) == {("assign", ("bob", "mon")): 1}
    assert locked.symmetry == []


def test_a_slice_keeps_who_works_and_who_does_not():
    locked = apply(_model(), [{"var": "assign", "where": {"day": ["mon"]}, "from_run": 7}], BASE, {})
    assert _fixed(locked) == {("assign", ("ann", "mon")): 1, ("assign", ("bob", "mon")): 0}


def test_a_slice_over_a_set_twice_matches_at_every_position():
    locked = apply(_model(), [{"var": "arc", "where": {"stop": ["x"]}, "from_run": 7}], BASE, {})
    assert _fixed(locked) == {("arc", ("x", "x")): 0}
    assert locked.constraints[0].index == {"var": "arc", "stop#1": "x", "stop#2": "x"}


def test_a_horizon_freezes_every_decision_on_the_days_before_the_cut_off():
    locked = apply(_model(), [{"before": "2026-10-06", "attr": "date", "set": "day", "from_run": 7}], BASE, DAYS)
    assert _fixed(locked) == {("assign", ("ann", "mon")): 1, ("assign", ("bob", "mon")): 0}


def test_an_amount_is_locked_from_what_the_run_kept():
    locked = apply(_model(), [{"var": "hours", "where": {"employee": ["ann", "bob"]}, "from_run": 7}], BASE, {})
    assert _fixed(locked) == {("hours", ("ann",)): 8, ("hours", ("bob",)): 0}


@pytest.mark.parametrize("lock, bases, code", [
    ({"var": "nope", "index": ["ann"], "value": 1}, {}, "lock_unknown"),
    ({"var": "assign", "index": ["ann"], "value": 1}, {}, "lock_index_arity"),
    ({"var": "assign", "index": ["ann", "mon"], "value": 2}, {}, "lock_out_of_bounds"),
    ({"var": "hours", "index": ["ann"], "value": 7.5}, {}, "lock_out_of_bounds"),
    ({"var": "assign", "where": {"day": ["mon"]}, "from_run": 99}, BASE, "lock_run_invalid"),
    ({"var": "assign", "where": {"stop": ["x"]}, "from_run": 7}, BASE, "lock_unknown"),
    ({"var": "hours", "where": {"employee": ["ann"]}, "from_run": 7},
     {7: Base(BASE[7].assignments, None)}, "lock_amounts_missing"),
    ({"before": 3, "attr": "date", "set": "day", "from_run": 7}, BASE, "lock_unknown"),
])
def test_a_lock_that_cannot_be_kept_as_written_is_refused_by_name(lock, bases, code):
    with pytest.raises(LockRefused) as refused:
        apply(_model(), [lock], bases, DAYS)
    assert refused.value.code == code and "lock:1" in str(refused.value)


# -- through a run -------------------------------------------------------------------


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _solve(db, scenario):
    run = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    assert claim_next(db) == run
    return run, execute_run(db, run)


def _roster(db, run):
    stored = db.execute(text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": run}).scalar_one()
    return {tuple(r) for r in stored["assign"]}


def _locked_scenario(db, version, patch):
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name, patch)"
             " VALUES (:p, :v, 'locked', CAST(:patch AS jsonb)) RETURNING id"),
        {"p": problem, "v": version, "patch": json.dumps(patch)},
    ).scalar_one()
    db.commit()
    return scenario


def test_a_re_plan_keeps_the_locked_day_cell_for_cell(db, empty_queue):
    version, _ = _feasible(db)
    first, outcome = _solve(db, _scenario_for(db, version))
    assert outcome.status == "optimal"
    monday = {r for r in _roster(db, first) if r[1] == "mon"}
    # Whoever worked Monday keeps it; Tuesday goes to sara whatever the first plan said.
    scenario = _locked_scenario(db, version, {"lock": [
        {"var": "assign", "where": {"day": ["mon"]}, "from_run": first},
        {"var": "assign", "index": ["sara", "tue", "morning"], "value": 1},
    ]})
    second, outcome = _solve(db, scenario)
    assert outcome.status == "optimal" and outcome.objective == 2
    roster = _roster(db, second)
    assert {r for r in roster if r[1] == "mon"} == monday and ("sara", "tue", "morning") in roster
    held = db.execute(text("SELECT constraint_id, hard, satisfied FROM constraint_result"
                           " WHERE run_id = :r AND constraint_id LIKE 'lock:%' ORDER BY 1"), {"r": second}).all()
    assert [tuple(h) for h in held] == [("lock:1", True, True), ("lock:2", True, True)]


def test_locks_that_fight_the_rules_make_an_infeasible_run_that_names_them(db, empty_queue):
    version, _ = _feasible(db)
    scenario = _locked_scenario(db, version, {"lock": [
        {"var": "assign", "index": ["ahmed", "mon", "morning"], "value": 0},
        {"var": "assign", "index": ["sara", "mon", "morning"], "value": 0},
    ]})
    run, outcome = _solve(db, scenario)
    assert outcome.status == "infeasible"
    conflict = db.execute(text("SELECT conflict FROM run WHERE id = :r"), {"r": run}).scalar_one()
    assert {item["constraint_id"] for item in conflict} == {"lock:1", "lock:2", "c_cover"}


def test_a_lock_that_cannot_be_kept_ends_the_run_with_its_reason(db, empty_queue):
    version, _ = _feasible(db)
    scenario = _locked_scenario(db, version, {"lock": [
        {"var": "assign", "index": ["ahmed", "mon", "morning"], "value": 3},
    ]})
    run, outcome = _solve(db, scenario)
    assert outcome.status == "error"
    error = db.execute(text("SELECT error FROM run WHERE id = :r"), {"r": run}).scalar_one()
    assert "lock:1" in error and "outside" in error


def test_the_same_locks_with_symmetry_ordering_on_reach_the_same_answer(db, empty_queue):
    version, _ = _feasible(db)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value)"
                    " VALUES ('problem', :p, 'solve.symmetry', CAST('true' AS jsonb))"), {"p": problem})
    db.commit()
    # Sara on both days: an ordering that puts ahmed first would cut this plan off.
    scenario = _locked_scenario(db, version, {"lock": [
        {"var": "assign", "index": ["sara", "mon", "morning"], "value": 1},
        {"var": "assign", "index": ["sara", "tue", "morning"], "value": 1},
    ]})
    run, outcome = _solve(db, scenario)
    assert outcome.status == "optimal" and outcome.objective == 2


# -- the API ---------------------------------------------------------------------------


def _post(client, auth_headers, body):
    return client.post("/api/v1/scenarios", json=body, headers=auth_headers)


@pytest.mark.parametrize("lock, where, code", [
    ({"var": "nope", "index": ["ahmed"], "value": 1}, "var", "lock_unknown"),
    ({"var": "assign", "index": ["ahmed"], "value": 1}, "index", "lock_index_arity"),
    ({"var": "assign", "where": {"stop": ["x"]}, "from_run": 1}, "where", "lock_unknown"),
    ({"var": "assign", "where": {"day": ["mon"]}, "from_run": 987654321}, "from_run", "lock_run_invalid"),
    ({"before": "2026-10-01", "attr": "date", "set": "week", "from_run": 1}, "set", "lock_unknown"),
])
def test_the_api_refuses_a_lock_it_can_already_tell_is_wrong(client, auth_headers, db, lock, where, code):
    version, _ = _feasible(db)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    db.commit()
    response = _post(client, auth_headers, {"problem_id": problem, "model_version_id": version,
                                            "name": "locked", "patch": {"lock": [lock]}})
    assert response.status_code == 422, response.text
    detail = response.json()["detail"][0]
    assert detail["loc"][-1] == where and code in detail["msg"], detail


def test_the_api_stores_a_lock_as_sent(client, auth_headers, db):
    version, _ = _feasible(db)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    db.commit()
    lock = {"var": "assign", "index": ["ahmed", "mon", "morning"], "value": 1}
    response = _post(client, auth_headers, {"problem_id": problem, "model_version_id": version,
                                            "name": "locked", "patch": {"lock": [lock]}})
    assert response.status_code == 201, response.text
    assert response.json()["patch"] == {"lock": [lock]}
