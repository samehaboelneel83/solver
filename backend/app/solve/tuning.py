"""A solver's own options, tuned per problem by Bayesian optimisation (9 October 2026).

The whitelist (`app.solve.params`) lists every option the platform may set and the values each may take; the
benchmark gate enabled the few that win everywhere. Which wins on *this* problem is an empirical question, and
most runs re-solve a problem already solved -- so each run is one measurement, and the problem's runs tune it:

1. **Defaults first.** A problem's first `WARMUP` runs on a backend use its options as the gate left them.
2. **Then a trial every other run**, chosen by Bayesian optimisation: a Gaussian process (squared-exponential
   kernel on the options one-hot encoded, noise for run-to-run variation) is fitted to the log of each run's
   score -- seconds to a proof, or an unproven run's time allowed times (2 + gap) -- and the configuration with
   the greatest expected improvement over the best median so far is tried. Up to `BUDGET` trials.
3. **Otherwise the best configuration**: the lowest median score among those measured at least twice (the
   defaults always are), so one lucky run decides nothing.
4. **Checked again**: one trial every `RECHECK` runs once the budget is spent -- the data may have changed.

Options only change how fast a solver answers, never what it may answer (that is the whitelist's promise), so a
trial costs time at worst. A run's own options, or the `solve.solver_params` setting, override the tuning. Each
run records what it used and why (`params.tuning`).
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from statistics import median
from typing import Any

import numpy as np

from app.solve.params import ENABLED, WHITELIST

WARMUP = 2
BUDGET = 12
RECHECK = 10
RECENT = 60


@dataclass(frozen=True)
class Tuned:
    options: dict[str, Any]
    trial: bool
    evidence: str


def space(backend: str) -> list[dict[str, Any]]:
    """Every configuration of the backend's whitelisted options (the enabled values as its default)."""
    options = WHITELIST.get(backend, {})
    names = sorted(options)
    return [dict(zip(names, values)) for values in itertools.product(*(options[n] for n in names))]


def default(backend: str) -> dict[str, Any]:
    options = WHITELIST.get(backend, {})
    return {name: ENABLED.get(backend, {}).get(name, values[0]) for name, values in options.items()}


def _key(config: dict[str, Any]) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in config.items()))


def _encode(backend: str, config: dict[str, Any]) -> np.ndarray:
    out = []
    for name in sorted(WHITELIST.get(backend, {})):
        values = WHITELIST[backend][name]
        out += [1.0 if str(config.get(name)) == str(v) else 0.0 for v in values]
    return np.array(out)


def score(run: dict[str, Any]) -> float:
    from app.solve.choices import _score

    return max(1e-3, _score(run))


def _expected_improvement(X: np.ndarray, y: np.ndarray, C: np.ndarray, best: float) -> np.ndarray:
    """EI of each candidate row of C under a GP fitted to (X, y), minimising y."""
    length, noise = 1.0, 0.1
    mean_y, std_y = float(y.mean()), float(y.std()) or 1.0
    t = (y - mean_y) / std_y

    def kernel(A, B):
        d = ((A[:, None, :] - B[None, :, :]) ** 2).sum(axis=2)
        return np.exp(-0.5 * d / length ** 2)

    K = kernel(X, X) + noise * np.eye(len(X))
    L = np.linalg.cholesky(K)
    alpha = np.linalg.solve(L.T, np.linalg.solve(L, t))
    Ks = kernel(C, X)
    mu = Ks @ alpha
    v = np.linalg.solve(L, Ks.T)
    var = np.maximum(1.0 + noise - (v ** 2).sum(axis=0), 1e-12)
    sigma = np.sqrt(var)
    target = (best - mean_y) / std_y
    z = (target - mu) / sigma
    cdf = 0.5 * (1 + np.vectorize(math.erf)(z / math.sqrt(2)))
    pdf = np.exp(-0.5 * z ** 2) / math.sqrt(2 * math.pi)
    return (target - mu) * cdf + sigma * pdf


def tune(backend: str, history: list[dict[str, Any]]) -> Tuned | None:
    """`history`: this problem's recent runs on `backend`, newest first, each {options, trial, status, seconds,
    limit, gap}. None when the backend has nothing to tune."""
    configs = space(backend)
    if len(configs) <= 1:
        return None
    base = default(backend)
    history = history[:RECENT]
    by: dict[tuple, list[float]] = {}
    for run in history:
        by.setdefault(_key(run.get("options") or base), []).append(score(run))
    measured = {k: v for k, v in by.items() if len(v) >= 2}
    if len(history) < WARMUP:
        return Tuned(base, False, f"{backend}: its default options ({len(history) + 1} of {WARMUP} runs before tuning)")
    best_key = min(measured, key=lambda k: median(measured[k])) if measured else _key(base)
    best_config = next((c for c in configs if _key(c) == best_key), base)
    best_median = median(measured[best_key]) if best_key in measured else median(by.get(_key(base), [1.0]))
    trials = sum(1 for r in history if r.get("trial"))
    last_trial = next((i for i, r in enumerate(history) if r.get("trial")), None)
    due = (trials < BUDGET and (last_trial is None or last_trial >= 1)) or \
          (trials >= BUDGET and (last_trial is None or last_trial >= RECHECK))
    if not due:
        return Tuned(best_config, False, f"{backend}: {_said(best_config)} -- the best median "
                                          f"({_seconds(best_median)}) over this problem's runs")
    # Bayesian optimisation: the GP on every measured run, EI over every configuration.
    X = np.array([_encode(backend, r.get("options") or base) for r in history])
    y = np.log(np.array([score(r) for r in history]))
    C = np.array([_encode(backend, c) for c in configs])
    ei = _expected_improvement(X, y, C, math.log(best_median))
    # A configuration measured twice or more has had its say: the trial goes to one that could still surprise.
    for i, c in enumerate(configs):
        if len(by.get(_key(c), [])) >= 2:
            ei[i] *= 0.5
    pick = configs[int(np.argmax(ei))]
    return Tuned(pick, True, f"{backend}: trying {_said(pick)} (Bayesian optimisation: the largest expected "
                             f"improvement on {_seconds(best_median)}, trial {trials + 1})")


def _said(config: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(config.items())) or "its defaults"


def _seconds(value: float) -> str:
    return f"{value * 1000:.3g} ms" if value < 1 else f"{value:.3g} s"
