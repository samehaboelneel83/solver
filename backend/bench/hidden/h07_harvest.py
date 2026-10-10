"""Hidden problem h07 (multi-period linear program).

    python -m bench.hidden.h07_harvest gen [S M]
    python -m bench.hidden.h07_harvest check <case> <export.csv>
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, decision_over, export_rows, read_csv, write_csv
from bench.hidden._util_a import CLOSE, OPEN, Model, export_text, finish, num_re, search, tol

SIZES = {"S": (5, 4), "M": (80, 10)}  # stands, five-year periods
OUT = Path(__file__).parent / "cases" / "h07"
SPECIES = {"PINE": (450, 520, 9000), "SPRUCE": (560, 610, 10000), "BIRCH": (300, 380, 7000)}  # max m3/ha, EGP/m3, cost/ha
MIN_AGE, OLD_AGE, RETAIN, SWING = 35, 80, 0.30, 0.15


def make(size: str, seed: int = 7) -> dict:
    ns, npd = SIZES[size]
    rng = np.random.default_rng(seed * 86028121 + ns)
    S = [f"ST{i + 1:02d}" for i in range(ns)]
    Pd = [f"P{t + 1}" for t in range(npd)]
    sp = {s: list(SPECIES)[int(rng.integers(3))] for s in S}
    ha = {s: int(rng.integers(20, 151)) for s in S}
    age = {s: int(rng.integers(15, 115)) for s in S}
    if not any(age[s] >= OLD_AGE for s in S):
        age[S[0]] = 95
    yields = {}
    for s in S:
        for t in range(npd):
            a = age[s] + 5 * t
            if a >= MIN_AGE:
                yields[(s, Pd[t])] = int(round(SPECIES[sp[s]][0] * (1 - math.exp(-0.035 * a)) ** 3))
    disc = {Pd[t]: round(1 / 1.05 ** (5 * t), 4) for t in range(npd)}
    total_vol = sum(max((yields.get((s, p), 0) for p in Pd), default=0) * ha[s] for s in S)
    mill = {p: int(round(0.3 * total_vol / npd, -2)) for p in Pd}
    maxha = {p: int(round(1.6 * sum(ha.values()) / npd)) for p in Pd}
    return dict(S=S, P=Pd, sp=sp, ha=ha, age=age, yields=yields, disc=disc, mill=mill, maxha=maxha)


def solve(d: dict, seconds: float = 300):
    m = Model()
    for (s, p), y in d["yields"].items():
        pr, cost = SPECIES[d["sp"][s]][1], SPECIES[d["sp"][s]][2]
        m.var((s, p), cost=d["disc"][p] * (pr * y - cost))
    for s in d["S"]:
        m.add([((s, p), 1) for p in d["P"] if (s, p) in d["yields"]], hi=d["ha"][s])
    vol = {p: [((s, p), y) for (s, pp), y in d["yields"].items() if pp == p] for p in d["P"]}
    for p in d["P"]:
        m.add(vol[p], lo=d["mill"][p])
        m.add([((s, p), 1) for (s, pp) in d["yields"] if pp == p], hi=d["maxha"][p])
    for a, b in zip(d["P"], d["P"][1:]):
        m.add(vol[b] + [(k, -(1 - SWING) * c) for k, c in vol[a]], lo=0)
        m.add(vol[b] + [(k, -(1 + SWING) * c) for k, c in vol[a]], hi=0)
    old = [s for s in d["S"] if d["age"][s] >= OLD_AGE]
    # harvested old area <= (1 - RETAIN) x old area
    m.add([((s, p), 1) for (s, p) in d["yields"] if s in old], hi=(1 - RETAIN) * sum(d["ha"][s] for s in old))
    r = m.solve(maximize=True, seconds=seconds)
    if r is None:
        return None
    rows = [("harvest", k, v) for k, v in r["x"].items() if v > 1e-9]
    return {"goal": r["obj"], "bound": r["bound"], "optimal": r["optimal"], "export": export_text(rows)}


def write(size: str) -> Path:
    seed, d, ref = search(make, solve, size, 7, 300)
    folder = OUT / size
    write_csv(folder / "stands.csv", ["stand", "species", "hectares", "age_years_now"], [(s, d["sp"][s], d["ha"][s], d["age"][s]) for s in d["S"]])
    write_csv(folder / "species.csv", ["species", "price_egp_per_m3", "harvest_cost_egp_per_ha"],
              [(k, v[1], v[2]) for k, v in SPECIES.items() if k in set(d["sp"].values())])
    write_csv(folder / "yields.csv", ["stand", "period", "m3_per_ha"], [(s, p, y) for (s, p), y in d["yields"].items()])
    write_csv(folder / "periods.csv", ["period", "discount_factor", "mill_minimum_m3", "max_harvest_ha"],
              [(p, d["disc"][p], d["mill"][p], d["maxha"][p]) for p in d["P"]])
    write_csv(folder / "policy.csv", ["old_growth_age_years", "old_growth_retained_share", "max_volume_change_share"],
              [(OLD_AGE, RETAIN, SWING)])
    names = ["stands.csv", "species.csv", "yields.csv", "periods.csv"]
    head = (OPEN.format(name="Harvest schedule") + f"Our forestry company must plan the clear-cut harvest of "
            f"{len(d['S'])} forest stands over the next {len(d['P'])} five-year periods ({d['P'][0]} to {d['P'][-1]}).\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in [
            ("Stands", names[0]), ("Species", names[1]),
            ("Yield if a stand is harvested in a period (m3 per hectare; a missing pair means the stand is too young then)", names[2]),
            ("Periods", names[3])])
        files: list[str] = []
    else:
        body = ("The data are in the attached files: stands.csv (species, hectares and age today), species.csv (timber "
                "price and harvesting cost), yields.csv (m3 per hectare if the stand is harvested in that period; a "
                "missing stand-period pair means it may not be harvested then), periods.csv (discount factor, the "
                "mill's minimum volume and the maximum area that may be cut per period).")
        files = names
    rules = ("Rules (all hard): hectares of a stand may be cut in any period listed for it in the yields, in "
             "fractional amounts, and over all periods at most the stand's hectares are cut (cut land is replanted "
             "and not cut again within the plan). In every period the volume cut (hectares x m3 per hectare) is at "
             "least the mill's minimum and the hectares cut are at most the period's maximum. Even flow: the volume "
             f"of each period is between {1 - SWING:.0%} and {1 + SWING:.0%} of the previous period's volume. "
             f"Old growth: of the stands aged {OLD_AGE} years or more today, at least {RETAIN:.0%} of their total "
             "hectares is never cut. Goal: the largest net present value = for every stand and period, discount "
             "factor x hectares cut x (m3 per hectare x price - harvest cost per hectare). Report the hectares cut "
             "per stand and period, the net present value, the volume and area per period, the old-growth area "
             "kept, and which rules limit the plan.")
    message = head + body + "\n\n" + rules + "\n\n" + CLOSE
    report = [["hectares per stand and period", r"ST\d\d[^\n]{0,60}P\d+|P\d+[^\n]{0,60}ST\d\d"],
              ["net present value", num_re(ref["goal"])], ["volume per period", r"m3|m³|cubic"],
              ["old growth kept", r"old[- ]growth"], ["limiting rules", r"\bbind|tight|even[- ]flow|constrain|\blimit(s|ing)?\b"]]
    finish(folder, "h07", size, "maximize", ref, seed, check, message, report, files)
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    stands = {r["stand"]: r for r in read_csv(folder / "stands.csv")}
    species = {r["species"]: r for r in read_csv(folder / "species.csv")}
    yields = {(r["stand"], r["period"]): float(r["m3_per_ha"]) for r in read_csv(folder / "yields.csv")}
    periods = read_csv(folder / "periods.csv")
    pol = read_csv(folder / "policy.csv")[0]
    P = [r["period"] for r in periods]
    name, cut = decision_over(export_rows(export_csv), set(stands), set(P))
    if not name:
        name, c2 = decision_over(export_rows(export_csv), set(P), set(stands))
        cut = {(s, p): v for (p, s), v in c2.items()}
    if not name:
        return ["no decision over (stand, period) in the export", "COST 0.000000"]
    bad: list[str] = []
    for (s, p), v in cut.items():
        if v < -1e-6:
            bad.append(f"{s} {p}: negative {v:g}")
        if v > 1e-6 and (s, p) not in yields:
            bad.append(f"{s} {p}: cut {v:g} ha, not allowed in that period")
    for s, r in stands.items():
        tot = sum(v for (ss, _), v in cut.items() if ss == s)
        if tot > float(r["hectares"]) + tol(float(r["hectares"])):
            bad.append(f"{s}: {tot:g} ha cut, stand has {r['hectares']}")
    vols = []
    npv = 0.0
    for r in periods:
        p = r["period"]
        vol = sum(v * yields.get((s, p), 0.0) for (s, pp), v in cut.items() if pp == p)
        area = sum(v for (s, pp), v in cut.items() if pp == p)
        if vol < float(r["mill_minimum_m3"]) - tol(float(r["mill_minimum_m3"])):
            bad.append(f"{p}: {vol:,.1f} m3, below the mill minimum {r['mill_minimum_m3']}")
        if area > float(r["max_harvest_ha"]) + tol(float(r["max_harvest_ha"])):
            bad.append(f"{p}: {area:,.2f} ha cut, above {r['max_harvest_ha']}")
        vols.append(vol)
        for (s, pp), v in cut.items():
            if pp == p:
                sp = species[stands[s]["species"]]
                npv += float(r["discount_factor"]) * v * (yields.get((s, p), 0.0) * float(sp["price_egp_per_m3"])
                                                          - float(sp["harvest_cost_egp_per_ha"]))
    sw = float(pol["max_volume_change_share"])
    for i in range(1, len(vols)):
        lo, hi = (1 - sw) * vols[i - 1], (1 + sw) * vols[i - 1]
        if vols[i] < lo - tol(lo) or vols[i] > hi + tol(hi):
            bad.append(f"{P[i]}: volume {vols[i]:,.1f} outside {lo:,.1f}-{hi:,.1f} of {P[i - 1]}")
    old = [s for s, r in stands.items() if float(r["age_years_now"]) >= float(pol["old_growth_age_years"])]
    old_ha = sum(float(stands[s]["hectares"]) for s in old)
    kept = old_ha - sum(v for (s, _), v in cut.items() if s in old)
    need = float(pol["old_growth_retained_share"]) * old_ha
    if kept < need - tol(need):
        bad.append(f"old growth kept {kept:,.2f} ha, at least {need:,.2f}")
    return bad + [f"COST {npv:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
