"""Curvature by composition (app.solve.dcp): the rules, pinned one by one,
checked for soundness against the functions' values, and the model verdict
as classification reports it."""

from __future__ import annotations

import math
import random

import pytest

from app.solve.classify import classify
from app.solve.dcp import model_curvature, shape_of

X = {"var": "x", "index": []}
Y = {"var": "y", "index": []}


def fn(name, of):
    return {"fn": name, "of": of}


def k(value):
    return {"const": value}


def times(a, b):
    return {"mul": [a, b]}


def plus(*terms):
    return {"add": list(terms)}


def curvature(term, data=None, scope=None):
    return shape_of(term, data, scope).curvature


# -- the rules, one at a time -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "term, expected",
    [
        (k(3), "constant"),
        (X, "affine"),
        (plus(X, times(k(-2), Y), k(1)), "affine"),
        (fn("exp", X), "convex"),
        (fn("log", X), "concave"),
        (fn("sqrt", plus(X, k(1))), "concave"),
        (fn("abs", plus(X, times(k(-1), Y))), "convex"),
        # A number times a curve: kept at or above zero, flipped at or below.
        (times(k(2), fn("exp", X)), "convex"),
        (times(k(-2), fn("exp", X)), "concave"),
        (times(fn("log", X), k(-1)), "convex"),
        (times(k(0), fn("sin", X)), "unknown"),  # sin of a decision fails before the zero
        # Rising and bending the same way keeps the bend.
        (fn("exp", fn("exp", X)), "convex"),
        (fn("exp", fn("abs", X)), "convex"),
        (fn("log", fn("sqrt", X)), "concave"),
        (fn("sqrt", fn("log", X)), "concave"),
        # Bending the other way: no rule, though log(exp(x)) is x itself.
        (fn("log", fn("exp", X)), "unknown"),
        (fn("exp", fn("log", X)), "unknown"),
        # abs neither only rises nor only falls: of anything but affine, unknown.
        (fn("abs", fn("exp", X)), "unknown"),
        (fn("sin", X), "unknown"),
        (fn("cos", k(1)), "constant"),
        # Sums: convex with convex, concave with concave, never the two.
        (plus(fn("exp", X), fn("abs", Y), X), "convex"),
        (plus(fn("log", X), fn("sqrt", Y)), "concave"),
        (plus(fn("exp", X), fn("log", Y)), "unknown"),
        # A product of decisions is the eigenvalue check's, not this one's.
        (times(X, Y), "unknown"),
        (times(X, fn("exp", Y)), "unknown"),
    ],
)
def test_each_rule(term, expected):
    assert curvature(term) == expected


def test_an_unknown_says_where_the_rules_ran_out():
    assert shape_of(fn("log", fn("exp", X))).why == "log is concave, and its argument is convex"
    assert shape_of(plus(fn("exp", X), fn("log", Y))).why == "it adds a convex part to a concave one"
    assert shape_of(fn("cos", X)).why == "cos is neither convex nor concave"


@pytest.mark.parametrize(
    "points, expected",
    [
        ([[0, 0], [1, 1], [3, 3]], "affine"),
        ([[0, 0], [1, 1], [2, 4]], "convex"),  # slopes 1, 3: a price that rises
        ([[0, 0], [2, 10], [4, 16], [6, 20]], "concave"),  # 5, 3, 2: a volume discount
        ([[0, 0], [1, 2], [2, 3], [3, 6]], "unknown"),
    ],
)
def test_a_piecewise_curve_bends_as_its_slopes_do(points, expected):
    assert curvature({"pwl": X, "points": points}) == expected


# -- the data's signs -------------------------------------------------------------------------------


def _data(values, default=None):
    return {
        "sets": {"feed": [{"id": "a", "weight": 2}, {"id": "b", "weight": 0}], "day": [{"id": "d", "weight": -1}]},
        "parameters": {"cost": [{"feed": key, "value": v} for key, v in zip("ab", values)]},
        "parameter_defaults": {} if default is None else {"cost": default},
    }


