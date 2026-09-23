"""Products with a yes-or-no factor, written exactly (app.solve.mccormick).

Worked by hand:

- max x*y, y yes-or-no, x in [0, 4], x + 2y <= 5: y = 1 leaves x <= 3, so 3;
  y = 0 is worth 0. The best is 3.
- min 5 open + ship, ship in [0, 10], open * ship >= 4: closed ships
  nothing, so open, ship 4: 9.
- max 3ab - a - b over two yes-or-no: both, 1 (one alone is -1).
- max a*a - a/2 for a yes-or-no a: a*a is a, so 1/2.
- min x*y, x in [-3, 2], with x*y >= -1: y = 1, x = -1: -1.
"""

from __future__ import annotations

import itertools
import random
from decimal import Decimal
from fractions import Fraction

import pytest
from sqlalchemy import text

from app.solve import compile_model
from app.solve.backends import by_name, choose
from app.solve.classify import classify
from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.convexity import refine
from app.solve.mccormick import BILINEAR_BINARY, linearise
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401

NO_DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}


def v(name):
    return {"var": name, "index": []}


def k(value):
    return {"const": value}


def times(a, b):
    return {"mul": [a, b]}


def plus(*terms):
    return {"add": list(terms)}


def _ir(variables, goal, sense, rules=()):
    return {
        "version": 2,
        "sets": [],
        "parameters": {},
        "variables": {name: {"index": [], **spec} for name, spec in variables.items()},
        "constraints": [
            {"id": f"c_{i}", "left": left, "relation": rel, "right": right, "severity": "hard"}
            for i, (left, rel, right) in enumerate(rules)
        ],
        "objective": {"sense": sense, "terms": [{"id": "o_goal", "weight": 1, "expression": goal}]},
    }


BIN = {"domain": "binary"}


def cont(lower, upper):
    return {"domain": "continuous", "lower": lower, "upper": upper}


CASES = {
    "choose-x-when-y": (
        _ir({"x": cont(0, 4), "y": BIN}, times(v("x"), v("y")), "maximize",
            [(plus(v("x"), times(k(2), v("y"))), "<=", k(5))]),
        3,
    ),
    "ship-only-if-open": (
        _ir({"open": BIN, "ship": cont(0, 10)}, plus(times(k(5), v("open")), v("ship")), "minimize",
            [(times(v("open"), v("ship")), ">=", k(4))]),
        9,
    ),
    "and-of-two": (
        _ir({"a": BIN, "b": BIN}, plus(times(k(3), times(v("a"), v("b"))), times(k(-1), v("a")), times(k(-1), v("b"))),
            "maximize"),
        1,
    ),
    "binary-squared": (
        _ir({"a": BIN, "x": cont(0, 1)}, plus(times(v("a"), v("a")), times(k(-0.5), v("a"))), "maximize"),
        0.5,
    ),
    "negative-lower-bound": (
        _ir({"x": cont(-3, 2), "y": BIN}, times(v("x"), v("y")), "minimize", [(times(v("x"), v("y")), ">=", k(-1))]),
        -1,
    ),
}


@pytest.mark.parametrize("backend", ["highs", "milp", "scip"])
@pytest.mark.parametrize("case", sorted(CASES))
def test_worked_by_hand(case, backend):
    ir, best = CASES[case]
    result, _ = solve_compiled(by_name(backend), compile_model(ir, NO_DATA), time_limit=10, seed=1)
    assert (result.status, round(float(result.objective), 6)) == ("optimal", best)


def test_each_product_becomes_one_variable_and_four_rows():
    ir, _ = CASES["negative-lower-bound"]
    compiled = compile_model(ir, NO_DATA)
    linear, record = linearise(compiled)
    assert not linear.objective_quadratic and not any(c.quadratic for c in linear.constraints)
    assert record == [{"product": ["y", "x"], "bounds": [-3.0, 2.0]}]
    stand_ins = [key for key in linear.variables if key[0] == "__mccormick"]
    assert len(stand_ins) == 1  # the goal's x*y and the rule's are one product
    assert (linear.variables[stand_ins[0]].lower, linear.variables[stand_ins[0]].upper) == (-3, 2)
    assert len(linear.constraints) == len(compiled.constraints) + 4


# -- against every assignment -----------------------------------------------------------------------


def _random(seed: int) -> Compiled:
    rnd = random.Random(seed)
    b = [("b", (str(i),)) for i in range(2)]
    x = [("x", (str(i),)) for i in range(2)]
    variables = {key: Variable(key, "binary", Decimal(0), Decimal(1)) for key in b}
    for key in x:
        low = rnd.choice([0, -2, -1])
        variables[key] = Variable(key, "integer", Decimal(low), Decimal(low + rnd.choice([2, 3])))
    pairs = [(p, q) for p in b for q in x] + [(b[0], b[1]), (b[0], b[0])]

    def some_products():
        return {pair: Decimal(rnd.randint(-3, 3)) for pair in rnd.sample(pairs, 3) if rnd.random() < 0.9}

    rows = [
        Constraint(
            f"r{i}", {},
            Linear(coeffs={key: Decimal(rnd.randint(-2, 2)) for key in [*b, *x]}),
            rnd.choice(["<=", ">="]),
            Linear(const=Decimal(rnd.randint(-2, 3))),
            quadratic={pair: c for pair, c in some_products().items() if c},
        )
        for i in range(2)
    ]
    return Compiled(
        variables=variables,
        constraints=rows,
        objective=Linear(coeffs={key: Decimal(rnd.randint(-2, 2)) for key in x}),
        objective_quadratic={pair: c for pair, c in some_products().items() if c},
        sense=rnd.choice(["minimize", "maximize"]),
        var_index_sets={"b": [["i"]], "x": [["i"]]},
    )


