"""Robust solving (app.solve.robust): exact, checked by hand and by brute force.

The hand-worked case is a knapsack whose weights may each be 20% heavier:
items weigh 5, 4, 3, 2 and are worth 10, 7, 5, 3, the capacity is 9.

- Nominally, 5 + 4 fills it exactly: 17.
- If any one weight may be heavy (gamma 1), 5 + 4 could weigh 10: out.
  5 + 3 weighs 8, 9 at worst: 15. (4 + 3 + 2 could weigh 9.8.)
- If any two may be (gamma 2), 5 + 3 could weigh 9.6: out. 5 + 2 is 7, 8.4
  at worst: 13 -- the best that survives.

So the price of robustness is 2, then 4.
"""

from __future__ import annotations

import itertools
import random
from decimal import Decimal
from fractions import Fraction

import pytest
from sqlalchemy import text

from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.robust import NotRobust, RowDeviation, deviations, rewrite
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

ITEMS = {"a": (5, 10), "b": (4, 7), "c": (3, 5), "d": (2, 3)}
I = [{"index": "i", "set": "item"}]


def _ir(gamma=None, relation="<=", exact=False) -> dict:
    uncertainty = {"kind": "interval", "deviation": 0.2, **({"gamma": gamma} if gamma is not None else {})}
    return {
        "version": 2,
        "sets": ["item"],
        "parameters": {
            "weight": {"index": ["item"], **({} if exact else {"uncertainty": uncertainty})},
            "value": {"index": ["item"]},
        },
        "variables": {"take": {"index": ["item"], "domain": "binary"}},
        "constraints": [{
            "id": "c_capacity", "note": "what is taken fits",
            "left": {"sum": {"mul": [{"par": "weight", "index": ["i"]}, {"var": "take", "index": ["i"]}]}, "over": I},
            "relation": relation, "right": {"const": 9}, "severity": "hard",
        }],
        "objective": {"sense": "maximize", "terms": [{"id": "o_value", "weight": 1, "expression": {
            "sum": {"mul": [{"par": "value", "index": ["i"]}, {"var": "take", "index": ["i"]}]}, "over": I}}]},
    }


def _data() -> dict:
    return {
        "sets": {"item": [{"id": key} for key in ITEMS]},
        "parameters": {
            "weight": [{"item": k, "value": w} for k, (w, _) in ITEMS.items()],
            "value": [{"item": k, "value": v} for k, (_, v) in ITEMS.items()],
        },
        "parameter_defaults": {},
        "relationships": {},
    }


def test_each_coefficient_moves_by_its_share_and_the_budget_is_capped_by_the_count():
    compiled = compile_model(_ir(gamma=2), _data())
    (row,) = deviations(_ir(gamma=2), _data(), compiled).values()
    assert {k[1][0]: float(v) for k, v in row.coefficients.items()} == pytest.approx(
        {"a": 1.0, "b": 0.8, "c": 0.6, "d": 0.4})
    assert row.constant == 0 and row.gamma == 2
    # No budget: every coefficient may move at once -- four of them.
    (row,) = deviations(_ir(), _data(), compile_model(_ir(), _data())).values()
    assert row.gamma == 4


@pytest.mark.parametrize("backend", ["highs", "scip", "milp"])
@pytest.mark.parametrize("gamma, best", [(None, 17), (1, 15), (2, 13)], ids=["nominal", "gamma-1", "gamma-2"])
def test_the_knapsack_worked_by_hand(backend, gamma, best):
    ir = _ir(gamma=gamma, exact=gamma is None)
    compiled = compile_model(ir, _data())
    robust, record = rewrite(compiled, deviations(ir, _data(), compiled))
    result, _ = solve_compiled(by_name(backend), robust, time_limit=10, seed=1)
    assert (result.status, round(float(result.objective), 6)) == ("optimal", best)
    assert len(record) == (0 if gamma is None else 1)


def test_an_equality_that_reads_an_uncertain_value_is_refused():
    with pytest.raises(NotRobust, match="equality"):
        deviations(_ir(gamma=1, relation="="), _data(), compile_model(_ir(gamma=1, relation="="), _data()))


# -- the rewrite against every assignment -------------------------------------------------------


def _worst(amounts: list[Fraction], gamma: Fraction) -> Fraction:
    """The most `gamma` of these can add: the largest whole ones, then a
    share of the next (Bertsimas-Sim's budget, fractional as well)."""
    ordered = sorted(amounts, reverse=True)
    whole = int(gamma)
    extra = ordered[whole] * (gamma - whole) if whole < len(ordered) else Fraction(0)
    return sum(ordered[:whole], Fraction(0)) + extra


