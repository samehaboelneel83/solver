"""Epic ML: `predict` compiled -- of data a number, of decisions exact rows.

The central promise: optimizing over a trained tree ensemble finds what
enumerating every input would find. Checked on small integer grids, where
brute force is cheap, for a random forest and for gradient boosting, on
every backend that takes a mixed-integer model; and checked by
`app.solve.verify` on every answer (the embedded prediction is re-made by the
model itself).
"""

from __future__ import annotations

import copy
import itertools
import json
from decimal import Decimal

import numpy as np
import pytest
from sqlalchemy import text

from app.ml.trees import from_sklearn, predict
from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.classify import classify
from app.solve.compile import Unsupported
from app.solve.predict import LEAF, MAX_EMBEDDED_LEAVES, ROW_ID
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from app.solve.verify import accept
from tests.test_functions import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401

A = {"var": "a", "index": []}
B = {"var": "b", "index": []}


def _fitted(kind: str, seed: int = 1):
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor

    rng = np.random.default_rng(seed)
    X = rng.uniform(0, 10, (400, 2))
    y = np.sin(X[:, 0]) * 10 + X[:, 1] * (10 - X[:, 1]) + rng.normal(0, 0.5, 400)
    if kind == "forest":
        model = RandomForestRegressor(n_estimators=12, max_depth=5, random_state=0)
    else:
        model = GradientBoostingRegressor(n_estimators=20, max_depth=3, random_state=0)
    return from_sklearn(model.fit(X, y), ["a", "b"])


def _ir(expression, *, sense="maximize", a=(0, 10), b=(0, 10), constraints=(), domain="integer"):
    return {
        "version": 2, "sets": [], "parameters": {}, "predictors": {"m": {"inputs": 2}},
        "variables": {
            "a": {"index": [], "domain": domain, "lower": a[0], "upper": a[1]},
            "b": {"index": [], "domain": domain, "lower": b[0], "upper": b[1]},
        },
        "constraints": list(constraints),
        "objective": {"sense": sense, "terms": [{"id": "o_goal", "weight": 1, "expression": expression}]},
    }


def _data(model):
    return {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {},
            "predictors": {"m": {"model": model}}}


BUDGET = {"id": "c_budget", "left": {"add": [A, B]}, "relation": "<=", "right": {"const": 12}, "severity": "hard"}
PREDICT = {"predict": "m", "of": [A, B]}


@pytest.mark.parametrize("kind", ["forest", "boosting"])
@pytest.mark.parametrize("backend", ["highs", "scip", "milp"])
@pytest.mark.parametrize("sense", ["maximize", "minimize"])
def test_optimizing_over_a_trained_model_finds_what_enumeration_finds(kind, backend, sense):
    model = _fitted(kind)
    compiled = compile_model(_ir(PREDICT, sense=sense, constraints=[BUDGET]), _data(model))
    pick = max if sense == "maximize" else min
    best = pick(predict(model, [a, b]) for a, b in itertools.product(range(11), repeat=2) if a + b <= 12)
    result, _ = solve_compiled(by_name(backend), compiled, time_limit=60, seed=1)
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(best, abs=1e-5)
    x = [result.assignments[("a", ())], result.assignments[("b", ())]]
    assert predict(model, x) == pytest.approx(best, abs=1e-5)
    report = accept(compiled, result)
    assert report["accepted"] and "predictions" in report["checks"]


def test_a_linear_input_is_split_on_as_one_expression():
    # m(a + b, a - b): the splits are on the sums, each written once per leaf.
    model = _fitted("forest")
    expression = {"predict": "m", "of": [{"add": [A, B]}, {"add": [A, {"mul": [{"const": -1}, B]}]}]}
    compiled = compile_model(_ir(expression, a=(0, 5), b=(0, 5)), _data(model))
    best = max(predict(model, [a + b, a - b]) for a, b in itertools.product(range(6), repeat=2))
    result, _ = solve_compiled(by_name("highs"), compiled, time_limit=60, seed=1)
    assert float(result.objective) == pytest.approx(best, abs=1e-5)


def test_a_prediction_from_data_is_a_number_and_adds_nothing_to_solve():
    model = _fitted("forest")
    expression = {"mul": [{"predict": "m", "of": [{"const": 4}, {"const": 3}]}, A]}
    compiled = compile_model(_ir(expression), _data(model))
    assert not compiled.predictions
    assert not any(key[0] == LEAF for key in compiled.variables)
    assert float(compiled.objective.coeffs[("a", ())]) == pytest.approx(predict(model, [4, 3]))
    assert classify(_ir(expression), _data(model)).model_class == "IP"


