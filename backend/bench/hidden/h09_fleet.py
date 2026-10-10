"""Hidden problem 9: airline fleet assignment (generalised assignment, yes/no).

    python -m bench.hidden.h09_fleet gen [S M]
    python -m bench.hidden.h09_fleet check <case> <export.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (10, 3), "M": (120, 6)}  # flights, aircraft types
OUT = Path(__file__).parent / "cases" / "h09"
TYPES = [("ATR72", 70, 2200, 1500, 11), ("A220", 120, 3600, 5000, 12), ("A320", 174, 4300, 6100, 13),
         ("B737M", 186, 4500, 6500, 13), ("A321", 210, 5200, 5900, 13), ("B787", 290, 9800, 13000, 15)]


def make(size: str, seed: int = 9) -> dict:
    nf, nk = SIZES[size]
    rng = np.random.default_rng(seed * 101 + nf)
    pick = [0, 2, 5] if nk == 3 else list(range(nk))
    types = []
    for i in pick:
        name, seats, cph, rng_km, hrs = TYPES[i]
        types.append(dict(id=name, seats=seats, cost=cph, range_km=rng_km, max_hours=hrs, count=0))
    F = [f"FL{100 + i}" for i in range(nf)]
    dist = rng.integers(300, 6000, nf)
    if nf <= 10:
        dist = rng.integers(300, 2800, nf)
    hours = np.round((dist / 750 + 0.5) * 2) / 2  # half hours
    pax = rng.integers(50, 300, nf)
    fare = rng.integers(60, 260, nf) * 10
    flights = [dict(id=F[i], distance_km=int(dist[i]), block_hours=float(hours[i]), passengers=int(pax[i]),
                    fare=int(fare[i])) for i in range(nf)]
    total_hours = float(hours.sum())
    for t in types:
        share = total_hours / len(types) * rng.uniform(1.05, 1.45)
        t["count"] = max(1, int(round(share / t["max_hours"])))
    return dict(F=flights, K=types)


def pair_cost(f: dict, t: dict) -> float:
    spill = max(0, f["passengers"] - t["seats"])
    return f["block_hours"] * t["cost"] + spill * f["fare"]


def solve(d: dict, seconds: float) -> dict:
    from scipy.optimize import Bounds, LinearConstraint, milp

    F, K = d["F"], d["K"]
    pairs = [(i, k) for i in range(len(F)) for k in range(len(K)) if K[k]["range_km"] >= F[i]["distance_km"]]
    n = len(pairs)
    c = np.array([pair_cost(F[i], K[k]) for i, k in pairs])
    A, lo, hi = [], [], []
    for i in range(len(F)):
        r = np.zeros(n)
        for j, (ii, _) in enumerate(pairs):
            if ii == i:
                r[j] = 1
        A.append(r); lo.append(1); hi.append(1)
    for k in range(len(K)):
        r = np.zeros(n)
        for j, (i, kk) in enumerate(pairs):
            if kk == k:
                r[j] = F[i]["block_hours"]
        A.append(r); lo.append(-np.inf); hi.append(K[k]["count"] * K[k]["max_hours"])
    res = milp(c, constraints=LinearConstraint(np.array(A), lo, hi), integrality=np.ones(n),
               bounds=Bounds(np.zeros(n), np.ones(n)), options={"time_limit": seconds, "disp": False, "mip_rel_gap": 0})
    if res.x is None:
        return {"feasible": False}
    exp = ["decision,key1,key2,value"]
    for (i, k), x in zip(pairs, res.x):
        if x > 0.5:
            exp.append(f"assign,{F[i]['id']},{K[k]['id']},1")
    return {"feasible": True, "goal": float(res.fun), "bound": float(getattr(res, "mip_dual_bound", None) or res.fun),
            "optimal": res.status == 0, "export": "\n".join(exp) + "\n"}


def instance(size: str) -> tuple[dict, dict]:
    for seed in range(9, 60):
        d = make(size, seed)
        ref = solve(d, 120)
        if ref["feasible"]:
            return d, ref
    raise RuntimeError("no feasible instance")


def write(size: str) -> Path:
    d, ref = instance(size)
    folder = OUT / size
    write_csv(folder / "aircraft_types.csv", ["type", "aircraft", "seats", "cost_per_block_hour", "range_km",
                                               "max_block_hours_per_aircraft"],
              [(t["id"], t["count"], t["seats"], t["cost"], t["range_km"], t["max_hours"]) for t in d["K"]])
    write_csv(folder / "flights.csv", ["flight", "distance_km", "block_hours", "passengers", "average_fare"],
              [(f["id"], f["distance_km"], f["block_hours"], f["passengers"], f["fare"]) for f in d["F"]])
    names = ["aircraft_types.csv", "flights.csv"]
    rules = ("Rules (all hard): every flight on tomorrow's schedule is flown by exactly one aircraft type, the whole "
             "flight on that type. A type can fly a flight only if the flight's distance is at most the type's range. "
             "The block hours of all flights given to a type are at most its number of aircraft times its maximum "
             "block hours per aircraft. Passengers above the seats of the type are turned away and their average fare "
             "is lost. Goal, as small as possible, in USD: the operating cost (block hours times the type's cost per "
             "block hour) plus the lost revenue (passengers turned away times the flight's average fare). Report the "
             "type assigned to each flight, the total cost split into operating cost and lost revenue, the "
             "passengers turned away, and the block hours used by each type against what it has available.")
    head = ('Please build this in a new workspace called "{workspace}". Call the problem "Fleet assignment". '
            f"We are an airline and must decide which aircraft type flies each of our {len(d['F'])} flights "
            f"tomorrow; we have {len(d['K'])} aircraft types.\n\n")
    if size == "S":
        body = ("Aircraft types:\n" + csv_text(folder / names[0]) + "\n\nFlights (average fare in USD):\n"
                + csv_text(folder / names[1]))
        files = []
    else:
        body = ("The data are in the attached files: aircraft_types.csv (fleet size, seats, cost per block hour, "
                "range and daily block-hour limit per type) and flights.csv (distance, block hours, expected "
                "passengers and average fare per flight).")
        files = names
    message = (head + body + "\n\n" + rules +
               "\n\nEverything you need is here: please propose the model without further questions, then solve it.")
    write_case(folder, message, {})
    cost = float(check(folder, ref["export"])[-1].split()[1])
    goal_txt = f"{cost:,.0f}".replace(",", ",?")
    report = [["type per flight", r"FL\d{3}\W+.{0,40}(ATR72|A220|A320|B737M|A321|B787)"],
              ["total cost", goal_txt],
              ["operating cost and lost revenue", r"lost revenue|spill|turned away"],
              ["passengers turned away", r"(passengers?|pax)[^\n]{0,40}(turned away|spill|lost)|(turned away|spill)[^\n]{0,40}\d"],
              ["block hours per type", r"block[- ]hours?"]]
    write_case(folder, message, {"problem": "h09", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": cost if ref["optimal"] else None, "known_feasible": cost,
                                 "bound": cost if ref["optimal"] else ref["bound"], "sense": "minimize", "report": report, "files": files})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    types = {r["type"]: r for r in read_csv(folder / "aircraft_types.csv")}
    flights = {r["flight"]: r for r in read_csv(folder / "flights.csv")}
    by: dict[str, dict[tuple[str, str], float]] = {}
    for r in export_rows(export_csv):
        a, b = r.get("key1") or "", r.get("key2") or ""
        if any(r.get(k) for k in r if k.startswith("key") and k not in ("key1", "key2")):
            continue
        if a in flights and b in types:
            by.setdefault(r["decision"], {})[(a, b)] = float(r["value"])
        elif a in types and b in flights:
            by.setdefault(r["decision"], {})[(b, a)] = float(r["value"])
    if not by:
        return ["no decision over (flight, aircraft type) in the export"]
    name = max(by, key=lambda n: (all(v in (0.0, 1.0) for v in by[n].values()), len([v for v in by[n].values() if v > 1e-6])))
    x = by[name]
    bad: list[str] = []
    hours = {t: 0.0 for t in types}
    cost = 0.0
    for f, fr in flights.items():
        chosen = [(t, v) for (ff, t), v in x.items() if ff == f and abs(v) > 1e-6]
        for t, v in chosen:
            if abs(v - 1) > 1e-6:
                bad.append(f"{f} on {t}: value {v:g}, a flight is flown whole by one type")
        if len(chosen) != 1:
            bad.append(f"{f} is given {len(chosen)} aircraft types, exactly one is needed")
        for t, v in chosen:
            tr = types[t]
            if float(fr["distance_km"]) > float(tr["range_km"]) + 1e-9:
                bad.append(f"{f} ({fr['distance_km']} km) beyond the range of {t}")
            hours[t] += v * float(fr["block_hours"])
            spill = max(0.0, float(fr["passengers"]) - float(tr["seats"]))
            cost += v * (float(fr["block_hours"]) * float(tr["cost_per_block_hour"]) + spill * float(fr["average_fare"]))
    for t, tr in types.items():
        cap = float(tr["aircraft"]) * float(tr["max_block_hours_per_aircraft"])
        if hours[t] > cap + 1e-6:
            bad.append(f"{t}: {hours[t]:g} block hours, above {cap:g}")
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
