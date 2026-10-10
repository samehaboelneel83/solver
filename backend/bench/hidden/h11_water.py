"""Hidden problem 11: water network operation over a day (time-expanded network flow with storage).

    python -m bench.hidden.h11_water gen [S M]
    python -m bench.hidden.h11_water check <case> <export.csv>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (2, 1, 2, 6), "M": (4, 2, 8, 24)}  # sources, tanks, zones, periods
OUT = Path(__file__).parent / "cases" / "h11"


def make(size: str, seed: int = 11) -> dict:
    ns, nt, nz, T = SIZES[size]
    rng = np.random.default_rng(seed * 7 + T)
    S = [f"SRC{i + 1}" for i in range(ns)]
    TK = [f"TANK{i + 1}" for i in range(nt)]
    Z = [f"ZONE{i + 1}" for i in range(nz)]
    H = [f"P{t + 1:02d}" for t in range(T)]
    hours_per = 24 // T
    shape = np.array([0.6 + 0.6 * np.sin(np.pi * ((t + 0.5) * hours_per - 5) / 24) ** 2 for t in range(T)])
    base = rng.integers(80, 220, nz) * hours_per
    demand = np.rint(np.outer(base, shape)).astype(int)
    tariff = np.array([0.9 if 7 <= (t * hours_per) % 24 < 17 else (1.6 if 17 <= (t * hours_per) % 24 < 22 else 0.5)
                       for t in range(T)])
    peak = demand.sum(axis=0).max()
    srcs = []
    for i in range(ns):
        srcs.append(dict(id=S[i], max_m3=int(peak / ns * rng.uniform(0.8, 1.1)),
                         cost=round(float(rng.uniform(0.6, 2.4)), 2)))
    tanks = []
    for k in range(nt):
        cap = int(demand.sum() / nt * rng.uniform(0.15, 0.25))
        tanks.append(dict(id=TK[k], min=int(cap * 0.2), max=cap, start=int(cap * 0.5)))
    pipes = []
    for s in range(ns):  # every source feeds every tank, and a couple of zones directly
        for k in range(nt):
            pipes.append((S[s], TK[k], int(peak * rng.uniform(0.4, 0.8) / max(1, nt)), round(float(rng.uniform(0.25, 0.6)), 2)))
        for z in rng.choice(nz, min(nz, 2), replace=False):
            pipes.append((S[s], Z[z], int(base[z] * rng.uniform(0.5, 1.0)), round(float(rng.uniform(0.3, 0.8)), 2)))
    for z in range(nz):  # tanks feed zones by gravity (small energy), each zone from one or two tanks
        for k in rng.choice(nt, min(nt, 1 + int(rng.random() < 0.5)), replace=False):
            pipes.append((TK[k], Z[z], int(base[z] * 1.6), 0.0))
    return dict(S=srcs, TK=tanks, Z=Z, H=H, demand=demand, tariff=tariff, pipes=pipes, hours_per=hours_per)


def solve(d: dict, seconds: float) -> dict:
    from scipy.optimize import linprog

    S, TK, Z, H, pipes = d["S"], d["TK"], d["Z"], d["H"], d["pipes"]
    T = len(H)
    idx = {}
    for p, (a, b, cap, e) in enumerate(pipes):
        for t in range(T):
            idx[("f", p, t)] = len(idx)
    for k in range(len(TK)):
        for t in range(T):
            idx[("l", k, t)] = len(idx)
    n = len(idx)
    c = np.zeros(n)
    hi = np.full(n, np.inf)
    lo = np.zeros(n)
    srccost = {s["id"]: s["cost"] for s in S}
    for p, (a, b, cap, e) in enumerate(pipes):
        for t in range(T):
            j = idx[("f", p, t)]
            c[j] = e * d["tariff"][t] + srccost.get(a, 0.0)
            hi[j] = cap
    for k, tk in enumerate(TK):
        for t in range(T):
            lo[idx[("l", k, t)]] = tk["min"]
            hi[idx[("l", k, t)]] = tk["max"]
    Aeq, beq, Aub, bub = [], [], [], []
    for t in range(T):
        for z_i, z in enumerate(Z):
            r = np.zeros(n)
            for p, (a, b, *_rest) in enumerate(pipes):
                if b == z:
                    r[idx[("f", p, t)]] = 1
            Aeq.append(r); beq.append(d["demand"][z_i, t])
        for k, tk in enumerate(TK):
            r = np.zeros(n)
            r[idx[("l", k, t)]] = 1
            if t > 0:
                r[idx[("l", k, t - 1)]] = -1
            for p, (a, b, *_rest) in enumerate(pipes):
                if b == tk["id"]:
                    r[idx[("f", p, t)]] -= 1
                if a == tk["id"]:
                    r[idx[("f", p, t)]] += 1
            Aeq.append(r); beq.append(tk["start"] if t == 0 else 0)
        for s in S:
            r = np.zeros(n)
            for p, (a, *_rest) in enumerate(pipes):
                if a == s["id"]:
                    r[idx[("f", p, t)]] = 1
            Aub.append(r); bub.append(s["max_m3"])
    for k, tk in enumerate(TK):
        lo[idx[("l", k, T - 1)]] = max(tk["min"], tk["start"])
    res = linprog(c, A_ub=np.array(Aub), b_ub=bub, A_eq=np.array(Aeq), b_eq=beq, bounds=list(zip(lo, hi)),
                  method="highs", options={"time_limit": seconds})
    if res.status != 0:
        return {"feasible": False}
    exp = ["decision,key1,key2,key3,value"]
    for p, (a, b, *_rest) in enumerate(pipes):
        for t in range(T):
            x = res.x[idx[("f", p, t)]]
            if x > 1e-9:
                exp.append(f"flow,{a},{b},{H[t]},{x:.9f}")
    return {"feasible": True, "goal": float(res.fun), "bound": float(res.fun), "optimal": True,
            "export": "\n".join(exp) + "\n"}


def instance(size: str) -> tuple[dict, dict]:
    for seed in range(11, 80):
        d = make(size, seed)
        ref = solve(d, 120)
        if ref["feasible"]:
            return d, ref
    raise RuntimeError("no feasible instance")


def write(size: str) -> Path:
    d, ref = instance(size)
    folder = OUT / size
    hp = d["hours_per"]
    write_csv(folder / "sources.csv", ["source", "max_m3_per_period", "production_cost_per_m3"],
              [(s["id"], s["max_m3"], s["cost"]) for s in d["S"]])
    write_csv(folder / "tanks.csv", ["tank", "min_m3", "max_m3", "start_m3"],
              [(t["id"], t["min"], t["max"], t["start"]) for t in d["TK"]])
    write_csv(folder / "pipes.csv", ["from", "to", "max_m3_per_period", "pumping_kwh_per_m3"], d["pipes"])
    write_csv(folder / "periods.csv", ["period", "order", "tariff_per_kwh"],
              [(h, i + 1, float(d["tariff"][i])) for i, h in enumerate(d["H"])])
    write_csv(folder / "demand.csv", ["zone", "period", "m3"],
              [(z, h, int(d["demand"][zi, t])) for zi, z in enumerate(d["Z"]) for t, h in enumerate(d["H"])])
    names = ["sources.csv", "tanks.csv", "pipes.csv", "periods.csv", "demand.csv"]
    rules = (f"The day is split into {len(d['H'])} periods of {hp} hours, in the order given. Rules (all hard): water "
             "moves only along the listed pipes, in the listed direction, and a pipe carries at most its maximum m3 "
             "in a period. A source sends out at most its maximum m3 per period, in total over its pipes. Each zone "
             "must receive exactly its demand in every period (zones do not pass water on). A tank's level at the end "
             "of a period is its level at the end of the previous period (its start level for the first period) "
             "plus what flows in minus what flows out during the period; that level must stay between the tank's "
             "minimum and maximum at the end of every period, and at the end of the last period every tank must "
             "hold at least its start level. Goal, as small as possible, in EGP: production cost (m3 sent out by a "
             "source times its production cost per m3) plus pumping energy cost (m3 through a pipe times its "
             "pumping kWh per m3 times the period's tariff per kWh). Report the flow in each pipe in each period, "
             "the tank levels through the day, the total cost split into production and energy, how much each "
             "source produces, and how the plan shifts pumping away from the expensive periods.")
    head = ('Please build this in a new workspace called "{workspace}". Call the problem "Water network day plan". '
            "Our water utility must plan tomorrow's pumping: how much each source sends through which pipes in each "
            "period so the zones get their water at least cost, using the storage tanks as buffers.\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in zip(
            ["Sources", "Tanks", "Pipes", "Periods (tariff in EGP per kWh)", "Zone demand (m3 per period)"], names))
        files = []
    else:
        body = ("The data are in the attached files: sources.csv, tanks.csv, pipes.csv (direction, capacity and "
                "pumping energy), periods.csv (order and electricity tariff), demand.csv (m3 per zone and period).")
        files = names
    message = (head + body + "\n\n" + rules +
               "\n\nEverything you need is here: please propose the model without further questions, then solve it.")
    write_case(folder, message, {})
    cost = float(check(folder, ref["export"])[-1].split()[1])
    lead = f"{cost:,.0f}"[:-2].replace(",", ",?")
    report = [["pipe flows per period", r"(SRC|TANK)\d\W+.{0,40}(TANK|ZONE)\d"],
              ["tank levels", r"level"],
              ["total cost", lead + r"\d\d"],
              ["production vs energy cost", r"energy|pumping cost|electric"],
              ["source output", r"SRC\d[^\n]{0,60}\d"],
              ["peak-period shifting", r"peak|expensive|tariff"]]
    write_case(folder, message, {"problem": "h11", "size": size, "kind": "exact", "goal": cost,
                                 "known_feasible": cost, "bound": cost, "sense": "minimize",
                                 "report": report, "files": files})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    src = {r["source"]: r for r in read_csv(folder / "sources.csv")}
    tanks = {r["tank"]: r for r in read_csv(folder / "tanks.csv")}
    pipes = {(r["from"], r["to"]): r for r in read_csv(folder / "pipes.csv")}
    periods = sorted(read_csv(folder / "periods.csv"), key=lambda r: int(r["order"]))
    P = [r["period"] for r in periods]
    tariff = {r["period"]: float(r["tariff_per_kwh"]) for r in periods}
    dem = {(r["zone"], r["period"]): float(r["m3"]) for r in read_csv(folder / "demand.csv")}
    zones = {z for z, _ in dem}
    nodes = set(src) | set(tanks) | zones

    def per(x: str):
        if x in tariff:
            return x
        m = re.fullmatch(r"[A-Za-z_]*0*(\d+)", (x or "").strip())
        if m and 1 <= int(m.group(1)) <= len(P):
            return P[int(m.group(1)) - 1]
        return None

    by: dict[str, dict[tuple, float]] = {}
    for r in export_rows(export_csv):
        a, b, t = r.get("key1") or "", r.get("key2") or "", per(r.get("key3") or "")
        if r.get("key4") or t is None or a not in nodes or b not in nodes:
            continue
        cell = by.setdefault(r["decision"], {})
        cell[(a, b, t)] = cell.get((a, b, t), 0.0) + float(r["value"])
    if not by:
        return ["no decision over (from, to, period) in the export"]
    name = max(by, key=lambda n: (any(v not in (0.0, 1.0) for v in by[n].values()), len(by[n])))
    f = by[name]
    bad: list[str] = []
    cost = 0.0
    for (a, b, t), q in f.items():
        if abs(q) <= 1e-9:
            continue
        if (a, b) not in pipes:
            bad.append(f"{a}->{b} in {t}: no such pipe ({q:g})")
            continue
        if q < -1e-6:
            bad.append(f"{a}->{b} in {t}: negative flow {q:g}")
        if q > float(pipes[(a, b)]["max_m3_per_period"]) + 1e-6:
            bad.append(f"{a}->{b} in {t}: {q:g} above the pipe's {pipes[(a, b)]['max_m3_per_period']}")
        cost += q * float(pipes[(a, b)]["pumping_kwh_per_m3"]) * tariff[t]
        if a in src:
            cost += q * float(src[a]["production_cost_per_m3"])
    for t in P:
        for s, r in src.items():
            out = sum(q for (a, _, tt), q in f.items() if a == s and tt == t)
            if out > float(r["max_m3_per_period"]) + 1e-6:
                bad.append(f"{s} in {t}: sends {out:g}, above {r['max_m3_per_period']}")
        for z in zones:
            got = sum(q for (_, b, tt), q in f.items() if b == z and tt == t)
            sent = sum(q for (a, _, tt), q in f.items() if a == z and tt == t)
            if abs(got - sent - dem[(z, t)]) > 1e-4:
                bad.append(f"{z} in {t}: receives {got - sent:g}, demand {dem[(z, t)]:g}")
    for k, r in tanks.items():
        level = float(r["start_m3"])
        for t in P:
            level += sum(q for (_, b, tt), q in f.items() if b == k and tt == t)
            level -= sum(q for (a, _, tt), q in f.items() if a == k and tt == t)
            if level < float(r["min_m3"]) - 1e-4 or level > float(r["max_m3"]) + 1e-4:
                bad.append(f"{k} at the end of {t}: level {level:g} outside {r['min_m3']}..{r['max_m3']}")
        if level < float(r["start_m3"]) - 1e-4:
            bad.append(f"{k} ends the day at {level:g}, below its start level {r['start_m3']}")
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