def _brute(compiled: Compiled):
    keys = list(compiled.variables)
    ranges = [range(int(compiled.variables[k].lower), int(compiled.variables[k].upper) + 1) for k in keys]
    best = None

    def value(linear: Linear, quadratic: dict, at: dict) -> Fraction:
        total = Fraction(str(linear.const)) + sum(Fraction(str(c)) * at[k] for k, c in linear.coeffs.items())
        return total + sum(Fraction(str(c)) * at[a] * at[b] for (a, b), c in quadratic.items())

    for values in itertools.product(*ranges):
        at = dict(zip(keys, values))
        ok = all(
            (value(c.left, c.quadratic, at) <= c.right.const) if c.relation == "<=" else (value(c.left, c.quadratic, at) >= c.right.const)
            for c in compiled.constraints
        )
        if ok:
            goal = value(compiled.objective, compiled.objective_quadratic, at)
            if best is None or (goal < best if compiled.sense == "minimize" else goal > best):
                best = goal
    return best


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize("backend", ["highs", "milp"])
def test_the_rewrite_agrees_with_every_assignment(seed, backend):
    compiled = _random(seed)
    expected = _brute(compiled)
    result, _ = solve_compiled(by_name(backend), compiled, time_limit=10, seed=1)
    if expected is None:
        assert result.status == "infeasible", seed
    else:
        assert result.status == "optimal", (seed, result.status)
        assert abs(Fraction(str(result.objective)) - expected) <= Fraction(1, 10**6), (seed, result.objective, expected)


def test_the_random_models_are_not_one_easy_case():
    outcomes = {_brute(_random(seed)) is None for seed in range(40)}
    assert outcomes == {True, False}


# -- which models, and where they go ----------------------------------------------------------------


def _found(ir):
    return refine(classify(ir, NO_DATA), compile_model(ir, NO_DATA))


def test_a_mixed_model_whose_products_have_a_binary_factor_is_linear_and_goes_to_highs():
    found = _found(CASES["choose-x-when-y"][0])
    assert found.model_class == "MILP"
    assert BILINEAR_BINARY in found.needs and not {"quadratic", "quadratic-constraints", "nonconvex"} & found.needs
    assert any("written exactly as linear rows (McCormick)" in r for r in found.reasons)
    assert choose(found)[0].name == "highs"
    assert choose(found, "scip")[0].name == "scip"


def test_an_all_whole_one_stays_with_cp_sat():
    ir = _ir({"a": BIN, "n": {"domain": "integer", "lower": 0, "upper": 5}}, times(v("a"), v("n")), "maximize")
    found = _found(ir)
    assert found.model_class == "IP" and choose(found)[0].name == "cp-sat"


@pytest.mark.parametrize(
    "variables, why",
    [
        # No yes-or-no factor: the envelope is only a relaxation there.
        ({"x": cont(0, 4), "y": {"domain": "integer", "lower": 0, "upper": 3}}, "no yes-or-no factor"),
        # A ceiling the model never set is not a bound to rest rows on.
        ({"x": {"domain": "continuous", "lower": 0}, "y": BIN}, "no declared upper bound"),
    ],
)
def test_a_product_that_is_not_exact_stays_with_scip(variables, why):
    ir = _ir(variables, times(v("x"), v("y")), "maximize", [(plus(v("x"), v("y")), "<=", k(5))])
    found = _found(ir)
    assert BILINEAR_BINARY not in found.needs and found.model_class in ("MIQP", "QP")
    assert choose(found)[0].name == "scip"
    from app.solve.mccormick import blocked

    assert why in blocked(compile_model(ir, NO_DATA))


# -- through a run ----------------------------------------------------------------------------------


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def test_a_run_takes_it_to_highs_at_the_hand_worked_optimum(db, empty_queue):
    ir, best = CASES["ship-only-if-open"]
    domain = make_domain(db, "mccormick")
    version = make_model_version(db, make_problem(db, domain), ir)
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) "
             "SELECT problem_id, id, 's' FROM model_version WHERE id = :v RETURNING id"),
        {"v": version},
    ).scalar_one()
    db.commit()
    try:
        run_id = enqueue_run(db, scenario, time_limit=20.0)
        assert claim_next(db) == run_id
        outcome = execute_run(db, run_id)
        row = db.execute(text("SELECT solver, params, objective FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
        assert outcome.status == "optimal" and float(row["objective"]) == best
        # Recorded as written (a run's class is set when it is queued); the
        # solver is the one the linear form admits.
        assert row["solver"].startswith("highs") and row["params"]["classified_as"] == "MIQCQP"
        assignments = db.execute(text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": run_id}).scalar_one()
        assert set(assignments) <= {"open", "ship"}
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()
