"""Hidden problem h06 (set covering with side rules).

    python -m bench.hidden.h06_clinics gen [S M]
    python -m bench.hidden.h06_clinics check <case> <export.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, decision_over, export_rows, read_csv, write_csv
from bench.hidden._util_a import CLOSE, OPEN, Model, export_text, finish, num_re, search

SIZES = {"S": (10, 6, 4), "M": (150, 40, 25)}  # clinics, skills, coaches
OUT = Path(__file__).parent / "cases" / "h06"
SKILLS_S = ["PASSING", "FINISHING", "PRESSING", "SET_PIECES", "GOALKEEPING", "SPRINT"]


def make(size: str, seed: int = 6) -> dict:
    nk, ns, np_ = SIZES[size]
    rng = np.random.default_rng(seed * 67867967 + nk)
    K = [f"CL{i + 1:03d}" for i in range(nk)]
    S = SKILLS_S if size == "S" else [f"SK{i + 1:02d}" for i in range(ns)]
    coaches = [f"COACH{i + 1:02d}" for i in range(np_)]
    coach = {k: coaches[int(rng.integers(np_))] for k in K}
    days = {k: int(rng.integers(1, 4)) for k in K}
    cover = {}
    for k in K:
        m = int(rng.integers(1, 4)) if size == "S" else int(rng.integers(2, 7))
        cover[k] = sorted(S[int(i)] for i in rng.choice(ns, m, replace=False))
    cost = {k: int(round((6000 + 4000 * days[k] + 2500 * len(cover[k])) * rng.uniform(0.7, 1.3), -2)) for k in K}
    need = {s: int(rng.integers(1, 3)) if size == "S" else int(rng.integers(1, 4)) for s in S}
    # every skill offered often enough, by different coaches
    for s in S:
        while sum(1 for k in K if s in cover[k]) < need[s] + 2:
            k = K[int(rng.integers(nk))]
            if s not in cover[k]:
                cover[k] = sorted(cover[k] + [s])
    camp_days = int(round(sum(need.values()) * 2.0 / (1.6 if size == "S" else 3.5))) + 2
    return dict(K=K, S=S, coach=coach, days=days, cover=cover, cost=cost, need=need, camp_days=camp_days, per_coach=2)


def solve(d: dict, seconds: float = 300):
    m = Model()
    for k in d["K"]:
        m.var(k, 0, 1, integer=True, cost=d["cost"][k])
    for s in d["S"]:
        m.add([(k, 1) for k in d["K"] if s in d["cover"][k]], lo=d["need"][s])
    m.add([(k, d["days"][k]) for k in d["K"]], hi=d["camp_days"])
    for c in sorted(set(d["coach"].values())):
        m.add([(k, 1) for k in d["K"] if d["coach"][k] == c], hi=d["per_coach"])
    r = m.solve(maximize=False, seconds=seconds)
    if r is None:
        return None
    rows = [("book", (k,), 1.0) for k in d["K"] if r["x"][k] > 0.5]
    return {"goal": r["obj"], "bound": r["bound"], "optimal": r["optimal"], "export": export_text(rows)}


def write(size: str) -> Path:
    seed, d, ref = search(make, solve, size, 6, 280)
    folder = OUT / size
    write_csv(folder / "clinics.csv", ["clinic", "coach", "fee_egp", "days"], [(k, d["coach"][k], d["cost"][k], d["days"][k]) for k in d["K"]])
    write_csv(folder / "clinic_skills.csv", ["clinic", "skill"], [(k, s) for k in d["K"] for s in d["cover"][k]])
    write_csv(folder / "skills.csv", ["skill", "sessions_required"], [(s, d["need"][s]) for s in d["S"]])
    write_csv(folder / "camp.csv", ["camp_days", "max_clinics_per_coach"], [(d["camp_days"], d["per_coach"])])
    names = ["clinics.csv", "clinic_skills.csv", "skills.csv", "camp.csv"]
    head = (OPEN.format(name="Pre-season clinics") + f"Our football club is planning its pre-season training camp. "
            f"Guest coaches offer {len(d['K'])} specialist clinics; we must choose which ones to book so the squad "
            f"gets enough sessions on each of {len(d['S'])} skills.\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in [
            ("Clinics (fee and length in days)", names[0]), ("Skills each clinic trains", names[1]),
            ("Sessions required per skill", names[2]), ("Camp limits", names[3])])
        files: list[str] = []
    else:
        body = ("The data are in the attached files: clinics.csv (coach, fee and length in days of each clinic), "
                "clinic_skills.csv (the skills each clinic trains), skills.csv (sessions required per skill), "
                "camp.csv (days in the camp and the most clinics one coach may run).")
        files = names
    rules = ("Rules (all hard): a clinic is booked whole or not at all, at most once. Every skill must be trained by "
             "at least its required number of booked clinics (a clinic counts once for every skill it trains). "
             "Clinics run one after another, so the days of all booked clinics add up to at most the camp days. A "
             "coach runs at most the maximum number of clinics per coach. Goal: the lowest total fee of the booked "
             "clinics. Report the clinics booked, the total fee, how many booked clinics train each skill against "
             "its requirement, the camp days used, and the clinics booked per coach.")
    message = head + body + "\n\n" + rules + "\n\n" + CLOSE
    report = [["clinics booked", r"CL\d{3}"], ["total fee", num_re(ref["goal"])],
              ["coverage per skill", r"(" + ("|".join(SKILLS_S) if size == "S" else r"SK\d\d") + r")[^\n]{0,60}\d"],
              ["camp days used", r"days"], ["clinics per coach", r"COACH\d\d"]]
    finish(folder, "h06", size, "minimize", ref, seed, check, message, report, files)
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    clinics = {r["clinic"]: r for r in read_csv(folder / "clinics.csv")}
    cover: dict[str, set[str]] = {}
    for r in read_csv(folder / "clinic_skills.csv"):
        cover.setdefault(r["clinic"], set()).add(r["skill"])
    need = {r["skill"]: int(r["sessions_required"]) for r in read_csv(folder / "skills.csv")}
    camp = read_csv(folder / "camp.csv")[0]
    name, sel = decision_over(export_rows(export_csv), set(clinics))
    if not name:
        return ["no decision over clinics in the export", "COST 0.000000"]
    bad: list[str] = []
    for (k,), v in sel.items():
        if abs(v) > 1e-6 and abs(v - 1) > 1e-6:
            bad.append(f"{k}: {v:g} is not 0 or 1")
    booked = {k for (k,), v in sel.items() if v > 0.5}
    for s, n in need.items():
        got = sum(1 for k in booked if s in cover.get(k, set()))
        if got < n:
            bad.append(f"{s}: trained by {got} booked clinics, needs {n}")
    days = sum(float(clinics[k]["days"]) for k in booked)
    if days > float(camp["camp_days"]) + 1e-6:
        bad.append(f"{days:g} clinic days, camp has {camp['camp_days']}")
    per: dict[str, int] = {}
    for k in booked:
        per[clinics[k]["coach"]] = per.get(clinics[k]["coach"], 0) + 1
    bad += [f"{c} runs {n} clinics, at most {camp['max_clinics_per_coach']}" for c, n in per.items()
            if n > int(camp["max_clinics_per_coach"])]
    return bad + [f"COST {sum(float(clinics[k]['fee_egp']) for k in booked):.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
