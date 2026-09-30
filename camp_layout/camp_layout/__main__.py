"""python -m camp_layout [complex|small] [--solver cpsat|scip|cbc|highs|heuristic] [--out DIR] [--beds-seconds N] [--seconds N]"""
from __future__ import annotations

import argparse
import json

from . import examples, export
from .pipeline import solve


def main() -> None:
    ap = argparse.ArgumentParser(prog="camp_layout", description="Lay out a camp and validate it.")
    ap.add_argument("example", nargs="?", default="complex", choices=["complex", "small"])
    ap.add_argument("--solver", default="cpsat")
    ap.add_argument("--out", default=None, help="folder for GeoJSON, report and viewer")
    ap.add_argument("--seconds", type=float, default=60.0, help="time limit per later stage")
    ap.add_argument("--beds-seconds", type=float, default=180.0, help="time limit for the bed-count stage")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--validate", default=None, metavar="LAYOUT_JSON",
                    help="only re-validate a saved layout.json against the example, and print the checks")
    a = ap.parse_args()
    if a.validate:
        from .result import from_json
        from .validate import validate
        problem = examples.complex_camp() if a.example == "complex" else examples.small_camp()
        v = validate(problem, from_json(json.loads(open(a.validate).read())))
        for c in v.checks:
            print("ok " if c.ok else "BAD", c.name, "-", c.detail)
        print(json.dumps({k: x for k, x in v.summary().items() if k != "checks"}))
        return
    problem = examples.complex_camp() if a.example == "complex" else examples.small_camp()
    run = solve(problem, a.solver, time_limit=a.seconds, threads=a.threads, stage_limits={"beds": a.beds_seconds})
    folder = a.out or f"examples/{a.example}"
    files = export.write(run, folder)
    rep = json.loads(files["report"].read_text())
    print(json.dumps({k: rep[k] for k in ("beds", "beds_by_type", "objectives", "zone_depth_m")}, indent=2))
    print("valid" if run.validation.ok else "INVALID", "->", ", ".join(str(p) for p in files.values()))


if __name__ == "__main__":
    main()
