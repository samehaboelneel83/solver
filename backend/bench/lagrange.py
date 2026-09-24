"""The Lagrangian bound against the solver's own, on the bench (queue R5).

    python -m bench.lagrange --time-limit 20

Near-separable instances large enough that the solver ends without a proof:
the solver alone for the time allowed on 8 threads, then -- as a run with
`solve.lagrangian` does -- a quarter more for the Lagrangian bound, kept when
tighter. Reported per instance: the answer, the solver's gap, the gap with
the Lagrangian bound, the rounds. The verdict is "enable" when the bound
narrows the reported gap on at least two families and is never invalid
(past the answer).
"""

from __future__ import annotations

import argparse

CASES = [
    ("rota", "XL", 0), ("rota_rates", "XL", 0), ("rota_teams", "XL", 0),
    ("facility", "XL", 0), ("facility", "L", 0),
    ("districting", "M", 0),
]


def _row(family, size, instance, backend, time_limit):
    from app.solve import compile_model, sandbox
    from app.solve.backends import by_name
    from app.solve.blocks import structure
    from app.solve.service import _lagrangian_bound, gap_of
    from bench.families import generate

    case = generate(family, size, instance)
    compiled = compile_model(case.ir, case.data)
    row = {"family": family, "size": size, "instance": instance, "backend": backend, "status": "-", "answer": None,
           "solver_gap": None, "lagr_gap": None, "rounds": 0, "kept": False, "invalid": False, "why": ""}
    try:
        alone = sandbox.run("app.solve.sandbox:solve_in_child",
                            {"backend": backend, "compiled": compiled, "time_limit": time_limit, "seed": 1, "workers": 8,
                             "gap_rel": 0.0}, time_limit=time_limit, workers=8)[0]
    except Exception as exc:  # noqa: BLE001 -- a model this solver cannot take is a row, not a crash
        row["why"] = f"{backend} cannot take it: {str(exc)[:80]}"
        return row
    row = {"family": family, "size": size, "instance": instance, "backend": backend, "status": alone.status,
           "answer": alone.objective, "solver_gap": gap_of(alone.objective, alone.best_bound), "lagr_gap": None,
           "rounds": 0, "kept": False, "invalid": False, "why": ""}
    if alone.status != "feasible":
        row["why"] = f"solver ended {alone.status}"
        return row
    found = structure(compiled)
    result, record = _lagrangian_bound(compiled, found, by_name(backend), alone, time_limit=time_limit, seed=1,
                                       workers=8, should_stop=lambda: False)
    row.update(lagr_gap=gap_of(result.objective, result.best_bound), rounds=record.get("rounds", 0),
               kept=bool(record.get("kept")), why=record.get("why", ""))
    bound = record.get("bound")
    if bound is not None and alone.objective is not None:
        row["invalid"] = bound > float(alone.objective) + 1e-6 if compiled.sense == "minimize" else bound < float(alone.objective) - 1e-6
    return row


def report(rows) -> tuple[str, bool]:
    fmt = lambda g: "-" if g is None else f"{g * 100:.3g}%"  # noqa: E731
    lines = ["| family | size | solver | status | answer | solver gap | with Lagrangian | rounds | kept | note |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['family']} | {r['size']} | {r['backend']} | {r['status']} | {r['answer']} | {fmt(r['solver_gap'])} | "
                     f"{fmt(r['lagr_gap'])} | {r['rounds']} | {'yes' if r['kept'] else 'no'} | {r['why']} |")
    narrowed = sorted({r["family"] for r in rows if r["kept"]})
    invalid = [f"{r['family']}-{r['size']}" for r in rows if r["invalid"]]
    enable = len(narrowed) >= 2 and not invalid
    lines += ["", f"- families whose gap it narrowed: {', '.join(narrowed) or 'none'}",
              f"- invalid bounds: {', '.join(invalid) or 'none'}", f"- verdict: {'enable' if enable else 'leave off'}"]
    return "\n".join(lines) + "\n", enable


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.lagrange", description=__doc__.split("\n\n")[0])
    parser.add_argument("--time-limit", type=float, default=20.0)
    parser.add_argument("--backend", default="highs")
    args = parser.parse_args(argv)
    rows = []
    for family, size, instance in CASES:
        rows.append(_row(family, size, instance, args.backend, args.time_limit))
        print(report([rows[-1]])[0].splitlines()[2], flush=True)
    print(report(rows)[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
