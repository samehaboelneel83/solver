"""Problem 8: cybersecurity defence budget (portfolio selection with dependencies and overlapping protection).

    python -m bench.phase1.p08_cyber gen [S M L]
    python -m bench.phase1.p08_cyber check <case> <export.csv>

Controls each cost money and staff, and protect some assets by an amount (0-100). Protection does not add up:
an asset's protection is the *largest* amount any selected control gives it (overlapping controls do not stack).
Risk reduced = sum over assets of asset value x protection / 100. Some controls need another control selected
first. Each critical asset must reach its minimum protection. Within the budget and the staff, the most risk
reduced. The reference is CP-SAT with the "largest of" written exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import HERE, csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (8, 4), "M": (40, 12), "L": (200, 60)}  # controls, assets
OUT = HERE / "cases" / "p08"
KINDS = ["network monitoring", "endpoint detection", "intrusion prevention", "backups", "identity protection",
         "incident response", "email filtering", "patch management", "data loss prevention", "segmentation"]


def make(size: str, seed: int = 8) -> dict:
    n_c, n_a = SIZES[size]
    rng = np.random.default_rng(seed + n_c)
    C = [f"CTL{i + 1:03d}" for i in range(n_c)]
    A = [f"AST{i + 1:02d}" for i in range(n_a)]
    kind = [KINDS[i % len(KINDS)] for i in range(n_c)]
    cost = rng.integers(20, 200, n_c) * 1000
    staff = np.round(rng.uniform(0.2, 2.0, n_c), 1)
    value = rng.integers(50, 500, n_a) * 1000
    critical = rng.random(n_a) < 0.3
    critical[0] = True
    protect = {}
    for i in range(n_c):
        for a in rng.choice(n_a, int(rng.integers(1, max(2, n_a // 3) + 1)), replace=False):
            protect[(i, int(a))] = int(rng.integers(20, 90))
    minimum = {a: int(rng.integers(40, 70)) for a in range(n_a) if critical[a]}
    for a, need in minimum.items():  # some control can meet each minimum
        if max([p for (i, aa), p in protect.items() if aa == a] or [0]) < need:
            protect[(int(rng.integers(0, n_c)), a)] = need + 5
    needs = {}
    for i in range(n_c):
        if rng.random() < 0.2:
            j = int(rng.integers(0, n_c))
            if j != i and needs.get(j) != i:
                needs[i] = j
    budget = int(cost.sum() * 0.35 // 1000 * 1000)
    staff_cap = round(float(staff.sum()) * 0.4, 1)
    return dict(C=C, A=A, kind=kind, cost=cost, staff=staff, value=value, critical=critical, protect=protect,
                minimum=minimum, needs=needs, budget=budget, staff_cap=staff_cap)


def solve(d: dict, seconds: float = 120) -> dict:
    from ortools.sat.python import cp_model

    C, A = d["C"], d["A"]
    md = cp_model.CpModel()
    x = [md.NewBoolVar(f"x{i}") for i in range(len(C))]
    prot = []
    for a in range(len(A)):
        options = [(i, p) for (i, aa), p in d["protect"].items() if aa == a]
        level = md.NewIntVar(0, 100, f"p{a}")
        # level = the largest protection among selected controls on this asset (0 if none)
        pick = {i: md.NewBoolVar("") for i, _ in options}
        md.Add(sum(pick.values()) <= 1)
        for i, p in options:
            md.AddImplication(pick[i], x[i])
        md.Add(level == sum(p * pick[i] for i, p in options))
        if a in d["minimum"]:
            md.Add(level >= d["minimum"][a])
        prot.append(level)
    for i, j in d["needs"].items():
        md.AddImplication(x[i], x[j])
    md.Add(sum(int(d["cost"][i]) * x[i] for i in range(len(C))) <= d["budget"])
    md.Add(sum(int(round(d["staff"][i] * 10)) * x[i] for i in range(len(C))) <= int(round(d["staff_cap"] * 10)))
    md.Maximize(sum(int(d["value"][a] // 1000) * prot[a] for a in range(len(A))))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = seconds
    s.parameters.num_workers = 8
    st = s.Solve(md)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": s.StatusName(st)}
    # risk reduced in EGP = sum value x level / 100
    return {"goal": s.ObjectiveValue() * 1000 / 100, "bound": s.BestObjectiveBound() * 1000 / 100,
            "optimal": st == cp_model.OPTIMAL, "chosen": [C[i] for i in range(len(C)) if s.Value(x[i])]}


def write(size: str) -> Path:
    for seed in range(8, 60):
        d = make(size, seed)
        ref = solve(d)
        if "goal" in ref:
            break
    folder = OUT / size
    C, A = d["C"], d["A"]
    write_csv(folder / "controls.csv", ["id", "kind", "cost", "staff", "needs"],
              [(C[i], d["kind"][i], int(d["cost"][i]), float(d["staff"][i]), C[d["needs"][i]] if i in d["needs"] else "")
               for i in range(len(C))])
    write_csv(folder / "assets.csv", ["id", "value", "critical", "min_protection"],
              [(A[a], int(d["value"][a]), "yes" if d["critical"][a] else "no", d["minimum"].get(a, 0)) for a in range(len(A))])
    write_csv(folder / "protection.csv", ["control", "asset", "protection"],
              [(C[i], A[a], p) for (i, a), p in sorted(d["protect"].items())])
    names = ["controls.csv", "assets.csv", "protection.csv"]
    rules = (f"Rules: the controls chosen cost at most {d['budget']:,} EGP and need at most {d['staff_cap']} staff in "
             "total. A control with a 'needs' entry can be chosen only if the control it needs is chosen too. "
             "Protection does NOT add up: an asset's protection is the largest protection any chosen control gives "
             "it (two controls protecting the same asset at 60 and 50 give it 60, not 110), and 0 if no chosen "
             "control protects it. Every critical asset reaches at least its min_protection. Risk reduced = sum over "
             "assets of value x protection / 100. Goal: the most risk reduced. Report the controls chosen and their "
             "cost, budget used, risk reduced, the protection of each critical asset, why each control was chosen "
             "or left out, and other portfolios for a smaller and a larger budget.")
    head = (f'Please build this in a new workspace called "{{workspace}}". Call the problem "Security portfolio". '
            f"We must choose which of {len(C)} security controls to fund this year to protect {len(A)} assets.\n\n")
    if size == "S":
        body = "\n\n".join(f"{label}:\n{csv_text(folder / n)}" for label, n in [
            ("Controls (cost in EGP, staff needed, and the control it needs, if any)", names[0]),
            ("Assets (value in EGP, critical or not, minimum protection 0-100 for critical ones)", names[1]),
            ("Protection each control gives each asset (0-100)", names[2])])
        files = []
    else:
        body = "The data are in the attached files: controls.csv, assets.csv, protection.csv."
        files = names
    message = head + body + "\n\n" + rules + "\n\nEverything you need is here: please propose the model without further questions, then solve it."
    report = [["controls chosen and cost", r"CTL\d{3}"], ["budget used", r"budget"],
              ["risk reduced", f"{ref['goal']:,.0f}".replace(",", ",?")],
              ["critical asset coverage", r"critical"], ["why chosen or excluded", r"because|excluded|left out|not chosen"],
              ["other budgets", r"smaller budget|larger budget|other portfolio|alternative"]]
    write_case(folder, message, {"problem": "p08", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": ref["goal"] if ref["optimal"] else None, "known_feasible": ref["goal"],
                                 "bound": ref["bound"], "sense": "maximize", "report": report, "files": files,
                                 "naive_additive_note": "adding protections would overstate risk reduced"})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    """Which controls the plan chose (the yes/no decision over controls), then every rule and the true risk
    reduced -- with protection as the largest of the chosen controls', whatever the model did."""
    ctl = {r["id"]: r for r in read_csv(folder / "controls.csv")}
    assets = {r["id"]: r for r in read_csv(folder / "assets.csv")}
    prot: dict[str, dict[str, float]] = {}
    for r in read_csv(folder / "protection.csv"):
        prot.setdefault(r["asset"], {})[r["control"]] = float(r["protection"])
    rows = export_rows(export_csv)
    by: dict[str, dict[str, float]] = {}
    for r in rows:
        if r.get("key1") in ctl and not r.get("key2"):
            by.setdefault(r["decision"], {})[r["key1"]] = float(r["value"])
    picks = [cells for cells in by.values() if all(v in (0.0, 1.0) for v in cells.values())]
    # The export lists only cells that are not 0: no row for any control means none was chosen.
    chosen = {c for c, v in max(picks, key=len).items() if v > 0.5} if picks else set()
    msg = (folder / "message.txt").read_text(encoding="utf-8")
    import re

    budget = float(re.search(r"cost at most ([\d,]+) EGP", msg).group(1).replace(",", ""))
    staff = float(re.search(r"need at most ([\d.]+) staff", msg).group(1))
    bad = []
    spent = sum(float(ctl[c]["cost"]) for c in chosen)
    if spent > budget + 1e-6:
        bad.append(f"cost {spent:,.0f} above the budget {budget:,.0f}")
    used = sum(float(ctl[c]["staff"]) for c in chosen)
    if used > staff + 1e-6:
        bad.append(f"staff {used:.1f} above {staff}")
    for c in chosen:
        if ctl[c]["needs"] and ctl[c]["needs"] not in chosen:
            bad.append(f"{c} chosen without {ctl[c]['needs']}, which it needs")
    risk = 0.0
    for a, r in assets.items():
        level = max([p for c, p in prot.get(a, {}).items() if c in chosen] or [0.0])
        if r["critical"] == "yes" and level < float(r["min_protection"]) - 1e-6:
            bad.append(f"critical {a} protected {level:g}, needs {r['min_protection']}")
        risk += float(r["value"]) * level / 100
    return bad + [f"COST {risk:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:220])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
