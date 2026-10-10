"""Rules learnt from past plans (app.solve.learn): what every plan kept and the model does not say."""
from __future__ import annotations

import random

import pytest
from sqlalchemy import text

from app.solve import compile_model
from app.solve.learn import MIN_PLANS, learn, plans_from_answers
from tests.test_api_runs import auth_headers, ensure_admin_seeded  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_entity, make_entity_type, make_model_version, make_problem  # noqa: F401

EMPLOYEES = [f"e{i}" for i in range(6)]
DAYS = [f"d{i}" for i in range(5)]


def _ir() -> dict:
    return {
        "version": 1, "sets": ["employee", "day"], "parameters": {},
        "variables": {"assign": {"index": ["employee", "day"], "domain": "binary"},
                      "extra": {"index": ["day"], "domain": "integer", "lower": 0, "upper": 20}},
        "constraints": [{"id": "c_cover", "forall": [{"index": "d", "set": "day"}],
                         "left": {"sum": {"var": "assign", "index": ["e", "d"]}, "over": [{"index": "e", "set": "employee"}]},
                         "relation": ">=", "right": {"const": 2}, "severity": "hard"}],
        "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {
            "sum": {"var": "assign", "index": ["e", "d"]},
            "over": [{"index": "e", "set": "employee"}, {"index": "d", "set": "day"}]}}]},
    }


def _data() -> dict:
    return {"sets": {"employee": [{"id": e} for e in EMPLOYEES], "day": [{"id": d} for d in DAYS]},
            "parameters": {}, "parameter_defaults": {}, "relationships": {}}


def _plans(count: int = 4, seed: int = 1) -> list[dict]:
    """Rosters where nobody works more than 3 days and the extra hours stay within 2 to 6 a day."""
    rnd = random.Random(seed)
    plans = []
    for _ in range(count):
        plan, load = {}, {e: 0 for e in EMPLOYEES}
        for d in DAYS:
            for e in sorted(EMPLOYEES, key=lambda e: (load[e], rnd.random()))[:rnd.choice([2, 3])]:
                plan[("assign", (e, d))] = 1.0
                load[e] += 1
            plan[("extra", (d,))] = float(rnd.randint(2, 6))
        plans.append(plan)
    return plans


def _by(found: dict, decision: str, by: list[str], direction: str):
    return next((r for r in found["rules"] if r["decision"] == decision and r["by"] == by
                 and r["direction"] == direction), None)


def test_a_rule_every_plan_kept_and_the_model_does_not_is_proposed():
    found = learn(_ir(), compile_model(_ir(), _data()), _plans())
    rule = _by(found, "assign", ["employee"], "most")
    assert rule is not None and rule["bound"] == 3 and rule["model_allows"] == 5 and rule["plans"] == 4
    assert rule["rule"] == {
        "id": "c_learnt_assign_employee_max", "forall": [{"index": "e", "set": "employee"}],
        "left": {"sum": {"var": "assign", "index": ["e", "d"]}, "over": [{"index": "d", "set": "day"}]},
        "relation": "<=", "right": {"const": 3}, "severity": "hard",
        "note": "learnt from 4 past plans: never more than 3; the model allows 5"}
    assert "assign, summed over day, for each employee: at most 3" in rule["says"]


def test_what_the_model_already_says_is_not_proposed():
    """Every day had at least 2 on: the model's own cover rule says so, so nothing is learnt there."""
    found = learn(_ir(), compile_model(_ir(), _data()), _plans())
    assert _by(found, "assign", ["day"], "least") is None


def test_a_whole_number_decision_is_learnt_cell_by_cell_too():
    found = learn(_ir(), compile_model(_ir(), _data()), _plans())
    most = _by(found, "extra", ["day"], "most")
    least = _by(found, "extra", ["day"], "least")
    assert most is not None and most["bound"] <= 6 and most["model_allows"] == 20
    assert least is not None and least["bound"] >= 2 and least["rule"]["left"] == {"var": "extra", "index": ["d"]}


def test_every_proposed_rule_holds_in_every_plan_and_compiles():
    ir, plans = _ir(), _plans()
    found = learn(ir, compile_model(ir, _data()), plans)
    assert found["rules"]
    for proposal in found["rules"]:
        with_rule = {**ir, "constraints": [*ir["constraints"], proposal["rule"]]}
        compiled = compile_model(with_rule, _data())
        rows = [c for c in compiled.constraints if c.id == proposal["id"]]
        assert rows
        for plan in plans:
            for c in rows:
                gap = float(c.left.evaluated_at(plan)) - float(c.right.evaluated_at(plan))
                assert gap <= 1e-9 if c.relation == "<=" else gap >= -1e-9, (proposal["says"], c)


def test_one_plan_teaches_nothing():
    found = learn(_ir(), compile_model(_ir(), _data()), _plans(1))
    assert found["rules"] == [] and f"at least {MIN_PLANS} plans" in found["says"]


def test_stored_answers_read_as_plans():
    plans = plans_from_answers(_ir(), [({"assign": [["e1", "d0"]], "unknown": [["x"]]},
                                        {"extra": [{"index": ["d0"], "value": 4}]})])
    assert plans == [{("assign", ("e1", "d0")): 1.0, ("extra", ("d0",)): 4.0}]


@pytest.fixture
def empty_queue(db):  # noqa: F811
    db.execute(text("DELETE FROM approved_plan"))
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM approved_plan"))
    db.execute(text("DELETE FROM run"))
    db.commit()


def test_a_problem_learns_from_its_approved_plans(db, empty_queue, auth_headers):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.main import app

    domain = make_domain(db, "learn")
    employee = make_entity_type(db, domain, "employee", "resource")
    day = make_entity_type(db, domain, "day", "time")
    for e in EMPLOYEES:
        make_entity(db, employee, e)
    for d in DAYS:
        make_entity(db, day, d)
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, _ir())
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's')"
                               " RETURNING id"), {"p": problem, "v": version}).scalar_one()
    dataset = db.execute(text("SELECT snapshot_dataset(:v)"), {"v": version}).scalar_one()
    org = db.execute(text("SELECT organization_id FROM problem WHERE id = :p"), {"p": problem}).scalar_one()
    try:
        for plan in _plans(3):
            run = db.execute(text("INSERT INTO run (scenario_id, dataset_id, status, compiler_version, params)"
                                  " VALUES (:s, :d, 'feasible', 'test', '{}') RETURNING id"),
                             {"s": scenario, "d": dataset}).scalar_one()
            assignments = {"assign": [list(k[1]) for k in plan if k[0] == "assign"]}
            amounts = {"extra": [{"index": list(k[1]), "value": v} for k, v in plan.items() if k[0] == "extra"]}
            import json

            db.execute(text("INSERT INTO solution (run_id, assignments, amounts) VALUES (:r, CAST(:a AS jsonb),"
                            " CAST(:m AS jsonb))"), {"r": run, "a": json.dumps(assignments), "m": json.dumps(amounts)})
            db.execute(text("INSERT INTO approved_plan (organization_id, run_id, problem_id, reason)"
                            " VALUES (:o, :r, :p, 'the roster we used')"), {"o": org, "r": run, "p": problem})
        db.commit()
        got = TestClient(app).get(f"/api/v1/problems/{problem}/learned-rules", headers=auth_headers)
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["plans"] == 3 and body["source"] == "approved" and len(body["runs"]) == 3
        assert any(r["id"] == "c_learnt_assign_employee_max" for r in body["rules"]), body
    finally:
        db.execute(text("DELETE FROM approved_plan"))
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()
