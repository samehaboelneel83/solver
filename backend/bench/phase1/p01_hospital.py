"""Problem 1: hospital resource allocation (integer programming).

    python -m bench.phase1.p01_hospital gen [S M L]
    python -m bench.phase1.p01_hospital check <case> <export.csv>

Hospitals share nothing but a supply budget; each has nurses, doctors and beds to split among its departments.
In each department: patients <= nurses x patients per nurse, patients <= doctors x patients per doctor, beds >=
patients x beds per patient, patients <= the department's demand; nurses and doctors at least the department's
minimum. Each hospital keeps an emergency reserve unassigned: a number of nurses and of beds. Supplies cost a
sum per patient, all hospitals within one budget. Most patients treated in all. Whole numbers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import HERE, csv_text, decision_over, export_rows, read_csv, write_case, write_csv

SIZES = {"S": 1, "M": 3, "L": 15}  # hospitals, four departments each
DEPTS = [("EMERGENCY", 3, 6, 0.6, 900), ("ICU", 1, 3, 1.0, 2600), ("SURGERY", 2, 5, 1.0, 1800),
         ("GENERAL", 5, 10, 1.0, 500)]  # patients per nurse, per doctor, beds per patient, supply cost per patient
OUT = HERE / "cases" / "p01"


def make(size: str, seed: int = 1) -> dict:
    n_h = SIZES[size]
    rng = np.random.default_rng(seed + n_h)
    H = ["MH"] if n_h == 1 else [f"H{i + 1:02d}" for i in range(n_h)]
    rows = []
    for h in H:
        scale = 1 if n_h == 1 else rng.uniform(0.6, 1.4)
        for name, ppn, ppd, bpp, cost in DEPTS:
            rows.append(dict(id=f"{h}-{name}", hospital=h, kind=name,
                             patients_per_nurse=ppn, patients_per_doctor=ppd, beds_per_patient=bpp,
                             supply_cost=int(cost * rng.uniform(0.9, 1.1)),
                             demand=int(rng.integers(25, 70) * scale),
                             min_nurses=int(rng.integers(4, 10)), min_doctors=int(rng.integers(1, 4))))
    hosp = []
    for h in H:
        scale = 1 if n_h == 1 else rng.uniform(0.6, 1.4)
        hosp.append(dict(id=h, nurses=int(120 * scale), doctors=int(40 * scale), beds=int(80 * scale),
                         reserve_nurses=int(max(2, 8 * scale)), reserve_beds=int(max(2, 8 * scale))))
    budget = int(sum(r["supply_cost"] * r["demand"] for r in rows) * 0.55)
    return dict(depts=rows, hosp=hosp, budget=budget)


def solve(d: dict) -> dict:
    from ortools.sat.python import cp_model

    md = cp_model.CpModel()
    n, dr, b, p = {}, {}, {}, {}
    for r in d["depts"]:
        k = r["id"]
        n[k] = md.NewIntVar(r["min_nurses"], 500, f"n{k}")
        dr[k] = md.NewIntVar(r["min_doctors"], 500, f"d{k}")
        b[k] = md.NewIntVar(0, 500, f"b{k}")
        p[k] = md.NewIntVar(0, r["demand"], f"p{k}")
        md.Add(p[k] <= r["patients_per_nurse"] * n[k])
        md.Add(p[k] <= r["patients_per_doctor"] * dr[k])
        md.Add(10 * b[k] >= int(round(r["beds_per_patient"] * 10)) * p[k])
    for h in d["hosp"]:
        mine = [r["id"] for r in d["depts"] if r["hospital"] == h["id"]]
        md.Add(sum(n[k] for k in mine) <= h["nurses"] - h["reserve_nurses"])
        md.Add(sum(dr[k] for k in mine) <= h["doctors"])
        md.Add(sum(b[k] for k in mine) <= h["beds"] - h["reserve_beds"])
    md.Add(sum(r["supply_cost"] * p[r["id"]] for r in d["depts"]) <= d["budget"])
    md.Maximize(sum(p.values()))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 120
    s.parameters.num_workers = 8
    st = s.Solve(md)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE), s.StatusName(st)
    return {"goal": s.ObjectiveValue(), "bound": s.BestObjectiveBound(), "optimal": st == cp_model.OPTIMAL}


def write(size: str) -> Path:
    d = make(size)
    ref = solve(d)
    folder = OUT / size
    dept_cols = ["id", "hospital", "kind", "patients_per_nurse", "patients_per_doctor", "beds_per_patient",
                 "supply_cost", "demand", "min_nurses", "min_doctors"]
    write_csv(folder / "departments.csv", dept_cols, [[r[c] for c in dept_cols] for r in d["depts"]])
    hosp_cols = ["id", "nurses", "doctors", "beds", "reserve_nurses", "reserve_beds"]
    write_csv(folder / "hospitals.csv", hosp_cols, [[h[c] for c in hosp_cols] for h in d["hosp"]])
    rules = (f"Rules: in each department the patients treated are at most its nurses times patients per nurse, at "
             "most its doctors times patients per doctor, and at most its demand; its beds are at least patients "
             "times beds per patient; it has at least its minimum nurses and minimum doctors. In each hospital, the "
             "nurses given to its departments are at most its nurses minus its reserve nurses, the doctors at most "
             "its doctors, and the beds at most its beds minus its reserve beds (the reserve is kept free for "
             f"emergencies). Supplies cost the department's supply cost per patient, and all supplies together cost "
             f"at most {d['budget']:,} EGP. Nurses, doctors, beds and patients are whole numbers. Goal: the most "
             "patients treated in total. Report the allocation of nurses, doctors, beds and supplies per department, "
             "patients per department and in total, resource utilization, which limits bind and what is left "
             "unused, and other allocations that treat as many patients.")
    head = (f'Please build this in a new workspace called "{{workspace}}". Call the problem "Resource allocation". '
            + ("A military hospital must allocate its nurses, doctors and beds to four departments and its supplies "
               "within a budget." if size == "S" else
               f"{len(d['hosp'])} military hospitals must each allocate their nurses, doctors and beds to their four "
               "departments, with one supply budget for all.") + "\n\n")
    if size == "S":
        body = ("Hospital:\n" + csv_text(folder / "hospitals.csv") + "\n\nDepartments:\n" + csv_text(folder / "departments.csv"))
        files = []
    else:
        body = "The data are in the attached files: hospitals.csv (staff, beds and reserves per hospital) and departments.csv."
        files = ["hospitals.csv", "departments.csv"]
    message = head + body + "\n\n" + rules + "\n\nEverything you need is here: please propose the model without further questions, then solve it."
    report = [["allocation per department", r"(nurses?|doctors?|beds?)[^\n]{0,80}\d"],
              ["patients per department", r"(EMERGENCY|ICU|SURGERY|GENERAL)[^\n]{0,60}\d"],
              ["total patients", f"{ref['goal']:,.0f}".replace(",", ",?")],
              ["resource utilization", r"utili[sz]|used|% of"],
              ["binding limits and unused resources", r"\bbind|tight|unused|left over|spare|slack"],
              ["alternative allocations", r"alternative|other allocation"]]
    write_case(folder, head + body + "\n\n" + rules + "\n\nEverything you need is here: please propose the model without further questions, then solve it.",
               {"problem": "p01", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                "goal": ref["goal"] if ref["optimal"] else None, "known_feasible": ref["goal"], "bound": ref["bound"],
                "sense": "maximize", "report": report, "files": files})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    depts = {r["id"]: r for r in read_csv(folder / "departments.csv")}
    hosp = {r["id"]: r for r in read_csv(folder / "hospitals.csv")}
    rows = export_rows(export_csv)
    found = {}
    # Each of the four per-department decisions, by which limit it fits: the model names its own decisions.
    by: dict[str, dict[str, float]] = {}
    # A department may be named by its kind ("EMERGENCY") when only one hospital has that kind.
    kinds: dict[str, list[str]] = {}
    for k, r in depts.items():
        kinds.setdefault(r["kind"], []).append(k)
    alias = {kind: ids[0] for kind, ids in kinds.items() if len(ids) == 1}
    for r in rows:
        key = r.get("key1")
        key = key if key in depts else alias.get(key)
        if key and not r.get("key2"):
            by.setdefault(r["decision"], {})[key] = float(r["value"])
    for name, cells in by.items():
        low = name.lower()
        for role, words in (("nurses", ("nurse",)), ("doctors", ("doctor", "physician")), ("beds", ("bed",)),
                            ("patients", ("patient", "treat"))):
            if any(w in low for w in words) and role not in found:
                found[role] = cells
    missing = [r for r in ("nurses", "doctors", "beds", "patients") if r not in found]
    if missing:
        return [f"no decision per department for {', '.join(missing)} (decisions: {', '.join(by)})"]
    n, dr, b, p = (found[k] for k in ("nurses", "doctors", "beds", "patients"))
    bad = []
    budget = None
    import re as _re
    msg = (folder / "message.txt").read_text(encoding="utf-8")
    m = _re.search(r"at most ([\d,]+) EGP", msg)
    budget = float(m.group(1).replace(",", "")) if m else None
    for k, r in depts.items():
        nk, dk, bk, pk = (x.get(k, 0.0) for x in (n, dr, b, p))
        for label, v in (("nurses", nk), ("doctors", dk), ("beds", bk), ("patients", pk)):
            if abs(v - round(v)) > 1e-6 or v < -1e-6:
                bad.append(f"{k} {label} = {v:g} is not a whole number >= 0")
        if pk > float(r["patients_per_nurse"]) * nk + 1e-6:
            bad.append(f"{k}: {pk:g} patients, {nk:g} nurses")
        if pk > float(r["patients_per_doctor"]) * dk + 1e-6:
            bad.append(f"{k}: {pk:g} patients, {dk:g} doctors")
        if bk < float(r["beds_per_patient"]) * pk - 1e-6:
            bad.append(f"{k}: {pk:g} patients, {bk:g} beds")
        if pk > float(r["demand"]) + 1e-6:
            bad.append(f"{k}: {pk:g} patients above demand {r['demand']}")
        if nk < float(r["min_nurses"]) - 1e-6 or dk < float(r["min_doctors"]) - 1e-6:
            bad.append(f"{k}: below minimum staffing ({nk:g} nurses, {dk:g} doctors)")
    for h, r in hosp.items():
        mine = [k for k, v in depts.items() if v["hospital"] == h]
        if sum(n.get(k, 0) for k in mine) > float(r["nurses"]) - float(r["reserve_nurses"]) + 1e-6:
            bad.append(f"{h}: nurses beyond what the reserve leaves")
        if sum(dr.get(k, 0) for k in mine) > float(r["doctors"]) + 1e-6:
            bad.append(f"{h}: more doctors than it has")
        if sum(b.get(k, 0) for k in mine) > float(r["beds"]) - float(r["reserve_beds"]) + 1e-6:
            bad.append(f"{h}: beds beyond what the reserve leaves")
    spent = sum(float(depts[k]["supply_cost"]) * v for k, v in p.items() if k in depts)
    if budget is not None and spent > budget + 1e-6:
        bad.append(f"supplies {spent:,.0f} above the budget {budget:,.0f}")
    return bad + [f"COST {sum(p.values()):.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
