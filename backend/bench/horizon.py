"""Relax-and-fix over the days against the solver on the whole model, on the bench (queue R9).

    python -m bench.horizon --time-limit 30

The families laid out over a `day` set at their largest sizes: HiGHS on the
whole model for the time allowed, 8 threads, against relax-and-fix
(`app.solve.horizon`, four windows) with the same time. Both in sandboxed
children, as a run does. The verdict is "enable" when relax-and-fix finds a
better answer (or one where the whole solve finds none) on at least two
families and is never more than 1% worse where the whole solve proves the
optimum.
"""

from __future__ import annotations

import argparse
import time

CASES = [("rota", "L"), ("rota", "XL"), ("rota_rates", "L"), ("rota_rates", "XL"), ("rota_teams", "L"), ("rota_teams", "XL")]


def _row(family, size, time_limit, backend):
    from app.solve import compile_model, sandbox
    from bench.families import generate

    case = generate(family, size, 0)
    compiled = compile_model(case.ir, case.data)
    periods = [str(r["id"]) for r in case.data["sets"]["day"]]
    common = {"backend": backend, "compiled": compiled, "time_limit": time_limit, "seed": 1, "workers": 8, "gap_rel": 0.0}
    t0 = time.monotonic()
    whole = sandbox.run("app.solve.sandbox:solve_in_child", common, time_limit=time_limit, workers=8)[0]
    whole_s = time.monotonic() - t0
    t0 = time.monotonic()
    rolled, record = sandbox.run("app.solve.sandbox:horizon_in_child", {**common, "time_set": "day", "periods": periods},
                                 time_limit=time_limit, workers=8)
    rolled_s = time.monotonic() - t0
    sense = compiled.sense
    worse = better = False
    if rolled.objective is not None and whole.objective is not None:
        a, b = float(rolled.objective), float(whole.objective)
        slack = 1e-9 * max(1.0, abs(b))
        better = a < b - slack if sense == "minimize" else a > b + slack
        worse = (a > b * 1.01 + slack) if sense == "minimize" else (a < b * 0.99 - slack)
    elif rolled.objective is not None:
        better = True
    return {"family": family, "size": size, "whole": (whole.status, whole.objective, round(whole_s, 1)),
            "rolled": (rolled.status, rolled.objective, round(rolled_s, 1)), "windows": record.get("windows"),
            "better": better, "worse_than_proof": worse and whole.status == "optimal"}


def report(rows) -> tuple[str, bool]:
    lines = ["| family | size | whole: status / answer / s | relax-and-fix: status / answer / s | windows |",
             "|---|---|---|---|---|"]
    for r in rows:
        w, h = r["whole"], r["rolled"]
        lines.append(f"| {r['family']} | {r['size']} | {w[0]} / {w[1]} / {w[2]} | {h[0]} / {h[1]} / {h[2]} | {r['windows']} |")
    better = sorted({r["family"] for r in rows if r["better"]})
    worse = [f"{r['family']}-{r['size']}" for r in rows if r["worse_than_proof"]]
    enable = len(better) >= 2 and not worse
    lines += ["", f"- families where it found better: {', '.join(better) or 'none'}",
              f"- more than 1% worse than a proven optimum: {', '.join(worse) or 'none'}",
              f"- verdict: {'enable' if enable else 'leave off'}"]
    return "\n".join(lines) + "\n", enable


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.horizon", description=__doc__.split("\n\n")[0])
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--backend", default="highs")
    args = parser.parse_args(argv)
    rows = []
    for family, size in CASES:
        rows.append(_row(family, size, args.time_limit, args.backend))
        print(report([rows[-1]])[0].splitlines()[2], flush=True)
    print(report(rows)[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
