"""Hidden problem h08 (knapsack-like with groups).

    python -m bench.hidden.h08_shelf gen [S M]
    python -m bench.hidden.h08_shelf check <case> <export.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, decision_over, export_rows, read_csv, write_csv
from bench.hidden._util_a import CLOSE, OPEN, Model, export_text, finish, num_re, search

SIZES = {"S": (8, 3, 2), "M": (40, 6, 8)}  # products, shelves, categories
OUT = Path(__file__).parent / "cases" / "h08"
CATS = ["BEVERAGES", "SNACKS", "DAIRY", "BAKERY", "CANNED", "CLEANING", "PERSONAL_CARE", "FROZEN"]


def make(size: str, seed: int = 8) -> dict:
    n, nsh, nc = SIZES[size]
    rng = np.random.default_rng(seed * 122949829 + n)
    P = [f"SKU{i + 1:03d}" for i in range(n)]
    SH = [f"SH{i + 1:02d}" for i in range(nsh)]
    cats = CATS[:nc]
    cat = {p: cats[i % nc] for i, p in enumerate(P)}
    width = {p: int(rng.integers(8, 31)) for p in P}
    upf = {p: 4 * int(rng.integers(1, 4)) for p in P}
    demand = {p: int(rng.integers(10, 81)) for p in P}
    margin = {p: int(rng.integers(2, 26)) for p in P}
    must = {p: bool(rng.random() < 0.2) for p in P}
    for p in P:  # a must-carry product fits one facing on any shelf
        if must[p]:
            demand[p] = max(demand[p], int(upf[p] * 1.25))
    maxf = {p: int(rng.integers(2, 9)) for p in P}
    vis = {s: [0.75, 1.0, 1.25][i % 3] for i, s in enumerate(SH)}
    total_w = sum(width[p] * 3 for p in P) * 0.45
    shw = {s: int(round(total_w / nsh * rng.uniform(0.8, 1.2), -1)) for s in SH}
    per_cat = {c: sum(1 for p in P if cat[p] == c) for c in cats}
    maxp = {c: max(sum(1 for p in P if cat[p] == c and must[p]), int(np.ceil(per_cat[c] * 0.6))) for c in cats}
    return dict(P=P, SH=SH, cats=cats, cat=cat, width=width, upf=upf, demand=demand, margin=margin, must=must,
                maxf=maxf, vis=vis, shw=shw, maxp=maxp)


def solve(d: dict, seconds: float = 300):
    m = Model()
    P, SH = d["P"], d["SH"]
    for p in P:
        for s in SH:
            u = d["upf"][p] * d["vis"][s]
            top = min(d["maxf"][p], int(d["demand"][p] // u + 1e-9))
            m.var(("f", p, s), 0, top, integer=True, cost=d["margin"][p] * u)
            m.var(("y", p, s), 0, 1 if top > 0 else 0, integer=True)
            m.add([(("f", p, s), 1), (("y", p, s), -top)], hi=0)
            m.add([(("f", p, s), 1), (("y", p, s), -1)], lo=0)
        m.add([(("y", p, s), 1) for s in SH], lo=1 if d["must"][p] else 0, hi=1)
        m.add([(("f", p, s), 1) for s in SH], hi=d["maxf"][p])
    for s in SH:
        m.add([(("f", p, s), d["width"][p]) for p in P], hi=d["shw"][s])
    for c in d["cats"]:
        m.add([(("y", p, s), 1) for p in P if d["cat"][p] == c for s in SH], hi=d["maxp"][c])
    r = m.solve(maximize=True, seconds=seconds)
    if r is None:
        return None
    rows = [("facings", (p, s), r["x"][("f", p, s)]) for p in P for s in SH if r["x"][("f", p, s)] > 0.5]
    return {"goal": r["obj"], "bound": r["bound"], "optimal": r["optimal"], "export": export_text(rows)}


def write(size: str) -> Path:
    seed, d, ref = search(make, solve, size, 8, 280)
    folder = OUT / size
    P = d["P"]
    write_csv(folder / "products.csv", ["product", "category", "width_cm", "units_per_facing_per_week", "weekly_demand_units",
                                        "margin_egp_per_unit", "must_carry", "max_facings"],
              [(p, d["cat"][p], d["width"][p], d["upf"][p], d["demand"][p], d["margin"][p],
                "yes" if d["must"][p] else "no", d["maxf"][p]) for p in P])
    write_csv(folder / "shelves.csv", ["shelf", "width_cm", "visibility_factor"], [(s, d["shw"][s], d["vis"][s]) for s in d["SH"]])
    write_csv(folder / "categories.csv", ["category", "max_products_listed"], [(c, d["maxp"][c]) for c in d["cats"]])
    names = ["products.csv", "shelves.csv", "categories.csv"]
    head = (OPEN.format(name="Shelf plan") + f"For our new convenience-store format we must decide which of "
            f"{len(P)} products to stock on {len(d['SH'])} shelves, on which shelf, and with how many facings.\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in [
            ("Products", names[0]), ("Shelves", names[1]), ("Most products listed per category", names[2])])
        files: list[str] = []
    else:
        body = ("The data are in the attached files: products.csv (category, width of one facing, weekly units one "
                "facing sells on a shelf of visibility 1, weekly demand, margin per unit, whether it must be carried, "
                "most facings), shelves.csv (width and visibility factor; eye-level shelves sell more), "
                "categories.csv (the most products of each category we may list).")
        files = names
    rules = ("Rules (all hard): a product is placed on at most one shelf, with a whole number of facings, at most "
             "its max_facings; a product with must_carry = yes gets at least one facing. On every shelf, the facings "
             "times the product widths add up to at most the shelf width. A product is listed if it has at least one "
             "facing, and each category has at most its maximum number of listed products. A product sells per week "
             "facings x units per facing x the shelf's visibility factor, and to avoid overstock this may not exceed "
             "its weekly demand. Goal: the largest weekly margin = for every product, units sold x margin per unit. "
             "Report the shelf and "
             "facings of every listed product, the total weekly margin, the units sold per product, the width used "
             "on each shelf, and the products left out.")
    message = head + body + "\n\n" + rules + "\n\n" + CLOSE
    report = [["shelf and facings per product", r"SKU\d{3}[^\n]{0,60}SH\d\d|SH\d\d[^\n]{0,60}SKU\d{3}"],
              ["total weekly margin", num_re(ref["goal"])], ["units sold", r"units|sold|sales"],
              ["shelf width used", r"\bcm\b|width"], ["products left out", r"left out|not (listed|stocked|placed)|delist|excluded|dropped"]]
    finish(folder, "h08", size, "maximize", ref, seed, check, message, report, files)
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    prods = {r["product"]: r for r in read_csv(folder / "products.csv")}
    shelves = {r["shelf"]: r for r in read_csv(folder / "shelves.csv")}
    maxp = {r["category"]: int(r["max_products_listed"]) for r in read_csv(folder / "categories.csv")}
    name, fac = decision_over(export_rows(export_csv), set(prods), set(shelves))
    if not name:
        name, f2 = decision_over(export_rows(export_csv), set(shelves), set(prods))
        fac = {(p, s): v for (s, p), v in f2.items()}
    if not name:
        return ["no decision over (product, shelf) in the export", "COST 0.000000"]
    bad: list[str] = []
    for (p, s), v in fac.items():
        if v < -1e-6 or abs(v - round(v)) > 1e-6:
            bad.append(f"{p} {s}: {v:g} facings is not a whole number >= 0")
    margin = 0.0
    listed: dict[str, int] = {}
    for p, r in prods.items():
        on = {s: v for (pp, s), v in fac.items() if pp == p and v > 1e-6}
        if len(on) > 1:
            bad.append(f"{p} on {len(on)} shelves: {', '.join(sorted(on))}")
        tot = sum(on.values())
        if tot > float(r["max_facings"]) + 1e-6:
            bad.append(f"{p}: {tot:g} facings, at most {r['max_facings']}")
        if r["must_carry"] == "yes" and tot < 1 - 1e-6:
            bad.append(f"{p}: must be carried but has no facing")
        if tot > 1e-6:
            listed[r["category"]] = listed.get(r["category"], 0) + 1
        sold = sum(v * float(r["units_per_facing_per_week"]) * float(shelves[s]["visibility_factor"]) for s, v in on.items())
        if sold > float(r["weekly_demand_units"]) + 1e-6:
            bad.append(f"{p}: sells {sold:g} units, above its weekly demand {r['weekly_demand_units']}")
        margin += sold * float(r["margin_egp_per_unit"])
    for s, r in shelves.items():
        used = sum(v * float(prods[p]["width_cm"]) for (p, ss), v in fac.items() if ss == s)
        if used > float(r["width_cm"]) + 1e-6:
            bad.append(f"{s}: {used:g} cm used, width {r['width_cm']}")
    bad += [f"{c}: {n} products listed, at most {maxp[c]}" for c, n in listed.items() if n > maxp.get(c, 10 ** 9)]
    return bad + [f"COST {margin:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