def test_leaves_the_bounds_rule_out_are_not_written():
    model = _fitted("forest")
    wide = compile_model(_ir(PREDICT), _data(model))
    narrow = compile_model(_ir(PREDICT, a=(2, 3), b=(7, 7)), _data(model))
    count = lambda c: sum(1 for key in c.variables if key[0] == LEAF)  # noqa: E731
    assert count(narrow) < count(wide) / 4
    result, _ = solve_compiled(by_name("highs"), narrow, time_limit=30, seed=1)
    best = max(predict(model, [a, 7]) for a in (2, 3))
    assert float(result.objective) == pytest.approx(best, abs=1e-5)


def test_the_same_prediction_written_twice_is_one_set_of_choices():
    model = _fitted("forest")
    once = compile_model(_ir(PREDICT), _data(model))
    twice = compile_model(_ir({"add": [PREDICT, PREDICT]}), _data(model))
    assert len(twice.predictions) == 1
    assert sum(1 for k in twice.variables if k[0] == LEAF) == sum(1 for k in once.variables if k[0] == LEAF)


def test_an_input_without_a_declared_upper_bound_is_refused_by_name():
    model = _fitted("forest")
    ir = _ir(PREDICT)
    del ir["variables"]["b"]["upper"]
    with pytest.raises(Unsupported, match="reads b, which declares no upper bound"):
        compile_model(ir, _data(model))


def test_a_model_too_large_to_embed_is_refused_with_what_to_do():
    from sklearn.ensemble import RandomForestRegressor

    rng = np.random.default_rng(3)
    X = rng.uniform(0, 10, (600, 2))
    deep = from_sklearn(RandomForestRegressor(n_estimators=4, random_state=0).fit(X, X.sum(axis=1)), ["a", "b"])
    model = copy.deepcopy(deep)
    # Copies of fully grown trees: within the format's limits, past the leaf cap.
    per_tree = sum(1 for n in deep["trees"][0]["nodes"] if "value" in n)
    model["trees"] = deep["trees"] * (MAX_EMBEDDED_LEAVES // (per_tree * 4) + 2)
    with pytest.raises(Unsupported, match="fewer or shallower trees"):
        compile_model(_ir(PREDICT), _data(model))


def test_a_dataset_frozen_without_the_predictor_says_so():
    with pytest.raises(Unsupported, match="carries no predictor 'm'"):
        compile_model(_ir(PREDICT), {"predictors": {}})


def test_a_prediction_over_decisions_makes_the_model_mixed_integer_and_fractional():
    model = _fitted("forest")
    found = classify(_ir(PREDICT, domain="continuous"), _data(model))
    assert found.model_class == "MILP"
    assert {"integral", "fractional-data"} <= found.needs
    assert any("trained model m" in reason for reason in found.reasons)


def test_the_rows_are_the_compiler_s_own_and_carry_the_prediction_they_serve():
    compiled = compile_model(_ir(PREDICT), _data(_fitted("forest")))
    rows = [c for c in compiled.constraints if c.id == ROW_ID]
    assert rows and all(c.index["predict"] == "m" for c in rows)


def test_verification_refuses_an_answer_whose_rows_disagree_with_the_model():
    model = _fitted("forest")
    compiled = compile_model(_ir(PREDICT), _data(model))
    result, _ = solve_compiled(by_name("highs"), compiled, time_limit=30, seed=1)
    # Tamper with what the rows say the prediction is.
    compiled.predictions[0].expression.const += Decimal(5)
    report = accept(compiled, result)
    assert not report["accepted"]
    assert report["failures"][-1]["kind"] == "prediction_mismatch"


def test_a_run_freezes_the_predictor_and_solves_over_it(db, empty_queue):  # noqa: F811
    model = _fitted("boosting")
    domain = make_domain(db, "predict")
    db.execute(
        text("INSERT INTO predictor (domain_id, name, inputs, model) VALUES (:d, 'm', :i, CAST(:m AS jsonb))"),
        {"d": domain, "i": model["inputs"], "m": json.dumps(model)},
    )
    problem = make_problem(db, domain)
    with_model = make_model_version(db, problem, _ir(PREDICT, constraints=[BUDGET]))
    without = make_model_version(db, problem, {**_ir(A), "predictors": None} | {"predictors": {}})
    plain = _ir(A)
    del plain["predictors"]
    no_predictors = make_model_version(db, problem, plain)
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
        {"p": problem, "v": with_model},
    ).scalar_one()
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=30.0, reuse=False)
    claim_next(db)
    outcome = execute_run(db, run_id)
    best = max(predict(model, [a, b]) for a, b in itertools.product(range(11), repeat=2) if a + b <= 12)
    row = db.execute(
        text("SELECT r.objective, d.data FROM run r JOIN dataset d ON d.id = r.dataset_id WHERE r.id = :r"),
        {"r": run_id},
    ).mappings().one()
    assert outcome.status == "optimal"
    assert float(row["objective"]) == pytest.approx(best, abs=1e-5)
    assert row["data"]["predictors"]["m"]["model"] == model
    # The compiler's own rows get no constraint_result of their own.
    ids = db.execute(text("SELECT constraint_id FROM constraint_result WHERE run_id = :r"), {"r": run_id}).scalars().all()
    assert "c_budget" in ids and not any(i.startswith("__") for i in ids)
    # A model that declares no predictors freezes exactly what it did before 0087.
    for version in (no_predictors,):
        dataset = db.execute(text("SELECT snapshot_dataset(:v)"), {"v": version}).scalar_one()
        data = db.execute(text("SELECT data FROM dataset WHERE id = :d"), {"d": dataset}).scalar_one()
        assert "predictors" not in data
    # One that declares an empty set freezes an empty set.
    dataset = db.execute(text("SELECT snapshot_dataset(:v)"), {"v": without}).scalar_one()
    data = db.execute(text("SELECT data FROM dataset WHERE id = :d"), {"d": dataset}).scalar_one()
    assert data["predictors"] == {}
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
    db.commit()


