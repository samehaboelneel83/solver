"""How far each number may move (queue R27): LP ranging, checked by moving the numbers, and what-ifs."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.solve.backends import by_name
from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.service import _ranged_by_highs, claim_next, enqueue_run, execute_run
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_continuous import _blend
from tests.test_diagnose import _scenario_for
from tests.test_solve import _feasible
from tests.test_v1_problem_run import db  # noqa: F401

X, Y = ("x", ()), ("y", ())


def _lp(need=10, cap=6, cost_x=2, cost_y=3) -> Compiled:
    """min cost_x x + cost_y y with x + y >= need and x <= cap: at (2, 3, 10, 6), x = 6, y = 4, 24."""
    inf = Decimal(1000)
    return Compiled(
        variables={X: Variable(X, "continuous", Decimal(0), inf), Y: Variable(Y, "continuous", Decimal(0), inf)},
        constraints=[
            Constraint("c_need", {}, Linear(coeffs={X: Decimal(1), Y: Decimal(1)}), ">=", Linear(const=Decimal(need))),
            Constraint("c_cap", {}, Linear(coeffs={X: Decimal(1)}), "<=", Linear(const=Decimal(cap))),
        ],
        objective=Linear(coeffs={X: Decimal(cost_x), Y: Decimal(cost_y)}),
        sense="minimize",
        var_index_sets={"x": [], "y": []},
    )


def _solve(model):
    return by_name("highs").solve(model, time_limit=10, workers=1)


def test_the_ranges_are_the_ones_worked_by_hand():
    ranges = _solve(_lp()).ranges
    rows = {r["rule"]: r for r in ranges["rows"]}
    # Each unit more needed costs 3 (a unit of y), exact from 6 (x alone) until y reaches its
    # declared 1000 (1006).
    assert (rows["c_need"]["rhs"], rows["c_need"]["dual"], rows["c_need"]["low"], rows["c_need"]["high"]) == (10, 3, 6, 1006)
    # Each unit more x may take saves 1, exact until x covers everything (10).
    assert (rows["c_cap"]["dual"], rows["c_cap"]["low"], rows["c_cap"]["high"]) == (-1, 0, 10)
    costs = {c["var"]: c for c in ranges["costs"]}
    assert (costs["x"]["low"], costs["x"]["high"]) == (None, 3)
    assert (costs["y"]["low"], costs["y"]["high"]) == (2, None)


@pytest.mark.parametrize("rule, field", [("c_need", "need"), ("c_cap", "cap")])
def test_inside_a_limits_range_the_dual_is_exact_and_outside_it_is_not(rule, field):
    base = _solve(_lp())
    row = next(r for r in base.ranges["rows"] if r["rule"] == rule)
    for end, step in ((row["high"], 0.5), (row["low"], -0.5)):
        if end is None:
            continue
        inside = _solve(_lp(**{field: end - step}))
        moved = (end - step) - row["rhs"]
        assert float(inside.objective) == pytest.approx(float(base.objective) + row["dual"] * moved)
        outside = _solve(_lp(**{field: end + step}))
        predicted = float(base.objective) + row["dual"] * ((end + step) - row["rhs"])
        assert outside.status != "optimal" or float(outside.objective) != pytest.approx(predicted)


@pytest.mark.parametrize("var, field", [("x", "cost_x"), ("y", "cost_y")])
def test_inside_a_costs_range_the_plan_stays_and_outside_it_moves(var, field):
    base = _solve(_lp())
    cost = next(c for c in base.ranges["costs"] if c["var"] == var)
    for end, step in ((cost["high"], 0.25), (cost["low"], -0.25)):
        if end is None:
            continue
        assert _solve(_lp(**{field: end - step})).assignments == pytest.approx(base.assignments)
        assert _solve(_lp(**{field: end + step})).assignments != pytest.approx(base.assignments)


def test_a_model_with_a_whole_number_decision_has_no_ranges():
    model = _lp()
    whole = replace(model, variables={**model.variables, X: replace(model.variables[X], domain="integer")})
    assert _solve(whole).ranges is None


def test_ranges_from_another_optimal_plan_are_not_borrowed():
    """With x and y costing the same, every split of 10 is optimal: a plan HiGHS does not stand at
    gets no ranges, and says why."""
    model = _lp(cost_x=3, cost_y=3)
    ranged = _solve(model)
    other = replace(ranged, ranges=None, assignments={X: 5.0, Y: 5.0})
    if ranged.assignments == pytest.approx({X: 5.0, Y: 5.0}):  # pragma: no cover -- HiGHS stands at a vertex
        other = replace(other, assignments={X: 6.0, Y: 4.0})
    kept, note = _ranged_by_highs(model, other, 10)
    assert kept.ranges is None and "more than one optimal plan" in note


# -- through a run -------------------------------------------------------------------


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _run(db, version):
    run = enqueue_run(db, _scenario_for(db, version), time_limit=10.0, reuse=False)
    assert claim_next(db) == run
    execute_run(db, run)
    return run


def test_a_blend_run_keeps_its_ranges(db, empty_queue, client, auth_headers):
    """30 kg of maize (0.2 protein at 1) and 8 of barley (0.5 at 3) make the 10 protein for 54.
    A unit more protein is 2 kg more barley, 6; exact from 6 (maize alone) to 21 (30 kg of barley)."""
    run = _run(db, _blend(db))
    read = client.get(f"/api/v1/runs/{run}", headers=auth_headers).json()
    assert read["status"] == "optimal" and read["objective"] == 54
    (row,) = read["ranges"]["rows"]
    assert (row["rule"], row["rhs"], row["dual"], row["low"], row["high"]) == ("c_protein", 10, 6, 6, 21)


def test_a_rota_run_has_none(db, empty_queue, client, auth_headers):
    version, _ = _feasible(db)
    read = client.get(f"/api/v1/runs/{_run(db, version)}", headers=auth_headers).json()
    assert read["ranges"] is None


def test_a_what_if_changes_a_value_for_the_question_only(db, empty_queue, client, auth_headers):
    """Maize at 2 is dearer per unit of protein than barley: all barley, 20 kg for 60 -- 6 more."""
    run = _run(db, _blend(db))
    dataset = db.execute(text("SELECT dataset_id FROM run WHERE id = :r"), {"r": run}).scalar_one()
    before = db.execute(text("SELECT data FROM dataset WHERE id = :d"), {"d": dataset}).scalar_one()
    response = client.post(f"/api/v1/runs/{run}/why-not", headers=auth_headers,
                           json={"override": [{"param": "cost", "index": ["maize"], "value": 2}]})
    assert response.status_code == 201, response.text
    probe = response.json()["run_id"]
    assert claim_next(db) == probe
    execute_run(db, probe)
    verdict = client.get(f"/api/v1/runs/{probe}", headers=auth_headers).json()["verdict"]
    # The closest plan is taken with the goal held within 1e-6 of its best (a continuous lex stage).
    assert verdict["kind"] == "possible" and verdict["objective"] == pytest.approx(60, rel=1e-5)
    assert verdict["delta"] == pytest.approx(6, rel=1e-4)
    assert verdict["override"] == [{"param": "cost", "index": ["maize"], "value": 2.0}]
    assert db.execute(text("SELECT data FROM dataset WHERE id = :d"), {"d": dataset}).scalar_one() == before


def test_a_what_if_names_a_number_parameter_the_model_has(db, empty_queue, client, auth_headers):
    run = _run(db, _blend(db))
    response = client.post(f"/api/v1/runs/{run}/why-not", headers=auth_headers,
                           json={"override": [{"param": "price", "index": ["maize"], "value": 2}]})
    assert response.status_code == 422 and response.json()["detail"][0]["type"] == "why_not_unknown"


def test_a_model_highs_cannot_take_is_not_sent_to_it_for_ranges():
    """A rule that multiplies continuous decisions is not a linear program: no ranges, no re-solve,
    and the answer it came with stands (found by the full check: such a run once errored here)."""
    model = _lp()
    product = Constraint("c_product", {}, Linear(), ">=", Linear(const=Decimal(1)), quadratic={(X, Y): Decimal(1)})
    curved = replace(model, constraints=[*model.constraints, product])
    answer = replace(_solve(model), ranges=None)
    kept, note = _ranged_by_highs(curved, answer, 10)
    assert kept is answer and note is None
