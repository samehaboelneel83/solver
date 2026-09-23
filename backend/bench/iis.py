"""Native IIS against deletion filtering: what an explanation costs.

    python -m bench.iis --sizes S,M,L --out bench/results/<date>-native-iis.md

Each family is made infeasible in a way a planner would recognise, then
diagnosed twice with the backend a run would choose: by deletion filtering
over the whole model (`diagnose.explain`), and with HiGHS's IIS of the
linear relaxation as a core that the same backend confirms and shrinks
(`core=highs.iis`). Reported per instance: probes (solves), seconds, the
size of the conflict, whether it is proven minimal, and whether both name
the same rules.

- `feed_blend` (LP): the first nutrient's floor is 60 kg in a 100 kg batch
  whose feeds hold at most 0.5 kg/kg of it -- the batch and that floor.
- `rota` (IP): the first day's first shift needs one more person than
  there are -- one cover instance, against the variables' own bounds.
- `facility` (MILP): every site's capacity cut to 30% -- together they no
  longer hold the demand; every site's capacity and every customer's
  service are in it.
"""

from __future__ import annotations

import argparse
import copy
import time
from typing import Any

from bench.families import generate


def _plant(family: str, data: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(data)
    if family == "feed_blend":
        data["parameters"]["need"][0]["value"] = 60
    elif family == "rota":
        data["parameters"]["demand"][0]["value"] = len(data["sets"]["person"]) + 1
    elif family == "facility":
        for site in data["sets"]["site"]:
            site["capacity"] = int(site["capacity"] * 0.3)
    else:  # pragma: no cover
        raise KeyError(family)
    return data


def measure(family: str, size: str, probe_seconds: float) -> dict[str, Any]:
    from app.solve import compile_model, highs
    from app.solve.backends import choose
    from app.solve.classify import classify
    from app.solve.convexity import refine
    from app.solve.diagnose import explain
    from app.solve.service import solve_compiled

    case = generate(family, size, 0)
    data = _plant(family, case.data)
    compiled = compile_model(case.ir, data)
    backend, _ = choose(refine(classify(case.ir, data), compiled))
    verdict, _ = solve_compiled(backend, compiled, time_limit=60)
    row: dict[str, Any] = {
        "family": family, "size": size, "backend": backend.name, "status": verdict.status,
        "instances": len(compiled.constraints),
    }
    if verdict.status != "infeasible":
        return row

    def solve(model, **kwargs):
        return backend.solve(model, **kwargs)

    for label, core in (("deletion", None), ("iis", lambda model: highs.iis(model, time_limit=probe_seconds * 4))):
        started = time.monotonic()
        conflict = explain(compiled, solve, probe_seconds=probe_seconds, core=core)
        row[label] = {
            "method": conflict.method,
            "probes": conflict.probes,
            "seconds": round(time.monotonic() - started, 3),
            "size": len(conflict.items),
            "minimal": conflict.minimal,
            "rules": sorted(conflict.rules),
        }
    row["same_rules"] = row["deletion"]["rules"] == row["iis"]["rules"]
    return row


def report(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| family | size | backend | instances | deletion: probes / s / size / minimal | IIS core: probes / s / size / minimal | same rules |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "iis" not in r:
            lines.append(f"| {r['family']} | {r['size']} | {r['backend']} | {r['instances']} | not infeasible ({r['status']}) | | |")
            continue
        d, i = r["deletion"], r["iis"]
        lines.append(
            f"| {r['family']} | {r['size']} | {r['backend']} | {r['instances']} | "
            f"{d['probes']} / {d['seconds']} / {d['size']} / {d['minimal']} | "
            f"{i['probes']} / {i['seconds']} / {i['size']} / {i['minimal']} ({i['method']}) | {r['same_rules']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.iis", description=__doc__.split("\n\n")[0])
    parser.add_argument("--families", default="feed_blend,rota,facility")
    parser.add_argument("--sizes", default="S,M")
    parser.add_argument("--probe-seconds", type=float, default=5.0)
    parser.add_argument("--out", help="write the table here; default stdout")
    args = parser.parse_args(argv)
    rows = []
    for family in args.families.split(","):
        for size in args.sizes.split(","):
            rows.append(measure(family, size, args.probe_seconds))
            print(report(rows[-1:]).splitlines()[-1], flush=True)
    table = report(rows)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(table)
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