def test_the_readiness_check_reads_the_workspace_s_predictors(db):  # noqa: F811
    """Benchmark re-test, October 2026: a model reading a forecast was reported "the dataset carries
    no predictor ...; it was frozen before the model declared it" on the problem's Overview, and
    offered no Solve -- the check built today's data without the trained models."""
    from app.api.preflight import model_findings
    from app.solve.preview import live_data

    model = _fitted("boosting")
    domain = make_domain(db, "predict_check")
    db.execute(
        text("INSERT INTO predictor (domain_id, name, inputs, model) VALUES (:d, 'm', :i, CAST(:m AS jsonb))"),
        {"d": domain, "i": model["inputs"], "m": json.dumps(model)},
    )
    problem = make_problem(db, domain)
    ir = _ir(PREDICT, constraints=[BUDGET])
    assert live_data(db, domain, ir)["predictors"]["m"]["model"] == model
    found = model_findings(db, domain, problem, ir)
    assert not [f for f in found["findings"] if f["code"] == "does_not_compile"], found["findings"]
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
    db.commit()


@pytest.mark.parametrize("kind", ["forest", "boosting"])
@pytest.mark.parametrize("sense", ["maximize", "minimize"])
def test_a_prediction_varying_in_one_input_is_its_step_function_and_finds_what_enumeration_finds(kind, sense):
    """Benchmark round 4: a yield model read one decision (irrigation) and data; it is a step function of it."""
    model = _fitted(kind)
    expression = {"predict": "m", "of": [A, {"const": 3}]}
    compiled = compile_model(_ir(expression, sense=sense, domain="continuous"), _data(model))
    steps = [k for k in compiled.variables if k[0] == LEAF]
    assert steps and all(k[1][1] == "step" for k in steps)
    pick = max if sense == "maximize" else min
    grid = sorted({0.0, 10.0, *(float(n["threshold"]) for t in model["trees"] for n in t["nodes"] if "value" not in n and n["feature"] == 0)})
    best = pick(predict(model, [x, 3]) for x in [*grid, *(x + 1e-5 for x in grid)] if 0 <= x <= 10)
    result, _ = solve_compiled(by_name("highs"), compiled, time_limit=60, seed=1)
    assert result.status == "optimal"
    assert float(result.objective) == pytest.approx(best, abs=1e-4)
    assert accept(compiled, result)["accepted"]


def test_a_model_past_the_leaf_cap_fits_as_a_step_function_of_its_one_decision():
    """Benchmark round 4: an R² 0.98 model was refused for more than 20,000 leaf choices."""
    from sklearn.ensemble import RandomForestRegressor

    rng = np.random.default_rng(3)
    X = rng.uniform(0, 10, (600, 2))
    deep = from_sklearn(RandomForestRegressor(n_estimators=4, random_state=0).fit(X, X.sum(axis=1)), ["a", "b"])
    model = copy.deepcopy(deep)
    per_tree = sum(1 for n in deep["trees"][0]["nodes"] if "value" in n)
    model["trees"] = deep["trees"] * (MAX_EMBEDDED_LEAVES // (per_tree * 4) + 2)
    compiled = compile_model(_ir({"predict": "m", "of": [A, {"const": 5}]}), _data(model))
    result, _ = solve_compiled(by_name("highs"), compiled, time_limit=60, seed=1)
    best = max(predict(model, [a, 5]) for a in range(11))
    assert float(result.objective) == pytest.approx(best, abs=1e-5)
