"""Problem 7: microgrid scheduling over hours (time-indexed mixed-integer).

    python -m bench.phase1.p07_grid gen [S M L]
    python -m bench.phase1.p07_grid check <case> <export.csv>

Every hour: solar used (at most the solar available) + diesel output + battery discharge - battery charge +
unmet demand = demand. A generator that is on runs between its minimum and maximum; one switched on pays its
start cost. The battery's stored energy changes by charge x efficiency - discharge, stays within its capacity,
starts and ends at its initial level; charge and discharge each at most the battery's power. Reserve: the
maximum output of the generators that are on, plus what the battery could still discharge in the hour, is at
least the demand x (1 + reserve share). Cost = fuel + start costs + emissions x carbon price + unmet x penalty,
as small as possible.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import HERE, csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (24, 2), "M": (168, 3), "L": (720, 4)}  # hours, generators
OUT = HERE / "cases" / "p07"
SECONDS = {"S": 60, "M": 300, "L": 600}
CARBON = 0.08  # EGP per kg CO2
PENALTY = 50.0  # EGP per kWh not served
RESERVE = 0.10


def make(size: str, seed: int = 7) -> dict:
    n_h, n_g = SIZES[size]
    rng = np.random.default_rng(seed + n_h)
    H = [f"H{h + 1:03d}" for h in range(n_h)]
    hod = np.arange(n_h) % 24
    demand = np.rint(400 + 250 * np.sin((hod - 6) / 24 * 2 * math.pi) ** 2 + rng.normal(0, 25, n_h)).clip(250)
    cloud = rng.uniform(0.5, 1.0, n_h // 24 + 1).repeat(24)[:n_h]
    solar = np.rint(np.maximum(0, np.sin((hod - 6) / 12 * math.pi)) * 650 * cloud * (hod >= 6) * (hod <= 18))
    G = [f"G{g + 1}" for g in range(n_g)]
    gmax = rng.integers(250, 450, n_g)
    gmin = np.rint(gmax * rng.uniform(0.25, 0.4, n_g))
    fuel = np.round(rng.uniform(2.0, 3.2, n_g), 2)  # EGP per kWh
    start = rng.integers(300, 900, n_g)
    co2 = np.round(rng.uniform(0.7, 0.9, n_g), 2)  # kg per kWh
    battery = dict(capacity=1200, power=300, efficiency=0.92, initial=600)
    return dict(H=H, demand=demand, solar=solar, G=G, gmax=gmax, gmin=gmin, fuel=fuel, start=start, co2=co2,
                battery=battery)


def solve(d: dict, seconds: float) -> dict:
    from scipy.optimize import Bounds, LinearConstraint, milp

    H, G, b = d["H"], d["G"], d["battery"]
    nh, ng = len(H), len(G)
    idx = {}

    def var(name, *k):
        idx.setdefault((name, *k), len(idx))
        return idx[(name, *k)]

    for t in range(nh):
        for name in ("sol", "ch", "dis", "soc", "unmet"):
            var(name, t)
        for g in range(ng):
            var("p", g, t); var("on", g, t); var("up", g, t)
    n = len(idx)
    c = np.zeros(n)
    lo, hi, integ = np.zeros(n), np.full(n, np.inf), np.zeros(n)
    for t in range(nh):
        hi[idx["sol", t]] = d["solar"][t]
        hi[idx["ch", t]] = hi[idx["dis", t]] = b["power"]
        hi[idx["soc", t]] = b["capacity"]
        c[idx["unmet", t]] = PENALTY
        for g in range(ng):
            c[idx["p", g, t]] = d["fuel"][g] + d["co2"][g] * CARBON
            c[idx["up", g, t]] = d["start"][g]
            for k in ("on", "up"):
                hi[idx[k, g, t]] = 1
                integ[idx[k, g, t]] = 1
    rows, rl, rh = [], [], []

    def row(coefs, l, h):
        r = np.zeros(n)
        for k, v in coefs:
            r[k] += v
        rows.append(r); rl.append(l); rh.append(h)

    for t in range(nh):
        row([(idx["sol", t], 1), (idx["dis", t], 1), (idx["ch", t], -1), (idx["unmet", t], 1)]
            + [(idx["p", g, t], 1) for g in range(ng)], d["demand"][t], d["demand"][t])
        prev = b["initial"] if t == 0 else None
        terms = [(idx["soc", t], 1), (idx["ch", t], -b["efficiency"]), (idx["dis", t], 1)]
        if t > 0:
            terms.append((idx["soc", t - 1], -1))
            row(terms, 0, 0)
        else:
            row(terms, prev, prev)
        for g in range(ng):
            row([(idx["p", g, t], 1), (idx["on", g, t], -d["gmax"][g])], -np.inf, 0)
            row([(idx["p", g, t], 1), (idx["on", g, t], -d["gmin"][g])], 0, np.inf)
            on_prev = [] if t == 0 else [(idx["on", g, t - 1], -1)]
            row([(idx["up", g, t], 1), (idx["on", g, t], -1)] + [(k, -v) for k, v in on_prev], 0, np.inf)
        # reserve: online max + min(power, soc before the hour) >= demand (1 + r); soc before = soc[t-1] or initial
        before = [(idx["soc", t - 1], 1)] if t > 0 else []
        row([(idx["on", g, t], d["gmax"][g]) for g in range(ng)] + [(idx["dis", t], 0)], d["demand"][t] * (1 + RESERVE) - b["power"], np.inf)
        row([(idx["on", g, t], d["gmax"][g]) for g in range(ng)] + before,
            d["demand"][t] * (1 + RESERVE) - (b["initial"] if t == 0 else 0), np.inf)
    row([(idx["soc", nh - 1], 1)], b["initial"], np.inf)
    r = milp(c, constraints=LinearConstraint(np.array(rows), rl, rh), integrality=integ, bounds=Bounds(lo, hi),
             options={"time_limit": seconds, "disp": False})
    assert r.x is not None, r.message
    names = {"sol": "solar_used", "ch": "charge", "dis": "discharge", "soc": "stored", "unmet": "unmet",
             "p": "output", "on": "on"}
    export = ["decision,key1,key2,value"]
    for key, k in idx.items():
        if key[0] == "up":
            continue
        value = round(float(r.x[k]), 6)
        if key[0] in ("p", "on"):
            export.append(f"{names[key[0]]},{G[key[1]]},{H[key[2]]},{value}")
        else:
            export.append(f"{names[key[0]]},{H[key[1]]},,{value}")
    return {"goal": float(r.fun), "bound": float(getattr(r, "mip_dual_bound", r.fun) or r.fun),
            "optimal": r.status == 0, "unmet": float(sum(r.x[idx["unmet", t]] for t in range(nh))),
            "export": "\n".join(export) + "\n"}


def write(size: str) -> Path:
    d = make(size)
    ref = solve(d, SECONDS[size])
    folder = OUT / size
    b = d["battery"]
    write_csv(folder / "hours.csv", ["id", "order", "demand_kwh", "solar_kwh"],
              [(h, i + 1, int(d["demand"][i]), int(d["solar"][i])) for i, h in enumerate(d["H"])])
    write_csv(folder / "generators.csv", ["id", "min_kw", "max_kw", "fuel_cost_per_kwh", "start_cost", "co2_kg_per_kwh"],
              [(g, int(d["gmin"][i]), int(d["gmax"][i]), float(d["fuel"][i]), int(d["start"][i]), float(d["co2"][i]))
               for i, g in enumerate(d["G"])])
    rules = (f"The battery stores at most {b['capacity']} kWh, charges or discharges at most {b['power']} kWh in an "
             f"hour, keeps {b['efficiency']} of what it charges (a kWh charged adds {b['efficiency']} kWh stored), "
             f"starts with {b['initial']} kWh and must end the last hour with at least {b['initial']} kWh. "
             "Rules: every hour, solar used (at most the solar available; the rest is curtailed) + diesel output + "
             "battery discharge - battery charge + unmet demand = demand. A generator that is on in an hour runs "
             "between its min and max kW; one that is off produces nothing. A generator switched on in an hour (off "
             "the hour before, or the first hour) pays its start cost. Stored energy = stored the hour before (or the "
             "initial) + charge x efficiency - discharge. Reserve: in every hour, the max kW of the generators that "
             f"are on, plus the battery's discharge limit or the energy stored before the hour if that is smaller, is "
             f"at least the demand x {1 + RESERVE}. Goal: the lowest cost = fuel + start costs + CO2 kg x {CARBON} "
             f"EGP + {PENALTY} EGP per kWh of unmet demand. Report the hourly schedule (generation, battery charge, "
             "discharge and level, generator on/off), total cost and CO2, solar used and curtailed, unmet demand, "
             "and how the cost changes with fuel price, demand and solar.")
    head = (f'Please build this in a new workspace called "{{workspace}}". Call the problem "Microgrid schedule". '
            f"Schedule our microgrid over {len(d['H'])} hours: solar, one battery and {len(d['G'])} diesel "
            "generators.\n\n")
    if size == "S":
        body = ("Hours (demand and solar available in kWh):\n" + csv_text(folder / "hours.csv")
                + "\n\nGenerators:\n" + csv_text(folder / "generators.csv"))
        files = []
    else:
        body = "The data are in the attached files: hours.csv (order, demand and solar per hour) and generators.csv."
        files = ["hours.csv", "generators.csv"]
    message = head + body + "\n\n" + rules + "\n\nEverything you need is here: please propose the model without further questions, then solve it."
    report = [["hourly schedule", r"H0\d\d"], ["generator on/off", r"\b(on|off|commit)"],
              ["total cost", f"{ref['goal']:,.0f}".replace(",", ",?")], ["CO2 / emissions", r"CO2|emission"],
              ["solar used / curtailed", r"curtail|solar used|renewable"], ["unmet demand", r"unmet|not served|shed"],
              ["sensitivity to fuel, demand, solar", r"fuel price|sensitiv|if (fuel|demand|solar)"]]
    write_case(folder, message, {"problem": "p07", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": ref["goal"] if ref["optimal"] else None, "known_feasible": ref["goal"],
                                 "bound": ref["bound"], "sense": "minimize", "reference_unmet": ref["unmet"],
                                 "report": report, "files": files})
    return folder


def _by_word(rows, hours, gens):
    """The model's decisions by what their names say: per (generator, hour) and per hour."""
    per_gh: dict[str, dict] = {}
    per_h: dict[str, dict] = {}
    for r in rows:
        k1, k2 = r.get("key1"), r.get("key2")
        if k1 in gens and k2 in hours:
            per_gh.setdefault(r["decision"], {})[(k1, k2)] = float(r["value"])
        elif k1 in hours and not k2:
            per_h.setdefault(r["decision"], {})[k1] = float(r["value"])
    def pick(table, words, avoid=()):
        for name in table:
            low = name.lower()
            if any(w in low for w in words) and not any(a in low for a in avoid):
                return table[name]
        return None
    return dict(p=pick(per_gh, ("gen", "output", "power", "diesel", "prod")) or
                next((v for v in per_gh.values() if any(x not in (0, 1) for x in v.values())), None),
                on=pick(per_gh, ("on", "commit", "status", "run")) ,
                ch=pick(per_h, ("charge",), ("dis",)), dis=pick(per_h, ("dis",)),
                soc=pick(per_h, ("soc", "stor", "level", "state", "energy")),
                sol=pick(per_h, ("solar", "pv", "renew"), ("curt",)), unmet=pick(per_h, ("unmet", "shed", "short", "lost")))


