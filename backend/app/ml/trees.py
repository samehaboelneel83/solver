"""Trained tree ensembles as data: the `tree-ensemble/1` format (Epic ML).

A predictor is a trained regression model the problem IR reads through a
`predict` term. It is stored, frozen and shipped as plain JSON -- never as a
pickle, because loading a pickle runs code and the IR's promise is that a
model is data, not code.

The format::

    {"format": "tree-ensemble/1",
     "inputs": ["price", "promotion"],
     "aggregation": "mean",          # "mean" (random forest) or "sum" (boosting)
     "base": 0,                      # added to the aggregate
     "trees": [{"nodes": [{"feature": 0, "threshold": 4.5, "left": 1, "right": 2},
                          {"value": 120.0}, {"value": 80.0}]}]}

Node 0 is the root. A split sends ``x[feature] <= threshold`` left and
anything greater right -- scikit-learn's rule, so an exported model predicts
exactly what it predicted before export. A leaf carries only ``value``.

Everything that reads a predictor (the registry API, `snapshot_dataset()`'s
consumer the compiler, `app.solve.verify`) goes through `check_ensemble`
first, so a malformed document is refused by name once, at the door, and
every later reader may assume the shape.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

FORMAT = "tree-ensemble/1"
AGGREGATIONS = ("mean", "sum")

MAX_INPUTS = 32
MAX_TREES = 500
MAX_DEPTH = 16
MAX_NODES = 100_000

_SPLIT_KEYS = frozenset({"feature", "threshold", "left", "right"})
_LEAF_KEYS = frozenset({"value"})
_TOP_KEYS = frozenset({"format", "inputs", "aggregation", "base", "trees"})


class EnsembleError(ValueError):
    """Why a document is not a `tree-ensemble/1` model. `path` names the
    element, as a list of keys and positions, so an API can point at it."""

    def __init__(self, message: str, path: Sequence[str | int] = ()) -> None:
        super().__init__(message)
        self.path = list(path)


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _is_index(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_ensemble(doc: Any) -> None:
    """Raise `EnsembleError` naming the first thing wrong with ``doc``.

    Checks the shape, the limits, finite numbers, input positions in range,
    and that every tree is a proper binary tree rooted at node 0: each node
    reached exactly once, so no cycle and no orphan.
    """
    if not isinstance(doc, dict):
        raise EnsembleError("a predictor model is a JSON object")
    unknown = set(doc) - _TOP_KEYS
    if unknown:
        raise EnsembleError(f"unknown key {sorted(unknown)[0]!r}", [sorted(unknown)[0]])
    if doc.get("format") != FORMAT:
        raise EnsembleError(f"format is {FORMAT!r}", ["format"])
    inputs = doc.get("inputs")
    if (
        not isinstance(inputs, list)
        or not 1 <= len(inputs) <= MAX_INPUTS
        or not all(isinstance(n, str) and n for n in inputs)
        or len(set(inputs)) != len(inputs)
    ):
        raise EnsembleError(
            f"inputs are 1 to {MAX_INPUTS} distinct, non-empty names", ["inputs"]
        )
    if doc.get("aggregation") not in AGGREGATIONS:
        raise EnsembleError(f"aggregation is one of {', '.join(AGGREGATIONS)}", ["aggregation"])
    if "base" in doc and not _is_number(doc["base"]):
        raise EnsembleError("base is a finite number", ["base"])
    trees = doc.get("trees")
    if not isinstance(trees, list) or not 1 <= len(trees) <= MAX_TREES:
        raise EnsembleError(f"trees are 1 to {MAX_TREES} trees", ["trees"])
    total = 0
    for t, tree in enumerate(trees):
        if not isinstance(tree, dict) or set(tree) != {"nodes"} or not isinstance(tree["nodes"], list):
            raise EnsembleError('a tree is {"nodes": [...]}', ["trees", t])
        nodes = tree["nodes"]
        if not nodes:
            raise EnsembleError("a tree has at least one node", ["trees", t, "nodes"])
        total += len(nodes)
        if total > MAX_NODES:
            raise EnsembleError(f"the model has more than {MAX_NODES} nodes", ["trees", t])
        _check_tree(nodes, len(inputs), ["trees", t, "nodes"])


def _check_tree(nodes: list[Any], n_inputs: int, path: list[str | int]) -> None:
    seen = [False] * len(nodes)
    stack: list[tuple[int, int]] = [(0, 0)]
    while stack:
        i, depth = stack.pop()
        if seen[i]:
            raise EnsembleError("a node is reached twice; a tree has no shared nodes", [*path, i])
        seen[i] = True
        node = nodes[i]
        if not isinstance(node, dict):
            raise EnsembleError("a node is an object", [*path, i])
        keys = set(node)
        if keys == _LEAF_KEYS:
            if not _is_number(node["value"]):
                raise EnsembleError("a leaf's value is a finite number", [*path, i, "value"])
            continue
        if keys != _SPLIT_KEYS:
            raise EnsembleError(
                'a node is a split {"feature", "threshold", "left", "right"} or a leaf {"value"}',
                [*path, i],
            )
        if depth >= MAX_DEPTH:
            raise EnsembleError(f"a tree is at most {MAX_DEPTH} splits deep", [*path, i])
        feature = node["feature"]
        if not _is_index(feature) or not 0 <= feature < n_inputs:
            raise EnsembleError(f"feature is an input position 0..{n_inputs - 1}", [*path, i, "feature"])
        if not _is_number(node["threshold"]):
            raise EnsembleError("threshold is a finite number", [*path, i, "threshold"])
        for side in ("left", "right"):
            child = node[side]
            if not _is_index(child) or not 0 < child < len(nodes):
                raise EnsembleError(f"{side} is the position of another node of this tree", [*path, i, side])
            stack.append((child, depth + 1))
    if not all(seen):
        orphan = seen.index(False)
        raise EnsembleError("a node is not reachable from the root", [*path, orphan])


def predict(doc: dict[str, Any], x: Sequence[float]) -> float:
    """The model's prediction at ``x`` (inputs in the model's order)."""
    total = 0.0
    for tree in doc["trees"]:
        total += leaf_value(tree["nodes"], x)
    if doc["aggregation"] == "mean":
        total /= len(doc["trees"])
    return float(doc.get("base", 0)) + total


def spread(doc: dict[str, Any], x: Sequence[float], low: float = 10, high: float = 90) -> tuple[float, float] | None:
    """The `low`-th and `high`-th percentiles of the trees' own predictions
    at ``x`` -- a quantile-forest style range for an averaged ensemble. None
    for a summed one (a boosted tree is a correction, not a guess) or a
    single tree. The spread of the trees, not a calibrated interval: training
    measures how often it holds (`interval_coverage`)."""
    if doc["aggregation"] != "mean" or len(doc["trees"]) < 2:
        return None
    base = float(doc.get("base", 0))
    values = sorted(base + leaf_value(tree["nodes"], x) for tree in doc["trees"])
    return _percentile(values, low), _percentile(values, high)


def _percentile(ordered: list[float], q: float) -> float:
    """Linear interpolation between order statistics, as numpy's default."""
    at = (len(ordered) - 1) * q / 100
    below = math.floor(at)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (ordered[above] - ordered[below]) * (at - below)


