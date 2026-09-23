"""The function catalogue (`fn` terms): contract, compile, classify, SCIP.

Every optimum here is worked by hand:

- Ten to split between log(1 + x) and sqrt(y): at the best split the two
  returns rise equally fast, 1/(1 + x) = 1/(2 sqrt y). With x = 10 - y,
  2 sqrt(y) = 11 - y, so sqrt(y) = sqrt(12) - 1 -- y = 6.0718, x = 3.9282,
  worth ln(4.9282) + 2.4641 = 4.0591.
- exp(x) - 2x falls until e^x = 2: x = ln 2, worth 2 - 2 ln 2 = 0.6137.
- |x - 3| + |x + 1| is 4 anywhere between -1 and 3, more outside.
- sin on [0, 10] peaks at 1 twice (pi/2 and 5 pi/2): a function neither
  convex nor concave, whose best is found, not assumed.
- exp(|x - 2|) is least, 1, at x = 2: a function of a function.
"""

from __future__ import annotations

import math

import pytest
from sqlalchemy import text

from app.ir.contract import CONTRACT, FUNCTIONS
from app.solve import compile_model
from app.solve.backends import NoBackend, by_name, choose
from app.solve.classify import classify
from app.solve.compile import Unsupported
from app.solve.robust import NotRobust, deviations
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
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

X = {"var": "x", "index": []}
Y = {"var": "y", "index": []}
NO_DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}


def _ir(expression, sense="minimize", *, x=(-5, 5), y=(0, 10), domain="continuous", constraints=()) -> dict:
    return {
        "version": 2,
        "sets": [],
        "parameters": {},
        "variables": {
            "x": {"index": [], "domain": domain, "lower": x[0], "upper": x[1]},
            "y": {"index": [], "domain": "continuous", "lower": y[0], "upper": y[1]},
        },
        "constraints": list(constraints),
        "objective": {"sense": sense, "terms": [{"id": "o_goal", "weight": 1, "expression": expression}]},
    }


def fn(name, of):
    return {"fn": name, "of": of}


def plus(*terms):
    return {"add": list(terms)}


def times(k, term):
    return {"mul": [{"const": k}, term]}


BUDGET = {"id": "c_budget", "left": plus(X, Y), "relation": "<=", "right": {"const": 10}, "severity": "hard"}


def _solve(ir, data=NO_DATA):
    compiled = compile_model(ir, data)
    result, _ = solve_compiled(by_name("scip"), compiled, time_limit=20, seed=1)
    return compiled, result


# -- the catalogue ----------------------------------------------------------------------------------


def test_every_function_is_labelled_from_the_contract_s_vocabularies():
    assert set(FUNCTIONS) == {"exp", "log", "sqrt", "abs", "sin", "cos"}
    for name, spec in FUNCTIONS.items():
        assert spec["convexity"] in CONTRACT["functionConvexities"], name
        assert spec["monotone"] in CONTRACT["functionMonotonicity"], name
        assert spec["domain"] in CONTRACT["functionDomains"], name
        assert spec["text"].strip(), name
    labels = {name: spec["convexity"] for name, spec in FUNCTIONS.items()}
    assert labels == {"exp": "convex", "abs": "convex", "log": "concave", "sqrt": "concave",
                      "sin": "neither", "cos": "neither"}


def test_the_labels_hold_on_a_grid():
    """Convex means every midpoint lies on or under the chord; concave, over."""
    grids = {"any": [-3 + 0.25 * i for i in range(25)], "nonnegative": [0.25 * i for i in range(25)],
             "positive": [0.1 + 0.25 * i for i in range(25)]}
    for name, spec in FUNCTIONS.items():
        f = {"exp": math.exp, "log": math.log, "sqrt": math.sqrt, "abs": abs, "sin": math.sin, "cos": math.cos}[name]
        points = grids[spec["domain"]]
        gaps = [f((a + b) / 2) - (f(a) + f(b)) / 2 for a in points for b in points]
        convex, concave = all(g <= 1e-12 for g in gaps), all(g >= -1e-12 for g in gaps)
        assert (convex, concave) == {"convex": (True, False), "concave": (False, True),
                                     "neither": (False, False)}[spec["convexity"]], name


