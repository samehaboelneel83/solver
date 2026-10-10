"""Hidden problem h01 (linear program).

    python -m bench.hidden.h01_crops gen [S M]
    python -m bench.hidden.h01_crops check <case> <export.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, decision_over, export_rows, read_csv, write_csv
from bench.hidden._util_a import CLOSE, OPEN, Model, export_text, finish, num_re, search, tol

SIZES = {"S": (4, 4, 3, 2), "M": (30, 8, 6, 4)}  # fields, crops, months, districts
OUT = Path(__file__).parent / "cases" / "h01"
# crop: (tons per ha, EGP per ton, cost EGP per ha, water m3 per ha, legume)
CROPS = {"WHEAT": (6.5, 11000, 26000, 5500, "no"), "MAIZE": (8.0, 9000, 30000, 7000, "no"),
         "COTTON": (3.0, 30000, 48000, 8500, "no"), "CLOVER": (25.0, 1600, 16000, 7500, "yes"),
         "TOMATO": (40.0, 4000, 95000, 7000, "no"), "POTATO": (30.0, 5000, 72000, 6000, "no"),
         "SUGARBEET": (60.0, 1500, 42000, 7000, "no"), "FABA": (3.5, 16000, 21000, 4000, "yes")}
MONTHS = ["NOV", "DEC", "JAN", "FEB", "MAR", "APR"]


def make(size: str, seed: int = 1) -> dict:
    nf, nc, nm, nd = SIZES[size]
    rng = np.random.default_rng(seed * 7919 + nf)
    F = [f"F{i + 1:02d}" for i in range(nf)]
    C = list(CROPS)[:nc]
    M = MONTHS[:nm]
    D = [f"D{j + 1}" for j in range(nd)]
    ha = {f: int(rng.integers(20, 121)) for f in F}
    dist = {f: D[i % nd] if i < nd else D[int(rng.integers(nd))] for i, f in enumerate(F)}
    yields = {}
    for f in F:
        for c in C:
            if rng.random() < 0.18 and CROPS[c][4] == "no":
                continue
            yields[(f, c)] = round(CROPS[c][0] * rng.uniform(0.8, 1.2), 1)
    hours = {(c, m): int(rng.integers(4, 41)) * (2 if c in ("TOMATO", "POTATO") else 1) for c in C for m in M}
    total = sum(ha.values())
    quota = {dd: int(round(0.72 * 6500 * sum(ha[f] for f in F if dist[f] == dd), -3)) for dd in D}
    avail = {m: int(round(0.65 * total * np.mean([hours[(c, m)] for c in C]), -2)) for m in M}
    mins, maxs = {}, {}
    for c in C:
        base = CROPS[c][0] * total / nc
        mins[c] = int(round(0.25 * base)) if rng.random() < 0.6 or c == "WHEAT" else 0
        maxs[c] = int(round(1.2 * base))
    return dict(F=F, C=C, M=M, D=D, ha=ha, dist=dist, yields=yields, hours=hours, quota=quota, avail=avail,
                mins=mins, maxs=maxs, legume_share=0.15)


def solve(d: dict, seconds: float = 300):
    m = Model()
    for (f, c), y in d["yields"].items():
        m.var((f, c), cost=y * CROPS[c][1] - CROPS[c][2])
    for f in d["F"]:
        m.add([((f, c), 1) for c in d["C"] if (f, c) in d["yields"]], hi=d["ha"][f])
    for dd in d["D"]:
        m.add([((f, c), CROPS[c][3]) for (f, c) in d["yields"] if d["dist"][f] == dd], hi=d["quota"][dd])
    for mo in d["M"]:
        m.add([((f, c), d["hours"][(c, mo)]) for (f, c) in d["yields"]], hi=d["avail"][mo])
    for c in d["C"]:
        m.add([((f, cc), y) for (f, cc), y in d["yields"].items() if cc == c], lo=d["mins"][c], hi=d["maxs"][c])
    m.add([((f, c), 1) for (f, c) in d["yields"] if CROPS[c][4] == "yes"], lo=d["legume_share"] * sum(d["ha"].values()))
    r = m.solve(maximize=True, seconds=seconds)
    if r is None:
        return None
    rows = [("area", k, v) for k, v in r["x"].items() if v > 1e-9]
    return {"goal": r["obj"], "bound": r["bound"], "optimal": r["optimal"], "export": export_text(rows)}


def write(size: str) -> Path:
    seed, d, ref = search(make, solve, size, 1, 300)
    folder = OUT / size
    write_csv(folder / "fields.csv", ["field", "district", "hectares"], [(f, d["dist"][f], d["ha"][f]) for f in d["F"]])
    write_csv(folder / "districts.csv", ["district", "water_quota_m3"], [(x, d["quota"][x]) for x in d["D"]])
    write_csv(folder / "crops.csv", ["crop", "legume", "price_egp_per_ton", "cost_egp_per_ha", "water_m3_per_ha",
                                     "min_tons", "max_tons"],
              [(c, CROPS[c][4], CROPS[c][1], CROPS[c][2], CROPS[c][3], d["mins"][c], d["maxs"][c]) for c in d["C"]])
    write_csv(folder / "yields.csv", ["field", "crop", "tons_per_ha"], [(f, c, y) for (f, c), y in d["yields"].items()])
    write_csv(folder / "labour.csv", ["crop", "month", "hours_per_ha"], [(c, m, d["hours"][(c, m)]) for c in d["C"] for m in d["M"]])
    write_csv(folder / "months.csv", ["month", "hours_available"], [(m, d["avail"][m]) for m in d["M"]])
    write_csv(folder / "settings.csv", ["legume_share_min"], [(d["legume_share"],)])
    names = ["fields.csv", "districts.csv", "crops.csv", "yields.csv", "labour.csv", "months.csv"]
    head = (OPEN.format(name="Winter crop plan") + f"Our farm company has {len(d['F'])} fields in {len(d['D'])} "
            f"irrigation districts and must decide how many hectares of each crop to plant on each field this winter "
            f"season ({', '.join(d['M'])}).\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in [
            ("Fields", names[0]), ("Water quota per district for the season", names[1]),
            ("Crops (min_tons is our contract minimum, max_tons what the market takes)", names[2]),
            ("Yields (only these field-crop pairs are possible)", names[3]),
            ("Labour hours per hectare per month", names[4]), ("Labour hours available per month", names[5])])
        files: list[str] = []
    else:
        body = ("The data are in the attached files: fields.csv (district and hectares per field), districts.csv "
                "(season water quota), crops.csv (price, growing cost, water need, contract minimum and market maximum "
                "per crop, and whether it is a legume), yields.csv (tons per hectare; only the field-crop pairs "
                "listed are possible), labour.csv (hours per hectare per crop and month), months.csv (labour hours "
                "available per month).")
        files = names
    share = int(d["legume_share"] * 100)
    rules = ("Rules (all hard): hectares are planted only on the field-crop pairs in the yields list, may be "
             "fractional, and the hectares planted on a field are at most its size (part of a field may stay fallow). "
             "Water: the hectares in a district times each crop's water need are at most the district's quota. "
             "Labour: in every month, hectares times the crop's hours per hectare for that month, over all fields, "
             "are at most the hours available. Production of each crop (hectares times the field's yield) is at "
             "least its min_tons and at most its max_tons. Soil rule: legume crops cover at least "
             f"{share}% of the farm's total hectares (all fields together). Goal: the largest total profit = for "
             "every field and crop, hectares x (yield x price - cost per hectare). Report the hectares per field "
             "and crop, the total profit, the production per crop, water used per district, labour used per month, "
             "and which limits are binding.")
    message = head + body + "\n\n" + rules + "\n\n" + CLOSE
    report = [["hectares per field and crop", r"F\d\d[^\n]{0,60}(" + "|".join(CROPS) + r")|(" + "|".join(CROPS) + r")[^\n]{0,60}F\d\d"],
              ["total profit", num_re(ref["goal"])],
              ["production per crop", r"\bton"],
              ["water per district", r"water[^\n]{0,80}(D\d|district)|(D\d|district)[^\n]{0,80}water"],
              ["labour per month", r"labou?r|hours"],
              ["binding limits", r"\bbind|tight|bottleneck|limiting|shadow"]]
    finish(folder, "h01", size, "maximize", ref, seed, check, message, report, files)
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    fields = {r["field"]: r for r in read_csv(folder / "fields.csv")}
    quota = {r["district"]: float(r["water_quota_m3"]) for r in read_csv(folder / "districts.csv")}
    crops = {r["crop"]: r for r in read_csv(folder / "crops.csv")}
    yields = {(r["field"], r["crop"]): float(r["tons_per_ha"]) for r in read_csv(folder / "yields.csv")}
    hours = {(r["crop"], r["month"]): float(r["hours_per_ha"]) for r in read_csv(folder / "labour.csv")}
    avail = {r["month"]: float(r["hours_available"]) for r in read_csv(folder / "months.csv")}
    share = float(read_csv(folder / "settings.csv")[0]["legume_share_min"])
    name, area = decision_over(export_rows(export_csv), set(fields), set(crops))
    if not name:
        # a crop-field order is natural too
        name, a2 = decision_over(export_rows(export_csv), set(crops), set(fields))
        area = {(f, c): v for (c, f), v in a2.items()}
    if not name:
        return ["no decision over (field, crop) in the export", "COST 0.000000"]
    bad: list[str] = []
    profit = 0.0
    for (f, c), v in area.items():
        if v < -1e-6:
            bad.append(f"{f} {c}: negative hectares {v:g}")
        if v > 1e-6 and (f, c) not in yields:
            bad.append(f"{f} {c}: planted ({v:g} ha) but this pair is not possible")
        profit += v * (yields.get((f, c), 0.0) * float(crops[c]["price_egp_per_ton"]) - float(crops[c]["cost_egp_per_ha"]))
    for f, r in fields.items():
        used = sum(v for (ff, _), v in area.items() if ff == f)
        if used > float(r["hectares"]) + tol(float(r["hectares"])):
            bad.append(f"{f}: {used:g} ha planted, field has {r['hectares']}")
    for dd, q in quota.items():
        w = sum(v * float(crops[c]["water_m3_per_ha"]) for (f, c), v in area.items() if fields[f]["district"] == dd)
        if w > q + tol(q):
            bad.append(f"{dd}: water {w:,.1f} above quota {q:,.0f}")
    for mo, h in avail.items():
        u = sum(v * hours[(c, mo)] for (f, c), v in area.items())
        if u > h + tol(h):
            bad.append(f"{mo}: labour {u:,.1f} h above {h:,.0f}")
    for c, r in crops.items():
        p = sum(v * yields.get((f, c), 0.0) for (f, cc), v in area.items() if cc == c)
        if p < float(r["min_tons"]) - tol(float(r["min_tons"])):
            bad.append(f"{c}: production {p:,.2f} t below the minimum {r['min_tons']}")
        if p > float(r["max_tons"]) + tol(float(r["max_tons"])):
            bad.append(f"{c}: production {p:,.2f} t above the maximum {r['max_tons']}")
    total = sum(float(r["hectares"]) for r in fields.values())
    leg = sum(v for (f, c), v in area.items() if crops[c]["legume"] == "yes")
    if leg < share * total - tol(share * total):
        bad.append(f"legumes {leg:g} ha below {share:.0%} of {total:g} ha")
    return bad + [f"COST {profit:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
