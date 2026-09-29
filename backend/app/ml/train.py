"""Training a predictor from the domain's own data (Epic ML).

The rows are a domain's entities of one type: each entity's numeric
attributes are the inputs, one attribute is the target. Training runs in the
API process with hard size limits, so a request cannot tie up a worker; a
model too large to embed in a MILP is still stored, and the compiler says so
when a model version tries to optimize over it (`app.solve.predict`).

A *classifier* (`random_forest_classifier`) learns a yes-or-no target -- a
boolean, or any attribute holding exactly two values -- and predicts the
probability that it is the `positive` value: a number from 0 to 1 a rule can
read like any other prediction (a chance of churn, of a late delivery).

Metrics are measured on a held-out 20% of the rows (when there are at least
10), then the model is refitted on every row. The stored metrics therefore
describe a model trained on less data than the one stored -- the usual,
slightly pessimistic, convention -- and say so (`evaluated_on`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.ml.trees import from_sklearn

KINDS = ("random_forest", "gradient_boosting", "random_forest_classifier")
#: The range a random forest's `predict` reports: these percentiles of its trees.
RANGE = (10, 90)
MAX_ROWS = 200_000
MAX_TREES = 200
MAX_DEPTH = 12
MIN_ROWS = 5


class TrainingError(ValueError):
    """Why the rows cannot train a model, in words a person can act on."""


@dataclass(frozen=True)
class Trained:
    model: dict[str, Any]
    metrics: dict[str, Any]


def matrix(rows: list[dict[str, Any]], features: list[str], target: str) -> tuple[list[list[float]], list[float], int]:
    """The numeric rows: inputs in `features` order and the target. A row
    missing a value, or holding a non-number, is skipped and counted."""
    xs: list[list[float]] = []
    ys: list[float] = []
    skipped = 0
    for row in rows:
        values = [row.get(name) for name in [*features, target]]
        if any(not _number(v) for v in values):
            skipped += 1
            continue
        numbers = [float(v) for v in values]
        xs.append(numbers[:-1])
        ys.append(numbers[-1])
    return xs, ys, skipped


def label(value: Any) -> str | None:
    """A target value as the class it names: booleans as true/false, whole
    numbers without a decimal point, anything else as its text."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def classes(rows: list[dict[str, Any]], features: list[str], target: str, positive: str | None
            ) -> tuple[list[list[float]], list[float], int, str, str]:
    """The rows for a classifier: numeric inputs, the target as 1 (positive) or
    0, the skipped count, and the two classes (positive first)."""
    xs: list[list[float]] = []
    labels: list[str] = []
    skipped = 0
    for row in rows:
        named = label(row.get(target))
        inputs = [row.get(name) for name in features]
        if named is None or any(not _number(v) for v in inputs):
            skipped += 1
            continue
        xs.append([float(v) for v in inputs])
        labels.append(named)
    seen = sorted(set(labels))
    if len(seen) != 2:
        shown = ", ".join(seen[:5]) + (" …" if len(seen) > 5 else "")
        raise TrainingError(
            f"a yes-or-no model learns a target with exactly two values; {target} has {len(seen)}"
            + (f" ({shown})" if seen else "")
        )
    if positive is None:
        chosen = "true" if "true" in seen else seen[1]
    else:
        chosen = label(positive) or ""
        if chosen not in seen:
            raise TrainingError(f"{positive!r} is not one of {target}'s values ({', '.join(seen)})")
    other = seen[0] if seen[1] == chosen else seen[1]
    return xs, [1.0 if named == chosen else 0.0 for named in labels], skipped, chosen, other


def _number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, str):
        try:
            return math.isfinite(float(value))
        except ValueError:
            return False
    return False