def check(folder: Path, export_csv: str) -> list[str]:
    hours = {r["id"]: r for r in read_csv(folder / "hours.csv")}
    gens = {r["id"]: r for r in read_csv(folder / "generators.csv")}
    msg = (folder / "message.txt").read_text(encoding="utf-8")
    cap = float(re.search(r"stores at most ([\d.]+) kWh", msg).group(1))
    power = float(re.search(r"at most ([\d.]+) kWh in an hour", msg).group(1))
    eff = float(re.search(r"keeps ([\d.]+) of what", msg).group(1))
    init = float(re.search(r"starts with ([\d.]+) kWh", msg).group(1))
    dec = _by_word(export_rows(export_csv), set(hours), set(gens))
    missing = [k for k in ("p", "ch", "dis", "sol") if dec[k] is None]
    if missing:
        return [f"could not tell the model's decisions apart for: {', '.join(missing)}"]
    order = sorted(hours, key=lambda h: int(hours[h]["order"]))
    bad: list[str] = []
    soc = init
    cost = 0.0
    on_before = {g: False for g in gens}
    for h in order:
        d = float(hours[h]["demand_kwh"])
        sol = dec["sol"].get(h, 0.0)
        ch, dis = dec["ch"].get(h, 0.0), dec["dis"].get(h, 0.0)
        unmet = (dec["unmet"] or {}).get(h, 0.0)
        if sol > float(hours[h]["solar_kwh"]) + 1e-6:
            bad.append(f"{h}: solar used {sol:g} above available {hours[h]['solar_kwh']}")
        if ch > power + 1e-6 or dis > power + 1e-6:
            bad.append(f"{h}: battery power above {power:g}")
        out = 0.0
        online_max = 0.0
        for g, r in gens.items():
            p = dec["p"].get((g, h), 0.0)
            on = p > 1e-6 or (dec["on"] or {}).get((g, h), 0.0) > 0.5
            if p > 1e-6 and (p < float(r["min_kw"]) - 1e-6 or p > float(r["max_kw"]) + 1e-6):
                bad.append(f"{h}: {g} at {p:g}, outside [{r['min_kw']}, {r['max_kw']}]")
            if on:
                online_max += float(r["max_kw"])
                if not on_before[g]:
                    cost += float(r["start_cost"])
            on_before[g] = on
            out += p
            cost += p * (float(r["fuel_cost_per_kwh"]) + float(r["co2_kg_per_kwh"]) * CARBON)
        if abs(sol + out + dis - ch + unmet - d) > 1e-4:
            bad.append(f"{h}: supply {sol + out + dis - ch + unmet:g} is not the demand {d:g}")
        if online_max + min(power, soc) < d * (1 + RESERVE) - 1e-4:
            bad.append(f"{h}: reserve {online_max + min(power, soc):g} below {d * (1 + RESERVE):g}")
        soc = soc + ch * eff - dis
        if soc < -1e-4 or soc > cap + 1e-4:
            bad.append(f"{h}: battery at {soc:g}, outside [0, {cap:g}]")
        cost += unmet * PENALTY
    if soc < init - 1e-4:
        bad.append(f"the battery ends at {soc:g}, below {init:g}")
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:220])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
