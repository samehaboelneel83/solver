"""Hidden problem 15: chemical plant product mix with process routes, intermediates and unit capacities (LP).

    python -m bench.hidden.h15_chemicals gen [S M]
    python -m bench.hidden.h15_chemicals check <case> <export.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (2, 2, 3, 2), "M": (6, 14, 8, 5)}  # intermediates, finals, raw materials, units
OUT = Path(__file__).parent / "cases" / "h15"
INTER = ["ETHYLENE", "PROPYLENE", "BENZENE", "METHANOL", "CHLORINE", "AMMONIA"]
FINAL = ["POLYETHYLENE", "POLYPROPYLENE", "STYRENE", "ACETIC_ACID", "PVC", "UREA", "FORMALDEHYDE", "MTBE",
         "NITRIC_ACID", "CUMENE", "GLYCOL", "ACRYLONITRILE", "PHENOL", "CAPROLACTAM"]
RAW = ["NAPHTHA", "ETHANE", "NATURAL_GAS", "PROPANE", "SALT", "OXYGEN", "REFORMATE", "SULFUR"]
UNITS = ["CRACKER", "REACTOR", "DISTILLATION", "POLYMERISER", "SYNTHESIS"]


def make(size: str, seed: int = 15) -> dict:
    ni, nf, nr, nu = SIZES[size]
    rng = np.random.default_rng(seed * 23 + nf)
    I, F, R, U = INTER[:ni], FINAL[:nf], RAW[:nr], UNITS[:nu]
    raws = {r: dict(cost=int(rng.integers(150, 600)), avail=int(rng.integers(20, 80)) * 100) for r in R}
    routes = []
    prods = {}
    for p in I + F:
        final = p in F
        n_routes = 1 + int(rng.random() < 0.5)
        for k in range(n_routes):
            rid = f"{p}-R{k + 1}"
            ins = {}
            for r in rng.choice(R, 1 + int(rng.random() < 0.5), replace=False):
                ins[str(r)] = round(float(rng.uniform(0.3, 1.0)), 2)
            if final:
                for q in rng.choice(I, 1 + int(rng.random() < 0.3), replace=False):
                    ins[str(q)] = round(float(rng.uniform(0.4, 0.9)), 2)
            hrs = {}
            for u in rng.choice(U, 1 + int(rng.random() < 0.6), replace=False):
                hrs[str(u)] = round(float(rng.uniform(0.05, 0.3)), 3)
            routes.append(dict(id=rid, product=p, var=int(rng.integers(20, 120)), ins=ins, hrs=hrs))
        mat = np.mean([sum(raws[r]["cost"] * v for r, v in rt["ins"].items() if r in raws)
                       for rt in routes if rt["product"] == p])
        if final:
            price = int(mat + 900 + rng.integers(0, 900))
            mx = int(rng.integers(10, 40)) * 100
            mn = int(rng.integers(0, 4)) * 100 if rng.random() < 0.5 else 0
        else:
            price = int(mat + 250 + rng.integers(0, 300))
            mx = int(rng.integers(0, 10)) * 100
            mn = 0
        prods[p] = dict(price=price, min=mn, max=mx)
    units = {u: int(rng.integers(30, 90)) * 10 for u in U}
    return dict(I=I, F=F, R=R, U=U, raws=raws, routes=routes, prods=prods, units=units)


def solve(d: dict, seconds: float) -> dict:
    from scipy.optimize import linprog

    routes, prods = d["routes"], d["prods"]
    n = len(routes)
    # profit per ton made on a route = price of its product - var cost - raw costs - (value of intermediates used,
    # counted through the net sales of those products)
    c = np.zeros(n)
    for j, rt in enumerate(routes):
        c[j] = prods[rt["product"]]["price"] - rt["var"]
        for inp, a in rt["ins"].items():
            if inp in d["raws"]:
                c[j] -= a * d["raws"][inp]["cost"]
            else:
                c[j] -= a * prods[inp]["price"]
    A, b = [], []
    for p, pr in prods.items():
        net = np.array([(1 if rt["product"] == p else 0) - rt["ins"].get(p, 0.0) for rt in routes])
        A.append(net); b.append(pr["max"])
        A.append(-net); b.append(-pr["min"])
    for r, rr in d["raws"].items():
        A.append(np.array([rt["ins"].get(r, 0.0) for rt in routes])); b.append(rr["avail"])
    for u, h in d["units"].items():
        A.append(np.array([rt["hrs"].get(u, 0.0) for rt in routes])); b.append(h)
    res = linprog(-c, A_ub=np.array(A), b_ub=b, bounds=(0, None), method="highs", options={"time_limit": seconds})
    if res.status != 0:
        return {"feasible": False}
    exp = ["decision,key1,value"]
    for rt, x in zip(routes, res.x):
        if x > 1e-9:
            exp.append(f"make,{rt['id']},{x:.9f}")
    return {"feasible": True, "goal": -float(res.fun), "bound": -float(res.fun), "optimal": True,
            "export": "\n".join(exp) + "\n"}


def instance(size: str) -> tuple[dict, dict]:
    for seed in range(15, 90):
        d = make(size, seed)
        ref = solve(d, 120)
        if ref["feasible"] and ref["goal"] > 0:
            return d, ref
    raise RuntimeError("no feasible instance")


def write(size: str) -> Path:
    d, ref = instance(size)
    folder = OUT / size
    write_csv(folder / "products.csv", ["product", "price_per_ton", "min_sales_tons", "max_sales_tons"],
              [(p, v["price"], v["min"], v["max"]) for p, v in d["prods"].items()])
    write_csv(folder / "raw_materials.csv", ["raw_material", "cost_per_ton", "available_tons"],
              [(r, v["cost"], v["avail"]) for r, v in d["raws"].items()])
    write_csv(folder / "units.csv", ["unit", "hours_available"], list(d["units"].items()))
    write_csv(folder / "routes.csv", ["route", "product", "variable_cost_per_ton"],
              [(rt["id"], rt["product"], rt["var"]) for rt in d["routes"]])
    write_csv(folder / "route_inputs.csv", ["route", "input", "tons_per_ton"],
              [(rt["id"], k, v) for rt in d["routes"] for k, v in rt["ins"].items()])
    write_csv(folder / "route_hours.csv", ["route", "unit", "hours_per_ton"],
              [(rt["id"], k, v) for rt in d["routes"] for k, v in rt["hrs"].items()])
    names = ["products.csv", "raw_materials.csv", "units.csv", "routes.csv", "route_inputs.csv", "route_hours.csv"]
    rules = ("Each route makes one product; making one ton on a route consumes the listed inputs (tons of raw "
             "material or of another product per ton made) and the listed hours on the plant units. Some products "
             "are intermediates that other routes consume. Rules (all hard, quantities in tons, fractions allowed): "
             "the net output of a product (tons made on all its routes minus tons consumed as input by other routes) "
             "is what we sell, and it must be between the product's min_sales_tons (contracts) and max_sales_tons "
             "(the market); nothing can be stored or thrown away. Raw materials used are at most the tons available. "
             "Hours used on a unit are at most its hours available this month. Goal, as large as possible, in USD: "
             "the profit = sales (net output times price per ton) minus raw material cost (tons used times cost per "
             "ton) minus processing cost (tons made on a route times its variable cost per ton). Report the tons made "
             "on each route, the tons sold of each product, the raw material and unit hours used against what is "
             "available, the total profit, and which units or materials limit the profit.")
    head = ('Please build this in a new workspace called "{workspace}". Call the problem "Plant product mix". '
            f"Our chemical plant must decide next month's production of {len(d['prods'])} products, each made by one "
            "or two process routes.\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in zip(
            ["Products (price in USD per ton)", "Raw materials (cost in USD per ton)", "Plant units",
             "Routes (variable cost in USD per ton made)", "Route inputs (per ton made)",
             "Route hours (per ton made)"], names))
        files = []
    else:
        body = ("The data are in the attached files: products.csv, raw_materials.csv, units.csv, routes.csv (which "
                "product each route makes and its variable cost), route_inputs.csv (inputs per ton made), "
                "route_hours.csv (unit hours per ton made).")
        files = names
    message = (head + body + "\n\n" + rules +
               "\n\nEverything you need is here: please propose the model without further questions, then solve it.")
    write_case(folder, message, {})
    cost = float(check(folder, ref["export"])[-1].split()[1])
    lead = f"{cost:,.0f}"[:-2].replace(",", ",?")
    report = [["tons per route", r"[A-Z_]+-R\d[^\n]{0,40}\d"],
              ["tons sold per product", r"(" + "|".join(d["prods"]) + r")[^\n]{0,60}\d"],
              ["resource use", r"hours|available"],
              ["total profit", lead + r"\d\d"],
              ["limiting resources", r"\bbind|limit|bottleneck|tight"]]
    write_case(folder, message, {"problem": "h15", "size": size, "kind": "exact", "goal": cost,
                                 "known_feasible": cost, "bound": cost, "sense": "maximize",
                                 "report": report, "files": files})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    prods = {r["product"]: r for r in read_csv(folder / "products.csv")}
    raws = {r["raw_material"]: r for r in read_csv(folder / "raw_materials.csv")}
    units = {r["unit"]: r for r in read_csv(folder / "units.csv")}
    routes = {r["route"]: r for r in read_csv(folder / "routes.csv")}
    ins: dict[str, dict[str, float]] = {}
    for r in read_csv(folder / "route_inputs.csv"):
        ins.setdefault(r["route"], {})[r["input"]] = float(r["tons_per_ton"])
    hrs: dict[str, dict[str, float]] = {}
    for r in read_csv(folder / "route_hours.csv"):
        hrs.setdefault(r["route"], {})[r["unit"]] = float(r["hours_per_ton"])
    by: dict[str, dict[str, float]] = {}
    for r in export_rows(export_csv):
        a, b, c = r.get("key1") or "", r.get("key2") or "", r.get("key3") or ""
        if c:
            continue
        if a in routes and not b:
            rid = a
        elif a in prods and b in routes and routes[b]["product"] == a:
            rid = b
        elif b in prods and a in routes and routes[a]["product"] == b:
            rid = a
        else:
            continue
        by.setdefault(r["decision"], {})[rid] = float(r["value"])
    if not by:
        return ["no decision over the routes in the export"]
    name = max(by, key=lambda n: (any(v not in (0.0, 1.0) for v in by[n].values()), len(by[n])))
    x = by[name]
    bad: list[str] = []
    net = {p: 0.0 for p in prods}
    raw_use = {r: 0.0 for r in raws}
    unit_use = {u: 0.0 for u in units}
    profit = 0.0
    for rid, q in x.items():
        if q < -1e-6:
            bad.append(f"{rid}: negative amount {q:g}")
        net[routes[rid]["product"]] += q
        profit -= q * float(routes[rid]["variable_cost_per_ton"])
        for inp, a in ins.get(rid, {}).items():
            if inp in raws:
                raw_use[inp] += a * q
            else:
                net[inp] -= a * q
        for u, h in hrs.get(rid, {}).items():
            unit_use[u] += h * q
    for p, r in prods.items():
        if net[p] < float(r["min_sales_tons"]) - 1e-4 or net[p] > float(r["max_sales_tons"]) + 1e-4:
            bad.append(f"{p}: net output {net[p]:g} outside {r['min_sales_tons']}..{r['max_sales_tons']}")
        profit += net[p] * float(r["price_per_ton"])
    for m, r in raws.items():
        if raw_use[m] > float(r["available_tons"]) + 1e-4:
            bad.append(f"{m}: {raw_use[m]:g} t used, {r['available_tons']} available")
        profit -= raw_use[m] * float(r["cost_per_ton"])
    for u, r in units.items():
        if unit_use[u] > float(r["hours_available"]) + 1e-4:
            bad.append(f"{u}: {unit_use[u]:g} h used, {r['hours_available']} available")
    return bad + [f"COST {profit:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
