"""The trade-off front between two goals (app.solve.pareto, migration 0045).

The fixture is worked by hand: pick one of three options, each with a cost
and a time, and make both small. A (cost 1, time 9), B (6, 6), C (9, 1).
None beats another on both, so all three are the front. B is the point a
weighted sum can never return -- it lies above the line from A to C
(6 + 6 = 12 > 10), so for any weights A or C scores better -- and the one
the epsilon-constraint method must find.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.api.runs import _read
from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.pareto import NotTwoGoals, front
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from tests.test_api_runs import auth_headers, ensure_admin_seeded  # noqa: F401
from tests.test_v1_problem_run import (  # noqa: F401
    db,
    make_domain,
    make_entity,
    make_entity_type,
    make_model_version,
    make_parameter_def,
    make_parameter_value,
    make_problem,
)

OPTIONS = {"a": (1, 9), "b": (6, 6), "c": (9, 1)}
O = [{"index": "o", "set": "option"}]


def _goal(parameter: str) -> dict:
    return {"sum": {"mul": [{"par": parameter, "index": ["o"]}, {"var": "pick", "index": ["o"]}]}, "over": O}


def _ir(sense: str = "minimize", terms: tuple[str, ...] = ("cost", "time"), soft: bool = False) -> dict:
    rule = {"id": "c_one", "left": {"sum": {"var": "pick", "index": ["o"]}, "over": O}, "relation": "=",
            "right": {"const": 1}, "severity": "hard"}
    if soft:
        rule = {**rule, "severity": "soft", "weight": 3}
    return {
        "version": 1,
        "sets": ["option"],
        "parameters": {"cost": {"index": ["option"]}, "time": {"index": ["option"]}},
        "variables": {"pick": {"index": ["option"], "domain": "binary"}},
        "constraints": [rule],
        "objective": {"sense": sense, "terms": [{"id": f"o_{t}", "weight": 1, "expression": _goal(t)} for t in terms]},
    }


def _data(values=OPTIONS) -> dict:
    return {
        "sets": {"option": [{"id": key} for key in values]},
        "parameters": {
            "cost": [{"option": k, "value": v[0]} for k, v in values.items()],
            "time": [{"option": k, "value": v[1]} for k, v in values.items()],
        },
        "parameter_defaults": {},
        "relationships": {},
    }


def _front(ir, data, backend="cp-sat", steps=4):
    chosen = by_name(backend)
    compiled = compile_model(ir, data)
    return front(chosen, compiled, steps=steps, time_limit=20,
                 solve=lambda model, limit: solve_compiled(chosen, model, time_limit=limit, seed=1)[0])


@pytest.mark.parametrize("backend", ["cp-sat", "highs", "scip"])
def test_the_front_is_every_point_neither_goal_can_improve_on(backend):
    points = _front(_ir(), _data(), backend)
    assert [(p.first, p.second) for p in points] == [(1, 9), (6, 6), (9, 1)]
    assert all(p.status == "optimal" for p in points)
    # The ends carry no bound; the middle point was found under one.
    assert points[0].epsilon is None and points[-1].epsilon is None and points[1].epsilon is not None


def test_a_weighted_sum_would_have_missed_the_middle_point():
    """Why the method: for every weighting, B scores worse than A or C."""
    for w in [i / 20 for i in range(21)]:
        score = {k: w * c + (1 - w) * t for k, (c, t) in OPTIONS.items()}
        assert score["b"] > min(score["a"], score["c"])


def test_a_point_neither_end_nor_front_is_never_on_it():
    """D (7, 7) is beaten by B on both goals: not on the front."""
    points = _front(_ir(), _data({**OPTIONS, "d": (7, 7)}))
    assert (7, 7) not in [(p.first, p.second) for p in points]


def test_the_front_under_maximise_turns_the_other_way():
    """Make both large: A' (9, 1), B' (6, 6), C' (1, 9) mirror the fixture;
    ordered by the first goal, best first."""
    points = _front(_ir("maximize"), _data({"a": (9, 1), "b": (6, 6), "c": (1, 9)}))
    assert [(p.first, p.second) for p in points] == [(9, 1), (6, 6), (1, 9)]


@pytest.mark.parametrize("ir, reason", [
    (_ir(terms=("cost",)), "has 1 term\\b"),
    (_ir(terms=("cost", "time", "cost", "time", "cost", "time", "cost")), "has 7 terms"),
    (_ir(soft=True), "preferred rule"),
])
def test_a_front_is_refused_for_what_it_cannot_show(ir, reason):
    with pytest.raises(NotTwoGoals, match=reason):
        _front(ir, _data())


# -- a run ------------------------------------------------------------------------------


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _scenario(db) -> tuple[int, int]:
    domain = make_domain(db, "pareto")
    option = make_entity_type(db, domain, "option", "resource")
    ids = {key: make_entity(db, option, key) for key in OPTIONS}
    cost = make_parameter_def(db, domain, "cost", [option])
    time_ = make_parameter_def(db, domain, "time", [option])
    for key, (c, t) in OPTIONS.items():
        make_parameter_value(db, cost, [ids[key]], c)
        make_parameter_value(db, time_, [ids[key]], t)
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, _ir())
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    return domain, scenario


def test_a_run_records_the_front_each_point_a_run_of_its_own(db, empty_queue):
    domain, scenario = _scenario(db)
    try:
        run_id = enqueue_run(db, scenario, time_limit=20.0, pareto_steps=4)
        assert claim_next(db) == run_id
        outcome = execute_run(db, run_id)

        read = _read(db, run_id)
        assert outcome.status == "optimal"
        assert read.pareto_terms == ["o_cost", "o_time"]
        assert [(p.first, p.second, p.status) for p in read.pareto] == [
            (1, 9, "optimal"), (6, 6, "optimal"), (9, 1, "optimal")]
        # Each point is a run with its own answer: B's run picked b.
        middle = _read(db, read.pareto[1].run_id)
        assert middle.status == "optimal" and middle.assignments["pick"] == [["b"]]
        assert middle.params["pareto_of"] == run_id
        # The run's own answer is the first end, its goal the sum of both terms.
        assert read.assignments["pick"] == [["a"]] and float(read.objective) == 10
        # A front is neither reused nor reusable.
        assert db.execute(text("SELECT cache_key FROM run WHERE id = :r"), {"r": run_id}).scalar_one() is None
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()


def test_the_runs_list_leaves_the_points_to_their_front(db, empty_queue, auth_headers):
    from fastapi.testclient import TestClient

    from app.main import app

    domain, scenario = _scenario(db)
    try:
        run_id = enqueue_run(db, scenario, time_limit=20.0, pareto_steps=4)
        claim_next(db)
        execute_run(db, run_id)
        listed = TestClient(app).get(f"/api/v1/runs?scenario_id={scenario}", headers=auth_headers).json()
        everything = db.execute(text("SELECT count(*) FROM run WHERE scenario_id = :s"), {"s": scenario}).scalar_one()
        assert [item["id"] for item in listed["items"]] == [run_id] and listed["total"] == 1
        assert everything == 4
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()


@pytest.mark.parametrize("order", ["points first", "all at once", "the front's run alone"])
def test_a_front_never_stops_its_runs_being_deleted(db, empty_queue, order):
    """Whatever order a front's runs go in, the delete stands. (The failure
    this guards against came from the table's tenant trigger firing on the
    foreign key's nulling update and looking the parent up under row
    security; the trigger is now insert-only. It showed only in the full
    suite, where cleanups run in other modules' sessions.)"""
    domain, scenario = _scenario(db)
    try:
        run_id = enqueue_run(db, scenario, time_limit=20.0, pareto_steps=4)
        claim_next(db)
        execute_run(db, run_id)
        if order == "points first":
            db.execute(text("DELETE FROM run WHERE params ? 'pareto_of'"))
            db.execute(text("DELETE FROM run WHERE id = :r"), {"r": run_id})
        elif order == "all at once":
            db.execute(text("DELETE FROM run"))
        else:
            db.execute(text("DELETE FROM run WHERE id = :r"), {"r": run_id})
            assert db.execute(text("SELECT count(*) FROM pareto_point")).scalar_one() == 0
        db.commit()
    finally:
        db.rollback()
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()