# -- solved by hand ---------------------------------------------------------------------------------


def test_diminishing_returns_split_where_they_rise_equally_fast():
    ir = _ir(plus(fn("log", plus({"const": 1}, X)), fn("sqrt", Y)), "maximize", x=(0, 10), constraints=[BUDGET])
    compiled, result = _solve(ir)
    s = math.sqrt(12) - 1
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(math.log(11 - s * s) + s, abs=1e-5)
    # The top is flat: a split 0.01 off is worth about 3e-6 less, inside the
    # solver's tolerance, so the split is held to 0.01 and the worth to 1e-5.
    assert float(result.assignments[("y", ())]) == pytest.approx(s * s, abs=1e-2)
    assert float(result.assignments[("x", ())]) == pytest.approx(10 - s * s, abs=1e-2)
    assert [f.name for f in compiled.functions] == ["log", "sqrt"]


def test_exp_minus_a_line_is_least_where_its_slope_is_two():
    _, result = _solve(_ir(plus(fn("exp", X), times(-2, X))))
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(2 - 2 * math.log(2), abs=1e-5)
    assert float(result.assignments[("x", ())]) == pytest.approx(math.log(2), abs=1e-3)


def test_two_absolute_values_over_whole_numbers():
    ir = _ir(plus(fn("abs", plus(X, {"const": -3})), fn("abs", plus(X, {"const": 1}))), domain="integer")
    compiled, result = _solve(ir)
    assert (result.status, round(float(result.objective), 6)) == ("optimal", 4)
    assert -1 <= result.assignments[("x", ())] <= 3
    # |x + 1| is bounded by what x may be: 0 to 6, not a guess.
    stand_in = compiled.variables[compiled.functions[1].y]
    assert (float(stand_in.lower), float(stand_in.upper)) == pytest.approx((0, 6), abs=1e-6)


def test_sine_is_neither_and_its_best_is_found_not_assumed():
    _, result = _solve(_ir(fn("sin", X), "maximize", x=(0, 10)))
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(1, abs=1e-6)
    assert math.sin(float(result.assignments[("x", ())])) == pytest.approx(1, abs=1e-6)
    _, result = _solve(_ir(fn("cos", X), x=(0, 4)))
    assert float(result.objective) == pytest.approx(-1, abs=1e-6)
    assert float(result.assignments[("x", ())]) == pytest.approx(math.pi, abs=1e-3)


def test_a_function_of_a_function():
    compiled, result = _solve(_ir(fn("exp", fn("abs", plus(X, {"const": -2})))))
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(1, abs=1e-6)
    assert float(result.assignments[("x", ())]) == pytest.approx(2, abs=1e-4)
    assert [f.name for f in compiled.functions] == ["abs", "exp"]


def test_a_function_in_a_rule():
    # sqrt(y) >= 3 keeps y at 9 or more; the least y is 9.
    rule = {"id": "c_root", "left": fn("sqrt", Y), "relation": ">=", "right": {"const": 3}, "severity": "hard"}
    _, result = _solve(_ir(Y, constraints=[rule]))
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(9, abs=1e-5)


def test_the_same_function_of_the_same_thing_is_one_stand_in():
    compiled = compile_model(_ir(plus(fn("exp", X), fn("exp", X))), NO_DATA)
    assert len(compiled.functions) == 1
    assert list(compiled.objective.coeffs.values()) == [2]


# -- a function of data is a number -----------------------------------------------------------------


def test_a_function_of_data_is_only_a_number_and_the_model_stays_linear():
    ir = _ir(times(-1, X), constraints=[
        {"id": "c_cap", "left": X, "relation": "<=", "right": fn("sqrt", {"const": 16}), "severity": "hard"}])
    compiled = compile_model(ir, NO_DATA)
    assert compiled.functions == [] and compiled.constraints[0].right.const == 4
    found = classify(ir)
    assert found.model_class == "LP" and "functions" not in found.needs


