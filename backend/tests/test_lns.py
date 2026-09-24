"""Large-neighbourhood search (app.solve.lns, queue R3): what it frees, what it fixes, what it claims."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.solve import compile_model, lns
from app.solve.backends import by_name
from app.solve.result import Solution
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from bench.families import generate
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401


def _knapsack():
    case = generate("knapsack_depots", "M", 0)
    return compile_model(case.ir, case.data)


def _holds(compiled, assignments) -> bool:
    for rule in compiled.constraints:
        left = rule.left.evaluated_at(assignments) - rule.right.evaluated_at(assignments)
        slack = Decimal("1e-6")
        if (rule.relation == "<=" and left > slack) or (rule.relation == ">=" and left < -slack) or (
                rule.relation == "=" and abs(left) > slack):
            return False
    return True


@pytest.mark.parametrize("operator", lns.OPERATORS)
def test_each_neighbourhood_frees_about_its_share_of_integer_decisions_only(operator):
    compiled = _knapsack()
    decisions = lns._decisions(compiled)
    free = lns.neighbourhood(operator, compiled, decisions, 0.2, random.Random(1))
    assert free and free <= set(decisions)
    assert len(free) >= 0.2 * len(decisions) - 1


def test_the_entity_neighbourhood_frees_everything_that_touches_an_entity():
    compiled = _knapsack()
    decisions = lns._decisions(compiled)
    free = lns.neighbourhood("entity", compiled, decisions, 0.01, random.Random(3))
    members = {m for key in free for m in key[1]}
    # Every decision of at least one freed entity is free.
    assert any(all(key in free for key in decisions if member in key[1]) for member in members)


def test_fixing_holds_every_decision_outside_the_neighbourhood_at_its_value():
    compiled = _knapsack()
    decisions = lns._decisions(compiled)
    incumbent = {key: 1 for key in decisions}
    free = set(decisions[:5])
    held = lns.fixed(compiled, incumbent, free)
    for key in decisions:
        var = held.variables[key]
        if key in free:
            assert var == compiled.variables[key]
        else:
            assert var.lower == var.upper == 1
    # The model it was given is untouched.
    assert held.variables is not compiled.variables
    assert all(compiled.variables[key] == var for key, var in _knapsack().variables.items())


def S(status, objective, bound=None, assignments=None):
    return Solution(status=status, optimal=status == "optimal", objective=objective, assignments=assignments or {},
                    wall_seconds=0.1, solver="highs", best_bound=bound)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


def test_a_proved_first_solve_is_the_answer_and_no_neighbourhood_is_tried():
    calls = []
    searched = lns.search(_knapsack(), lambda m, s, h: calls.append(s) or S("optimal", 10, 10), time_limit=30)
    assert searched.solution.status == "optimal" and len(calls) == 1
    assert searched.record == {"used": False, "why": "the first solve ended optimal"}


def test_better_answers_are_kept_the_first_bound_stands_and_the_answer_claims_nothing():
    compiled = _knapsack()  # maximize
    answers = iter([S("feasible", 100, 120), S("optimal", 105), S("optimal", 103), S("feasible", 110)])
    hints = []

    def run(model, seconds, hint):
        hints.append(hint)
        return next(answers, S("optimal", 90))

    searched = lns.search(compiled, run, time_limit=6, seed=1, clock=FakeClock())
    solution = searched.solution
    assert solution.objective == 110 and solution.best_bound == 120
    assert solution.status == "feasible" and not solution.optimal
    assert hints[0] is None and hints[1] is not None  # each neighbourhood starts from the answer
    assert searched.record["used"] and searched.record["improvements"] == 2


def test_an_answer_that_meets_the_first_bound_is_proven():
    answers = iter([S("feasible", 100, 110), S("optimal", 110)])
    searched = lns.search(_knapsack(), lambda m, s, h: next(answers, S("optimal", 110)), time_limit=4,
                          clock=FakeClock())
    assert searched.solution.status == "optimal" and searched.solution.objective == 110


def test_only_highs_and_the_milp_wrapper_and_only_a_weighted_goal():
    compiled = _knapsack()
    assert lns.applies("highs", compiled) is None and lns.applies("milp", compiled) is None
    assert lns.applies("cp-sat", compiled) == "cp-sat searches neighbourhoods itself"
    from dataclasses import replace

    assert lns.applies("highs", replace(compiled, objective_mode="lex")) == "a goal in order of importance is solved stage by stage"


def test_a_real_search_never_loses_ground_and_its_answer_holds_every_rule():
    compiled = _knapsack()
    highs = by_name("highs")

    def run(model, seconds, hint):
        return solve_compiled(highs, model, time_limit=seconds, seed=1, workers=4, hint=hint)[0]

    searched = lns.search(compiled, run, time_limit=5, seed=1)
    solution = searched.solution
    assert solution.objective is not None and _holds(compiled, solution.assignments)
    if searched.record["used"]:
        assert solution.objective >= searched.record["first_objective"]  # maximize: never worse than the first
        assert solution.best_bound is None or solution.objective <= solution.best_bound + 1e-6


def test_a_run_with_lns_on_records_what_it_did(db, empty_queue):  # noqa: F811
    ir = {
        "version": 2, "sets": [], "parameters": {},
        "variables": {"x": {"index": [], "domain": "integer", "lower": 0, "upper": 9}},
        "constraints": [{"id": "c", "left": {"var": "x", "index": []}, "relation": "<=", "right": {"const": 7}, "severity": "hard"}],
        "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": []}}]},
    }
    problem = make_problem(db, make_domain(db, "lns"))
    version = make_model_version(db, problem, ir)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.lns', CAST('true' AS jsonb)),"
                    " ('problem', :p, 'solve.memory', CAST('false' AS jsonb))"), {"p": problem})
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=10.0, reuse=False, solver="highs")
    claim_next(db)
    outcome = execute_run(db, run_id)
    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    assert outcome.status == "optimal" and outcome.objective == 7
    assert params["lns"] == {"used": False, "why": "the first solve ended optimal"}
    # How the model splits is recorded on every run (queue R4): one decision is one block.
    assert params["structure"]["blocks"] == 1
