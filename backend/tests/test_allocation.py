"""The exact resource-allocation decomposition (app.solve.allocation, queue R12): priced, proven, or declined."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.solve import allocation, compile_model
from app.solve.backends import by_name
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from bench.families import generate
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_entity, make_entity_type, make_model_version, make_problem  # noqa: F401

NO_DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}


def spread(total: float, relation: str = "=", sense: str = "minimize", caps=(10, 10, 10)) -> dict:
    """Split `total` over three decisions as evenly as their caps allow: min sum x_i^2."""
    x = [{"var": f"x{i}", "index": []} for i in range(3)]
    square = [{"id": f"o{i}", "weight": 1 if sense == "minimize" else -1, "expression": {"mul": [x[i], x[i]]}} for i in range(3)]
    return {
        "version": 2, "sets": [], "parameters": {},
        "variables": {f"x{i}": {"index": [], "domain": "continuous", "lower": 0, "upper": 100} for i in range(3)},
        "constraints": [{"id": "c_total", "left": {"add": x}, "relation": relation, "right": {"const": total}, "severity": "hard"},
                        *({"id": f"c_cap{i}", "left": x[i], "relation": "<=", "right": {"const": c}, "severity": "hard"}
                          for i, c in enumerate(caps))],
        "objective": {"sense": sense, "terms": square},
    }


def _solve(ir):
    return allocation.solve(compile_model(ir, NO_DATA))


def test_an_even_split_worked_by_hand():
    # 12 over three, capped at 10: 4 each, worth 48.
    result = _solve(spread(12)).solution
    assert result.status == "optimal" and result.objective == pytest.approx(48)
    assert all(v == pytest.approx(4) for v in result.assignments.values())
    assert result.best_bound == pytest.approx(48) and result.best_bound <= result.objective


def test_a_cap_moves_the_rest_onto_the_others():
    # 12 over three, one capped at 2: 2, 5, 5 -- worth 54.
    result = _solve(spread(12, caps=(2, 10, 10))).solution
    assert sorted(result.assignments.values()) == pytest.approx([2, 5, 5]) and result.objective == pytest.approx(54)


def test_an_inequality_that_holds_unpriced_costs_nothing():
    solved = _solve(spread(12, relation="<="))
    assert solved.solution.objective == pytest.approx(0) and solved.record["multiplier"] == 0


def test_a_total_the_caps_cannot_reach_is_infeasible_and_says_so():
    solved = _solve(spread(40))
    assert solved.solution.status == "infeasible" and "cannot be met" in solved.record["why"]


def test_a_maximised_concave_goal_is_the_same_problem_read_the_other_way():
    result = _solve(spread(12, sense="maximize")).solution
    assert result.objective == pytest.approx(-48) and result.best_bound >= result.objective


@pytest.mark.parametrize("size", ["M", "L"])
def test_it_matches_the_solvers_proven_optimum_on_load_balance(size):
    case = generate("load_balance", size, 0)
    compiled = compile_model(case.ir, case.data)
    ours = allocation.solve(compiled).solution
    theirs = solve_compiled(by_name("highs"), compiled, time_limit=30, seed=1)[0]
    assert theirs.status == "optimal"
    assert ours.objective == pytest.approx(float(theirs.objective), rel=1e-7)


def test_at_five_thousand_people_it_proves_what_the_solvers_do_not():
    case = generate("load_balance", "XL", 0)
    solved = allocation.solve(compile_model(case.ir, case.data))
    assert solved.solution.status == "optimal" and solved.record["pieces"] == 5000
    assert solved.solution.best_bound == pytest.approx(solved.solution.objective, rel=1e-9)


@pytest.mark.parametrize("family, why", [("rota", "a whole-number decision"), ("feed_blend", "more than one rule ties"),
                                         ("facility", "a whole-number decision")])
def test_it_declines_what_it_does_not_fit_and_says_why(family, why):
    case = generate(family, "M", 0)
    assert why in allocation.applies(compile_model(case.ir, case.data))


def test_a_run_uses_it_where_it_applies_and_records_it(db, empty_queue):  # noqa: F811
    domain = make_domain(db, "allocation")
    person = make_entity_type(db, domain, "person")
    db.execute(text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, 'capacity', 'integer')"), {"t": person})
    for i, cap in enumerate([30, 50, 20, 60]):
        make_entity(db, person, f"p{i}", attrs={"capacity": cap})
    problem = make_problem(db, domain)
    hours = {"var": "hours", "index": ["p"]}
    each = [{"index": "p", "set": "person"}]
    ir = {
        "version": 2, "sets": ["person"], "parameters": {},
        "variables": {"hours": {"index": ["person"], "domain": "continuous", "lower": 0, "upper": 60}},
        "constraints": [
            {"id": "c_total", "left": {"sum": hours, "over": each}, "relation": "=", "right": {"const": 100}, "severity": "hard"},
            {"id": "c_capacity", "forall": each, "left": hours, "relation": "<=", "right": {"attr": {"of": "p", "name": "capacity"}},
             "severity": "hard"},
        ],
        "objective": {"sense": "minimize", "terms": [{"id": "o_even", "weight": 1,
                                                      "expression": {"sum": {"mul": [hours, hours]}, "over": each}}]},
    }
    version = make_model_version(db, problem, ir)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    claim_next(db)
    outcome = execute_run(db, run_id)
    row = db.execute(text("SELECT objective, optimality, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
    # 100 over caps 30, 50, 20, 60: 20 is capped, the rest share 80 -- 26.67 each; worth 400 + 3 x 711.1 = 2533.33.
    assert outcome.status == "optimal" and row["optimality"] == "global"
    assert float(row["objective"]) == pytest.approx(400 + 3 * (80 / 3) ** 2, rel=1e-6)
    assert row["params"]["decomposition"]["rule"] == "c_total"
