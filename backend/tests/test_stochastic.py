"""Two-stage stochastic programming (app.solve.stochastic, queue R7): the best plan across sampled futures.

The newsvendor, worked by hand: order q now at 1 a unit, sell s <= min(q, D)
at 3 once demand D is known, D uniform on [50, 150] (100 give or take 50%).
The best order is the (3 - 1) / 3 quantile of D: 50 + 100 * 2/3 = 116.67,
worth an expected E[3 min(q, D)] - q = 166.67. Ordering for the average
demand (100) is worth 3 * E[min(100, D)] - 100 = 162.5: less.
"""

from __future__ import annotations

import math

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
    assert solved.solution.wall_seconds > 0.05  # the whole solve, costing the plan included
    out = solved.record["out_of_sample"]
    # Judged on fresh futures: up to OUT_OF_SAMPLE_PER per sample, as many as fit in the time (October 2026).
    # How many fit is the machine's speed (38 in 20 s here, each a HiGHS child of half a second), so only the least is held.
    assert out["unmet"] == 0 and stochastic.OUT_OF_SAMPLE_MIN <= out["futures"] <= stochastic.OUT_OF_SAMPLE_PER * 50
    assert abs(out["mean"] - 166.67) <= out["ci95"] + 5  # the true expected profit, within the interval
    # Each future's cost is kept, so its spread can be drawn (queue R17b): they average to the mean.
    n = out["futures"]
    assert len(out["costs"]) == n and out["costs"] == sorted(out["costs"])
    assert abs(sum(out["costs"]) / n - out["mean"]) < 1e-3


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
    (newsvendor(uncertain={"kind": "scenarios"}), "no futures"),
])
def test_what_it_refuses_by_name(ir, why):
    with pytest.raises(stochastic.NotStochastic, match=why):
        stochastic.solve(ir, DATA, compile_model(ir, DATA), _run, samples=5, time_limit=5)


def test_named_scenario_futures_scale_the_parameter():
    """OAAS / R7b: `{kind: scenarios, futures: [{factor}]}` is a discrete sample."""
    ir = newsvendor(uncertain={
        "kind": "scenarios",
        "futures": [
            {"label": "low", "factor": 0.5},
            {"label": "high", "factor": 1.5},
        ],
    })
    assert stochastic.scenario_count(ir) == 2
    demands = [
        stochastic.apply_scenarios(DATA, ir, i)["parameter_defaults"]["demand"]
        for i in range(2)
    ]
    assert sorted(demands) == pytest.approx([50.0, 150.0])
    samples = stochastic.futures(ir, DATA, count=10, seed=1)
    assert len(samples) == 2
    solved = stochastic.solve(ir, DATA, compile_model(ir, DATA), _run, samples=10, time_limit=10, seed=1)
    assert solved.solution.assignments[("order", ())] > 0
    assert solved.record["samples"] == 2
    assert {f["label"] for f in solved.record["scenario_futures"]} == {"low", "high"}


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


# -- chance rules (queue R8) -------------------------------------------------------------------------------


def covered(epsilon: float) -> dict:
    """Order as little as possible, yet enough for demand in all but `epsilon` of the futures.
    Worked by hand: the order is demand's (1 - epsilon) quantile -- 50 + 100 * 0.9 = 140 at 0.1."""
    return {
        "version": 2, "sets": [],
        "parameters": {"demand": {"index": [], "uncertainty": {"kind": "interval", "deviation": 0.5}}},
        "variables": {"order": {"index": [], "domain": "continuous", "lower": 0, "upper": 300}},
        "constraints": [{"id": "c_cover", "left": Q, "relation": ">=", "right": {"par": "demand", "index": []},
                         "severity": "hard", "chance": {"epsilon": epsilon}}],
        "objective": {"sense": "minimize", "terms": [{"id": "o_cost", "weight": 1, "expression": Q}]},
    }