def leaf_value(nodes: list[dict[str, Any]], x: Sequence[float]) -> float:
    node = nodes[0]
    while "value" not in node:
        node = nodes[node["left"] if x[node["feature"]] <= node["threshold"] else node["right"]]
    return float(node["value"])


@dataclass(frozen=True)
class Leaf:
    """One leaf with the conditions on its path: ``(feature, threshold,
    goes_left)`` for each split from the root down."""

    value: float
    path: tuple[tuple[int, float, bool], ...]


def leaves(nodes: list[dict[str, Any]]) -> list[Leaf]:
    """Every leaf of a tree with its path, in depth-first order."""
    out: list[Leaf] = []
    stack: list[tuple[int, tuple[tuple[int, float, bool], ...]]] = [(0, ())]
    while stack:
        i, path = stack.pop()
        node = nodes[i]
        if "value" in node:
            out.append(Leaf(float(node["value"]), path))
            continue
        f, theta = node["feature"], float(node["threshold"])
        stack.append((node["right"], (*path, (f, theta, False))))
        stack.append((node["left"], (*path, (f, theta, True))))
    return out


def summary(doc: dict[str, Any]) -> dict[str, Any]:
    """Size facts for the registry and for the compiler's size report."""
    trees = doc["trees"]
    n_leaves = sum(1 for tree in trees for node in tree["nodes"] if "value" in node)
    return {
        "inputs": len(doc["inputs"]),
        "trees": len(trees),
        "nodes": sum(len(tree["nodes"]) for tree in trees),
        "leaves": n_leaves,
        "aggregation": doc["aggregation"],
    }


