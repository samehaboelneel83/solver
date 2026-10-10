"""Problem 10: integrated disaster response over days (multi-period flow, open/close, closed roads, priorities,
several goals).

    python -m bench.phase1.p10_disaster gen [S M L]
    python -m bench.phase1.p10_disaster check <case> <export.csv>

Open temporary warehouses (at most K, each with an opening cost); every day relief arrives at each open
warehouse (its daily intake per good), is stored (up to its capacity) or trucked to affected locations along
roads that are open that day (a road closed on a day carries nothing). Each warehouse sends at most its truck
loads per day. A location's demand per day and good is met by deliveries or left unmet; unmet demand at a
priority location (hospital or isolated community) weighs more. Goals: unmet demand (weighted by priority),
delivery time (tons x road minutes) and cost (opening + trucking); the reference uses the stated weights,
and the case asks for the trade-off between cost and unmet demand too.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import HERE, csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (3, 6, 3, 1, 2), "M": (8, 30, 7, 2, 4), "L": (20, 80, 7, 2, 8)}  # warehouses, locations, days, goods, max open
OUT = HERE / "cases" / "p10"
W_UNMET, W_PRIORITY, W_MINUTE, TRUCK_TONS, TRUCK_COST = 1000, 5000, 1, 10, 800


def make(size: str, seed: int = 10) -> dict:
    n_w, n_l, n_d, n_g, k = SIZES[size]
    rng = np.random.default_rng(seed + n_l)
    W = [f"WH{i + 1:02d}" for i in range(n_w)]
    L = [f"LOC{i + 1:03d}" for i in range(n_l)]
    D = [f"DAY{i + 1}" for i in range(n_d)]
    G = ["FOOD", "MEDICAL"][:n_g]
    minutes = rng.integers(20, 240, (n_w, n_l))
    closed = {(w, l, d) for w in range(n_w) for l in range(n_l) for d in range(n_d) if rng.random() < 0.08}
    priority = rng.random(n_l) < 0.2
    demand = rng.integers(2, 15, (n_l, n_d, n_g))
    total = demand.sum(axis=(0, 2))  # per day
    intake = np.rint(np.outer(np.ones(n_w), total.mean() * rng.uniform(0.9, 1.3, n_g) / n_g) * 1.0 / k * 0.85).astype(int)
    cap = np.rint(intake.sum(axis=1) * 3).astype(int)
    open_cost = rng.integers(20000, 60000, n_w)
    trucks = rng.integers(3, 10, n_w)  # truck loads per day
    return dict(W=W, L=L, D=D, G=G, minutes=minutes, closed=closed, priority=priority, demand=demand,
                intake=intake, cap=cap, open_cost=open_cost, trucks=trucks, k=k)


def solve(d: dict, seconds: float) -> dict:
    from scipy.optimize import Bounds, LinearConstraint, milp

    W, L, D, G = d["W"], d["L"], d["D"], d["G"]
    idx: dict = {}

    def v(*k):
        return idx.setdefault(k, len(idx))

    for w in range(len(W)):
        v("open", w)
        for t in range(len(D)):
            for g in range(len(G)):
                v("stock", w, t, g)
                for l in range(len(L)):
                    if (w, l, t) not in d["closed"]:
                        v("ship", w, l, t, g)
    for l in range(len(L)):
        for t in range(len(D)):
            for g in range(len(G)):
                v("unmet", l, t, g)
    n = len(idx)
    c = np.zeros(n)
    hi = np.full(n, np.inf)
    integ = np.zeros(n)
    for key, i in idx.items():
        if key[0] == "open":
            c[i] = d["open_cost"][key[1]]
            hi[i] = 1
            integ[i] = 1
        elif key[0] == "ship":
            _, w, l, t, g = key
            c[i] = W_MINUTE * d["minutes"][w, l] + TRUCK_COST / TRUCK_TONS
        elif key[0] == "unmet":
            c[i] = W_PRIORITY if d["priority"][key[1]] else W_UNMET
    rows, rl, rh = [], [], []

    def row(terms, lo, up):
        r = np.zeros(n)
        for k, val in terms:
            r[k] += val
        rows.append(r); rl.append(lo); rh.append(up)

    for w in range(len(W)):
        for t in range(len(D)):
            for g in range(len(G)):
                out = [(idx["ship", w, l, t, g], 1) for l in range(len(L)) if ("ship", w, l, t, g) in idx]
                prev = [(idx["stock", w, t - 1, g], -1)] if t > 0 else []
                # stock today = stock yesterday + intake (if open) - shipped
                row([(idx["stock", w, t, g], 1), (idx["open", w], -float(d["intake"][w, g]))] + prev + out, 0, 0)
            row([(idx["stock", w, t, g], 1) for g in range(len(G))] + [(idx["open", w], -float(d["cap"][w]))], -np.inf, 0)
            row([(idx["ship", w, l, t, g], 1) for l in range(len(L)) for g in range(len(G)) if ("ship", w, l, t, g) in idx]
                + [(idx["open", w], -float(d["trucks"][w] * TRUCK_TONS))], -np.inf, 0)
    for l in range(len(L)):
        for t in range(len(D)):
            for g in range(len(G)):
                row([(idx["ship", w, l, t, g], 1) for w in range(len(W)) if ("ship", w, l, t, g) in idx]
                    + [(idx["unmet", l, t, g], 1)], float(d["demand"][l, t, g]), float(d["demand"][l, t, g]))
    row([(idx["open", w], 1) for w in range(len(W))], -np.inf, d["k"])
    r = milp(c, constraints=LinearConstraint(np.array(rows), rl, rh), integrality=integ, bounds=Bounds(np.zeros(n), hi),
             options={"time_limit": seconds, "disp": False})
    assert r.x is not None, r.message
    unmet = sum(r.x[i] for key, i in idx.items() if key[0] == "unmet")
    export = ["decision,key1,key2,key3,key4,value"]
    for key, i in idx.items():
        if key[0] == "open" and r.x[i] > 0.5:
            export.append(f"open,{W[key[1]]},,,,1")
        elif key[0] == "ship" and r.x[i] > 1e-9:
            _, w, l, t, g = key
            export.append(f"ship,{W[w]},{L[l]},{D[t]},{G[g]},{r.x[i]:.9f}")
    return {"goal": float(r.fun), "bound": float(getattr(r, "mip_dual_bound", None) or r.fun), "optimal": r.status == 0,
            "unmet": float(unmet), "export": "\n".join(export) + "\n"}


def write(size: str) -> Path:
    d = make(size)
    ref = solve(d, {"S": 60, "M": 600, "L": 900}[size])
    folder = OUT / size
    W, L, D, G = d["W"], d["L"], d["D"], d["G"]
    write_csv(folder / "warehouses.csv", ["id", "opening_cost", "capacity_tons", "truck_loads_per_day"]
              + [f"intake_{g.lower()}_tons_per_day" for g in G],
              [[W[w], int(d["open_cost"][w]), int(d["cap"][w]), int(d["trucks"][w])] + [int(x) for x in d["intake"][w]]
               for w in range(len(W))])
    write_csv(folder / "locations.csv", ["id", "priority"], [(L[l], "yes" if d["priority"][l] else "no") for l in range(len(L))])
    write_csv(folder / "days.csv", ["id", "order"], [(x, i + 1) for i, x in enumerate(D)])
    write_csv(folder / "demand.csv", ["location", "day", "good", "tons"],
              [(L[l], D[t], G[g], int(d["demand"][l, t, g])) for l in range(len(L)) for t in range(len(D)) for g in range(len(G))])
    write_csv(folder / "roads.csv", ["warehouse", "location", "minutes"],
              [(W[w], L[l], int(d["minutes"][w, l])) for w in range(len(W)) for l in range(len(L))])
    write_csv(folder / "closed_roads.csv", ["warehouse", "location", "day"],
              sorted((W[w], L[l], D[t]) for w, l, t in d["closed"]))
    names = ["warehouses.csv", "locations.csv", "days.csv", "demand.csv", "roads.csv", "closed_roads.csv"]
    rules = (f"Rules: open at most {d['k']} warehouses; an open warehouse costs its opening cost once. Every day, an "
             "open warehouse receives its intake of each good (a closed one receives nothing); what it does not "
             "ship stays in stock to the next day (starting from nothing), and its stock of all goods together is "
             f"at most its capacity. It ships at most its truck loads per day x {TRUCK_TONS} tons in all, each "
             f"ton costing {TRUCK_COST // TRUCK_TONS} EGP of trucking. A road listed in closed_roads.csv carries "
             "nothing on that day. For each location, day and good, tons delivered + unmet = demand (deliveries "
             f"arrive the same day). Goal, as small as possible: {W_UNMET} per ton unmet ({W_PRIORITY} at a priority "
             f"location -- hospitals and isolated communities) + tons x road minutes (delivery time) + opening and "
             "trucking costs. Report the warehouses opened, daily shipments and stock, unmet demand by location "
             "(priority first), delivery time, the cost breakdown, the trade-off between cost and unmet demand "
             "(Pareto alternatives), and what to change if a road closes or supplies fall.")
    head = (f'Please build this in a new workspace called "{{workspace}}". Call the problem "Relief plan". After a '
            f"disaster we must plan relief for {len(D)} days: which of {len(W)} temporary warehouses to open and what "
            f"to deliver each day to {len(L)} affected locations.\n\n")
    if size == "S":
        body = "\n\n".join(f"{label}:\n{csv_text(folder / n)}" for label, n in [
            ("Warehouses", names[0]), ("Locations", names[1]), ("Days", names[2]), ("Demand (tons)", names[3]),
            ("Road travel minutes", names[4]), ("Roads closed on a day", names[5])])
        files = []
    else:
        body = ("The data are in the attached files: warehouses.csv, locations.csv, days.csv, demand.csv (tons per "
                "location, day and good), roads.csv (minutes per warehouse-location pair), closed_roads.csv.")
        files = names
    message = head + body + "\n\n" + rules + "\n\nEverything you need is here: please propose the model without further questions, then solve it."
    report = [["warehouses opened", r"WH\d\d"], ["daily shipments and stock", r"DAY\d"], ["unmet demand", r"unmet"],
              ["delivery time", r"minute|delivery time"], ["cost breakdown", r"cost"],
              ["Pareto trade-off", r"pareto|trade-?off"], ["re-optimisation advice", r"road (closes|closure)|re-?optimi|if .*suppl"]]
    write_case(folder, message, {"problem": "p10", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": ref["goal"] if ref["optimal"] else None, "known_feasible": ref["goal"],
                                 "bound": ref["bound"], "sense": "minimize", "reference_unmet": ref["unmet"],
                                 "report": report, "files": files})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    """From the shipments (warehouse, location, day, good) and the warehouses that receive anything, the stock
    and every rule are recomputed from the files; unmet = demand - delivered."""
    wh = {r["id"]: r for r in read_csv(folder / "warehouses.csv")}
    loc = {r["id"]: r for r in read_csv(folder / "locations.csv")}
    days = sorted(read_csv(folder / "days.csv"), key=lambda r: int(r["order"]))
    D = [r["id"] for r in days]
    dem = {(r["location"], r["day"], r["good"]): float(r["tons"]) for r in read_csv(folder / "demand.csv")}
    G = sorted({g for _, _, g in dem})
    mins = {(r["warehouse"], r["location"]): float(r["minutes"]) for r in read_csv(folder / "roads.csv")}
    closed = {(r["warehouse"], r["location"], r["day"]) for r in read_csv(folder / "closed_roads.csv")}
    msg = (folder / "message.txt").read_text(encoding="utf-8")
    k = int(re.search(r"open at most (\d+) warehouses", msg).group(1))
    ship: dict[tuple, float] = {}
    opened: set[str] = set()
    for r in export_rows(export_csv):
        keys = [r.get(f"key{i}") for i in range(1, 5)]
        if keys[0] in wh and keys[1] in loc and keys[2] in D and keys[3] in G:
            ship[tuple(keys)] = ship.get(tuple(keys), 0.0) + float(r["value"])
        elif keys[0] in wh and not keys[1] and float(r["value"]) > 0.5 and "open" in r["decision"].lower():
            opened.add(keys[0])
    if not ship:
        return ["no shipment decision over (warehouse, location, day, good) in the export"]
    bad: list[str] = []
    opened |= {w for (w, _, _, _), q in ship.items() if q > 1e-6}
    if len(opened) > k:
        bad.append(f"{len(opened)} warehouses used, at most {k}")
    cost = sum(float(wh[w]["opening_cost"]) for w in opened)
    for w in wh:
        stock = {g: 0.0 for g in G}
        for t in D:
            out = 0.0
            for g in G:
                intake = float(wh[w][f"intake_{g.lower()}_tons_per_day"]) if w in opened else 0.0
                sent = sum(q for (ww, _, tt, gg), q in ship.items() if ww == w and tt == t and gg == g)
                stock[g] += intake - sent
                out += sent
                if stock[g] < -1e-6:
                    bad.append(f"{w} {t} {g}: ships {sent:g} with only {stock[g] + sent:g} on hand")
            if sum(stock.values()) > float(wh[w]["capacity_tons"]) + 1e-6:
                bad.append(f"{w} {t}: stock {sum(stock.values()):g} above capacity {wh[w]['capacity_tons']}")
            if out > float(wh[w]["truck_loads_per_day"]) * TRUCK_TONS + 1e-6:
                bad.append(f"{w} {t}: ships {out:g} tons, above its truck loads")
    for (w, l, t, g), q in ship.items():
        if q > 1e-6 and (w, l, t) in closed:
            bad.append(f"{w}->{l} on {t} uses a closed road ({q:g})")
        cost += q * (W_MINUTE * mins[(w, l)] + TRUCK_COST / TRUCK_TONS)
    for (l, t, g), need in dem.items():
        got = sum(q for (_, ll, tt, gg), q in ship.items() if ll == l and tt == t and gg == g)
        if got > need + 1e-6:
            bad.append(f"{l} {t} {g}: delivered {got:g} above demand {need:g}")
        cost += max(0.0, need - got) * (W_PRIORITY if loc[l]["priority"] == "yes" else W_UNMET)
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:220])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
