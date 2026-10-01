"""Stay close to a base plan (queue R25, app.solve.locks.stay_close): weighted and lexicographic."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.solve.backends import by_name
from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.locks import Base, LockRefused, stay_close
from app.solve.service import _solve_lex, claim_next, enqueue_run, execute_run
from tests.test_diagnose import _scenario_for
from tests.test_solve import _feasible
from tests.test_v1_problem_run import db  # noqa: F401

COSTS = (1, 1, 1, 5)
# The base plan took items 0 and 3: cost 6.
BASE = {1: Base({"take": [["0"], ["3"]]}, None)}


def _pick_two() -> Compiled:
    """Take exactly two of four items at least cost; items 0-2 cost 1, item 3 costs 5."""
    keys = [("take", (str(i),)) for i in range(4)]
    return Compiled(
        variables={k: Variable(k, "binary", Decimal(0), Decimal(1)) for k in keys},
        constraints=[Constraint("c_two", {}, Linear(coeffs={k: Decimal(1) for k in keys}), "=", Linear(const=Decimal(2)))],
        objective=Linear(coeffs={k: Decimal(c) for k, c in zip(keys, COSTS)}),
        sense="minimize",
        var_index_sets={"take": ["item"]},
    )


def _taken(result) -> set[str]:
    return {k[1][0] for k, v in result.assignments.items() if k[0] == "take" and v > 0.5}


def test_lex_reaches_the_cold_optimum_with_the_fewest_changes():
    model, measure = stay_close(_pick_two(), {"from_run": 1, "mode": "lex"}, BASE)
    result = _solve_lex(by_name("cp-sat"), model, time_limit=10, workers=1)
    assert result.status == "optimal" and result.objective == 2
    # Keep item 0, drop item 3, take one of 1 and 2: two changes, the least any cost-2 plan can make.
    assert "0" in _taken(result) and "3" not in _taken(result)
    assert measure.evaluated_at(result.assignments) == 2


@pytest.mark.parametrize("weight, expected", [(10, {"0", "3"}), (0.1, None)])
def test_a_weight_is_an_exchange_rate_between_cost_and_change(weight, expected):
    model, measure = stay_close(_pick_two(), {"from_run": 1, "weight": weight}, BASE)
    result = by_name("highs").solve(model, time_limit=10, workers=1)
    assert result.status == "optimal"
    if expected is not None:
        # Moving saves 4 and costs at least 2 changes x 10: the base plan stays.
        assert _taken(result) == expected
    else:
        # At 0.1 a change is cheap: cost 2, and still only the two changes needed.
        assert _taken(result) in ({"0", "1"}, {"0", "2"}) and measure.evaluated_at(result.assignments) == 2


def test_an_amount_is_held_by_how_far_it_moves():
    """Maximize x on 0..10 with the base at 4: a weight of 2 per unit moved outweighs the 1 per unit gained."""
    key = ("x", ())
    model = Compiled(variables={key: Variable(key, "continuous", Decimal(0), Decimal(10))}, constraints=[],
                     objective=Linear(coeffs={key: Decimal(1)}), sense="maximize", var_index_sets={"x": []})
    base = {1: Base({"x": [[]]}, {"x": [{"index": [], "value": 4}]})}
    held, measure = stay_close(model, {"from_run": 1, "weight": 2}, base)
    loose, _ = stay_close(model, {"from_run": 1, "weight": 0.5}, base)
    assert by_name("highs").solve(held, time_limit=10, workers=1).assignments[key] == pytest.approx(4)
    moved = by_name("highs").solve(loose, time_limit=10, workers=1)
    assert moved.assignments[key] == pytest.approx(10) and float(measure.evaluated_at(moved.assignments)) == pytest.approx(6)


def test_a_lex_goal_keeps_its_order_with_the_change_last():
    model = _pick_two()
    lex = Compiled(**{**model.__dict__, "objective_mode": "lex", "objective_terms": [model.objective],
                      "objective_term_ids": ["o_cost"]})
    changed, _ = stay_close(lex, {"from_run": 1, "mode": "lex"}, BASE)
    assert changed.objective_term_ids == ["o_cost", "stay_close"]


def test_an_amount_the_base_run_did_not_keep_is_refused():
    key = ("x", ())
    model = Compiled(variables={key: Variable(key, "continuous", Decimal(0), Decimal(10))}, constraints=[],
                     objective=Linear(), sense="minimize", var_index_sets={"x": []})
    with pytest.raises(LockRefused) as refused:
        stay_close(model, {"from_run": 1}, {1: Base({"x": [[]]}, None)})
    assert refused.value.code == "stay_close_amounts_missing"


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


def test_a_re_plan_after_a_lock_moves_only_what_it_must(db, empty_queue):
    version, _ = _feasible(db)
    first, outcome = _solve(db, _scenario_for(db, version))
    roster = db.execute(text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": first}).scalar_one()["assign"]
    gone = roster[0]
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    patch = {"lock": [{"var": "assign", "index": gone, "value": 0}], "stay_close": {"from_run": first, "mode": "lex"}}
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name, patch)"
             " VALUES (:p, :v, 'close', CAST(:patch AS jsonb)) RETURNING id"),
        {"p": problem, "v": version, "patch": json.dumps(patch)},
    ).scalar_one()
    db.commit()
    run, outcome = _solve(db, scenario)
    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run}).scalar_one()
    assert outcome.status == "optimal" and outcome.objective == 2
    # The lost shift goes to the other person on the same day; the other day is untouched.
    assert params["stay_close"] == {"from_run": first, "mode": "lex", "weight": 1, "change": 2, "plan_objective": 2}
    after = db.execute(text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": run}).scalar_one()["assign"]
    assert [c for c in after if c[1] != gone[1]] == [c for c in roster if c[1] != gone[1]]


# -- the API ---------------------------------------------------------------------------

from tests.test_api_problems import auth_headers, client  # noqa: E402,F401


def test_the_api_refuses_a_stay_close_on_a_run_that_is_not_this_problems(client, auth_headers, db):
    version, _ = _feasible(db)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    db.commit()
    body = {"problem_id": problem, "model_version_id": version, "name": "close",
            "patch": {"stay_close": {"from_run": 987654321, "mode": "lex"}}}
    response = client.post("/api/v1/scenarios", json=body, headers=auth_headers)
    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["loc"][-1] == "from_run" and "stay_close_run_invalid" in detail["msg"]
    body["patch"] = {"stay_close": {"from_run": 1, "mode": "sideways"}}
    assert client.post("/api/v1/scenarios", json=body, headers=auth_headers).status_code == 422


def test_the_api_stores_a_stay_close_as_sent(client, auth_headers, db, empty_queue):
    version, _ = _feasible(db)
    scenario = _scenario_for(db, version)
    first, _ = _solve(db, scenario)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    stay = {"from_run": first, "weight": 3.0, "vars": ["assign"]}
    response = client.post("/api/v1/scenarios", json={"problem_id": problem, "model_version_id": version,
                                                      "name": "close", "patch": {"stay_close": stay}}, headers=auth_headers)
    assert response.status_code == 201, response.text
    assert response.json()["patch"] == {"stay_close": stay}


def test_a_lex_goal_with_a_bent_rule_keeps_one_id_per_stage():
    """A lex goal + a preference + a why-not probe: the preference's price becomes a stage of its
    own, and it must carry an id -- the run summary pairs ids and stages strictly (user test, run 747)."""
    model = _pick_two()
    penalty = Linear(coeffs={("take", ("3",)): Decimal(7)})
    lex = Compiled(**{**model.__dict__, "objective_mode": "lex", "objective_terms": [model.objective],
                      "objective_term_ids": ["o_cost"], "penalty_objective": penalty})
    changed, _ = stay_close(lex, {"from_run": 1, "mode": "lex"}, BASE)
    assert changed.objective_term_ids == ["o_cost", "preferences", "stay_close"]
    assert len(changed.objective_term_ids) == len(changed.objective_terms)
    result = _solve_lex(by_name("cp-sat"), changed, time_limit=10, workers=1)
    assert result.status == "optimal"
    list(zip(changed.objective_term_ids, changed.objective_terms, strict=True))
