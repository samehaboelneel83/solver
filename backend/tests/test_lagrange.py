"""The Lagrangian bound (app.solve.lagrange, queue R5): valid for any prices, tighter as they are searched."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.solve import compile_model, lagrange
from app.solve.backends import by_name
from app.solve.blocks import blocks, structure
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from bench.families import generate
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401


def _model(family: str, size: str = "M"):
    case = generate(family, size, 0)
    return compile_model(case.ir, case.data)


def _run(model, seconds):
    return solve_compiled(by_name("highs"), model, time_limit=seconds, seed=1, workers=4)[0]


def test_the_linking_rules_are_the_ones_structure_names():
    compiled = _model("rota")
    rows = lagrange.linking_rows(compiled, structure(compiled))
    assert len(rows) == 21 and {compiled.constraints[i].id for i in rows} == {"c_cover"}


def test_without_its_linking_rules_the_model_falls_apart_into_blocks():
    compiled = _model("rota")
    rows = lagrange.linking_rows(compiled, structure(compiled))
    relaxed = lagrange.relaxed(compiled, rows, {i: 0.0 for i in rows})
    assert len(relaxed.constraints) == len(compiled.constraints) - 21
    assert sum(1 for b in blocks(relaxed) if b.rows) == 30


def test_a_price_charges_the_goal_for_breaking_its_rule_in_the_goals_own_direction():
    compiled = _model("rota")  # minimize
    rows = lagrange.linking_rows(compiled, structure(compiled))
    i = rows[0]
    rule = compiled.constraints[i]
    relaxed = lagrange.relaxed(compiled, rows, {i: 2.0})
    key = next(iter(rule.left.coeffs))
    assert relaxed.objective.coeffs.get(key, Decimal(0)) == compiled.objective.coeffs.get(key, Decimal(0)) + 2 * rule.left.coeffs[key]


@pytest.mark.parametrize("relation, price, kept", [("<=", -1.0, 0.0), (">=", 1.0, 0.0), ("=", -1.0, -1.0), ("<=", 3.0, 3.0)])
def test_prices_keep_the_sign_that_makes_the_bound_valid(relation, price, kept):
    assert lagrange._project(price, relation) == kept


@pytest.mark.parametrize("family, size", [("rota", "M"), ("facility", "M")])
def test_the_bound_never_passes_the_optimum_and_the_search_tightens_it(family, size):
    compiled = _model(family, size)
    optimum = _run(compiled, 30)
    assert optimum.status == "optimal"
    rows = lagrange.linking_rows(compiled, structure(compiled))
    at_zero = _run(lagrange.relaxed(compiled, rows, {i: 0.0 for i in rows}), 10)
    searched = lagrange.search(compiled, rows, _run, answer=optimum.objective, time_limit=6)
    assert searched.bound is not None and searched.record["rounds"] >= 2
    # Minimizing: a lower bound, at least as tight as the relaxation with no prices.
    assert searched.bound <= float(optimum.objective) + 1e-6
    assert searched.bound >= float(at_zero.objective) - 1e-6


def test_what_applies():
    compiled = _model("rota")
    assert lagrange.applies(compiled, structure(compiled)) is None
    one = _model("feed_blend", "L")
    assert lagrange.applies(one, structure(one)) == "the model is not a few blocks tied by a few rules"


def test_a_run_that_is_proven_never_asks_for_the_bound(db, empty_queue):  # noqa: F811
    ir = {
        "version": 2, "sets": [], "parameters": {},
        "variables": {"x": {"index": [], "domain": "integer", "lower": 0, "upper": 9}},
        "constraints": [{"id": "c", "left": {"var": "x", "index": []}, "relation": "<=", "right": {"const": 7}, "severity": "hard"}],
        "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": []}}]},
    }
    problem = make_problem(db, make_domain(db, "lagrange"))
    version = make_model_version(db, problem, ir)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.lagrangian', CAST('true' AS jsonb))"),
               {"p": problem})
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    claim_next(db)
    execute_run(db, run_id)
    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    assert params["lagrangian"] is True and "lagrangian_bound" not in params


def test_a_weak_bound_is_replaced_by_a_tighter_lagrangian_one_and_a_strong_one_is_kept():
    from dataclasses import replace

    from app.solve.service import _lagrangian_bound

    compiled = _model("rota")
    found = structure(compiled)
    optimum = _run(compiled, 30)
    weak = replace(optimum, status="feasible", optimal=False, best_bound=0.0)
    # Long enough that each round's relaxed solve (a tenth of the bound's share) settles even under load.
    result, record = _lagrangian_bound(compiled, found, by_name("highs"), weak, time_limit=40, seed=1, workers=4,
                                       should_stop=lambda: False)
    assert record["used"] and record["kept"] and record["solver_bound"] == 0.0
    assert 0.0 < result.best_bound <= float(optimum.objective) + 1e-6 and result.objective == optimum.objective
    # The solver's own proven bound is better: it stands.
    strong = replace(optimum, status="feasible", optimal=False)
    result, record = _lagrangian_bound(compiled, found, by_name("highs"), strong, time_limit=4, seed=1, workers=4,
                                       should_stop=lambda: False)
    assert record["used"] and not record["kept"] and result.best_bound == optimum.best_bound
