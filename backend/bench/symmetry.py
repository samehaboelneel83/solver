"""Symmetry breaking on and off, for the backends it is for.

    python -m bench.symmetry --families rota,facility --sizes M,L --instances 3

For each instance, the classes of interchangeable entities
(`app.solve.symmetry.classes`) and, on HiGHS and the MILP wrapper, the
solve with and without the ordering rows. Reported: status, objective and
seconds each way, and whether the optima agree -- the rows must never
change a proven optimum.
"""

from __future__ import annotations

import argparse
import math
import time
from typing import Any

from bench.families import generate


def measure(family: str, size: str, instance: int, time_limit: float) -> list[dict[str, Any]]:
    from app.solve import compile_model
    from app.solve.backends import NoBackend, by_name, choose
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from app.solve.service import solve_compiled
    from app.solve.symmetry import FOR

    case = generate(family, size, instance)
    compiled = compile_model(case.ir, case.data)
    found = refine(classify(case.ir, case.data), compiled)
    rows = []
    for name in sorted(FOR):
        try:
            choose(found, name)
        except NoBackend:
            continue
        backend = by_name(name)
        if not backend.is_available():
            continue
        row: dict[str, Any] = {
            "family": family, "size": size, "instance": instance, "backend": name,
            "classes": [(s, len(m)) for s, m in compiled.symmetry],
        }
        for label, on in (("off", False), ("on", True)):
            started = time.monotonic()
            result, _ = solve_compiled(backend, compiled, time_limit=time_limit, seed=1, symmetry=on)
            row[label] = {"status": result.status, "objective": result.objective,
                          "seconds": round(time.monotonic() - started, 3)}
        both = row["off"]["status"] == row["on"]["status"] == "optimal"
        row["agree"] = (not both) or abs(float(row["off"]["objective"]) - float(row["on"]["objective"])) <= 1e-6 * max(
            1.0, abs(float(row["off"]["objective"]))
        )
        rows.append(row)
    return rows


def _sgm(values: list[float], shift: float = 1.0) -> float:
    return math.exp(sum(math.log(v + shift) for v in values) / len(values)) - shift


def report(rows: list[dict[str, Any]], time_limit: float) -> str:
    lines = [
        "| family | size | inst | backend | classes | off: status / objective / s | on: status / objective / s | same optimum |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        f, n = r["off"], r["on"]
        classes = ", ".join(f"{s} x{k}" for s, k in r["classes"]) or "none"
        lines.append(
            f"| {r['family']} | {r['size']} | {r['instance']} | {r['backend']} | {classes} | "
            f"{f['status']} / {f['objective']} / {f['seconds']} | {n['status']} / {n['objective']} / {n['seconds']} | {r['agree']} |"
        )
    lines += ["", "| family | backend | runs | off SGM s | on SGM s | on faster | on slower | proofs gained |",
              "|---|---|---|---|---|---|---|---|"]
    charge = lambda part: part["seconds"] if part["status"] == "optimal" else time_limit  # noqa: E731
    for family in dict.fromkeys(r["family"] for r in rows):
        for backend in dict.fromkeys(r["backend"] for r in rows):
            mine = [r for r in rows if r["family"] == family and r["backend"] == backend]
            if not mine:
                continue
            off = [charge(r["off"]) for r in mine]
            on = [charge(r["on"]) for r in mine]
            gained = sum(r["on"]["status"] == "optimal" and r["off"]["status"] != "optimal" for r in mine) - sum(
                r["off"]["status"] == "optimal" and r["on"]["status"] != "optimal" for r in mine
            )
            lines.append(
                f"| {family} | {backend} | {len(mine)} | {_sgm(off):.3f} | {_sgm(on):.3f} | "
                f"{sum(n < 0.9 * f for f, n in zip(off, on))} | {sum(n > 1.1 * f for f, n in zip(off, on))} | {gained:+d} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.symmetry", description=__doc__.split("\n\n")[0])
    parser.add_argument("--families", default="rota,facility")
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