def test_a_chance_rule_alone_asks_for_a_stochastic_solve_and_orders_the_quantile():
    ir = covered(0.1)
    assert stochastic.wanted(ir) and not stochastic.second_stage(ir)
    solved = stochastic.solve(ir, DATA, compile_model(ir, DATA), _run, samples=50, time_limit=20, seed=1)
    order = solved.solution.assignments[("order", ())]
    assert 135 < order < 156  # above the 90% quantile (140): held to 97% in sample so 90% holds out of it
    held = solved.record["chance"]["c_cover"]
    assert held["asked"] == pytest.approx(0.9) and 0.7 <= held["held"] <= 1.0


def test_at_most_epsilon_times_n_futures_may_break_it():
    ir = covered(0.1)
    model, _ = stochastic.extensive(stochastic.futures(ir, DATA, 20, "t"), set())
    switches = [k for k in model.variables if k[0] == "__chance"]
    assert len(switches) == 20 and all(model.variables[k].domain == "binary" for k in switches)
    budget = [c for c in model.constraints if c.id == "_chance_c_cover"]
    # Held below the asked 10% so it holds out of sample: at 20 futures, in every one of them.
    assert len(budget) == 1 and float(budget[0].right.const) == math.floor(stochastic.in_sample(0.1, 20) * 20) == 0
    assert all(c.when is not None for c in model.constraints if c.id == "c_cover")


def test_a_looser_chance_orders_less():
    ir_tight, ir_loose = covered(0.05), covered(0.3)
    tight = stochastic.solve(ir_tight, DATA, compile_model(ir_tight, DATA), _run, samples=40, time_limit=15, seed=2)
    loose = stochastic.solve(ir_loose, DATA, compile_model(ir_loose, DATA), _run, samples=40, time_limit=15, seed=2)
    assert loose.solution.assignments[("order", ())] < tight.solution.assignments[("order", ())]


def test_a_chance_rule_over_an_unbounded_decision_is_refused_by_name():
    ir = covered(0.1)
    del ir["variables"]["order"]["upper"]
    with pytest.raises(stochastic.NotStochastic, match="no declared upper bound"):
        stochastic.solve(ir, DATA, compile_model(ir, DATA), _run, samples=5, time_limit=5)


def test_a_run_with_a_chance_rule_goes_to_an_integer_solver_and_records_how_often_it_held(db, empty_queue):  # noqa: F811
    domain = make_domain(db, "chance")
    product = make_entity_type(db, domain, "product")
    make_entity(db, product, "p1")
    make_parameter_def(db, domain, "demand", [product], default_value=100)
    problem = make_problem(db, domain)
    each = [{"index": "i", "set": "product"}]
    order = {"var": "order", "index": ["i"]}
    ir = {
        "version": 2, "sets": ["product"],
        "parameters": {"demand": {"index": ["product"], "uncertainty": {"kind": "interval", "deviation": 0.5}}},
        "variables": {"order": {"index": ["product"], "domain": "continuous", "lower": 0, "upper": 300}},
        "constraints": [{"id": "c_cover", "forall": each, "left": order, "relation": ">=",
                         "right": {"par": "demand", "index": ["i"]}, "severity": "hard", "chance": {"epsilon": 0.1}}],
        "objective": {"sense": "minimize", "terms": [{"id": "o_cost", "weight": 1, "expression": {"sum": order, "over": each}}]},
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
    row = db.execute(text("SELECT solver, optimality, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
    assert outcome.status == "optimal" and row["optimality"] == "approximate", row
    assert row["params"]["chosen_solver"] != "glop"  # the switches are binaries: not a linear-programming solver
    assert row["params"]["stochastic"]["chance"]["c_cover"]["asked"] == pytest.approx(0.9)


def test_the_in_sample_share_is_held_below_the_asked_one_and_the_gap_closes_with_more_futures():
    assert stochastic.in_sample(0.1, 20) == 0.0
    assert 0.02 < stochastic.in_sample(0.1, 50) < 0.04
    assert stochastic.in_sample(0.1, 50) < stochastic.in_sample(0.1, 5000) < 0.1