def from_sklearn(model: Any, inputs: list[str]) -> dict[str, Any]:
    """Export a fitted scikit-learn regressor to `tree-ensemble/1`.

    Supports `DecisionTreeRegressor`, `RandomForestRegressor`,
    `ExtraTreesRegressor` (all averaged) and `GradientBoostingRegressor`
    (summed; the learning rate is folded into the leaf values and the
    initial estimate becomes `base`). A two-class `RandomForestClassifier`
    trained on 0 and 1 exports as the averaged probability of class 1 --
    what its `predict_proba(...)[:, 1]` says -- so it embeds in a model
    exactly as a regressor does. Anything else is refused by name rather
    than exported wrongly.
    """
    name = type(model).__name__
    positive: int | None = None
    if name == "RandomForestClassifier":
        classes = [int(c) for c in getattr(model, "classes_", [])]
        if sorted(classes) != [0, 1]:
            raise EnsembleError("a classifier is exported when it was trained on the two classes 0 and 1")
        positive = classes.index(1)
        estimators, aggregation, base, scale = list(model.estimators_), "mean", 0.0, 1.0
    elif name == "DecisionTreeRegressor":
        estimators, aggregation, base, scale = [model], "mean", 0.0, 1.0
    elif name in ("RandomForestRegressor", "ExtraTreesRegressor"):
        estimators, aggregation, base, scale = list(model.estimators_), "mean", 0.0, 1.0
    elif name == "GradientBoostingRegressor":
        if getattr(model, "loss", "squared_error") != "squared_error":
            raise EnsembleError("only squared-error gradient boosting is exported")
        estimators = [row[0] for row in model.estimators_]
        aggregation, scale = "sum", float(model.learning_rate)
        base = float(model.init_.constant_.ravel()[0]) if hasattr(model.init_, "constant_") else 0.0
    else:
        raise EnsembleError(f"{name} is not a tree ensemble this platform exports")
    trees = []
    for estimator in estimators:
        tree = estimator.tree_
        nodes: list[dict[str, Any]] = []
        for i in range(tree.node_count):
            left, right = int(tree.children_left[i]), int(tree.children_right[i])
            if left == -1:
                if positive is None:
                    nodes.append({"value": float(tree.value[i].ravel()[0]) * scale})
                else:
                    counts = tree.value[i].ravel()
                    nodes.append({"value": float(counts[positive] / counts.sum())})
            else:
                nodes.append(
                    {"feature": int(tree.feature[i]), "threshold": float(tree.threshold[i]),
                     "left": left, "right": right}
                )
        trees.append({"nodes": nodes})
    doc = {"format": FORMAT, "inputs": list(inputs), "aggregation": aggregation, "base": base, "trees": trees}
    check_ensemble(doc)
    return doc
