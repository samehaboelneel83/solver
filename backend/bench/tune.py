"""Tuning search: every whitelisted combination of a solver's options, per family (queue R10).

    python -m bench.tune --time-limit 20

For each family, the backend the rules choose for it, and every combination
of that backend's whitelisted options (`app.solve.params.WHITELIST` -- 9 for
CP-SAT, 6 for HiGHS, 9 for SCIP: few enough to try all, so no sampler is
needed): each is solved on the training instances (M and L, instances 0 and
1) and scored by the shifted geometric mean of its time (a solve without a
proof is charged the time limit). The best is then confirmed against the
solver's defaults (with the platform's enabled options) on instances it never
saw (L, instance 2, two seeds): it is kept only when at least 10% faster
there, never twice as slow, and never with a different optimum. Every solve
is in a sandboxed child, as a run is.
"""

from __future__ import annotations

import argparse
import itertools
import math
import time
from typing import Any

FAMILIES = ("rota", "rota_rates", "rota_teams", "facility", "facility_regions", "knapsack", "knapsack_depots",
            "flow_shop_timed", "districting")


def _sgm(values: list[float], shift: float = 1.0) -> float:
    return math.exp(sum(math.log(v + shift) for v in values) / len(values)) - shift


def combinations(backend: str) -> list[dict[str, Any]]:
    from app.solve.params import WHITELIST

    options = WHITELIST.get(backend, {})
    names = sorted(options)
    return [dict(zip(names, values)) for values in itertools.product(*(options[n] for n in names))]


def _solve(backend, compiled, params, time_limit, seed):
    from app.solve import sandbox

    started = time.monotonic()
    try:
        result = sandbox.run("app.solve.sandbox:solve_in_child",
                             {"backend": backend, "compiled": compiled, "time_limit": time_limit, "seed": seed,
                              "workers": 8, "gap_rel": 0.0, "solver_params": params},
                             time_limit=time_limit, workers=8)[0]
    except Exception:  # noqa: BLE001 -- a failed solve is charged the limit
        return time_limit, None
    seconds = time.monotonic() - started
    return (seconds if result.status == "optimal" else time_limit), (result.objective if result.status == "optimal" else None)


def tune(family: str, time_limit: float) -> dict[str, Any] | None:
    from app.solve import compile_model
    from app.solve.backends import choose
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from bench.families import generate

    def model(size, instance):
        case = generate(family, size, instance)
        compiled = compile_model(case.ir, case.data)
        return compiled, refine(classify(case.ir, case.data), compiled)

    compiled, found = model("M", 0)
    backend = choose(found)[0].name
    candidates = combinations(backend)
    if len(candidates) < 2:
        return None
    train = [model(size, i)[0] for size in ("M", "L") for i in (0, 1)]
    scores = []
    for params in candidates:
        times = [_solve(backend, m, params, time_limit, 1)[0] for m in train]
        scores.append((_sgm(times), params))
    default = candidates[0]  # every option's first value is the solver's default
    best_score, best = min(scores, key=lambda pair: pair[0])
    row = {"family": family, "backend": backend, "tried": len(candidates), "best": best,
           "train_default": round(dict((str(p), s) for s, p in scores)[str(default)], 3), "train_best": round(best_score, 3)}
    if best == default:
        return {**row, "verdict": "defaults best on training"}
    holdout = model("L", 2)[0]
    base = [_solve(backend, holdout, default, time_limit, seed) for seed in (1, 2)]
    tuned = [_solve(backend, holdout, best, time_limit, seed) for seed in (1, 2)]
    a, b = _sgm([t for t, _ in base]), _sgm([t for t, _ in tuned])
    wrong = any(x[1] is not None and y[1] is not None and abs(float(x[1]) - float(y[1])) > 1e-6 * max(1, abs(float(x[1])))
                for x, y in zip(base, tuned))
    slower = any(y[0] > 2 * x[0] and y[0] - x[0] > 0.5 for x, y in zip(base, tuned))
    kept = b <= 0.9 * a and not slower and not wrong
    return {**row, "holdout_default": round(a, 3), "holdout_tuned": round(b, 3),
            "verdict": "tuned" if kept else ("lost on held-out" if not wrong else "different optimum")}


def report(rows) -> str:
    fmt = lambda p: ", ".join(f"{k}={v}" for k, v in sorted(p.items()))  # noqa: E731
    lines = ["| family | backend | combinations | best on training | SGM s default -> best (training) | held-out default -> tuned | verdict |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        held = f"{r['holdout_default']} -> {r['holdout_tuned']}" if "holdout_default" in r else "-"
        lines.append(f"| {r['family']} | {r['backend']} | {r['tried']} | {fmt(r['best'])} | {r['train_default']} -> {r['train_best']} | {held} | {r['verdict']} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.tune", description=__doc__.split("\n\n")[0])
    parser.add_argument("--time-limit", type=float, default=20.0)
    parser.add_argument("--families", default=",".join(FAMILIES))
    args = parser.parse_args(argv)
    rows = []
    for family in args.families.split(","):
        row = tune(family, args.time_limit)
        if row:
            rows.append(row)
            print(report([row]).splitlines()[2], flush=True)
    print(report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