def _two_goals(mode: str) -> dict:
    """Profit (more is better) and water (less is better, weight -1) under one maximise: x is profit,
    y water, and more profit needs more water (x <= y)."""
    x, y = {"var": "x", "index": []}, {"var": "y", "index": []}
    return {"version": 2, "sets": [], "parameters": {},
            "variables": {"x": {"index": [], "domain": "continuous", "lower": 0, "upper": 10},
                          "y": {"index": [], "domain": "continuous", "lower": 0, "upper": 10}},
            "constraints": [{"id": "needs_water", "left": x, "relation": "<=", "right": y, "severity": "hard"}],
            "objective": {"sense": "maximize", "mode": mode, "terms": [
                {"id": "profit", "weight": 1, "expression": x}, {"id": "water", "weight": -1, "expression": y}]}}


def test_goals_in_order_each_go_their_own_way():
    """Benchmark round 5: in this order every goal was maximised; "less water" had to be negated."""
    compiled = compile_model(_two_goals("lex"), {"sets": {}})
    result, _ = solve_compiled(by_name("highs"), compiled, time_limit=10, seed=1)
    assert result.status == "optimal"
    assert float(result.assignments[("x", ())]) == pytest.approx(10)
    assert float(result.assignments[("y", ())]) == pytest.approx(10)  # all the water profit needs, no more
    compiled = compile_model({**_two_goals("lex"), "objective": {**_two_goals("lex")["objective"],
                              "terms": list(reversed(_two_goals("lex")["objective"]["terms"]))}}, {"sets": {}})
    result, _ = solve_compiled(by_name("highs"), compiled, time_limit=10, seed=1)
    # Water first, as little as can be: none, so no profit.
    assert float(result.assignments[("y", ())]) == pytest.approx(0) and float(result.assignments[("x", ())]) == pytest.approx(0)


