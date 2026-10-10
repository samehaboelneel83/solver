"""Hidden problem 14: monthly inspection plan (multiple-choice knapsack with district groups).

    python -m bench.hidden.h14_inspections gen [S M]
    python -m bench.hidden.h14_inspections check <case> <export.csv>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (12, 3), "M": (400, 8)}  # establishments, districts
OUT = Path(__file__).parent / "cases" / "h14"


def make(size: str, seed: int = 14) -> dict:
    ne, nd = SIZES[size]
    rng = np.random.default_rng(seed * 19 + ne)
    D = [f"D{i + 1}" for i in range(nd)]
    E = []
    opts = []
    for i in range(ne):
        e = f"E{i + 1:03d}"
        dist = D[int(rng.integers(nd))]
        risk = int(rng.integers(5, 60))
        E.append(dict(id=e, district=dist, mandatory=bool(rng.random() < 0.12), travel=int(rng.integers(2, 12)) * 50))
        hb = int(rng.integers(2, 6))
        opts.append((e, "BASIC", hb, int(risk * rng.uniform(0.35, 0.6))))
        if rng.random() < 0.7:
            opts.append((e, "FULL", hb + int(rng.integers(3, 9)), int(risk * rng.uniform(0.8, 1.0))))
    hours = {}
    mins = {}
    for dd in D:
        mine = [o for o in opts if E[int(o[0][1:]) - 1]["district"] == dd and o[1] == "BASIC"]
        need = sum(o[2] for o in mine)
        hours[dd] = int(need * rng.uniform(0.45, 0.7)) + 4
        mins[dd] = max(1, int(len(mine) * 0.25))
    budget = int(sum(e["travel"] for e in E) * 0.45 / 100) * 100
    full_max = max(2, int(sum(1 for o in opts if o[1] == "FULL") * 0.2))
    return dict(E=E, D=D, opts=opts, hours=hours, mins=mins, budget=budget, full_max=full_max)


def solve(d: dict, seconds: float) -> dict:
    from scipy.optimize import Bounds, LinearConstraint, milp

    E, D, opts = d["E"], d["D"], d["opts"]
    dist = {e["id"]: e["district"] for e in E}
    travel = {e["id"]: e["travel"] for e in E}
    n = len(opts)
    c = -np.array([o[3] for o in opts], dtype=float)
    rows, rl, rh = [], [], []

    def row(coefs, a, b):
        rows.append(np.array(coefs, dtype=float)); rl.append(a); rh.append(b)

    for e in E:
        row([1 if o[0] == e["id"] else 0 for o in opts], 1 if e["mandatory"] else 0, 1)
    for dd in D:
        row([o[2] if dist[o[0]] == dd else 0 for o in opts], -np.inf, d["hours"][dd])
        row([1 if dist[o[0]] == dd else 0 for o in opts], d["mins"][dd], np.inf)
    row([travel[o[0]] for o in opts], -np.inf, d["budget"])
    row([1 if o[1] == "FULL" else 0 for o in opts], -np.inf, d["full_max"])
    res = milp(c, constraints=LinearConstraint(np.array(rows), rl, rh), integrality=np.ones(n),
               bounds=Bounds(np.zeros(n), np.ones(n)), options={"time_limit": seconds, "disp": False, "mip_rel_gap": 0})
    if res.x is None:
        return {"feasible": False}
    exp = ["decision,key1,key2,value"]
    for o, x in zip(opts, res.x):
        if x > 0.5:
            exp.append(f"inspect,{o[0]},{o[1]},1")
    return {"feasible": True, "goal": -float(res.fun), "bound": -float(getattr(res, "mip_dual_bound", None) or res.fun),
            "optimal": res.status == 0, "export": "\n".join(exp) + "\n"}


def instance(size: str) -> tuple[dict, dict]:
    for seed in range(14, 80):
        d = make(size, seed)
        ref = solve(d, 200)
        if ref["feasible"]:
            return d, ref
    raise RuntimeError("no feasible instance")


def write(size: str) -> Path:
    d, ref = instance(size)
    folder = OUT / size
    write_csv(folder / "districts.csv", ["district", "inspector_hours", "min_inspections"],
              [(x, d["hours"][x], d["mins"][x]) for x in d["D"]])
    write_csv(folder / "establishments.csv", ["establishment", "district", "mandatory", "travel_cost"],
              [(e["id"], e["district"], "yes" if e["mandatory"] else "no", e["travel"]) for e in d["E"]])
    write_csv(folder / "inspection_options.csv", ["establishment", "level", "hours", "risk_reduction"], d["opts"])
    names = ["districts.csv", "establishments.csv", "inspection_options.csv"]
    rules = ("Rules (all hard): each establishment gets at most one inspection this month, at one of the levels "
             "listed for it in the options (an establishment without a FULL option cannot get a FULL inspection). "
             "An establishment marked mandatory = yes must be inspected (either level). The hours of the inspections "
             "in a district are at most the district's inspector hours, and each district must have at least its "
             "min_inspections inspections. Every inspection costs the establishment's travel cost, and all travel "
             f"together is at most {d['budget']:,} EGP. FULL inspections need the specialist team, which can do at "
             f"most {d['full_max']} FULL inspections in total this month. Goal, as large as possible: the total risk "
             "reduction of the inspections chosen. Report the establishments inspected with their level, the "
             "inspections and hours per district against the hours available, the total risk reduction, the travel "
             "spent, and the highest-risk establishments left uninspected.")
    head = ('Please build this in a new workspace called "{workspace}". Call the problem "Inspection plan". '
            f"Our regulatory authority must choose which of {len(d['E'])} establishments in {len(d['D'])} districts "
            "to inspect this month, and how thoroughly.\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in zip(
            ["Districts", "Establishments (travel cost in EGP)", "Inspection options"], names))
        files = []
    else:
        body = ("The data are in the attached files: districts.csv (inspector hours and minimum inspections per "
                "district), establishments.csv (district, whether the inspection is mandatory, travel cost), "
                "inspection_options.csv (hours and risk reduction of each possible inspection level per "
                "establishment).")
        files = names
    message = (head + body + "\n\n" + rules +
               "\n\nEverything you need is here: please propose the model without further questions, then solve it.")
    write_case(folder, message, {})
    cost = float(check(folder, ref["export"])[-1].split()[1])
    report = [["establishments and level", r"E\d{3}\W+.{0,40}(BASIC|FULL)"],
              ["hours per district", r"D\d\b[^\n]{0,80}\d"],
              ["total risk reduction", rf"{cost:,.0f}".replace(",", ",?")],
              ["travel spent", r"travel"],
              ["uninspected high-risk", r"uninspected|not inspected|left out"]]
    write_case(folder, message, {"problem": "h14", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": cost if ref["optimal"] else None, "known_feasible": cost,
                                 "bound": cost if ref["optimal"] else ref["bound"], "sense": "maximize", "report": report, "files": files})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    dists = {r["district"]: r for r in read_csv(folder / "districts.csv")}
    ests = {r["establishment"]: r for r in read_csv(folder / "establishments.csv")}
    opts = {(r["establishment"], r["level"]): r for r in read_csv(folder / "inspection_options.csv")}
    levels = {lv for _, lv in opts}
    msg = (folder / "message.txt").read_text(encoding="utf-8")
    budget = float(re.search(r"all travel together is at most ([\d,]+) EGP", msg).group(1).replace(",", ""))
    full_max = float(re.search(r"at most (\d+) FULL inspections", msg).group(1))
    by: dict[str, dict[tuple, float]] = {}
    for r in export_rows(export_csv):
        a, b = r.get("key1") or "", (r.get("key2") or "").upper()
        if r.get("key3"):
            continue
        if not r.get("key2"):  # one key naming the option by both parts ("E1_FULL", "E1 FULL", "E1-FULL", "E1|FULL")
            parts = [p for p in re.split(r"\s*(?:_|-|\||\s)\s*", a.strip()) if p]
            if len(parts) != 2:
                continue
            a, b = parts[0], parts[1].upper()
            if a.upper() in levels and parts[1] in ests:
                a, b = parts[1], parts[0].upper()
            r = {**r, "key2": b}
        if a.upper() in levels and (r.get("key2") or "") in ests:
            a, b = r["key2"], a.upper()
        if a in ests and b in levels:
            by.setdefault(r["decision"], {})[(a, b)] = float(r["value"])
    if not by:
        return ["no decision over (establishment, level) in the export"]
    name = max(by, key=lambda n: (all(v in (0.0, 1.0) for v in by[n].values()), len([v for v in by[n].values() if v > 1e-6])))
    x = {k: v for k, v in by[name].items() if abs(v) > 1e-6}
    bad: list[str] = []
    gain = 0.0
    travel = 0.0
    full = 0
    hours = {k: 0.0 for k in dists}
    count = {k: 0 for k in dists}
    per_e: dict[str, int] = {}
    for (e, lv), v in x.items():
        if abs(v - 1) > 1e-6:
            bad.append(f"{e} {lv}: value {v:g}, expected yes/no")
        if (e, lv) not in opts:
            bad.append(f"{e} has no {lv} option")
            continue
        dd = ests[e]["district"]
        per_e[e] = per_e.get(e, 0) + 1
        hours[dd] += float(opts[(e, lv)]["hours"])
        count[dd] += 1
        travel += float(ests[e]["travel_cost"])
        full += lv == "FULL"
        gain += float(opts[(e, lv)]["risk_reduction"])
    for e, r in ests.items():
        if per_e.get(e, 0) > 1:
            bad.append(f"{e} inspected {per_e[e]} times")
        if r["mandatory"] == "yes" and per_e.get(e, 0) == 0:
            bad.append(f"{e} is mandatory and not inspected")
    for dd, r in dists.items():
        if hours[dd] > float(r["inspector_hours"]) + 1e-6:
            bad.append(f"{dd}: {hours[dd]:g} hours, above {r['inspector_hours']}")
        if count[dd] < int(r["min_inspections"]):
            bad.append(f"{dd}: {count[dd]} inspections, below {r['min_inspections']}")
    if travel > budget + 1e-6:
        bad.append(f"travel {travel:g} above {budget:g}")
    if full > full_max:
        bad.append(f"{full} FULL inspections, above {full_max:g}")
    return bad + [f"COST {gain:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