# -- where the argument may go ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression, message",
    [
        (fn("log", X), "log in the goal needs its argument above zero, but the decisions it reads let it go as low as -5"),
        (fn("sqrt", plus(X, {"const": 2})), "sqrt in the goal needs its argument at least zero"),
        (fn("log", {"const": 0}), "log in the goal is applied to 0; log needs its argument above zero"),
    ],
)
def test_an_argument_that_may_leave_the_function_s_domain_is_refused_by_name(expression, message):
    with pytest.raises(Unsupported, match=message.replace("(", r"\(")):
        compile_model(_ir(expression), NO_DATA)


def test_bounds_that_keep_the_argument_in_the_domain_are_accepted():
    compiled, result = _solve(_ir(times(-1, fn("log", X)), x=(0.5, 5)))
    assert float(result.objective) == pytest.approx(-math.log(5), abs=1e-6)
    stand_in = compiled.variables[compiled.functions[0].y]
    assert float(stand_in.lower) == pytest.approx(math.log(0.5)) and float(stand_in.upper) == pytest.approx(math.log(5))


def test_exp_of_an_unbounded_argument_has_an_unbounded_stand_in():
    ir = _ir(fn("exp", fn("exp", X)), x=(-2, 10))
    compiled, result = _solve(ir)
    outer = compiled.variables[compiled.functions[1].y]
    assert math.isinf(float(outer.upper))
    assert float(result.objective) == pytest.approx(math.exp(math.exp(-2)), abs=1e-6)


# -- classified and routed --------------------------------------------------------------------------


def test_a_function_of_a_decision_is_nonlinear_and_only_scip_takes_it():
    found = classify(_ir(fn("exp", X)))
    assert found.model_class == "NLP" and "functions" in found.needs
    assert any("applies exp to decisions" in r for r in found.reasons)
    assert choose(found)[0].name == "scip"
    whole = classify(_ir(fn("abs", X), domain="integer"))
    assert whole.model_class == "MINLP"
    assert choose(whole)[0].name == "scip"
    for name in ("highs", "cp-sat", "glop", "milp"):
        with pytest.raises(NoBackend, match=f"{name} cannot take a NLP model needing .*functions"):
            choose(found, name)


# -- robust solving ---------------------------------------------------------------------------------


def test_a_rule_reading_a_function_of_an_uncertain_value_is_not_made_robust():
    ir = {
        "version": 2,
        "sets": [],
        "parameters": {"rate": {"index": [], "uncertainty": {"kind": "interval", "deviation": 0.1}}},
        "variables": {"x": {"index": [], "domain": "continuous", "lower": 0, "upper": 5}},
        "constraints": [{"id": "c_growth", "left": fn("exp", {"mul": [{"par": "rate", "index": []}, X]}),
                         "relation": "<=", "right": {"const": 20}, "severity": "hard"}],
        "objective": {"sense": "maximize", "terms": [{"id": "o_x", "weight": 1, "expression": X}]},
    }
    data = {**NO_DATA, "parameters": {"rate": [{"value": 0.5}]}}
    with pytest.raises(NotRobust, match="a rule reads exp of the uncertain 'rate'"):
        deviations(ir, data, compile_model(ir, data))


# -- through a run ----------------------------------------------------------------------------------


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def test_a_run_solves_a_function_on_scip_and_reports_only_the_model_s_decisions(db, empty_queue):
    ir = _ir(plus(fn("log", plus({"const": 1}, X)), fn("sqrt", Y)), "maximize", x=(0, 10), constraints=[BUDGET])
    domain = make_domain(db, "functions")
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, ir)
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    try:
        run_id = enqueue_run(db, scenario, time_limit=20.0)
        assert claim_next(db) == run_id
        outcome = execute_run(db, run_id)
        row = db.execute(text("SELECT solver, params, objective FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
        s = math.sqrt(12) - 1
        assert outcome.status == "optimal"
        assert row["solver"].startswith("scip") and row["params"]["classified_as"] == "NLP"
        assert float(row["objective"]) == pytest.approx(math.log(11 - s * s) + s, abs=1e-5)
        assignments = db.execute(text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": run_id}).scalar_one()
        assert set(assignments) <= {"x", "y"}
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()
