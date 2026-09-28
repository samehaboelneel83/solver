"""How long a run will take: a random forest over the organization's own runs (Epic ML).

Every run records its model's fingerprint (`app.solve.fingerprint`) once it
compiles, and its wall time once it settles. That history is exactly what a
run-time estimate needs: models of this size and shape, on this solver, with
this time limit, took this long here. A random forest regression on
``log(seconds)`` learns it without any assumption about which features
matter, and the spread of its trees gives a rough range.

Honest about what it is:

- **Per organization**, trained on that organization's settled runs only.
- **No estimate below `MIN_RUNS`** settled runs with a fingerprint: the
  answer then says how many more it needs, not a guess.
- **The range is the spread of the trees** (their 10th and 90th
  percentiles), not a calibrated interval, and the response says so.
- Cached per organization for `CACHE_SECONDS`, and refitted when the number
  of settled runs it learned from has grown by a fifth.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any

MIN_RUNS = 30
MAX_RUNS = 5_000
CACHE_SECONDS = 600
TREES = 60

#: The fingerprint's numbers the estimate reads, in a fixed order. Counts are
#: taken as log(1 + n): a model twice the size is not twice as different.
_COUNTS = (
    "variables", "binary", "integer", "continuous", "auxiliary", "rows", "nnz",
    "rows_partition", "rows_cover", "rows_packing", "rows_cardinality", "rows_knapsack",
    "rows_general", "rows_quadratic", "rows_conditional", "rows_scheduling", "rows_connectivity",
    "intervals", "curves", "functions", "soft_rules", "blocks", "objective_terms",
)
_PLAIN = ("density", "coef_range_log10", "bounds_declared", "objective_degree")
_FLAGS = ("integral_data", "lexicographic")


def features(fingerprint: dict[str, Any], solver: str, time_limit: float | None, solvers: list[str]) -> list[float]:
    row = [math.log1p(max(0.0, float(fingerprint.get(k, 0) or 0))) for k in _COUNTS]
    row += [float(fingerprint.get(k, 0) or 0) for k in _PLAIN]
    row += [1.0 if fingerprint.get(k) else 0.0 for k in _FLAGS]
    row.append(math.log1p(float(time_limit)) if time_limit else 0.0)
    row += [1.0 if solver == s else 0.0 for s in solvers]
    return row


@dataclass(frozen=True)
class Estimate:
    seconds: float
    low: float
    high: float
    based_on: int


class _Model:
    def __init__(self, forest: Any, solvers: list[str], runs: int) -> None:
        self.forest, self.solvers, self.runs, self.fitted_at = forest, solvers, runs, time.monotonic()

    def estimate(self, fingerprint: dict[str, Any], solver: str, time_limit: float | None) -> Estimate:
        import numpy as np

        x = np.asarray([features(fingerprint, solver, time_limit, self.solvers)])
        per_tree = np.asarray([tree.predict(x)[0] for tree in self.forest.estimators_])
        seconds = float(np.expm1(per_tree.mean()))
        low, high = (float(np.expm1(q)) for q in np.percentile(per_tree, [10, 90]))
        if time_limit:
            # A run stops at its limit, whatever the forest says.
            seconds, low, high = (min(v, float(time_limit)) for v in (seconds, low, high))
        return Estimate(max(0.0, seconds), max(0.0, low), max(0.0, high), self.runs)


def fit(history: list[tuple[dict[str, Any], str, float | None, float]]) -> _Model | None:
    """`history`: (fingerprint, solver, time limit, wall seconds) of settled
    runs. None when there are fewer than `MIN_RUNS`."""
    if len(history) < MIN_RUNS:
        return None
    import numpy as np
    from sklearn.ensemble import RandomForestRegressor

    solvers = sorted({solver for _, solver, _, _ in history})
    X = np.asarray([features(fp, solver, limit, solvers) for fp, solver, limit, _ in history])
    y = np.log1p(np.asarray([max(0.0, float(seconds)) for *_, seconds in history]))
    forest = RandomForestRegressor(n_estimators=TREES, min_samples_leaf=2, random_state=0, n_jobs=1).fit(X, y)
    return _Model(forest, solvers, len(history))


_cache: dict[str, _Model | None] = {}
_counts: dict[str, int] = {}
_lock = threading.Lock()


def model_for(organization: str, count: int, load) -> _Model | None:
    """The organization's fitted model, refitted when stale. `count` is how
    many usable runs it has now; `load()` returns them when a refit is due."""
    with _lock:
        cached = _cache.get(organization)
        grown = count >= max(MIN_RUNS, int(_counts.get(organization, 0) * 1.2))
        fresh = cached is not None and time.monotonic() - cached.fitted_at < CACHE_SECONDS
        if organization in _cache and (fresh or cached is None) and not grown:
            return cached
    model = fit(load())
    with _lock:
        _cache[organization] = model
        _counts[organization] = count
    return model


def clear() -> None:
    with _lock:
        _cache.clear()
        _counts.clear()
