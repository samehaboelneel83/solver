"""Epic engine, E-1: alternative plans -- the next-best distinct answers within a gap.

A small knapsack whose every packing is enumerable: the k best distinct
packings are known exactly, so the list the platform returns is checked
against them, on each backend that takes a yes-or-no model.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.runs import _read
from app.main import app
from app.solve import compile_model
from app.solve.alternatives import ROW_ID, NotApplicable, bound, cut, find
from app.solve.backends import by_name
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from tests.test_api_runs import auth_headers, ensure_admin_seeded  # noqa: F401
from tests.test_functions import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401

WEIGHT = [3, 4, 5, 6, 2, 7, 1, 8]
VALUE = [4, 5, 7, 9, 3, 9, 1, 11]
CAPACITY = 15


def _x(i):
    return {"var": f"x{i}", "index": []}


def _knapsack(sense="maximize"):
    return {
        "version": 2, "sets": [], "parameters": {},
        "variables": {f"x{i}": {"index": [], "domain": "binary"} for i in range(8)},
        "constraints": [{"id": "c_capacity", "severity": "hard", "relation": "<=",
                         "left": {"add": [{"mul": [{"const": WEIGHT[i]}, _x(i)]} for i in range(8)]},
                         "right": {"const": CAPACITY}}],
        "objective": {"sense": sense, "terms": [{"id": "o_value", "weight": 1, "expression":
                      {"add": [{"mul": [{"const": VALUE[i]}, _x(i)]} for i in range(8)]}}]},
    }


def _ranked():
    packings = [p for p in itertools.product([0, 1], repeat=8) if sum(w * x for w, x in zip(WEIGHT, p)) <= CAPACITY]
    return sorted((sum(v * x for v, x in zip(VALUE, p)) for p in packings), reverse=True)


@pytest.mark.parametrize("backend", ["highs", "cp-sat", "scip", "milp"])
def test_the_alternatives_are_the_next_best_distinct_plans(backend):
    compiled = compile_model(_knapsack(), {})
    best, _ = solve_compiled(by_name(backend), compiled, time_limit=10, seed=1)
    solve = lambda model, limit: solve_compiled(by_name(backend), model, time_limit=limit, seed=1)[0]  # noqa: E731
    found = find(compiled, solve, best, count=6, within=0.5, time_limit=60)
    ranked = _ranked()
    assert best.objective == ranked[0]
    assert [a.solution.objective for a in found] == ranked[1:7]
    plans = [tuple(int(a.solution.assignments[(f"x{i}", ())]) for i in range(8)) for a in found]
    plans.append(tuple(int(best.assignments[(f"x{i}", ())]) for i in range(8)))
    assert len(set(plans)) == len(plans), "every plan differs from every other"
    assert all(a.changed >= 1 for a in found)


def test_nothing_outside_the_gap_is_listed():
    compiled = compile_model(_knapsack(), {})
    best, _ = solve_compiled(by_name("highs"), compiled, time_limit=10, seed=1)
    solve = lambda model, limit: solve_compiled(by_name("highs"), model, time_limit=limit, seed=1)[0]  # noqa: E731
    found = find(compiled, solve, best, count=20, within=0.05, time_limit=60)
    floor = float(bound(float(best.objective), 0.05, "maximize"))
    assert all(a.solution.objective >= floor for a in found)
    assert len(found) == sum(1 for v in _ranked()[1:] if v >= floor)


def test_a_minimized_goal_is_bounded_from_above():
    assert float(bound(100, 0.02, "minimize")) == 102
    assert float(bound(100, 0.02, "maximize")) == 98
    # A best of 0 still allows an absolute step of the gap.
    assert float(bound(0, 0.1, "minimize")) == pytest.approx(0.1)


def test_a_no_good_cut_forbids_exactly_that_plan():
    keys = [("a", ()), ("b", ()), ("c", ())]
    row = cut(keys, {keys[0]: 1, keys[1]: 0, keys[2]: 1})
    assert row.id == ROW_ID

    def holds(values):
        return float(row.left.evaluated_at(dict(zip(keys, values)))) >= 1

    assert not holds([1, 0, 1])
    assert all(holds(v) for v in itertools.product([0, 1], repeat=3) if v != (1, 0, 1))


@pytest.mark.parametrize("change, reason", [
    (lambda ir: ir["variables"].update({f"x{i}": {"index": [], "domain": "continuous", "lower": 0, "upper": 1}
                                        for i in range(8)}), "no yes-or-no decisions"),
    # A whole number with no upper bound has no big-M for its switch.
    (lambda ir: ir["variables"].update({f"x{i}": {"index": [], "domain": "integer", "lower": 0}
                                        for i in range(8)}), "no bounded whole-number"),
    (lambda ir: ir["objective"].update(mode="lex"), "term by term"),
])
def test_a_model_it_cannot_serve_is_refused_with_the_reason(change, reason):
    ir = _knapsack()
    change(ir)
    compiled = compile_model(ir, {})
    best, _ = solve_compiled(by_name("highs"), compiled, time_limit=10, seed=1)
    with pytest.raises(NotApplicable, match=reason):
        find(compiled, lambda m, t: best, best, count=2, within=0.1, time_limit=5)


def _plan(solution):
    return tuple(round(float(solution.assignments[(f"x{i}", ())])) for i in range(8))


@pytest.mark.parametrize("backend", ["highs", "scip"])
def test_plans_can_be_asked_to_differ_in_more_decisions(backend):
    compiled = compile_model(_knapsack(), {})
    best, _ = solve_compiled(by_name(backend), compiled, time_limit=10, seed=1)
    solve = lambda model, limit: solve_compiled(by_name(backend), model, time_limit=limit, seed=1)[0]  # noqa: E731
    found = find(compiled, solve, best, count=4, within=0.5, time_limit=60, min_changes=3)
    assert len(found) == 4
    plans = [_plan(best), *(_plan(a.solution) for a in found)]
    for a, b in itertools.combinations(plans, 2):
        assert sum(x != y for x, y in zip(a, b)) >= 3, (a, b)
    assert all(a.changed >= 3 for a in found)
    # No helper switch leaks into a plan.
    assert all(key[0].startswith("x") for a in found for key in a.solution.assignments)
    # Each is the best plan that far from all the earlier ones.
    packings = [p for p in itertools.product([0, 1], repeat=8) if sum(w * x for w, x in zip(WEIGHT, p)) <= CAPACITY]
    listed = [plans[0]]
    for alternative in found:
        allowed = [p for p in packings if all(sum(x != y for x, y in zip(p, q)) >= 3 for q in listed)]
        assert alternative.solution.objective == max(sum(v * x for v, x in zip(VALUE, p)) for p in allowed)
        listed.append(_plan(alternative.solution))


@pytest.mark.parametrize("backend", ["highs", "cp-sat"])
def test_whole_number_decisions_are_told_apart(backend):
    ir = _knapsack()
    ir["variables"] = {f"x{i}": {"index": [], "domain": "integer", "lower": 0, "upper": 2} for i in range(8)}
    compiled = compile_model(ir, {})
    best, _ = solve_compiled(by_name(backend), compiled, time_limit=10, seed=1)
    solve = lambda model, limit: solve_compiled(by_name(backend), model, time_limit=limit, seed=1)[0]  # noqa: E731
    found = find(compiled, solve, best, count=5, within=0.5, time_limit=60)
    packings = [p for p in itertools.product([0, 1, 2], repeat=8) if sum(w * x for w, x in zip(WEIGHT, p)) <= CAPACITY]
    ranked = sorted((sum(v * x for v, x in zip(VALUE, p)) for p in packings), reverse=True)
    assert best.objective == ranked[0]
    assert [a.solution.objective for a in found] == ranked[1:6]
    plans = [_plan(best), *(_plan(a.solution) for a in found)]
    assert len(set(plans)) == len(plans)
    assert all(a.changed >= 1 for a in found)


def test_more_changes_than_decisions_is_refused():
    compiled = compile_model(_knapsack(), {})
    best, _ = solve_compiled(by_name("highs"), compiled, time_limit=10, seed=1)
    with pytest.raises(NotApplicable, match="8 decisions"):
        find(compiled, lambda m, t: best, best, count=2, within=0.1, time_limit=5, min_changes=9)


def test_a_run_lists_its_alternatives_each_a_run_of_its_own(db, empty_queue, auth_headers):  # noqa: F811
    domain = make_domain(db, "alternatives")
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, _knapsack())
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.commit()
    try:
        run_id = enqueue_run(db, scenario, time_limit=20.0, alternatives=3, alternatives_within=0.2)
        assert claim_next(db) == run_id
        outcome = execute_run(db, run_id)
        read = _read(db, run_id)
        ranked = _ranked()
        assert outcome.status == "optimal" and float(read.objective) == ranked[0]
        assert [a.objective for a in read.alternatives] == ranked[1:4]
        assert read.params["alternatives_result"] == {"asked": 3, "within": 0.2, "found": 3}
        child = _read(db, read.alternatives[0].run_id)
        assert child.status == "optimal" and child.params["alternative_of"] == run_id
        assert float(child.objective) == ranked[1]
        # The compiler's own rows get no constraint_result, on the alternative either.
        ids = [c.constraint_id for c in child.constraints]
        assert ids == ["c_capacity"]
        # The runs list shows the run that was asked for, not its alternatives.
        client = TestClient(app)
        listed = client.get(f"/api/v1/runs?scenario_id={scenario}", headers=auth_headers).json()
        assert [item["id"] for item in listed["items"]] == [run_id]
        # ...but says which run ids its alternatives took, so the gap in the numbering is explained (F26).
        assert listed["items"][0]["part_runs"] == sorted(a.run_id for a in read.alternatives)
        # Every scenario of a problem at once, for its readiness checklist (F10).
        of_problem = client.get(f"/api/v1/runs?problem_id={problem}&limit=1", headers=auth_headers).json()
        assert of_problem["total"] == 1 and of_problem["items"][0]["id"] == run_id
        assert client.get(f"/api/v1/runs?problem_id={problem + 100000}", headers=auth_headers).json()["total"] == 0
        # Alternatives are neither reused nor reusable.
        assert db.execute(text("SELECT cache_key FROM run WHERE id = :r"), {"r": run_id}).scalar_one() is None
        # A gap without a count, or alternatives beside a front, is refused.
        bad = client.post(f"/api/v1/scenarios/{scenario}/runs", json={"alternatives_within": 0.1}, headers=auth_headers)
        assert bad.status_code == 422 and "alternatives" in bad.text
        apart = client.post(f"/api/v1/scenarios/{scenario}/runs", json={"alternatives_min_changes": 2},
                            headers=auth_headers)
        assert apart.status_code == 422 and "alternatives_min_changes" in apart.text
        both = client.post(f"/api/v1/scenarios/{scenario}/runs", json={"alternatives": 2, "pareto_steps": 3},
                           headers=auth_headers)
        assert both.status_code == 422
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()


def test_a_run_on_a_model_with_no_choices_says_why_it_lists_none(db, empty_queue):  # noqa: F811
    ir = _knapsack()
    ir["variables"] = {f"x{i}": {"index": [], "domain": "continuous", "lower": 0, "upper": 1} for i in range(8)}
    domain = make_domain(db, "alternatives-none")
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, ir)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.commit()
    try:
        run_id = enqueue_run(db, scenario, time_limit=10.0, alternatives=2)
        claim_next(db)
        assert execute_run(db, run_id).status == "optimal"
        read = _read(db, run_id)
        assert read.alternatives is None
        assert "no yes-or-no decisions" in read.params["alternatives_result"]["skipped"]
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()


def test_a_run_asked_for_plans_further_apart_gets_them(db, empty_queue):  # noqa: F811
    domain = make_domain(db, "alternatives-apart")
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, _knapsack())
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.commit()
    try:
        run_id = enqueue_run(db, scenario, time_limit=20.0, alternatives=2, alternatives_within=0.5,
                             alternatives_min_changes=3)
        claim_next(db)
        assert execute_run(db, run_id).status == "optimal"
        read = _read(db, run_id)
        assert read.params["alternatives_result"] == {"asked": 2, "within": 0.5, "min_changes": 3, "found": 2}
        assert all(a.changed >= 3 for a in read.alternatives)
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()