def test_the_front_draws_a_less_is_better_goal_as_less():
    compiled = compile_model(_two_goals("weighted"), {"sets": {}})
    points = front(by_name("highs"), compiled, steps=2, time_limit=20,
                   solve=lambda c, t: solve_compiled(by_name("highs"), c, time_limit=t, seed=1)[0])
    # Profit and water rise together: the front runs from (0, 0) to (10, 10), never "most water".
    values = sorted((round(p.first), round(p.second)) for p in points)
    assert values[0] == (0, 0) and values[-1] == (10, 10)


# -- three goals or more (augmented epsilon-constraint; NSGA-II for products) --------------------------------

THREE = {"a": (1, 9, 5), "b": (6, 6, 1), "c": (9, 1, 5), "d": (5, 5, 9), "e": (7, 7, 2)}


def _data3(values=THREE) -> dict:
    data = _data({k: v[:2] for k, v in values.items()})
    data["parameters"]["risk"] = [{"option": k, "value": v[2]} for k, v in values.items()]
    return data


def _ir3(sense: str = "minimize") -> dict:
    ir = _ir(sense, ("cost", "time", "risk"))
    ir["parameters"]["risk"] = {"index": ["option"]}
    return ir


@pytest.mark.parametrize("backend", ["cp-sat", "highs"])
def test_three_goals_every_point_none_beats_on_all_three(backend):
    """E (7, 7, 2) is beaten by B (6, 6, 1) on every goal; D (5, 5, 9) is past the payoff table's worst risk
    (5) and is found all the same, the loosest level leaving risk free."""
    points = _front(_ir3(), _data3(), backend, steps=10)
    assert sorted(p.values for p in points) == [(1, 9, 5), (5, 5, 9), (6, 6, 1), (9, 1, 5)]
    assert all(p.status == "optimal" for p in points)
    assert all((p.first, p.second) == p.values[:2] for p in points)


def test_three_goals_under_maximise():
    mirrored = {k: tuple(10 - x for x in v) for k, v in THREE.items()}
    points = _front(_ir3("maximize"), _data3(mirrored), steps=10)
    assert sorted(p.values for p in points) == sorted(tuple(10 - x for x in v) for k, v in THREE.items() if k != "e")


def test_three_goals_that_multiply_decisions_are_searched():
    """A goal with a product goes to NSGA-II for any number of goals; each point keeps every rule."""
    from app.solve.pareto import searched_front

    ir = _ir3()
    ir["variables"]["level"] = {"index": [], "domain": "integer", "lower": 0, "upper": 4}
    ir["objective"]["terms"][2]["expression"] = {"add": [ir["objective"]["terms"][2]["expression"],
                                                        {"mul": [{"var": "level", "index": []}, {"var": "level", "index": []}]}]}
    compiled = compile_model(ir, _data3())
    points = searched_front(compiled, steps=6, time_limit=3)
    assert points and all(len(p.values) == 3 for p in points) and len(points) <= 7
    for p in points:
        assert sum(v for (name, _), v in p.solution.assignments.items() if name == "pick") == 1


def test_a_run_records_every_goal_of_a_three_goal_front(db, empty_queue):
    domain = make_domain(db, "pareto3")
    option = make_entity_type(db, domain, "option", "resource")
    ids = {key: make_entity(db, option, key) for key in THREE}
    for i, name in enumerate(("cost", "time", "risk")):
        par = make_parameter_def(db, domain, name, [option])
        for key, values in THREE.items():
            make_parameter_value(db, par, [ids[key]], values[i])
    version = make_model_version(db, make_problem(db, domain), _ir3())
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    try:
        run_id = enqueue_run(db, scenario, time_limit=30.0, pareto_steps=10)
        assert claim_next(db) == run_id
        assert execute_run(db, run_id).status == "optimal"
        read = _read(db, run_id)
        assert read.pareto_terms == ["o_cost", "o_time", "o_risk"]
        assert sorted(tuple(p.values) for p in read.pareto) == [(1, 9, 5), (5, 5, 9), (6, 6, 1), (9, 1, 5)]
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()
