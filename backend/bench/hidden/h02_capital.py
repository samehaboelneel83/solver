"""Hidden problem h02 (integer program with yes/no decisions).

    python -m bench.hidden.h02_capital gen [S M]
    python -m bench.hidden.h02_capital check <case> <export.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, decision_over, export_rows, read_csv, write_csv
from bench.hidden._util_a import CLOSE, OPEN, Model, export_text, finish, num_re, search, tol

SIZES = {"S": (10, 3), "M": (60, 5)}  # projects, years
OUT = Path(__file__).parent / "cases" / "h02"
CATS = ["GROWTH", "EFFICIENCY", "COMPLIANCE", "DIGITAL"]


def make(size: str, seed: int = 2) -> dict:
    n, ny = SIZES[size]
    rng = np.random.default_rng(seed * 104729 + n)
    P = [f"P{i + 1:03d}" for i in range(n)]
    Y = [f"Y{t + 1}" for t in range(ny)]
    cat = {p: CATS[int(rng.choice(4, p=[0.35, 0.3, 0.15, 0.2]))] for p in P}
    for k, c in enumerate(CATS):  # every category is present
        cat[P[k]] = c
    outlay = {}
    npv = {}
    for p in P:
        start = int(rng.integers(0, ny))
        span = int(rng.integers(1, 3))
        size_k = int(rng.integers(5, 40)) * 100  # thousand EGP
        for t in range(ny):
            outlay[(p, Y[t])] = int(round(size_k / span, -1)) if start <= t < start + span else 0
        tot = sum(outlay[(p, y)] for y in Y)
        lo, hi = (-0.1, 0.15) if cat[p] == "COMPLIANCE" else (0.05, 0.7)
        npv[p] = int(round(tot * rng.uniform(lo, hi), -1))
    budget = {}
    for y in Y:
        budget[y] = int(round(0.42 * sum(outlay[(p, y)] for p in P) + 300, -2))
    ng = 1 if size == "S" else 8
    groups = {p: "" for p in P}
    pool = list(rng.permutation(P))
    for g in range(ng):
        for p in pool[g * 3: g * 3 + int(rng.integers(2, 4))]:
            groups[p] = f"G{g + 1}"
    deps = []
    for _ in range(2 if size == "S" else 12):
        a, b = sorted(rng.choice(n, 2, replace=False).tolist())
        if (P[b], P[a]) not in deps:
            deps.append((P[b], P[a]))  # P[b] requires P[a]
    mins = {"COMPLIANCE": 1 if size == "S" else 3, "DIGITAL": 1 if size == "S" else 2}
    return dict(P=P, Y=Y, cat=cat, outlay=outlay, npv=npv, budget=budget, groups=groups, deps=deps, mins=mins)


def solve(d: dict, seconds: float = 300):
    m = Model()
    for p in d["P"]:
        m.var(p, 0, 1, integer=True, cost=d["npv"][p])
    for t in range(len(d["Y"])):
        ys = d["Y"][: t + 1]
        m.add([(p, sum(d["outlay"][(p, y)] for y in ys)) for p in d["P"]], hi=sum(d["budget"][y] for y in ys))
    for g in sorted({g for g in d["groups"].values() if g}):
        m.add([(p, 1) for p in d["P"] if d["groups"][p] == g], hi=1)
    for p, q in d["deps"]:
        m.add([(p, 1), (q, -1)], hi=0)
    for c, k in d["mins"].items():
        m.add([(p, 1) for p in d["P"] if d["cat"][p] == c], lo=k)
    r = m.solve(maximize=True, seconds=seconds)
    if r is None:
        return None
    rows = [("select", (p,), 1.0) for p in d["P"] if r["x"][p] > 0.5]
    return {"goal": r["obj"], "bound": r["bound"], "optimal": r["optimal"], "export": export_text(rows)}


def write(size: str) -> Path:
    seed, d, ref = search(make, solve, size, 2, 300)
    folder = OUT / size
    P, Y = d["P"], d["Y"]
    write_csv(folder / "projects.csv", ["project", "category", "exclusive_group", "npv_kegp"] + [f"outlay_{y}_kegp" for y in Y],
              [[p, d["cat"][p], d["groups"][p], d["npv"][p]] + [d["outlay"][(p, y)] for y in Y] for p in P])
    write_csv(folder / "budgets.csv", ["year", "budget_kegp"], [(y, d["budget"][y]) for y in Y])
    write_csv(folder / "dependencies.csv", ["project", "requires"], d["deps"])
    write_csv(folder / "category_minimums.csv", ["category", "min_projects"], sorted(d["mins"].items()))
    names = ["projects.csv", "budgets.csv", "dependencies.csv", "category_minimums.csv"]
    head = (OPEN.format(name="Capital programme") + f"The investment committee must choose which of {len(P)} candidate "
            f"projects to fund over the next {len(Y)} years. Amounts are in thousand EGP; each project's NPV is "
            "already computed.\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in [
            ("Projects (outlay per year if funded)", names[0]), ("Capital budget per year", names[1]),
            ("Dependencies (a project may be funded only if the project it requires is funded too)", names[2]),
            ("Minimum number of funded projects per category", names[3])])
        files: list[str] = []
    else:
        body = ("The data are in the attached files: projects.csv (category, exclusive group, NPV and the outlay in "
                "each year), budgets.csv (capital budget per year), dependencies.csv (a project may be funded only if "
                "the project it requires is funded), category_minimums.csv (minimum number of funded projects per "
                "category).")
        files = names
    rules = ("Rules (all hard): a project is either funded in full (all its yearly outlays) or not at all. Budget: "
             "money not spent in a year carries over to the following years, but we cannot spend ahead of budget, "
             "so for every year the outlays of funded projects from the first year up to that year are at most the "
             "budgets from the first year up to that year. Projects sharing an exclusive_group are alternatives: "
             "at most one of each group (a blank group means no restriction). A project may be funded only if every "
             "project it requires is funded. Each category listed in the minimums has at least that many funded "
             "projects. Goal: the largest total NPV of the funded projects. Report the projects funded, the total "
             "NPV, spending versus budget in each year, the unspent money carried over, and the projects left out.")
    message = head + body + "\n\n" + rules + "\n\n" + CLOSE
    report = [["funded projects", r"P\d{3}"], ["total NPV", num_re(ref["goal"])],
              ["spending versus budget per year", r"Y\d[^\n]{0,80}\d"],
              ["carry-over", r"carr(y|ied)|unspent|left over|remaining budget|unused"],
              ["projects left out", r"not (funded|selected|chosen)|left out|rejected|excluded|unfunded"]]
    finish(folder, "h02", size, "maximize", ref, seed, check, message, report, files)
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    projects = {r["project"]: r for r in read_csv(folder / "projects.csv")}
    budgets = read_csv(folder / "budgets.csv")
    deps = [(r["project"], r["requires"]) for r in read_csv(folder / "dependencies.csv")]
    mins = {r["category"]: int(r["min_projects"]) for r in read_csv(folder / "category_minimums.csv")}
    name, sel = decision_over(export_rows(export_csv), set(projects))
    if not name:
        return ["no decision over projects in the export", "COST 0.000000"]
    sel = {k[0]: v for k, v in sel.items()}
    bad: list[str] = []
    for p, v in sel.items():
        if abs(v) > 1e-6 and abs(v - 1) > 1e-6:
            bad.append(f"{p}: {v:g} is not 0 or 1 (all or nothing)")
    funded = {p for p, v in sel.items() if v > 0.5}
    spent = got = 0.0
    for b in budgets:
        y = b["year"]
        spent += sum(float(projects[p][f"outlay_{y}_kegp"]) for p in funded)
        got += float(b["budget_kegp"])
        if spent > got + tol(got):
            bad.append(f"by {y}: outlays {spent:,.0f} above budgets {got:,.0f}")
    groups: dict[str, list[str]] = {}
    for p in funded:
        if projects[p]["exclusive_group"]:
            groups.setdefault(projects[p]["exclusive_group"], []).append(p)
    bad += [f"group {g}: {', '.join(sorted(ps))} all funded" for g, ps in groups.items() if len(ps) > 1]
    bad += [f"{p} funded without {q}" for p, q in deps if p in funded and q not in funded]
    for c, k in mins.items():
        have = sum(1 for p in funded if projects[p]["category"] == c)
        if have < k:
            bad.append(f"{c}: {have} funded, at least {k}")
    npv = sum(float(projects[p]["npv_kegp"]) for p in funded)
    return bad + [f"COST {npv:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
