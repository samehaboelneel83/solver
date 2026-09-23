"""Warm starts against cold: does the last answer make the next solve faster?

    python -m bench.warm --families rota,facility,knapsack --sizes M,L --instances 2

The situation a warm start is for: a problem solved once, then its data
changes a little and it is solved again. Per instance: solve it; perturb 5%
of its numeric data cells (parameter values and numeric attributes, by up
to 10%, whole numbers kept whole); solve the perturbed model cold and warm
-- hinted with the first answer's roster through `app.solve.warm.hint_from`,
exactly as a run would be -- on every backend that takes hints and the
model. Reported: status, objective, seconds, and whether both agree.
"""

from __future__ import annotations

import argparse
import copy
import math
import random
import time
from typing import Any

from bench.families import generate

HINTED = ("cp-sat", "highs", "scip")


def perturb(data: dict[str, Any], seed: str, share: float = 0.05) -> dict[str, Any]:
    data = copy.deepcopy(data)
    rnd = random.Random(seed)
    cells: list[tuple[dict, str]] = []
    for rows in data["parameters"].values():
        cells += [(row, "value") for row in rows if isinstance(row.get("value"), (int, float))]
    for rows in data["sets"].values():
        for row in rows:
            cells += [(row, k) for k, v in row.items() if k != "id" and isinstance(v, (int, float)) and not isinstance(v, bool)]
    for row, key in rnd.sample(cells, max(1, math.ceil(len(cells) * share))):
        value = row[key] * rnd.uniform(0.9, 1.1)
        row[key] = round(value) if isinstance(row[key], int) else round(value, 4)
    return data


def measure(family: str, size: str, instance: int, time_limit: float) -> list[dict[str, Any]]:
    from app.solve import compile_model
    from app.solve.backends import NoBackend, by_name, choose
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from app.solve.service import _assignments, solve_compiled
    from app.solve.warm import hint_from

    case = generate(family, size, instance)
    compiled = compile_model(case.ir, case.data)
    first_backend, _ = choose(refine(classify(case.ir, case.data), compiled))
    first, _ = solve_compiled(first_backend, compiled, time_limit=time_limit, seed=1)
    roster = _assignments(compiled, first)

    data = perturb(case.data, f"warm-{family}-{size}-{instance}")
    changed = compile_model(case.ir, data)
    found = refine(classify(case.ir, data), changed)
    hint = hint_from(changed, roster)
    rows = []
    for name in HINTED:
        try:
            choose(found, name)
        except NoBackend:
            continue
        backend = by_name(name)
        if not backend.is_available():
            continue
        row: dict[str, Any] = {"family": family, "size": size, "instance": instance, "backend": name,
                               "hinted": len(hint), "variables": len(changed.variables)}
        for label, given in (("cold", None), ("warm", hint)):
            started = time.monotonic()
            result, _ = solve_compiled(backend, changed, time_limit=time_limit, seed=1, hint=given)
            row[label] = {"status": result.status, "objective": result.objective,
                          "seconds": round(time.monotonic() - started, 3)}
        row["agree"] = row["cold"]["objective"] == row["warm"]["objective"] or (
            row["cold"]["status"] != "optimal" or row["warm"]["status"] != "optimal"
        )
        rows.append(row)
    return rows


def _sgm(values: list[float], shift: float = 1.0) -> float:
    return math.exp(sum(math.log(v + shift) for v in values) / len(values)) - shift


def report(rows: list[dict[str, Any]], time_limit: float) -> str:
    lines = [
        "| family | size | inst | backend | variables | hinted | cold: status / objective / s | warm: status / objective / s | same optimum |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        c, w = r["cold"], r["warm"]
        lines.append(
            f"| {r['family']} | {r['size']} | {r['instance']} | {r['backend']} | {r['variables']} | {r['hinted']} | "
            f"{c['status']} / {c['objective']} / {c['seconds']} | {w['status']} / {w['objective']} / {w['seconds']} | {r['agree']} |"
        )
    lines += ["", "| backend | runs | cold SGM s | warm SGM s | warm faster | warm slower | warm proved more |", "|---|---|---|---|---|---|---|"]
    for name in HINTED:
        mine = [r for r in rows if r["backend"] == name]
        if not mine:
            continue
        # An unproven answer is charged the whole limit, as bench.report does.
        charge = lambda part: part["seconds"] if part["status"] == "optimal" else time_limit  # noqa: E731
        cold = [charge(r["cold"]) for r in mine]
        warm = [charge(r["warm"]) for r in mine]
        faster = sum(w < 0.9 * c for c, w in zip(cold, warm))
        slower = sum(w > 1.1 * c for c, w in zip(cold, warm))
        proved = sum(r["warm"]["status"] == "optimal" and r["cold"]["status"] != "optimal" for r in mine) - sum(
            r["cold"]["status"] == "optimal" and r["warm"]["status"] != "optimal" for r in mine
        )
        lines.append(f"| {name} | {len(mine)} | {_sgm(cold):.3f} | {_sgm(warm):.3f} | {faster} | {slower} | {proved:+d} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.warm", description=__doc__.split("\n\n")[0])
    parser.add_argument("--families", default="rota,facility,knapsack")
    parser.add_argument("--sizes", default="M,L")
    parser.add_argument("--instances", type=int, default=2)
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--out", help="write the tables here; default stdout")
    args = parser.parse_args(argv)
    rows = []
    for family in args.families.split(","):
        for size in args.sizes.split(","):
            for instance in range(args.instances):
                new = measure(family, size, instance, args.time_limit)
                rows += new
                for row in new:
                    print(report([row], args.time_limit).splitlines()[2], flush=True)
    table = report(rows, args.time_limit)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(table)
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
