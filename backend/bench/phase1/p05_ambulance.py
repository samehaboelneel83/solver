"""Problem 5: ambulance stations, coverage and backup (location with a road travel-time matrix).

    python -m bench.phase1.p05_ambulance gen [S M L]
    python -m bench.phase1.p05_ambulance check <case> <export.csv>

Open at most K candidate stations and place the ambulances at open stations (at most a station's bays). A
zone is covered when an open station holding an ambulance reaches it within the threshold *by road* (the
travel-time matrix; the coordinates are given too, and straight-line time is shorter than road time, so a
model that computes it covers zones the roads do not). A high-priority zone needs backup: two such stations.
Each zone is served from one open station with an ambulance (its travel minutes x calls x cost per minute).
Cost = station operating costs + ambulance costs + travel + a penalty per person in an uncovered zone; least.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import HERE, csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (8, 25, 5, 3), "M": (50, 200, 25, 10), "L": (120, 800, 60, 25)}  # stations, zones, ambulances, max open
OUT = HERE / "cases" / "p05"
THRESHOLD = 12  # minutes
PENALTY = 40  # EGP per person not covered
MINUTE = 6  # EGP per minute travelled per call
AMBULANCE = 9000  # EGP per ambulance placed


def make(size: str, seed: int = 5) -> dict:
    n_s, n_z, n_a, k = SIZES[size]
    rng = np.random.default_rng(seed + n_z)
    side = 20 * math.sqrt(n_z / 25)
    sx, sy = rng.uniform(0, side, n_s), rng.uniform(0, side, n_s)
    zx, zy = rng.uniform(0, side, n_z), rng.uniform(0, side, n_z)
    straight = np.hypot(sx[:, None] - zx[None, :], sy[:, None] - zy[None, :]) / 0.8  # km at 48 km/h -> minutes
    road = np.rint(straight * rng.uniform(1.25, 1.9, straight.shape) + 1).astype(int)
    pop = rng.integers(800, 9000, n_z)
    calls = np.rint(pop / 400).astype(int) + 1
    priority = rng.random(n_z) < 0.15
    cost = rng.integers(15000, 40000, n_s)
    bays = rng.integers(2, 5, n_s)
    return dict(S=[f"ST{i + 1:03d}" for i in range(n_s)], Z=[f"Z{i + 1:03d}" for i in range(n_z)], sx=sx, sy=sy,
                zx=zx, zy=zy, road=road, straight=np.rint(straight).astype(int), pop=pop, calls=calls,
                priority=priority, cost=cost, bays=bays, n_a=n_a, k=k)


def solve(d: dict, seconds: float) -> dict:
    from ortools.sat.python import cp_model

    nS, nZ = len(d["S"]), len(d["Z"])
    md = cp_model.CpModel()
    op = [md.NewBoolVar("") for _ in range(nS)]
    amb = [md.NewIntVar(0, int(d["bays"][s]), "") for s in range(nS)]
    has = [md.NewBoolVar("") for _ in range(nS)]
    for s in range(nS):
        md.Add(amb[s] <= int(d["bays"][s]) * op[s])
        md.Add(amb[s] >= has[s])
        md.Add(amb[s] <= int(d["bays"][s]) * has[s])
    md.Add(sum(op) <= d["k"])
    md.Add(sum(amb) <= d["n_a"])
    cov = [md.NewBoolVar("") for _ in range(nZ)]
    serve = {}
    for z in range(nZ):
        near = [s for s in range(nS) if d["road"][s, z] <= THRESHOLD]
        md.Add(sum(has[s] for s in near) >= cov[z]) if near else md.Add(cov[z] == 0)
        if d["priority"][z]:
            md.Add(sum(has[s] for s in near) >= 2 * cov[z]) if near else None
        for s in range(nS):
            serve[s, z] = md.NewBoolVar("")
            md.AddImplication(serve[s, z], has[s])
        md.AddExactlyOne([serve[s, z] for s in range(nS)])
    md.Minimize(sum(int(d["cost"][s]) * op[s] + AMBULANCE * amb[s] for s in range(nS))
                + sum(MINUTE * int(d["calls"][z]) * int(d["road"][s, z]) * serve[s, z] for (s, z) in serve)
                + sum(PENALTY * int(d["pop"][z]) * (1 - cov[z]) for z in range(nZ)))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = seconds
    sv.parameters.num_workers = 8
    st = sv.Solve(md)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE), sv.StatusName(st)
    export = "decision,key1,key2,value\n" + "".join(
        f"ambulances,{d['S'][s]},,{sv.Value(amb[s])}\n" for s in range(nS) if sv.Value(amb[s])) + "".join(
        f"serve,{d['S'][s]},{d['Z'][z]},1\n" for (s, z), v in serve.items() if sv.Value(v))
    return {"goal": sv.ObjectiveValue(), "bound": sv.BestObjectiveBound(), "optimal": st == cp_model.OPTIMAL,
            "open": [d["S"][s] for s in range(nS) if sv.Value(op[s])], "export": export}


def write(size: str) -> Path:
    d = make(size)
    ref = solve(d, {"S": 60, "M": 600, "L": 900}[size])
    folder = OUT / size
    S, Z = d["S"], d["Z"]
    write_csv(folder / "stations.csv", ["id", "x_km", "y_km", "operating_cost", "bays"],
              [(S[s], round(float(d["sx"][s]), 2), round(float(d["sy"][s]), 2), int(d["cost"][s]), int(d["bays"][s]))
               for s in range(len(S))])
    write_csv(folder / "zones.csv", ["id", "x_km", "y_km", "population", "calls_per_month", "high_priority"],
              [(Z[z], round(float(d["zx"][z]), 2), round(float(d["zy"][z]), 2), int(d["pop"][z]), int(d["calls"][z]),
                "yes" if d["priority"][z] else "no") for z in range(len(Z))])
    write_csv(folder / "travel_minutes.csv", ["station", "zone", "road_minutes"],
              [(S[s], Z[z], int(d["road"][s, z])) for s in range(len(S)) for z in range(len(Z))])
    names = ["stations.csv", "zones.csv", "travel_minutes.csv"]
    rules = (f"Rules: open at most {d['k']} stations and place at most {d['n_a']} ambulances, only at open stations, "
             "at most a station's bays at each. Response time is the road travel time in travel_minutes.csv, not the "
             f"straight-line distance. A zone is covered when at least one station holding an ambulance reaches it "
             f"within {THRESHOLD} minutes; a high-priority zone counts as covered only with backup: at least two such "
             "stations. Every zone is served from exactly one station holding an ambulance, which costs its road "
             f"minutes x calls per month x {MINUTE} EGP. Each ambulance placed costs {AMBULANCE:,} EGP a month, each open "
             f"station its operating cost, and each person in a zone that is not covered {PENALTY} EGP. Goal: the "
             "lowest total. Report the stations opened, ambulances per station, which station serves each zone and "
             "its response time, coverage % of population, uncovered zones, operating and travel costs, and where "
             "coverage gaps are.")
    head = (f'Please build this in a new workspace called "{{workspace}}". Call the problem "Ambulance stations". '
            f"Choose ambulance stations among {len(S)} candidates for {len(Z)} demand zones.\n\n")
    if size == "S":
        body = "\n\n".join(f"{label}:\n{csv_text(folder / n)}" for label, n in [
            ("Candidate stations (coordinates in km)", names[0]), ("Zones", names[1]),
            ("Road travel time from each station to each zone (minutes)", names[2])])
        files = []
    else:
        body = "The data are in the attached files: stations.csv, zones.csv, travel_minutes.csv (road minutes for every station-zone pair)."
        files = names
    message = head + body + "\n\n" + rules + "\n\nEverything you need is here: please propose the model without further questions, then solve it."
    report = [["stations opened", r"ST\d{3}"], ["ambulances per station", r"ambulance"],
              ["response times", r"minute|response"], ["coverage %", r"\d+(\.\d+)? ?%|coverage"],
              ["uncovered zones / gaps", r"uncovered|not covered|gap"], ["costs", r"cost"]]
    write_case(folder, message, {"problem": "p05", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": ref["goal"] if ref["optimal"] else None, "known_feasible": ref["goal"],
                                 "bound": ref["bound"], "sense": "minimize", "report": report, "files": files})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    """From the placed ambulances and the serving assignment, everything else is computed by road time."""
    st = {r["id"]: r for r in read_csv(folder / "stations.csv")}
    zn = {r["id"]: r for r in read_csv(folder / "zones.csv")}
    road = {(r["station"], r["zone"]): int(r["road_minutes"]) for r in read_csv(folder / "travel_minutes.csv")}
    msg = (folder / "message.txt").read_text(encoding="utf-8")
    k = int(re.search(r"open at most (\d+) stations", msg).group(1))
    n_a = int(re.search(r"place at most (\d+) ambulances", msg).group(1))
    rows = export_rows(export_csv)
    per_s: dict[str, dict[str, float]] = {}
    serve: dict[str, list[str]] = {}
    for r in rows:
        if r.get("key1") in st and not r.get("key2"):
            per_s.setdefault(r["decision"], {})[r["key1"]] = float(r["value"])
        if r.get("key1") in st and r.get("key2") in zn and float(r["value"]) > 0.5:
            serve.setdefault(r["key2"], []).append(r["key1"])
        if r.get("key1") in zn and r.get("key2") in st and float(r["value"]) > 0.5:
            serve.setdefault(r["key1"], []).append(r["key2"])
    amb_name = next((n for n in per_s if "amb" in n.lower() or "vehic" in n.lower() or "fleet" in n.lower()), None)
    if amb_name is None:
        return [f"no decision for ambulances per station (decisions over stations: {', '.join(per_s)})"]
    amb = per_s[amb_name]
    bad: list[str] = []
    holding = {s for s, v in amb.items() if v > 0.5}
    if len(holding) > k:
        bad.append(f"{len(holding)} stations hold ambulances, at most {k} may open")
    if sum(amb.values()) > n_a + 1e-6:
        bad.append(f"{sum(amb.values()):g} ambulances placed, {n_a} available")
    for s, v in amb.items():
        if v > float(st[s]["bays"]) + 1e-6:
            bad.append(f"{s}: {v:g} ambulances, {st[s]['bays']} bays")
    cost = sum(float(st[s]["operating_cost"]) for s in holding) + AMBULANCE * sum(amb.values())
    for z, r in zn.items():
        near = [s for s in holding if road[(s, z)] <= THRESHOLD]
        covered = len(near) >= (2 if r["high_priority"] == "yes" else 1)
        if not covered:
            cost += PENALTY * float(r["population"])
        got = serve.get(z, [])
        if len(got) != 1:
            bad.append(f"{z} served from {len(got)} stations")
            continue
        if got[0] not in holding:
            bad.append(f"{z} served from {got[0]}, which holds no ambulance")
        cost += MINUTE * float(r["calls_per_month"]) * road[(got[0], z)]
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:220])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
