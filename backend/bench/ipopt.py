"""IPOPT after SCIP on continuous nonlinear models, on the bench (queue R6).

    python -m bench.ipopt --time-limit 20

Two nonconvex families at growing sizes -- `sines` (a sine and a cosine of
neighbouring decisions per decision, under a budget) and `bilinear` (products
of neighbours, under a budget and a quadratic cap) -- the kind SCIP proves by
spatial branch and bound when small and runs out of time on when large. SCIP
alone for the time allowed, then, as a run with `solve.local_fallback` does,
IPOPT for a quarter more from SCIP's answer. Reported: SCIP's status, answer
and bound; the answer after the fallback. The verdict is "enable" when the
fallback improves the answer on both families and never claims more than the
bound allows.
"""

from __future__ import annotations

import argparse
import random

SIZES = (10, 50, 200)


def sines(n: int, seed: int = 7) -> dict:
    rnd = random.Random(f"sines-{n}-{seed}")
    x = lambda i: {"var": f"x{i}", "index": []}  # noqa: E731
    terms = []
    for i in range(n):
        terms.append({"id": f"o_s{i}", "weight": round(rnd.uniform(0.5, 2), 3), "expression": {"fn": "sin", "of": x(i)}})
        terms.append({"id": f"o_c{i}", "weight": round(rnd.uniform(0.2, 1), 3),
                      "expression": {"fn": "cos", "of": {"add": [x(i), x((i + 1) % n)]}}})
    return {
        "version": 2, "sets": [], "parameters": {},
        "variables": {f"x{i}": {"index": [], "domain": "continuous", "lower": 0, "upper": 10} for i in range(n)},
        "constraints": [{"id": "c_budget", "left": {"add": [x(i) for i in range(n)]} if n > 1 else x(0),
                         "relation": "<=", "right": {"const": 4 * n}, "severity": "hard"}],
        "objective": {"sense": "maximize", "terms": terms},
    }


def bilinear(n: int, seed: int = 7) -> dict:
    rnd = random.Random(f"bilinear-{n}-{seed}")
    x = lambda i: {"var": f"x{i}", "index": []}  # noqa: E731
    return {
        "version": 2, "sets": [], "parameters": {},
        "variables": {f"x{i}": {"index": [], "domain": "continuous", "lower": 0, "upper": 10} for i in range(n)},
        "constraints": [{"id": "c_budget", "left": {"add": [x(i) for i in range(n)]}, "relation": "<=",
                         "right": {"const": 3 * n}, "severity": "hard"}],
        "objective": {"sense": "maximize", "terms": [
            {"id": f"o_{i}", "weight": round(rnd.uniform(0.5, 2), 3), "expression": {"mul": [x(i), x((i + 1) % n)]}}
            for i in range(n)
        ] + [{"id": f"o_q{i}", "weight": -round(rnd.uniform(0.1, 0.5), 3), "expression": {"mul": [x(i), x(i)]}}
             for i in range(n)]},
    }


FAMILIES = {"sines": sines, "bilinear": bilinear}
NO_DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}


def _row(family: str, n: int, time_limit: float):
    from app.solve import compile_model, sandbox
    from app.solve.backends import SCIP
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from app.solve.service import _local_fallback, gap_of

    ir = FAMILIES[family](n)
    compiled = compile_model(ir, NO_DATA)
    found = refine(classify(ir, NO_DATA), compiled)
    scip = sandbox.run("app.solve.sandbox:solve_in_child",
                       {"backend": "scip", "compiled": compiled, "time_limit": time_limit, "seed": 1, "workers": 8,
                        "gap_rel": 0.0}, time_limit=time_limit, workers=8)[0]
    row = {"family": family, "n": n, "class": found.model_class, "scip": (scip.status, scip.objective, scip.best_bound),
           "after": None, "kept": False, "claim_ok": True, "note": ""}
    if scip.status not in ("unknown", "feasible"):
        row["note"] = f"scip ended {scip.status}"
        return row
    result, backend, record = _local_fallback(compiled, found, SCIP, scip, time_limit=time_limit, seed=1, workers=8,
                                              should_stop=lambda: False)
    row.update(after=(result.status, result.objective, backend.name), kept=bool(record.get("kept")), note=record.get("why", ""))
    if result.objective is not None and scip.best_bound is not None:
        row["claim_ok"] = float(result.objective) <= float(scip.best_bound) + 1e-6  # maximize: never past the bound
    return row


def report(rows) -> tuple[str, bool]:
    lines = ["| family | n | class | SCIP: status / answer / bound | after IPOPT: status / answer / by | kept | note |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        s, a = r["scip"], r["after"]
        lines.append(f"| {r['family']} | {r['n']} | {r['class']} | {s[0]} / {s[1]} / {s[2]} | "
                     f"{'-' if a is None else f'{a[0]} / {a[1]} / {a[2]}'} | {'yes' if r['kept'] else 'no'} | {r['note']} |")
    improved = sorted({r["family"] for r in rows if r["kept"]})
    bad = [f"{r['family']}-{r['n']}" for r in rows if not r["claim_ok"]]
    enable = set(improved) == set(FAMILIES) and not bad
    lines += ["", f"- families it improved: {', '.join(improved) or 'none'}",
              f"- answers past SCIP's bound: {', '.join(bad) or 'none'}", f"- verdict: {'enable' if enable else 'leave off'}"]
    return "\n".join(lines) + "\n", enable


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.ipopt", description=__doc__.split("\n\n")[0])
    parser.add_argument("--time-limit", type=float, default=20.0)
    args = parser.parse_args(argv)
    rows = []
    for family in FAMILIES:
        for n in SIZES:
            rows.append(_row(family, n, args.time_limit))
            print(report([rows[-1]])[0].splitlines()[2], flush=True)
    print(report(rows)[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