def _random(seed: int):
    rnd = random.Random(seed)
    keys = [("x", (str(j),)) for j in range(3)]
    variables = {}
    for key in keys:
        low = rnd.choice([0, 0, -2])
        variables[key] = Variable(key, "integer", Decimal(low), Decimal(3))
    rows, moving = [], {}
    for i in range(2):
        coeffs = {k: Decimal(rnd.randint(-3, 4)) for k in keys}
        relation = rnd.choice(["<=", ">="])
        rows.append(Constraint(f"r{i}", {}, Linear(coeffs=coeffs), relation, Linear(const=Decimal(rnd.randint(-2, 8)))))
        moving[i] = RowDeviation(
            coefficients={k: Decimal(rnd.randint(0, 2)) for k in keys if rnd.random() < 0.7},
            constant=Decimal(rnd.choice([0, 0, 1])),
            gamma=Decimal(rnd.choice(["0", "1", "1.5", "2", "3"])),
        )
    goal = Linear(coeffs={k: Decimal(rnd.randint(-3, 3)) for k in keys})
    compiled = Compiled(variables=variables, constraints=rows, objective=goal,
                        sense=rnd.choice(["minimize", "maximize"]), var_index_sets={"x": [["j"]]})
    return compiled, moving


def _robust_best(compiled: Compiled, moving: dict[int, RowDeviation]):
    keys = list(compiled.variables)
    ranges = [range(int(compiled.variables[k].lower), int(compiled.variables[k].upper) + 1) for k in keys]
    best = None
    for values in itertools.product(*ranges):
        x = dict(zip(keys, values))
        ok = True
        for i, c in enumerate(compiled.constraints):
            left = sum(Fraction(str(a)) * x[k] for k, a in c.left.coeffs.items())
            dev = moving[i]
            amounts = [Fraction(str(a)) * abs(x[k]) for k, a in dev.coefficients.items()]
            if dev.constant:
                amounts.append(Fraction(str(dev.constant)))
            worst = _worst(amounts, Fraction(str(dev.gamma)))
            bound = Fraction(str(c.right.const))
            ok &= (left + worst <= bound) if c.relation == "<=" else (left - worst >= bound)
        if not ok:
            continue
        value = sum(Fraction(str(a)) * x[k] for k, a in compiled.objective.coeffs.items())
        if best is None or (value < best if compiled.sense == "minimize" else value > best):
            best = value
    return best


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize("backend", ["highs", "scip"])
def test_the_rewrite_agrees_with_every_assignment_tried(seed, backend):
    compiled, moving = _random(seed)
    expected = _robust_best(compiled, moving)
    robust, _ = rewrite(compiled, moving)
    result, _ = solve_compiled(by_name(backend), robust, time_limit=10, seed=1)
    if expected is None:
        assert result.status == "infeasible", seed
    else:
        assert result.status == "optimal", (seed, result.status)
        assert abs(Fraction(str(result.objective)) - expected) <= Fraction(1, 10**6), (seed, result.objective, expected)


def test_the_random_models_are_not_one_easy_case():
    outcomes = {_robust_best(*_random(seed)) is None for seed in range(40)}
    assert outcomes == {True, False}


# -- through a run -------------------------------------------------------------------------------


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _scenario(db, ir) -> tuple[int, int]:
    domain = make_domain(db, "robust")
    item = make_entity_type(db, domain, "item", "resource")
    ids = {key: make_entity(db, item, key) for key in ITEMS}
    weight = make_parameter_def(db, domain, "weight", [item])
    value = make_parameter_def(db, domain, "value", [item])
    for key, (w, v) in ITEMS.items():
        make_parameter_value(db, weight, [ids[key]], w)
        make_parameter_value(db, value, [ids[key]], v)
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, ir)
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    return domain, scenario


@pytest.mark.parametrize("gamma, robust_value, price", [(1, 15, 2), (2, 13, 4)])
def test_a_robust_run_answers_robustly_and_reports_the_price(db, empty_queue, gamma, robust_value, price):
    domain, scenario = _scenario(db, _ir(gamma=gamma))
    try:
        run_id = enqueue_run(db, scenario, time_limit=20.0, robust=True)
        assert claim_next(db) == run_id
        outcome = execute_run(db, run_id)
        row = db.execute(text("SELECT objective, params, cache_key FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
        assert outcome.status == "optimal" and float(row["objective"]) == robust_value
        robust = row["params"]["robust"]
        assert robust["nominal"] == 17 and robust["price"] == price
        assert robust["rows"] == [{"rule": "c_capacity", "index": [], "moving": 4, "gamma": float(gamma)}]
        # A robust answer is to a different question: neither reused nor reusable.
        assert row["cache_key"] is None
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()


def test_a_robust_run_of_an_exact_model_says_so(db, empty_queue):
    domain, scenario = _scenario(db, _ir(exact=True))
    try:
        run_id = enqueue_run(db, scenario, time_limit=20.0, robust=True)
        claim_next(db)
        outcome = execute_run(db, run_id)
        params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
        assert outcome.status == "optimal" and outcome.objective == 17
        assert params["robust"]["rows"] == [] and "nominal one" in params["robust"]["note"]
    finally:
        db.execute(text("DELETE FROM run"))
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.commit()
