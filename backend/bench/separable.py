"""Separable blocks solved at once, against the whole model, on every backend that takes it.

    python -m bench.separable --families facility_regions,knapsack_depots --sizes M,L --instances 3

Each solve runs as a run's does -- in a sandboxed child, the blocks in up to
four children at once with the threads shared out
(`app.solve.blocks`) -- so the comparison includes what a run pays to start
them. Reported: status, objective and seconds each way, and whether the
optima agree; blocks must never change a proven optimum.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from bench.families import generate
from bench.symmetry import _sgm

WORKERS = 8


def _whole(backend: str, compiled, time_limit: float):
    from app.solve import sandbox

    return sandbox.run(
        "app.solve.sandbox:solve_in_child",
        {"backend": backend, "compiled": compiled, "time_limit": time_limit, "seed": 1, "workers": WORKERS, "gap_rel": 0.0},
        time_limit=time_limit,
        workers=WORKERS,
    )[0]


def _blocked(backend: str, compiled, parts, time_limit: float):
    from app.solve import sandbox
    from app.solve.blocks import solve
    from app.solve.service import OPTIMAL_GAP

    def run_one(piece, share, hint):
        return sandbox.run(
            "app.solve.sandbox:solve_in_child",
            {"backend": backend, "compiled": piece, "time_limit": time_limit, "seed": 1, "workers": share,
             "gap_rel": 0.0, "hint": hint},
            time_limit=time_limit,
            workers=share,
        )

    return solve(compiled, parts, run_one, workers=WORKERS, optimal_gap=OPTIMAL_GAP)[0]


def measure(family: str, size: str, instance: int, time_limit: float) -> list[dict[str, Any]]:
    from app.solve import compile_model, sandbox
    from app.solve.backends import REGISTRY, NoBackend, choose
    from app.solve.blocks import blocks, refusal
    from app.solve.classify import classify
    from app.solve.convexity import refine

    case = generate(family, size, instance)
    compiled = compile_model(case.ir, case.data)
    found = refine(classify(case.ir, case.data), compiled)
    parts = blocks(compiled)
    if refusal(compiled) is not None or len(parts) < 2:
        return []
    rows = []
    for backend in REGISTRY:
        if not backend.automatic:
            continue
        try:
            choose(found, backend.name)
        except NoBackend:
            continue
        row: dict[str, Any] = {"family": family, "size": size, "instance": instance, "backend": backend.name,
                               "count": len(parts)}
        for label, how in (("whole", lambda: _whole(backend.name, compiled, time_limit)),
                           ("blocks", lambda: _blocked(backend.name, compiled, parts, time_limit))):
            started = time.monotonic()
            try:
                result = how()
                row[label] = {"status": result.status, "objective": result.objective}
            except sandbox.SandboxFailed as exc:
                # What a run would record: an error, with why.
                row[label] = {"status": "error", "objective": None, "why": str(exc)[:80]}
            row[label]["seconds"] = round(time.monotonic() - started, 3)
        both = row["whole"]["status"] == row["blocks"]["status"] == "optimal"
        row["agree"] = (not both) or abs(float(row["whole"]["objective"]) - float(row["blocks"]["objective"])) <= 1e-6 * max(
            1.0, abs(float(row["whole"]["objective"]))
        )
        rows.append(row)
    return rows


def report(rows: list[dict[str, Any]], time_limit: float) -> str:
    lines = [
        "| family | size | inst | backend | blocks | whole: status / objective / s | blocks: status / objective / s | same optimum |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        w, b = r["whole"], r["blocks"]
        lines.append(
            f"| {r['family']} | {r['size']} | {r['instance']} | {r['backend']} | {r['count']} | "
            f"{w['status']} / {w['objective']} / {w['seconds']} | {b['status']} / {b['objective']} / {b['seconds']} | {r['agree']} |"
        )
    lines += ["", "| family | backend | runs | whole SGM s | blocks SGM s | blocks faster | blocks slower | proofs gained | wrong |",
              "|---|---|---|---|---|---|---|---|---|"]
    charge = lambda part: part["seconds"] if part["status"] == "optimal" else time_limit  # noqa: E731
    for family in dict.fromkeys(r["family"] for r in rows):
        for backend in dict.fromkeys(r["backend"] for r in rows):
            mine = [r for r in rows if r["family"] == family and r["backend"] == backend]
            if not mine:
                continue
            whole = [charge(r["whole"]) for r in mine]
            split = [charge(r["blocks"]) for r in mine]
            gained = sum(r["blocks"]["status"] == "optimal" and r["whole"]["status"] != "optimal" for r in mine) - sum(
                r["whole"]["status"] == "optimal" and r["blocks"]["status"] != "optimal" for r in mine
            )
            lines.append(
                f"| {family} | {backend} | {len(mine)} | {_sgm(whole):.3f} | {_sgm(split):.3f} | "
                f"{sum(s < 0.9 * w for w, s in zip(whole, split))} | {sum(s > 1.1 * w for w, s in zip(whole, split))} | "
                f"{gained:+d} | {sum(not r['agree'] for r in mine)} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.separable", description=__doc__.split("\n\n")[0])
    parser.add_argument("--families", default="facility_regions,knapsack_depots")
    parser.add_argument("--sizes", default="M,L")
    parser.add_argument("--instances", type=int, default=3)
    parser.add_argument("--time-limit", type=float, default=30.0)
    args = parser.parse_args(argv)
    rows = []
    for family in args.families.split(","):
        for size in args.sizes.split(","):
            for instance in range(args.instances):
                new = measure(family, size, instance, args.time_limit)
                rows += new
                for row in new:
                    print(report([row], args.time_limit).splitlines()[2], flush=True)
    print(report(rows, args.time_limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
