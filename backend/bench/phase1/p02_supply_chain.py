"""Problem 2: multi-warehouse supply chain (transportation with restrictions).

    python -m bench.phase1.p02_supply_chain gen        # writes bench/phase1/cases/p02/{S,M,L}
    python -m bench.phase1.p02_supply_chain check <case> <export.csv>

Warehouses have stock and a shipping capacity; customers have demand; each route has a cost per unit; some
routes are closed; some customers may be served only from approved warehouses. Least total shipping cost, all
demand met. A "current plan" (the best plan at last year's route prices, paid at this year's) is written too, so
the saving can be compared. Shipments are whole units; the data are whole numbers, so the
linear program's optimum is whole and exact.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import HERE, csv_text, decision_over, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (3, 8), "M": (5, 30), "L": (15, 300)}
OUT = HERE / "cases" / "p02"


def make(size: str, seed: int = 2) -> dict:
    nw, nc = SIZES[size]
    rng = np.random.default_rng(seed + nw * 1000 + nc)
    W = [f"W{i + 1:02d}" for i in range(nw)]
    C = [f"C{j + 1:03d}" for j in range(nc)]
    demand = rng.integers(20, 120, nc)
    total = int(demand.sum())
    # Room for about a fifth more than the demand in all: tight enough that the cheapest warehouses fill up.
    stock = np.rint(total * 1.35 / nw * rng.uniform(0.7, 1.3, nw)).astype(int)
    shipcap = np.rint(total * 1.25 / nw * rng.uniform(0.7, 1.3, nw)).astype(int)
    while min(stock.sum(), shipcap.sum()) < total * 1.15:
        stock = stock + 5
        shipcap = shipcap + 5
    wx, wy = rng.uniform(0, 100, nw), rng.uniform(0, 100, nw)
    cx, cy = rng.uniform(0, 100, nc), rng.uniform(0, 100, nc)
    cost = np.rint(5 + np.hypot(wx[:, None] - cx[None, :], wy[:, None] - cy[None, :]) * rng.uniform(0.8, 1.2, (nw, nc)))
    closed = rng.random((nw, nc)) < 0.15
    approved = {}
    for j in rng.choice(nc, max(1, nc // 5), replace=False):
        approved[j] = set(rng.choice(nw, max(1, nw // 2), replace=False).tolist())
    allowed = ~closed
    for j, ok in approved.items():
        for i in range(nw):
            if i not in ok:
                allowed[i, j] = False
    for j in range(nc):  # every customer keeps at least one way in
        if not allowed[:, j].any():
            i = int(np.argmin(cost[:, j]))
            allowed[i, j] = True
            closed[i, j] = False
            if j in approved:
                approved[j].add(i)
    return dict(W=W, C=C, demand=demand, stock=stock, shipcap=shipcap, cost=cost, closed=closed,
                approved=approved, allowed=allowed)


def solve(d: dict, cost=None) -> tuple[float, dict]:
    """The least-cost plan (at `cost`, default this year's), and its cost at this year's prices."""
    from scipy.optimize import linprog

    W, C, allowed = d["W"], d["C"], d["allowed"]
    use = d["cost"] if cost is None else cost
    pairs = [(i, j) for i in range(len(W)) for j in range(len(C)) if allowed[i, j]]
    c = np.array([use[i, j] for i, j in pairs])
    A_eq = np.zeros((len(C), len(pairs)))
    A_ub = np.zeros((len(W), len(pairs)))
    for k, (i, j) in enumerate(pairs):
        A_eq[j, k] = 1
        A_ub[i, k] = 1
    cap = np.minimum(d["stock"], d["shipcap"])
    r = linprog(c, A_ub=A_ub, b_ub=cap, A_eq=A_eq, b_eq=d["demand"], bounds=(0, None), method="highs")
    assert r.status == 0, r.message
    plan = {(W[i], C[j]): round(float(x)) for (i, j), x in zip(pairs, r.x) if x > 1e-6}
    return round(sum(q * d["cost"][W.index(w), C.index(c)] for (w, c), q in plan.items()), 6), plan


def current_plan(d: dict) -> tuple[float, dict]:
    """The plan in use: the best one at last year's route prices, paid at this year's."""
    rng = np.random.default_rng(99)
    return solve(d, cost=np.rint(d["cost"] * rng.uniform(0.3, 1.7, d["cost"].shape)))


def write(size: str) -> Path:
    d = make(size)
    folder = OUT / size
    W, C = d["W"], d["C"]
    write_csv(folder / "warehouses.csv", ["id", "stock_units", "shipping_capacity_units"],
              [(w, int(s), int(k)) for w, s, k in zip(W, d["stock"], d["shipcap"])])
    write_csv(folder / "customers.csv", ["id", "demand_units"], [(c, int(q)) for c, q in zip(C, d["demand"])])
    write_csv(folder / "routes.csv", ["warehouse", "customer", "cost_per_unit", "open"],
              [(W[i], C[j], int(d["cost"][i, j]), "no" if d["closed"][i, j] else "yes")
               for i in range(len(W)) for j in range(len(C))])
    write_csv(folder / "approved.csv", ["customer", "warehouse"],
              [(C[j], W[i]) for j, ok in sorted(d["approved"].items()) for i in sorted(ok)])
    best, plan = solve(d)
    now, now_plan = current_plan(d)
    write_csv(folder / "current_plan.csv", ["warehouse", "customer", "units"],
              [(w, c, int(q)) for (w, c), q in sorted(now_plan.items())])
    rules = ("Rules: every customer receives exactly its demand. A warehouse ships no more than its stock and no "
             "more than its shipping capacity, in total over all its customers. A route marked open = no cannot be "
             "used. A customer listed in the approved list may be served only from the warehouses listed for it; "
             "customers not in that list may be served from any warehouse. A customer may be served from several "
             "warehouses. Shipments are whole units. Goal: the lowest total shipping cost (units on a route times "
             "its cost per unit). Then compare that cost with our current plan, whose cost is "
             f"{now:,.0f}, and say which warehouses are bottlenecks.")
    head = (f'Please build this in a new workspace called "{{workspace}}". Call the problem "Distribution plan". '
            f"We ship from {len(W)} warehouses to {len(C)} customers and need the cheapest shipping plan.\n\n")
    if size == "S":
        body = "\n\n".join([
            "Warehouses (stock in units, shipping capacity in units):\n" + csv_text(folder / "warehouses.csv"),
            "Customers (demand in units):\n" + csv_text(folder / "customers.csv"),
            "Routes (cost per unit; open = no means the route is unavailable):\n" + csv_text(folder / "routes.csv"),
            "Approved warehouses (only for the customers listed):\n" + csv_text(folder / "approved.csv")])
        files = []
    else:
        body = ("The data are in the attached files: warehouses.csv (stock and shipping capacity per warehouse), "
                "customers.csv (demand per customer), routes.csv (cost per unit for every warehouse-customer pair, "
                "and whether the route is open), approved.csv (for the customers listed, the only warehouses "
                "allowed to serve them).")
        files = ["warehouses.csv", "customers.csv", "routes.csv", "approved.csv"]
    message = head + body + "\n\n" + rules + "\n\nEverything you need is here: please propose the model without further questions, then solve it."
    goal_txt = f"{best:,.0f}".replace(",", ",?")
    report = [  # the problem's expected outputs, as what the final answer must contain
        ["shipment quantities per warehouse-customer pair", r"W0\d\W+.{0,40}C0\d\d.{0,40}\d"],
        ["total transportation cost", goal_txt],
        ["warehouse utilization", r"utili[sz]|capacity used|% of (its )?(capacity|stock)|full"],
        ["customer demand fulfilment", r"demand (is |are )?(fully )?(met|fulfil|satisf)|every customer|all (customers|demand)"],
        ["bottlenecks", r"bottleneck"],
        ["comparison with the current plan", r"current plan|sav(e|ing)|" + f"{now:,.0f}".replace(",", ",?")],
    ]
    write_case(folder, message, {"problem": "p02", "size": size, "kind": "exact", "goal": best, "sense": "minimize",
                                 "report": report,
                                 "current_plan_cost": now, "files": files,
                                 "routes": len(W) * len(C), "open_routes": int(d["allowed"].sum())})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    """Every hard rule of the case, on the exported plan, against the data files alone."""
    wh = {r["id"]: r for r in read_csv(folder / "warehouses.csv")}
    cu = {r["id"]: int(r["demand_units"]) for r in read_csv(folder / "customers.csv")}
    routes = {(r["warehouse"], r["customer"]): r for r in read_csv(folder / "routes.csv")}
    approved: dict[str, set[str]] = {}
    for r in read_csv(folder / "approved.csv"):
        approved.setdefault(r["customer"], set()).add(r["warehouse"])
    name, ship = decision_over(export_rows(export_csv), set(wh), set(cu))
    if not name:
        return ["no decision over (warehouse, customer) in the export"]
    bad: list[str] = []
    got = {c: 0.0 for c in cu}
    out = {w: 0.0 for w in wh}
    cost = 0.0
    for (w, c), q in ship.items():
        if q < -1e-6:
            bad.append(f"{w}->{c} negative ({q})")
        if q > 1e-6:
            if routes[(w, c)]["open"] != "yes":
                bad.append(f"{w}->{c} uses a closed route ({q})")
            if c in approved and w not in approved[c]:
                bad.append(f"{w}->{c} serves {c} from a warehouse not approved for it ({q})")
            if abs(q - round(q)) > 1e-6:
                bad.append(f"{w}->{c} is not a whole number ({q})")
        got[c] += q
        out[w] += q
        cost += q * float(routes[(w, c)]["cost_per_unit"])
    bad += [f"{c} receives {got[c]:g}, demand {d}" for c, d in cu.items() if abs(got[c] - d) > 1e-6]
    for w, r in wh.items():
        limit = min(int(r["stock_units"]), int(r["shipping_capacity_units"]))
        if out[w] > limit + 1e-6:
            bad.append(f"{w} ships {out[w]:g}, above its limit {limit}")
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in SIZES:
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:300])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
