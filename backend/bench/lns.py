"""Large-neighbourhood search against the solver alone, on the bench (queue R3).

    python -m bench.lns --time-limit 30

For each instance: HiGHS (or the MILP wrapper) alone for the whole time, on
all 8 threads, against the same solver with LNS (`app.solve.lns`: alone for
the first 30%, neighbourhoods for the rest). Both in sandboxed children, as a
run does. Reported per instance: status, the answer, the gap, seconds; the
verdict is "enable" when LNS finds a better answer on at least two families,
never a worse one, and never loses a proof the solver alone made.
"""

from __future__ import annotations

import argparse
import time

CASES = [
    ("knapsack_depots", "M", 0), ("knapsack_depots", "M", 1), ("knapsack_depots", "L", 0),
    ("facility", "L", 0), ("facility", "L", 1),
    ("facility_regions", "M", 0), ("facility_regions", "M", 1),
    ("districting", "M", 0), ("districting", "M", 1),
    ("rota_rates", "L", 0),
]


def _row(family, size, instance, backend, time_limit):
    from app.solve import compile_model, sandbox
    from app.solve.service import gap_of
    from bench.families import generate

    case = generate(family, size, instance)
    compiled = compile_model(case.ir, case.data)
    common = {"backend": backend, "compiled": compiled, "time_limit": time_limit, "seed": 1, "workers": 8, "gap_rel": 0.0}
    t0 = time.monotonic()
    alone = sandbox.run("app.solve.sandbox:solve_in_child", common, time_limit=time_limit, workers=8)[0]
    alone_s = time.monotonic() - t0
    t0 = time.monotonic()
    searched, record = sandbox.run("app.solve.sandbox:lns_in_child", common, time_limit=time_limit, workers=8)
    lns_s = time.monotonic() - t0
    sense = compiled.sense

    def better(a, b):
        if a is None or b is None:
            return a is not None and b is None
        return float(a) < float(b) - 1e-9 * max(1.0, abs(float(b))) if sense == "minimize" else float(a) > float(b) + 1e-9 * max(1.0, abs(float(b)))

    return {
        "family": family, "size": size, "instance": instance, "backend": backend,
        "alone": (alone.status, alone.objective, gap_of(alone.objective, alone.best_bound), alone_s),
        "lns": (searched.status, searched.objective, gap_of(searched.objective, searched.best_bound), lns_s),
        "rounds": record.get("rounds", 0), "improvements": record.get("improvements", 0),
        "better": better(searched.objective, alone.objective), "worse": better(alone.objective, searched.objective),
        "lost_proof": alone.status == "optimal" and searched.status != "optimal",
    }


def report(rows) -> tuple[str, bool]:
    fmt = lambda g: "-" if g is None else f"{g * 100:.3g}%"  # noqa: E731
    lines = ["| family | size | inst | solver | alone: status / answer / gap / s | LNS: status / answer / gap / s | rounds (better) |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        a, b = r["alone"], r["lns"]
        lines.append(f"| {r['family']} | {r['size']} | {r['instance']} | {r['backend']} | {a[0]} / {a[1]} / {fmt(a[2])} / {a[3]:.1f} | "
                     f"{b[0]} / {b[1]} / {fmt(b[2])} / {b[3]:.1f} | {r['rounds']} ({r['improvements']}) |")
    better = sorted({r["family"] for r in rows if r["better"]})
    worse = [f"{r['family']}-{r['size']}-{r['instance']}" for r in rows if r["worse"]]
    lost = [f"{r['family']}-{r['size']}-{r['instance']}" for r in rows if r["lost_proof"]]
    enable = len(better) >= 2 and not worse and not lost
    lines += ["", f"- families with a better answer: {', '.join(better) or 'none'}",
              f"- instances with a worse answer: {', '.join(worse) or 'none'}",
              f"- proofs lost: {', '.join(lost) or 'none'}", f"- verdict: {'enable' if enable else 'leave off'}"]
    return "\n".join(lines) + "\n", enable


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.lns", description=__doc__.split("\n\n")[0])
    parser.add_argument("--time-limit", type=float, default=30.0)
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