def train(
    rows: list[dict[str, Any]],
    features: list[str],
    target: str,
    *,
    kind: str = "random_forest",
    trees: int = 50,
    max_depth: int = 6,
    min_samples_leaf: int = 2,
    seed: int = 0,
    positive: str | None = None,
) -> Trained:
    """Fit a tree ensemble and return it as `tree-ensemble/1` with metrics."""
    if kind not in KINDS:
        raise TrainingError(f"kind is one of {', '.join(KINDS)}")
    if not 1 <= trees <= MAX_TREES:
        raise TrainingError(f"trees is 1 to {MAX_TREES}")
    if not 1 <= max_depth <= MAX_DEPTH:
        raise TrainingError(f"max_depth is 1 to {MAX_DEPTH}")
    if not features or len(set(features)) != len(features) or target in features:
        raise TrainingError("features are distinct attribute names and do not include the target")
    if len(rows) > MAX_ROWS:
        raise TrainingError(f"at most {MAX_ROWS} rows train a model here")
    classify = kind == "random_forest_classifier"
    if classify:
        xs, ys, skipped, chosen, other = classes(rows, features, target, positive)
    else:
        xs, ys, skipped = matrix(rows, features, target)
    if len(xs) < MIN_ROWS:
        raise TrainingError(
            f"{len(xs)} rows have a number in every feature and the target; at least {MIN_ROWS} are needed"
        )

    import numpy as np
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
    from sklearn.metrics import accuracy_score, brier_score_loss, mean_absolute_error, mean_squared_error, r2_score
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split

    def make() -> Any:
        if classify:
            return RandomForestClassifier(
                n_estimators=trees, max_depth=max_depth, min_samples_leaf=min_samples_leaf,
                random_state=seed, n_jobs=1,
            )
        if kind == "random_forest":
            return RandomForestRegressor(
                n_estimators=trees, max_depth=max_depth, min_samples_leaf=min_samples_leaf,
                random_state=seed, n_jobs=1,
            )
        return GradientBoostingRegressor(
            n_estimators=trees, max_depth=max_depth, min_samples_leaf=min_samples_leaf,
            random_state=seed, learning_rate=0.1,
        )

    X, y = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    if classify:
        y = y.astype(int)
    metrics: dict[str, Any] = {"rows": len(xs), "rows_skipped": skipped}
    if classify:
        metrics.update(positive=chosen, negative=other, predicts=f"the probability that {target} is {chosen}")
    if len(xs) >= 10:
        # A stratified split keeps both classes on both sides where it can.
        stratify = y if classify and min(int(y.sum()), int(len(y) - y.sum())) >= 2 else None
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=seed, stratify=stratify)
        held = make().fit(X_tr, y_tr)
        metrics.update(
            evaluated_on="a held-out 20% of the rows; the stored model is refitted on all of them",
            holdout_rows=int(len(y_te)),
        )
        if classify:
            chance = _chance(held, X_te)
            metrics.update(
                accuracy=_round(accuracy_score(y_te, (chance >= 0.5).astype(int))),
                auc=_round(roc_auc_score(y_te, chance)) if len(set(y_te.tolist())) == 2 else None,
                brier=_round(brier_score_loss(y_te, chance)),
            )
        else:
            guess = held.predict(X_te)
            metrics.update(
                r2=_round(r2_score(y_te, guess)) if len(y_te) > 1 else None,
                mae=_round(mean_absolute_error(y_te, guess)),
                rmse=_round(math.sqrt(mean_squared_error(y_te, guess))),
            )
            if kind == "random_forest" and trees > 1:
                per_tree = np.stack([tree.predict(X_te) for tree in held.estimators_])
                low, high = np.percentile(per_tree, RANGE, axis=0)
                metrics.update(
                    interval=f"{RANGE[0]}th to {RANGE[1]}th percentile of the trees",
                    interval_coverage=_round(float(np.mean((y_te >= low) & (y_te <= high)))),
                )
    else:
        metrics["evaluated_on"] = "too few rows to hold any out; no accuracy is claimed"
    fitted = make().fit(X, y)
    if classify and len(fitted.classes_) != 2:  # pragma: no cover -- `classes` saw both
        raise TrainingError("the rows hold only one of the two values")
    return Trained(from_sklearn(fitted, features), metrics)


def _chance(model: Any, X: Any) -> Any:
    """The probability of class 1, whichever column it is (a split may miss a class)."""
    proba = model.predict_proba(X)
    columns = [int(c) for c in model.classes_]
    import numpy as np

    return proba[:, columns.index(1)] if 1 in columns else np.zeros(len(X))


def _round(value: float) -> float | None:
    return None if not math.isfinite(value) else round(float(value), 6)
