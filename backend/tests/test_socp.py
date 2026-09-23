"""Convex quadratic rules and second-order cones (app.solve.socp).

Worked by hand:

- min t with x^2 + y^2 <= t^2, x >= 3, y >= 4, t >= 0: the cone; t = 5.
- min y + z with x^2 <= y z, x >= 2, y, z >= 0: the rotated cone; y + z is
  at least 2 sqrt(yz) >= 2x >= 4, and y = z = 2 reaches it: 4.
- max x + y with x^2 + y^2 <= 8: a disc; x = y = 2: 4.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.solve import compile_model
from app.solve.backends import by_name, choose
from app.solve.classify import classify
from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.convexity import refine
from app.solve.service import solve_compiled
from app.solve.socp import CONE, CONVEX, NOT_CONVEX, SOCP, rule_shapes, shape_of

NO_DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}


def v(name):
    return {"var": name, "index": []}


def k(value):
    return {"const": value}


def sq(name):
    return {"mul": [v(name), v(name)]}


def plus(*terms):
    return {"add": list(terms)}


def _ir(bounds, goal, sense, rules, domain="continuous"):
    return {
        "version": 2,
        "sets": [],
        "parameters": {},
        "variables": {n: {"index": [], "domain": domain, "lower": lo, "upper": hi} for n, (lo, hi) in bounds.items()},
        "constraints": [
            {"id": rid, "left": left, "relation": rel, "right": right, "severity": "hard"}
            for rid, (left, rel, right) in rules.items()
        ],
        "objective": {"sense": sense, "terms": [{"id": "o_goal", "weight": 1, "expression": goal}]},
    }


CONE_MODEL = _ir({"x": (3, 10), "y": (4, 10), "t": (0, 20)}, v("t"), "minimize",
                 {"c_norm": (plus(sq("x"), sq("y")), "<=", sq("t"))})
ROTATED = _ir({"x": (2, 5), "y": (0, 10), "z": (0, 10)}, plus(v("y"), v("z")), "minimize",
              {"c_rotated": (sq("x"), "<=", {"mul": [v("y"), v("z")]})})
DISC = _ir({"x": (-5, 5), "y": (-5, 5)}, plus(v("x"), v("y")), "maximize",
           {"c_disc": (plus(sq("x"), sq("y")), "<=", k(8))})


@pytest.mark.parametrize(
    "ir, rule, kind, best",
    [(CONE_MODEL, "c_norm", CONE, 5), (ROTATED, "c_rotated", CONE, 4), (DISC, "c_disc", CONVEX, 4)],
    ids=["cone", "rotated-cone", "disc"],
)
def test_recognised_routed_to_scip_and_solved_by_hand(ir, rule, kind, best):
    compiled = compile_model(ir, NO_DATA)
    assert [(s.rule, s.kind) for s in rule_shapes(compiled)] == [(rule, kind)]
    found = refine(classify(ir, NO_DATA), compiled)
    assert SOCP in found.needs and found.convex is True
    assert any(r.startswith(f"{rule} is a {kind}") for r in found.reasons)
    assert any("so it is a second-order cone program" in r for r in found.reasons)
    backend, _ = choose(found)
    assert backend.name == "scip"
    result, _ = solve_compiled(backend, compiled, time_limit=20, seed=1)
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(best, abs=1e-5)


@pytest.mark.parametrize(
    "bounds, rules, why",
    [
        # Outside a disc: curves down in both directions once written as <=.
        ({"x": (-5, 5), "y": (-5, 5)}, {"c_out": (plus(sq("x"), sq("y")), ">=", k(1))}, "more than one direction"),
        # t free to go negative: both halves of the double cone.
        ({"x": (-5, 5), "t": (-5, 5)}, {"c_double": (sq("x"), "<=", sq("t"))}, "double cone"),
        # A hyperboloid: one direction down, but not through the origin.
        ({"x": (-5, 5), "y": (-5, 5)}, {"c_hyper": (plus(sq("x"), {"mul": [k(-1), sq("y")]}), "<=", k(1))}, "not a cone"),
        ({"x": (-5, 5), "y": (-5, 5)}, {"c_curve": (sq("x"), "=", v("y"))}, "an equality with a product"),
        # x y >= 1 over positive x, y is convex -- but not by these rules,
        # which are sufficient, not necessary.
        ({"x": (0, 5), "y": (0, 5)}, {"c_hyperbola": ({"mul": [v("x"), v("y")]}, ">=", k(1))}, "not a cone"),
    ],
)
def test_what_is_not_proven_convex_says_why(bounds, rules, why):
    ir = _ir(bounds, v("x"), "maximize", rules)
    compiled = compile_model(ir, NO_DATA)
    (shape,) = rule_shapes(compiled)
    assert shape.kind == NOT_CONVEX and why in shape.why
    found = refine(classify(ir, NO_DATA), compiled)
    assert SOCP not in found.needs and found.convex is False
    assert any(r.startswith(f"{shape.rule} is not proven convex: ") for r in found.reasons)
    assert choose(found)[0].name == "scip"


def test_convex_rules_under_a_goal_that_curves_the_wrong_way_are_not_a_convex_model():
    ir = _ir({"x": (-5, 5), "y": (-5, 5)}, sq("x"), "maximize", {"c_disc": (plus(sq("x"), sq("y")), "<=", k(8))})
    found = refine(classify(ir, NO_DATA), compile_model(ir, NO_DATA))
    assert found.convex is False and SOCP not in found.needs
    assert any(r == "c_disc is a convex quadratic" for r in found.reasons)


def test_one_instance_that_is_not_a_cone_makes_the_rule_not_proven():
    ir = CONE_MODEL | {"sets": ["side"]}
    compiled = compile_model(CONE_MODEL, NO_DATA)
    # Two instances of one rule: the cone, and the same with t free below zero.
    t_free = Variable(("u", ()), "continuous", Decimal(-5), Decimal(5))
    compiled.variables[("u", ())] = t_free
    cone = compiled.constraints[0]
    other = Constraint(cone.id, {"side": "b"}, Linear(), "<=", Linear(),
                       quadratic={(("x", ()), ("x", ())): Decimal(1), (("u", ()), ("u", ())): Decimal(-1)})
    compiled.constraints.append(other)
    kinds = [s.kind for s in rule_shapes(compiled)]
    assert kinds == [CONE, NOT_CONVEX]
    found = refine(classify(ir, NO_DATA), compiled)
    assert found.convex is False and any(r.startswith("c_norm is not proven convex") for r in found.reasons)


def test_a_whole_number_cone_stays_with_cp_sat():
    ir = _ir({"x": (3, 10), "y": (4, 10), "t": (0, 20)}, v("t"), "minimize",
             {"c_norm": (plus(sq("x"), sq("y")), "<=", sq("t"))}, domain="integer")
    found = refine(classify(ir, NO_DATA), compile_model(ir, NO_DATA))
    assert SOCP in found.needs and choose(found)[0].name == "cp-sat"
    assert any("its continuous relaxation" in r for r in found.reasons)


# -- sound: what is called convex has a convex region ------------------------------------------------


def _random_rule(rnd: random.Random):
    keys = [("x", (str(i),)) for i in range(3)]
    variables = {}
    for key in keys:
        low = rnd.choice([-3, -1, 0])
        variables[key] = Variable(key, "continuous", Decimal(low), Decimal(low + rnd.choice([2, 4])))
    pairs = [(a, b) for i, a in enumerate(keys) for b in keys[i:]]
    quadratic = {pair: Decimal(rnd.choice([-2, -1, 1, 2])) for pair in rnd.sample(pairs, rnd.randint(1, 4))}
    linear = Linear(coeffs={key: Decimal(rnd.choice([0, 0, 1, -1])) for key in keys})
    linear.coeffs = {key: c for key, c in linear.coeffs.items() if c}
    if rnd.random() < 0.4:
        linear = Linear()
    rhs = Decimal(rnd.choice([0, 0, 1, 4]))
    rule = Constraint("c_r", {}, linear, rnd.choice(["<=", ">="]), Linear(const=rhs), quadratic=quadratic)
    return Compiled(variables=variables, constraints=[rule], objective=Linear(), sense="minimize",
                    var_index_sets={"x": [["i"]]}), rule


def _holds(rule: Constraint, point: dict) -> bool:
    left = sum(float(c) * point[key] for key, c in rule.left.coeffs.items())
    left += sum(float(c) * point[a] * point[b] for (a, b), c in rule.quadratic.items())
    right = float(rule.right.const)
    return left <= right + 1e-9 if rule.relation == "<=" else left >= right - 1e-9


@pytest.mark.parametrize("seed", range(200))
def test_every_convex_verdict_has_a_convex_region(seed):
    rnd = random.Random(seed)
    compiled, rule = _random_rule(rnd)
    if shape_of(compiled, rule).kind == NOT_CONVEX:
        return
    sampler = random.Random(seed + 1000)
    inside = []
    for _ in range(400):
        point = {key: sampler.uniform(float(spec.lower), float(spec.upper)) for key, spec in compiled.variables.items()}
        if _holds(rule, point):
            inside.append(point)
    for a, b in zip(inside, inside[1:]):
        mid = {key: (a[key] + b[key]) / 2 for key in a}
        assert _holds(rule, mid), (seed, rule, a, b)


def test_the_random_rules_reach_every_verdict():
    seen = {shape_of(*_random_rule(random.Random(seed))).kind for seed in range(200)}
    assert seen == {CONVEX, CONE, NOT_CONVEX}
