"""PDLP against the simplex (GLOP) and HiGHS on growing linear programs (queue R1).

    python -m bench.pdlp --sizes 50,200,500,1000 --time-limit 120

A transport problem -- `n` sources, `n` sinks, a cost per pair -- has n^2
decisions and 2n^2 nonzeros. For each size this measures what the platform
pays before any solver starts (generating the data, compiling it with the
platform's own compiler) apart from the solve itself, and solves in a
sandboxed child as a run does, under the same memory ceiling
(`SOLVE_MEMORY_MB`, 4096 by default). Reported per size and backend: status,
objective, seconds, and how far PDLP's objective is from the proven one.

The question it answers: at the sizes this platform can build, is there a
point past which PDLP answers where the exact solvers cannot, or answers
faster -- and so what `app.solve.pdlp.LARGE_SCALE_NNZ` should be.
"""

from __future__ import annotations

import argparse
import random
import time

WORKERS = 8
BACKENDS = ("glop", "highs", "pdlp")


def transport(n: int, seed: int = 7) -> tuple[dict, dict]:
    rnd = random.Random(f"transport-{n}-{seed}")
    supply = {f"s{i}": rnd.randint(50, 150) for i in range(n)}
    total = sum(supply.values())
    demand_each = total * 0.9 / n
    ir = {
        "version": 2,
        "sets": ["source", "sink"],
        "parameters": {"cost": {"index": ["source", "sink"]}},
        "variables": {"ship": {"index": ["source", "sink"], "domain": "continuous", "lower": 0, "upper": 1000}},
        "constraints": [
            {"id": "c_supply", "forall": [{"index": "i", "set": "source"}],
             "left": {"sum": {"var": "ship", "index": ["i", "j"]}, "over": [{"index": "j", "set": "sink"}]},
             "relation": "<=", "right": {"attr": {"of": "i", "name": "supply"}}, "severity": "hard"},
            {"id": "c_demand", "forall": [{"index": "j", "set": "sink"}],
             "left": {"sum": {"var": "ship", "index": ["i", "j"]}, "over": [{"index": "i", "set": "source"}]},
             "relation": ">=", "right": {"attr": {"of": "j", "name": "demand"}}, "severity": "hard"},
        ],
        "objective": {"sense": "minimize", "terms": [{"id": "o_cost", "weight": 1, "expression": {
            "sum": {"mul": [{"par": "cost", "index": ["i", "j"]}, {"var": "ship", "index": ["i", "j"]}]},
            "over": [{"index": "i", "set": "source"}, {"index": "j", "set": "sink"}]}}]},
    }
    data = {
        "sets": {
            "source": [{"id": k, "supply": v} for k, v in supply.items()],
            "sink": [{"id": f"d{j}", "demand": round(demand_each, 3)} for j in range(n)],
        },
        "parameters": {"cost": [{"source": f"s{i}", "sink": f"d{j}", "value": rnd.randint(1, 100)}
                                for i in range(n) for j in range(n)]},
        "parameter_defaults": {},
        "relationships": {},
    }
    return ir, data


def _solve(backend: str, compiled, time_limit: float):
    from app.solve import sandbox

    started = time.perf_counter()
    try:
        result = sandbox.run(
            "app.solve.sandbox:solve_in_child",
            {"backend": backend, "compiled": compiled, "time_limit": time_limit, "seed": 1, "workers": WORKERS, "gap_rel": 0.0},
            time_limit=time_limit,
            workers=WORKERS,
        )[0]
        return result.status, (None if result.objective is None else float(result.objective)), time.perf_counter() - started, ""
    except Exception as exc:  # noqa: BLE001 -- a solver that dies is a result here
        return "failed", None, time.perf_counter() - started, f"{type(exc).__name__}: {str(exc)[:120]}"


def main() -> None:
    from app.solve import compile_model
    from app.solve.pdlp import nonzeros

    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="50,200,500,1000")
    parser.add_argument("--time-limit", type=float, default=120.0)
    args = parser.parse_args()
    rows = []
    for n in (int(s) for s in args.sizes.split(",")):
        t0 = time.perf_counter()
        ir, data = transport(n)
        generated = time.perf_counter() - t0
        t0 = time.perf_counter()
        compiled = compile_model(ir, data)
        compiling = time.perf_counter() - t0
        nnz = nonzeros(compiled)
        results = {b: _solve(b, compiled, args.time_limit) for b in BACKENDS}
        exact = next((r[1] for b, r in results.items() if b != "pdlp" and r[0] == "optimal"), None)
        for b, (status, objective, seconds, note) in results.items():
            off = "" if exact is None or objective is None or b != "pdlp" else f"{abs(objective - exact) / max(abs(exact), 1e-9):.2e}"
            rows.append((n, n * n, nnz, round(generated, 1), round(compiling, 1), b, status, objective, round(seconds, 2), off, note))
            print(rows[-1], flush=True)
    print("| n | decisions | nonzeros | generate s | compile s | backend | status | objective | solve s | PDLP rel. error | note |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join("" if v is None else str(v) for v in row) + " |")


if __name__ == "__main__":
    main()
