"""Training a predictor from the domain's own data (Epic ML).

The rows are a domain's entities of one type: each entity's numeric
attributes are the inputs, one attribute is the target. Training runs in the
API process with hard size limits, so a request cannot tie up a worker; a
model too large to embed in a MILP is still stored, and the compiler says so
when a model version tries to optimize over it (`app.solve.predict`).

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

KINDS = ("random_forest", "gradient_boosting")
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
    xs, ys, skipped = matrix(rows, features, target)
    if len(xs) < MIN_ROWS:
        raise TrainingError(
            f"{len(xs)} rows have a number in every feature and the target; at least {MIN_ROWS} are needed"
        )

    import numpy as np
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    from sklearn.model_selection import train_test_split

    def make() -> Any:
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
    metrics: dict[str, Any] = {"rows": len(xs), "rows_skipped": skipped}
    if len(xs) >= 10:
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=seed)
        held = make().fit(X_tr, y_tr)
        guess = held.predict(X_te)
        metrics.update(
            evaluated_on="a held-out 20% of the rows; the stored model is refitted on all of them",
            holdout_rows=int(len(y_te)),
            r2=_round(r2_score(y_te, guess)) if len(y_te) > 1 else None,
            mae=_round(mean_absolute_error(y_te, guess)),
            rmse=_round(math.sqrt(mean_squared_error(y_te, guess))),
        )
    else:
        metrics["evaluated_on"] = "too few rows to hold any out; no accuracy is claimed"
    fitted = make().fit(X, y)
    return Trained(from_sklearn(fitted, features), metrics)


def _round(value: float) -> float | None:
    return None if not math.isfinite(value) else round(float(value), 6)