COST_TIMES_EXP = times({"par": "cost", "index": ["f"]}, fn("exp", {"var": "use", "index": ["f"]}))


def test_a_parameter_s_sign_comes_from_its_values():
    assert curvature(COST_TIMES_EXP, _data([3, 0])) == "convex"
    assert curvature(COST_TIMES_EXP, _data([-3, -0.5])) == "concave"
    assert curvature(COST_TIMES_EXP, _data([3, -1])) == "unknown"
    # A default counts: it stands in for every cell left out.
    assert curvature(COST_TIMES_EXP, _data([3, 1], default=-2)) == "unknown"
    # With no data, its sign is not known.
    assert curvature(COST_TIMES_EXP) == "unknown"


def test_an_attribute_s_sign_comes_from_its_set_s_rows():
    weight = times({"attr": {"of": "f", "name": "weight"}}, fn("exp", X))
    summed = {"sum": weight, "over": [{"index": "f", "set": "feed"}]}
    assert curvature(summed, _data([1, 1])) == "convex"
    assert curvature(weight, _data([1, 1]), {"f": "day"}) == "concave"


# -- sound: a verdict holds at every midpoint --------------------------------------------------------


def _random_term(rnd: random.Random, depth: int):
    if depth == 0 or rnd.random() < 0.25:
        return rnd.choice([X, plus(X, k(rnd.choice([1, 2]))), times(k(rnd.choice([-1, 2])), X), k(rnd.choice([1, -1]))])
    choice = rnd.random()
    if choice < 0.55:
        return fn(rnd.choice(["exp", "log", "sqrt", "abs", "sin", "cos"]), _random_term(rnd, depth - 1))
    if choice < 0.8:
        return plus(_random_term(rnd, depth - 1), _random_term(rnd, depth - 1))
    return times(k(rnd.choice([-2, -1, 1, 3])), _random_term(rnd, depth - 1))


def _value(term, x):
    if "const" in term:
        return term["const"]
    if "var" in term:
        return x
    if "add" in term:
        return sum(_value(t, x) for t in term["add"])
    if "mul" in term:
        return _value(term["mul"][0], x) * _value(term["mul"][1], x)
    f = {"exp": math.exp, "log": math.log, "sqrt": math.sqrt, "abs": abs, "sin": math.sin, "cos": math.cos}[term["fn"]]
    return f(_value(term["of"], x))


