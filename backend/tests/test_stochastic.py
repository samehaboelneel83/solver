"""Two-stage stochastic programming (app.solve.stochastic, queue R7): the best plan across sampled futures.

The newsvendor, worked by hand: order q now at 1 a unit, sell s <= min(q, D)
at 3 once demand D is known, D uniform on [50, 150] (100 give or take 50%).
The best order is the (3 - 1) / 3 quantile of D: 50 + 100 * 2/3 = 116.67,
worth an expected E[3 min(q, D)] - q = 166.67. Ordering for the average
demand (100) is worth 3 * E[min(100, D)] - 100 = 162.5: less.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.solve import compile_model, stochastic
from app.solve.backends import by_name
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import (  # noqa: F401
    db, make_domain, make_entity, make_entity_type, make_model_version, make_parameter_def, make_problem,
)

Q = {"var": "order", "index": []}
S = {"var": "sell", "index": []}
DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {"demand": 100}, "relationships": {}}


def newsvendor(stage_two: bool = True, uncertain: dict | None = None) -> dict:
    return {
        "version": 2, "sets": [],
        "parameters": {"demand": {"index": [], **({"uncertainty": uncertain or {"kind": "interval", "deviation": 0.5}}
                                                  if uncertain is not False else {})}},
        "variables": {
            "order": {"index": [], "domain": "continuous", "lower": 0, "upper": 300, "stage": 1},
            "sell": {"index": [], "domain": "continuous", "lower": 0, "upper": 300, **({"stage": 2} if stage_two else {})},
        },
        "constraints": [
            {"id": "c_stock", "left": S, "relation": "<=", "right": Q, "severity": "hard"},
            {"id": "c_demand", "left": S, "relation": "<=", "right": {"par": "demand", "index": []}, "severity": "hard"},
        ],
        "objective": {"sense": "maximize", "terms": [{"id": "o_sales", "weight": 3, "expression": S},
                                                     {"id": "o_cost", "weight": -1, "expression": Q}]},
    }


def _run(model, seconds):
    return solve_compiled(by_name("highs"), model, time_limit=seconds, seed=1)[0]


def test_the_plan_is_the_newsvendor_quantile_not_the_order_for_the_average_demand():
    ir = newsvendor()
    solved = stochastic.solve(ir, DATA, compile_model(ir, DATA), _run, samples=50, time_limit=20, seed=1)
    order = solved.solution.assignments[("order", ())]
    # 50 futures: the 2/3 quantile within about two of its standard errors (6.7).
    assert 100 < order < 133
    assert set(solved.solution.assignments) == {("order", ())}  # the plan only: selling waits for the data
    out = solved.record["out_of_sample"]
    assert out["unmet"] == 0 and out["futures"] == 50
    assert abs(out["mean"] - 166.67) <= out["ci95"] + 5  # the true expected profit, within the interval


def test_the_extensive_form_shares_the_plan_and_copies_the_recourse():
    ir = newsvendor()
    model, shared = stochastic.extensive(stochastic.futures(ir, DATA, 3, "t"), stochastic.second_stage(ir))
    assert shared == {("order", ())}
    assert {k for k in model.variables if k[0] == "sell"} == {("sell", (f"#s{k}",)) for k in range(3)}
    assert len(model.constraints) == 6  # both rules read a copy of sell: one of each per future
    assert float(model.objective.coeffs[("order", ())]) == pytest.approx(-1.0)  # averaged over the futures
    assert float(model.objective.coeffs[("sell", ("#s0",))]) == pytest.approx(1.0)


def test_the_same_seed_draws_the_same_futures():
    ir = newsvendor()
    a = stochastic.sample(DATA, ir, __import__("random").Random("x"))
    b = stochastic.sample(DATA, ir, __import__("random").Random("x"))
    assert a == b and 50 <= a["parameter_defaults"]["demand"] <= 150


@pytest.mark.parametrize("ir, why", [
    (newsvendor(stage_two=False), "no decision waits for the data"),
    (newsvendor(uncertain=False), "no data is uncertain"),
    (newsvendor(uncertain={"kind": "scenarios"}), "no values per scenario are stored yet"),
])
def test_what_it_refuses_by_name(ir, why):
    with pytest.raises(stochastic.NotStochastic, match=why):
        stochastic.solve(ir, DATA, compile_model(ir, DATA), _run, samples=5, time_limit=5)


def test_a_run_solves_the_plan_and_never_calls_it_proven(db, empty_queue):  # noqa: F811
    domain = make_domain(db, "stochastic")
    product = make_entity_type(db, domain, "product")
    make_entity(db, product, "p1")
    make_parameter_def(db, domain, "demand", [product], default_value=100)
    problem = make_problem(db, domain)
    p = {"var": "order", "index": ["i"]}
    s = {"var": "sell", "index": ["i"]}
    each = [{"index": "i", "set": "product"}]
    ir = {
        "version": 2, "sets": ["product"],
        "parameters": {"demand": {"index": ["product"], "uncertainty": {"kind": "interval", "deviation": 0.5}}},
        "variables": {
            "order": {"index": ["product"], "domain": "continuous", "lower": 0, "upper": 300, "stage": 1},
            "sell": {"index": ["product"], "domain": "continuous", "lower": 0, "upper": 300, "stage": 2},
        },
        "constraints": [
            {"id": "c_stock", "forall": each, "left": s, "relation": "<=", "right": p, "severity": "hard"},
            {"id": "c_demand", "forall": each, "left": s, "relation": "<=", "right": {"par": "demand", "index": ["i"]},
             "severity": "hard"},
        ],
        "objective": {"sense": "maximize", "terms": [
            {"id": "o_sales", "weight": 3, "expression": {"sum": s, "over": each}},
            {"id": "o_cost", "weight": -1, "expression": {"sum": p, "over": each}}]},
    }
    version = make_model_version(db, problem, ir)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.stochastic_samples', CAST('20' AS jsonb))"),
               {"p": problem})
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=20.0, reuse=False)
    claim_next(db)
    outcome = execute_run(db, run_id)
    row = db.execute(text("SELECT status, optimality, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
    assert outcome.status == "optimal" and row["optimality"] == "approximate", row
    record = row["params"]["stochastic"]
    assert record["samples"] == 20 and record["stage_two"] == ["sell"] and record["out_of_sample"]["unmet"] == 0
    assignments = db.execute(text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": run_id}).scalar_one()
    # The plan is decided now; how much to sell waits for each future's demand.
    assert assignments["order"] == [["p1"]] and assignments["sell"] == []
