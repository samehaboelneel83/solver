"""Epic ML: the `tree-ensemble/1` format, its scikit-learn export, and training.

No database: these are the module's own promises. The export is exact (a
model predicts after export what it predicted before), the checker refuses
by name, and training reports honest holdout metrics.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from app.ml import train as training
from app.ml.trees import EnsembleError, check_ensemble, from_sklearn, leaves, predict, summary

STUMP = {
    "format": "tree-ensemble/1",
    "inputs": ["price", "promo"],
    "aggregation": "mean",
    "base": 0,
    "trees": [
        {"nodes": [
            {"feature": 0, "threshold": 5.5, "left": 1, "right": 2},
            {"value": 120},
            {"feature": 1, "threshold": 0.5, "left": 3, "right": 4},
            {"value": 60},
            {"value": 90},
        ]}
    ],
}


def _data(n=300, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.uniform(0, 10, (n, 3))
    y = 3 * X[:, 0] - X[:, 1] ** 2 + np.sin(X[:, 2]) + rng.normal(0, 0.3, n)
    return X, y


def test_a_split_sends_a_value_on_its_threshold_left_as_scikit_learn_does():
    assert predict(STUMP, [5.5, 0]) == 120
    assert predict(STUMP, [5.6, 0]) == 60
    assert predict(STUMP, [9, 1]) == 90


@pytest.mark.parametrize("make", ["RandomForestRegressor", "ExtraTreesRegressor", "GradientBoostingRegressor",
                                  "DecisionTreeRegressor"])
def test_an_exported_model_predicts_exactly_what_it_predicted_before(make):
    from sklearn import ensemble, tree

    cls = getattr(ensemble, make, None) or getattr(tree, make)
    kwargs = {"random_state": 0, "max_depth": 5}
    if make != "DecisionTreeRegressor":
        kwargs["n_estimators"] = 15
    X, y = _data()
    fitted = cls(**kwargs).fit(X, y)
    doc = from_sklearn(fitted, ["a", "b", "c"])
    probes = np.random.default_rng(9).uniform(-1, 11, (400, 3))
    ours = np.array([predict(doc, p) for p in probes])
    theirs = fitted.predict(probes)
    assert np.max(np.abs(ours - theirs)) < 1e-9


def test_a_model_this_platform_cannot_export_is_refused_by_name():
    from sklearn.linear_model import LinearRegression

    X, y = _data(50)
    with pytest.raises(EnsembleError, match="LinearRegression"):
        from_sklearn(LinearRegression().fit(X, y), ["a", "b", "c"])


def _broken(mutate):
    doc = copy.deepcopy(STUMP)
    mutate(doc)
    return doc


@pytest.mark.parametrize(
    "mutate, path",
    [
        (lambda d: d.update(format="pickle"), ["format"]),
        (lambda d: d.update(extra=1), ["extra"]),
        (lambda d: d.update(inputs=[]), ["inputs"]),
        (lambda d: d.update(inputs=["a", "a"]), ["inputs"]),
        (lambda d: d.update(aggregation="median"), ["aggregation"]),
        (lambda d: d.update(base=float("nan")), ["base"]),
        (lambda d: d.update(trees=[]), ["trees"]),
        (lambda d: d["trees"][0]["nodes"][1].update(value=float("inf")), ["trees", 0, "nodes", 1, "value"]),
        (lambda d: d["trees"][0]["nodes"][0].update(feature=2), ["trees", 0, "nodes", 0, "feature"]),
        (lambda d: d["trees"][0]["nodes"][0].update(left=0), ["trees", 0, "nodes", 0, "left"]),
        # A cycle: node 2 sends right back to node 1, which is also node 0's left.
        (lambda d: d["trees"][0]["nodes"][2].update(right=1), ["trees", 0, "nodes", 1]),
        # An orphan: a node nothing reaches.
        (lambda d: d["trees"][0]["nodes"].append({"value": 1}), ["trees", 0, "nodes", 5]),
        (lambda d: d["trees"][0]["nodes"][1].update(feature=0), ["trees", 0, "nodes", 1]),
    ],
)
def test_a_malformed_model_is_refused_at_the_element_that_is_wrong(mutate, path):
    with pytest.raises(EnsembleError) as caught:
        check_ensemble(_broken(mutate))
    assert caught.value.path == path


def test_leaves_carry_their_paths_and_the_summary_counts_them():
    found = leaves(STUMP["trees"][0]["nodes"])
    assert [leaf.value for leaf in found] == [120, 60, 90]
    assert found[2].path == ((0, 5.5, False), (1, 0.5, False))
    assert summary(STUMP) == {"inputs": 2, "trees": 1, "nodes": 5, "leaves": 3, "aggregation": "mean"}


def test_training_reports_holdout_metrics_and_stores_a_checked_model():
    X, y = _data()
    rows = [{"a": float(a), "b": float(b), "c": float(c), "y": float(v)} for (a, b, c), v in zip(X, y)]
    rows.append({"a": "not a number", "b": 1, "c": 1, "y": 1})
    rows.append({"a": 1, "b": 1, "y": 1})
    trained = training.train(rows, ["a", "b", "c"], "y", trees=20, max_depth=6)
    check_ensemble(trained.model)
    assert trained.model["inputs"] == ["a", "b", "c"]
    assert trained.metrics["rows"] == 300 and trained.metrics["rows_skipped"] == 2
    assert trained.metrics["holdout_rows"] == 60
    assert trained.metrics["r2"] > 0.9


def test_boosting_trains_to_a_summed_model():
    X, y = _data()
    rows = [{"a": float(a), "b": float(b), "c": float(c), "y": float(v)} for (a, b, c), v in zip(X, y)]
    trained = training.train(rows, ["a", "b", "c"], "y", kind="gradient_boosting", trees=30, max_depth=3)
    assert trained.model["aggregation"] == "sum" and trained.model["base"] != 0


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"kind": "svm"}, "kind"),
        ({"trees": 0}, "trees"),
        ({"max_depth": 99}, "max_depth"),
    ],
)
def test_training_refuses_settings_outside_its_limits(kwargs, message):
    with pytest.raises(training.TrainingError, match=message):
        training.train([{"a": 1, "y": 1}] * 10, ["a"], "y", **kwargs)


def test_too_few_usable_rows_is_said_with_the_count():
    with pytest.raises(training.TrainingError, match="2 rows"):
        training.train([{"a": 1, "y": 1}, {"a": 2, "y": 2}, {"a": None, "y": 3}], ["a"], "y")


def test_a_target_among_the_features_is_refused():
    with pytest.raises(training.TrainingError, match="target"):
        training.train([{"a": 1}] * 10, ["a"], "a")