def _defined(term, x):
    try:
        value = _value(term, x)
    except (ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and abs(value) < 1e12 else None


@pytest.mark.parametrize("seed", range(300))
def test_every_curved_verdict_holds_at_every_midpoint(seed):
    rnd = random.Random(seed)
    term = _random_term(rnd, 3)
    verdict = curvature(term)
    if verdict not in ("convex", "concave", "affine"):
        return
    grid = [-4 + 0.2 * i for i in range(41)]
    # Where the term is defined -- a curvature is a claim over its domain,
    # which is an interval for every term built here.
    points = [(x, v) for x in grid if (v := _defined(term, x)) is not None]
    for i, (a, fa) in enumerate(points):
        for b, fb in points[i + 1:]:
            mid = _defined(term, (a + b) / 2)
            if mid is None:
                continue
            gap = mid - (fa + fb) / 2
            tolerance = 1e-9 * (1 + abs(fa) + abs(fb))
            if verdict in ("convex", "affine"):
                assert gap <= tolerance, (seed, term, a, b)
            if verdict in ("concave", "affine"):
                assert gap >= -tolerance, (seed, term, a, b)


def test_the_random_terms_reach_every_verdict():
    seen = {curvature(_random_term(random.Random(seed), 3)) for seed in range(300)}
    assert {"convex", "concave", "unknown", "constant"} <= seen


# -- the model ---------------------------------------------------------------------------------------


def _model(expression, sense="minimize", constraints=(), mode=None):
    objective = {"sense": sense, "terms": [{"id": "o_goal", "weight": 1, "expression": expression}]}
    if mode:
        objective["mode"] = mode
    return {
        "version": 2,
        "sets": [],
        "parameters": {},
        "variables": {
            "x": {"index": [], "domain": "continuous", "lower": 0.5, "upper": 10},
            "y": {"index": [], "domain": "continuous", "lower": 0, "upper": 10},
        },
        "constraints": list(constraints),
        "objective": objective,
    }


def rule(left, relation, right, id="c_rule"):
    return {"id": id, "left": left, "relation": relation, "right": right, "severity": "hard"}


BUDGET = rule(plus(X, Y), "<=", k(10), "c_budget")
RETURNS = plus(fn("log", plus(k(1), X)), fn("sqrt", Y))


def test_concave_returns_maximised_under_a_budget_are_a_convex_model():
    verdict = model_curvature(_model(RETURNS, "maximize", [BUDGET]))
    assert verdict.convex, verdict.reason


def test_the_same_returns_minimised_are_not():
    verdict = model_curvature(_model(RETURNS, "minimize", [BUDGET]))
    assert not verdict.convex
    assert verdict.reason == "the goal is not proven convex, as the goal to minimise needs to be: it is concave"


@pytest.mark.parametrize(
    "constraint, convex, reason",
    [
        # A concave left at least a number: the points it allows form one piece.
        (rule(fn("sqrt", Y), ">=", k(3)), True, None),
        (rule(fn("exp", X), "<=", k(5)), True, None),
        (rule(k(5), ">=", fn("exp", X)), True, None),
        (rule(fn("sqrt", Y), "<=", k(3)), False, "c_rule is not proven convex, as a <= rule needs to be: it is concave"),
        (rule(fn("exp", X), "=", k(5)), False, "c_rule is not proven affine, as a = rule needs to be: it is convex"),
        (rule(fn("sin", X), "<=", k(0)), False, "c_rule is not proven convex, as a <= rule needs to be: sin is neither convex nor concave"),
    ],
)
def test_each_rule_bends_the_way_its_relation_needs(constraint, convex, reason):
    verdict = model_curvature(_model(fn("exp", X), constraints=[constraint]))
    assert verdict.convex is convex
    if reason:
        assert verdict.reason == reason


def test_a_lexicographic_goal_is_judged_term_by_term():
    ir = _model(fn("exp", X), mode="lex")
    ir["objective"]["terms"].append({"id": "o_second", "weight": 1, "expression": fn("log", X)})
    verdict = model_curvature(ir)
    assert not verdict.convex and verdict.reason.startswith("o_second is not proven convex")
    # Weighted, the same two terms add a convex part to a concave one.
    del ir["objective"]["mode"]
    assert model_curvature(ir).reason.endswith("it adds a convex part to a concave one")


def test_a_negative_weight_flips_a_term():
    ir = _model(fn("log", X))
    ir["objective"]["terms"][0]["weight"] = -1
    assert model_curvature(ir).convex


# -- as classification reports it -------------------------------------------------------------------


def test_classification_says_whether_a_model_with_functions_is_convex():
    found = classify(_model(RETURNS, "maximize", [BUDGET]))
    assert found.convex is True
    assert "the model is convex: every rule and the goal bend the way a convex model needs" in " ".join(found.reasons)
    assert "the best answer nearby is the best overall" in " ".join(found.planner)

    found = classify(_model(fn("sin", X), "maximize"))
    assert found.convex is False
    assert any(r.startswith("the model is not proven convex: the goal is not proven concave") for r in found.reasons)

    whole = _model(fn("abs", X))
    whole["variables"]["x"]["domain"] = "integer"
    assert "its continuous relaxation" in " ".join(classify(whole).reasons)


def test_a_model_without_functions_is_not_asked():
    assert classify(_model(X, constraints=[BUDGET])).convex is None
