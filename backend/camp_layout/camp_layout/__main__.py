"""Command line.

  python -m camp_layout run complex|small|camp.xlsx [--solver cpsat|scip|cbc|highs|heuristic] [--out DIR]
                         [--beds-seconds N] [--seconds N] [--validate layout.json]
  python -m camp_layout dxf2xlsx plan.dxf camp.xlsx [--units mm|cm|m|in|ft] [--crs EPSG:32636] [--door-capacity N]
  python -m camp_layout template DIR      a sample drawing (.dxf) and workbook (.xlsx) to start from

The old form `python -m camp_layout complex ...` still works: it means `run complex ...`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import examples, export
from .pipeline import solve


def _problem(source: str):
    if source == "complex":
        return examples.complex_camp()
    if source == "small":
        return examples.small_camp()
    if source.endswith(".xlsx"):
        from .workbook import read_workbook
        return read_workbook(source)
    raise SystemExit(f"{source}: give complex, small or a camp workbook (.xlsx)")


def run(a) -> None:
    problem = _problem(a.source)
    if a.validate:
        from .result import from_json
        from .validate import validate
        v = validate(problem, from_json(json.loads(Path(a.validate).read_text())))
        for c in v.checks:
            print("ok " if c.ok else "BAD", c.name, "-", c.detail)
        print(json.dumps({k: x for k, x in v.summary().items() if k != "checks"}))
        raise SystemExit(0 if v.ok else 1)
    result = solve(problem, a.solver, time_limit=a.seconds, threads=a.threads, stage_limits={"beds": a.beds_seconds})
    folder = a.out or (f"examples/{a.source}" if a.source in ("complex", "small") else str(Path(a.source).with_suffix("")) + "_layout")
    files = export.write(result, folder)
    rep = json.loads(files["report"].read_text())
    print(json.dumps({k: rep[k] for k in ("beds", "beds_by_type", "objectives", "zone_depth_m")}, indent=2))
    print("valid" if result.validation.ok else "INVALID", "->", ", ".join(str(p) for p in files.values()))


def dxf2xlsx(a) -> None:
    from .dxf import DrawingError
    from .workbook import dxf_to_workbook
    try:
        path, notes = dxf_to_workbook(a.dxf, a.xlsx, units=a.units, crs=a.crs, door_capacity=a.door_capacity)
    except DrawingError as exc:
        raise SystemExit(f"cannot read the drawing: {exc}")
    for n in notes:
        print("-", n)
    print("wrote", path, "-- review the shaded cells, then: python -m camp_layout run", path)


def template(a) -> None:
    from .dxf import write_dxf
    from .workbook import write_workbook
    folder = Path(a.dir)
    folder.mkdir(parents=True, exist_ok=True)
    p = examples.complex_camp()
    write_dxf(p, str(folder / "camp_template.dxf"))
    write_workbook(p, folder / "camp_template.xlsx")
    print("wrote", folder / "camp_template.dxf", "and", folder / "camp_template.xlsx")


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and (argv[0] in ("complex", "small") or argv[0].endswith(".xlsx")):
        argv = ["run", *argv]
    ap = argparse.ArgumentParser(prog="camp_layout", description="Lay out a camp, from a drawing to a validated plan.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="solve a camp and write GeoJSON, report and map")
    r.add_argument("source", help="complex, small, or a camp workbook (.xlsx)")
    r.add_argument("--solver", default="cpsat")
    r.add_argument("--out", default=None)
    r.add_argument("--seconds", type=float, default=60.0, help="time limit per later stage")
    r.add_argument("--beds-seconds", type=float, default=180.0, help="time limit for the bed-count stage")
    r.add_argument("--threads", type=int, default=4)
    r.add_argument("--validate", default=None, metavar="LAYOUT_JSON", help="only re-validate a saved layout")
    r.set_defaults(fn=run)
    d = sub.add_parser("dxf2xlsx", help="read a CAD drawing into a camp workbook")
    d.add_argument("dxf")
    d.add_argument("xlsx")
    d.add_argument("--units", default=None, help="mm, cm, m, in or ft, if the drawing does not say")
    d.add_argument("--crs", default=None, help="the drawing's coordinate system, e.g. EPSG:32636, for GIS output")
    d.add_argument("--door-capacity", type=int, default=None)
    d.set_defaults(fn=dxf2xlsx)
    t = sub.add_parser("template", help="write a sample drawing and workbook")
    t.add_argument("dir")
    t.set_defaults(fn=template)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
