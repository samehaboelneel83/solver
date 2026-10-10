"""Hidden problem 13: raw-material purchasing with all-units quantity discounts and supplier order costs (MILP).

    python -m bench.hidden.h13_purchasing gen [S M]
    python -m bench.hidden.h13_purchasing check <case> <export.csv>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (3, 4), "M": (8, 25)}  # suppliers, materials
OUT = Path(__file__).parent / "cases" / "h13"


def make(size: str, seed: int = 13) -> dict:
    ns, nm = SIZES[size]
    rng = np.random.default_rng(seed * 17 + nm)
    S = [f"SUP{i + 1}" for i in range(ns)]
    M = [f"MAT{j + 1:02d}" for j in range(nm)]
    need = rng.integers(10, 60, nm) * 10
    volume = np.round(rng.uniform(0.5, 3.0, nm), 1)
    base = rng.integers(20, 200, nm)
    offers = {}  # (s, m) -> [(min_qty, price)]
    for j in range(nm):
        sup = rng.choice(ns, max(2, int(round(ns * rng.uniform(0.4, 0.8)))), replace=False)
        for i in sup:
            p = base[j] * rng.uniform(0.85, 1.2)
            brackets = [(1, round(p, 2))]
            q = int(need[j] * rng.uniform(0.3, 0.6) / 10) * 10 or 10
            for _ in range(int(rng.integers(1, 3))):
                p *= rng.uniform(0.86, 0.95)
                brackets.append((q, round(p, 2)))
                q = int(q * rng.uniform(1.5, 2.2) / 10) * 10
            offers[(S[i], M[j])] = brackets
    tot = int(need.sum())
    cap = {s: int(tot / ns * rng.uniform(0.7, 1.3) / 10) * 10 for s in S}
    fixed = {s: int(rng.integers(5, 40)) * 100 for s in S}
    minval = {s: int(rng.integers(10, 60)) * 1000 for s in S}
    storage = int(float((need * volume).sum()) * 1.12)
    return dict(S=S, M=M, need=need, volume=volume, offers=offers, cap=cap, fixed=fixed, minval=minval,
                storage=storage)


def solve(d: dict, seconds: float) -> dict:
    from scipy.optimize import Bounds, LinearConstraint, milp

    S, M, offers = d["S"], d["M"], d["offers"]
    idx = {}
    for (s, m), br in offers.items():
        for k in range(len(br)):
            idx[("q", s, m, k)] = len(idx)
            idx[("y", s, m, k)] = len(idx)
    for s in S:
        idx[("z", s)] = len(idx)
    n = len(idx)
    c = np.zeros(n)
    integ = np.ones(n)
    lo, hi = np.zeros(n), np.full(n, np.inf)
    rows, rl, rh = [], [], []

    def row(terms, a, b):
        r = np.zeros(n)
        for j, v in terms:
            r[j] += v
        rows.append(r); rl.append(a); rh.append(b)

    for (s, m), br in offers.items():
        for k, (mq, price) in enumerate(br):
            q, y = idx[("q", s, m, k)], idx[("y", s, m, k)]
            c[q] = price
            hi[y] = 1
            top = br[k + 1][0] - 1 if k + 1 < len(br) else d["cap"][s]
            row([(q, 1), (y, -mq)], 0, np.inf)
            row([(q, 1), (y, -top)], -np.inf, 0)
        row([(idx[("y", s, m, k)], 1) for k in range(len(br))], -np.inf, 1)
    for s in S:
        z = idx[("z", s)]
        c[z] = d["fixed"][s]
        hi[z] = 1
        qs = [(idx[("q", ss, m, k)], 1) for (ss, m), br in offers.items() if ss == s for k in range(len(br))]
        row(qs + [(z, -d["cap"][s])], -np.inf, 0)
        val = [(idx[("q", ss, m, k)], br[k][1]) for (ss, m), br in offers.items() if ss == s for k in range(len(br))]
        row(val + [(z, -d["minval"][s])], 0, np.inf)
    for j, m in enumerate(M):
        row([(idx[("q", s, mm, k)], 1) for (s, mm), br in offers.items() if mm == m for k in range(len(br))],
            float(d["need"][j]), np.inf)
    vol = {m: float(d["volume"][j]) for j, m in enumerate(M)}
    row([(idx[("q", s, m, k)], vol[m]) for (s, m), br in offers.items() for k in range(len(br))], -np.inf, d["storage"])
    res = milp(c, constraints=LinearConstraint(np.array(rows), rl, rh), integrality=integ, bounds=Bounds(lo, hi),
               options={"time_limit": seconds, "disp": False, "mip_rel_gap": 0})
    if res.x is None:
        return {"feasible": False}
    exp = ["decision,key1,key2,value"]
    for (s, m), br in offers.items():
        q = sum(res.x[idx[("q", s, m, k)]] for k in range(len(br)))
        if q > 0.5:
            exp.append(f"buy,{s},{m},{round(q)}")
    return {"feasible": True, "goal": float(res.fun), "bound": float(getattr(res, "mip_dual_bound", None) or res.fun),
            "optimal": res.status == 0, "export": "\n".join(exp) + "\n"}


def instance(size: str) -> tuple[dict, dict]:
    for seed in range(13, 80):
        d = make(size, seed)
        ref = solve(d, 200)
        if ref["feasible"]:
            return d, ref
    raise RuntimeError("no feasible instance")


def write(size: str) -> Path:
    d, ref = instance(size)
    folder = OUT / size
    write_csv(folder / "materials.csv", ["material", "required_units", "volume_m3_per_unit"],
              [(m, int(d["need"][j]), float(d["volume"][j])) for j, m in enumerate(d["M"])])
    write_csv(folder / "suppliers.csv", ["supplier", "order_cost", "min_order_value", "max_units"],
              [(s, d["fixed"][s], d["minval"][s], d["cap"][s]) for s in d["S"]])
    write_csv(folder / "price_breaks.csv", ["supplier", "material", "from_units", "unit_price"],
              [(s, m, q, p) for (s, m), br in sorted(d["offers"].items()) for q, p in br])
    names = ["materials.csv", "suppliers.csv", "price_breaks.csv"]
    rules = (f"Rules (all hard): for every material we buy at least the required units in total (buying more is "
             "allowed). A material can be bought only from suppliers that quote it in the price list. Quantities "
             "are whole units. Discounts are all-units: the unit price of an order line (one supplier, one material) "
             "is the price of the highest from_units row that the line's quantity reaches, and that price applies "
             "to every unit of the line. A supplier we buy anything from charges its order cost once, and the value "
             "of everything we buy from it (quantity times unit price, before the order cost) must be at least its "
             "min_order_value. A supplier sells us at most max_units units in total over all materials. Everything "
             f"bought must fit in our store: the total volume (units times volume per unit) is at most "
             f"{d['storage']:,} m3. Goal, as small as possible, in EGP: the value of all order lines plus the order "
             "costs of the suppliers used. Report the quantity bought per supplier and material with its unit "
             "price, the suppliers used, the total cost split into material value and order costs, where we buy "
             "above the requirement to reach a discount, and the storage volume used.")
    head = ('Please build this in a new workspace called "{workspace}". Call the problem "Material purchasing". '
            f"Our plant must buy next month's {len(d['M'])} raw materials from {len(d['S'])} suppliers that "
            "offer quantity discounts.\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in zip(
            ["Materials", "Suppliers (money in EGP)", "Price list (EGP per unit from the given quantity up)"], names))
        files = []
    else:
        body = ("The data are in the attached files: materials.csv (required units and volume per unit), "
                "suppliers.csv (order cost, minimum order value and maximum units per supplier), price_breaks.csv "
                "(the quantity-discount price list per supplier and material).")
        files = names
    message = (head + body + "\n\n" + rules +
               "\n\nEverything you need is here: please propose the model without further questions, then solve it.")
    write_case(folder, message, {})
    cost = float(check(folder, ref["export"])[-1].split()[1])
    lead = f"{cost:,.0f}"[:-2].replace(",", ",?")
    report = [["quantity per supplier and material", r"SUP\d\W+.{0,40}MAT\d\d|MAT\d\d\W+.{0,40}SUP\d"],
              ["suppliers used", r"suppliers? used|SUP\d"],
              ["total cost", lead + r"\d\d"],
              ["order costs", r"order cost"],
              ["buying above requirement for a discount", r"discount|price break"],
              ["storage used", r"storage|m3|volume"]]
    write_case(folder, message, {"problem": "h13", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": cost if ref["optimal"] else None, "known_feasible": cost,
                                 "bound": cost if ref["optimal"] else ref["bound"], "sense": "minimize", "report": report, "files": files})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    mats = {r["material"]: r for r in read_csv(folder / "materials.csv")}
    sups = {r["supplier"]: r for r in read_csv(folder / "suppliers.csv")}
    br: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for r in read_csv(folder / "price_breaks.csv"):
        br.setdefault((r["supplier"], r["material"]), []).append((float(r["from_units"]), float(r["unit_price"])))
    msg = (folder / "message.txt").read_text(encoding="utf-8")
    storage = float(re.search(r"is at most ([\d,]+) m3", msg).group(1).replace(",", ""))
    by: dict[str, dict[tuple, float]] = {}
    for r in export_rows(export_csv):
        a, b = r.get("key1") or "", r.get("key2") or ""
        if a in mats and b in sups:
            a, b = b, a
        if a not in sups or b not in mats:
            continue
        cell = by.setdefault(r["decision"], {})
        # A model may split a line by price bracket (a further key): the line's quantity is the sum.
        cell[(a, b)] = cell.get((a, b), 0.0) + float(r["value"])
    if not by:
        return ["no decision over (supplier, material) in the export"]
    name = max(by, key=lambda n: (any(v not in (0.0, 1.0) for v in by[n].values()), len(by[n])))
    x = by[name]
    bad: list[str] = []
    cost = 0.0
    got = {m: 0.0 for m in mats}
    units = {s: 0.0 for s in sups}
    value = {s: 0.0 for s in sups}
    vol = 0.0
    for (s, m), q in x.items():
        if abs(q) <= 1e-9:
            continue
        if q < -1e-6 or abs(q - round(q)) > 1e-6:
            bad.append(f"{s} {m}: quantity {q:g} is not a whole number >= 0")
        if (s, m) not in br:
            bad.append(f"{s} does not quote {m} ({q:g} bought)")
            continue
        reached = [(fq, p) for fq, p in br[(s, m)] if fq <= q + 1e-9] or [min(br[(s, m)])]
        price = max(reached)[1]
        value[s] += q * price
        units[s] += q
        got[m] += q
        vol += q * float(mats[m]["volume_m3_per_unit"])
    for m, r in mats.items():
        if got[m] < float(r["required_units"]) - 1e-6:
            bad.append(f"{m}: {got[m]:g} bought, {r['required_units']} required")
    for s, r in sups.items():
        if units[s] > 1e-9:
            cost += value[s] + float(r["order_cost"])
            if value[s] < float(r["min_order_value"]) - 1e-6:
                bad.append(f"{s}: order value {value[s]:,.2f} below its minimum {r['min_order_value']}")
            if units[s] > float(r["max_units"]) + 1e-6:
                bad.append(f"{s}: {units[s]:g} units, above its {r['max_units']}")
    if vol > storage + 1e-6:
        bad.append(f"volume {vol:g} m3 above the store's {storage:g}")
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
