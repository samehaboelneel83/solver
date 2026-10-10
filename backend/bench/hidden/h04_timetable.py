"""Hidden problem h04 (assignment).

    python -m bench.hidden.h04_timetable gen [S M]
    python -m bench.hidden.h04_timetable check <case> <export.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, export_rows, read_csv, write_csv
from bench.hidden._util_a import CLOSE, OPEN, export_text, finish, num_re, search

SIZES = {"S": (8, 4, 4, 2), "M": (60, 20, 10, 12)}  # courses, teachers, slots, cohorts
OUT = Path(__file__).parent / "cases" / "h04"
DAYS = ["MON", "TUE", "WED", "THU", "FRI"]


def make(size: str, seed: int = 4) -> dict:
    nk, nt, ns, nc = SIZES[size]
    rng = np.random.default_rng(seed * 32452843 + nk)
    K = [f"CRS{i + 1:02d}" for i in range(nk)]
    T = [f"T{i + 1:02d}" for i in range(nt)]
    S = [f"{DAYS[i // 2]}-{'AM' if i % 2 == 0 else 'EVE'}" for i in range(ns)]
    late = {s: s.endswith("EVE") for s in S}
    G = [f"Y{i // 2 + 1}{'AB'[i % 2]}" for i in range(nc)]
    cohort = {k: G[i % nc] for i, k in enumerate(K)}
    kind = {k: ("lab" if rng.random() < 0.25 else "lecture") for k in K}
    hours = {k: int(rng.integers(2, 5)) for k in K}
    qual = {}
    for k in K:
        for t in rng.choice(nt, int(rng.integers(2, 4)) if nk < 20 else int(rng.integers(3, 5)), replace=False):
            qual[(T[int(t)], k)] = int(rng.integers(1, 6))
    load = sum(hours.values())
    maxh = {t: int(np.ceil(load / nt * rng.uniform(1.15, 1.6))) for t in T}
    unavail = sorted({(T[int(rng.integers(nt))], S[int(rng.integers(ns))]) for _ in range(max(2, nt // 2))})
    rooms = {"lab": 1, "lecture": 2} if nk < 20 else {"lab": 2, "lecture": 5}
    return dict(K=K, T=T, S=S, late=late, cohort=cohort, kind=kind, hours=hours, qual=qual, maxh=maxh,
                unavail=unavail, rooms=rooms, late_penalty=2)


def solve(d: dict, seconds: float = 300):
    from ortools.sat.python import cp_model

    md = cp_model.CpModel()
    un = set(d["unavail"])
    z = {}
    for (t, k) in d["qual"]:
        for s in d["S"]:
            if (t, s) not in un:
                z[(k, t, s)] = md.NewBoolVar(f"z{k}{t}{s}")
    for k in d["K"]:
        md.AddExactlyOne([v for (kk, _, _), v in z.items() if kk == k])
    for t in d["T"]:
        md.Add(sum(d["hours"][k] * v for (k, tt, _), v in z.items() if tt == t) <= d["maxh"][t])
        for s in d["S"]:
            md.Add(sum(v for (_, tt, ss), v in z.items() if tt == t and ss == s) <= 1)
    for s in d["S"]:
        for g in set(d["cohort"].values()):
            md.Add(sum(v for (k, _, ss), v in z.items() if ss == s and d["cohort"][k] == g) <= 1)
        for kind, n in d["rooms"].items():
            md.Add(sum(v for (k, _, ss), v in z.items() if ss == s and d["kind"][k] == kind) <= n)
    md.Maximize(sum((d["qual"][(t, k)] - (d["late_penalty"] if d["late"][s] else 0)) * v for (k, t, s), v in z.items()))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = seconds
    sv.parameters.num_workers = 8
    st = sv.Solve(md)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    rows = []
    for (k, t, s), v in z.items():
        if sv.Value(v):
            rows.append(("teaches", (k, t), 1.0))
            rows.append(("slot", (k, s), 1.0))
    return {"goal": sv.ObjectiveValue(), "bound": sv.BestObjectiveBound(), "optimal": st == cp_model.OPTIMAL,
            "export": export_text(rows)}


def write(size: str) -> Path:
    seed, d, ref = search(make, solve, size, 4, 280)
    folder = OUT / size
    write_csv(folder / "courses.csv", ["course", "cohort", "room_type", "weekly_hours"],
              [(k, d["cohort"][k], d["kind"][k], d["hours"][k]) for k in d["K"]])
    write_csv(folder / "teachers.csv", ["teacher", "max_weekly_hours"], [(t, d["maxh"][t]) for t in d["T"]])
    write_csv(folder / "qualifications.csv", ["teacher", "course", "preference"], sorted((t, k, p) for (t, k), p in d["qual"].items()))
    write_csv(folder / "slots.csv", ["slot", "late"], [(s, "yes" if d["late"][s] else "no") for s in d["S"]])
    write_csv(folder / "unavailable.csv", ["teacher", "slot"], d["unavail"])
    write_csv(folder / "rooms.csv", ["room_type", "rooms_per_slot"], sorted(d["rooms"].items()))
    write_csv(folder / "settings.csv", ["late_penalty_per_course"], [(d["late_penalty"],)])
    names = ["courses.csv", "teachers.csv", "qualifications.csv", "slots.csv", "unavailable.csv", "rooms.csv"]
    head = (OPEN.format(name="Term timetable") + f"Our college must give each of {len(d['K'])} courses next term a "
            f"teacher and a weekly time slot (one of {len(d['S'])} slots; each course meets once a week in its slot).\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in [
            ("Courses", names[0]), ("Teachers", names[1]),
            ("Who may teach what (preference 1 = dislikes, 5 = loves)", names[2]), ("Slots", names[3]),
            ("Teacher not available in a slot", names[4]), ("Rooms of each type available in every slot", names[5])])
        files: list[str] = []
    else:
        body = ("The data are in the attached files: courses.csv (cohort, room type needed, weekly hours), "
                "teachers.csv (maximum weekly hours), qualifications.csv (the only teacher-course pairs allowed, "
                "with the teacher's preference from 1 = dislikes to 5 = loves), slots.csv (whether a slot is a late "
                "evening slot), unavailable.csv (teacher-slot pairs the teacher cannot do), rooms.csv (rooms of each "
                "type available in every slot).")
        files = names
    rules = ("Rules (all hard): every course gets exactly one teacher, who must be qualified for it (listed in the "
             "qualifications), and exactly one slot. A teacher's courses add up to at most the teacher's maximum "
             "weekly hours (a course counts its weekly hours). A teacher teaches at most one course in a slot and "
             "nothing in a slot where the teacher is unavailable. Two courses of the same cohort are never in the "
             "same slot. In every slot, the courses needing a room type are at most the rooms of that type. Goal: "
             f"the largest score = the sum of the preferences of the chosen teacher-course pairs minus "
             f"{d['late_penalty']} points for every course placed in a late slot. Report the teacher and the slot of "
             "every course, the total score, each teacher's weekly hours, the courses in late slots, and the rooms "
             "used per slot.")
    message = head + body + "\n\n" + rules + "\n\n" + CLOSE
    report = [["teacher and slot per course", r"CRS\d\d[^\n]{0,80}(T\d\d|(MON|TUE|WED|THU|FRI)-(AM|EVE))"],
              ["total score", num_re(ref["goal"])],
              ["teacher hours", r"T\d\d[^\n]{0,60}(hours?|h\b)|hours?[^\n]{0,60}T\d\d"],
              ["late slots", r"\blate\b|EVE"], ["rooms per slot", r"\broom|\blab"]]
    finish(folder, "h04", size, "maximize", ref, seed, check, message, report, files)
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    courses = {r["course"]: r for r in read_csv(folder / "courses.csv")}
    teachers = {r["teacher"]: float(r["max_weekly_hours"]) for r in read_csv(folder / "teachers.csv")}
    qual = {(r["teacher"], r["course"]): float(r["preference"]) for r in read_csv(folder / "qualifications.csv")}
    slots = {r["slot"]: r["late"] == "yes" for r in read_csv(folder / "slots.csv")}
    unavail = {(r["teacher"], r["slot"]) for r in read_csv(folder / "unavailable.csv")}
    rooms = {r["room_type"]: float(r["rooms_per_slot"]) for r in read_csv(folder / "rooms.csv")}
    pen = float(read_csv(folder / "settings.csv")[0]["late_penalty_per_course"])
    # Any decision whose keys hold a course and a teacher and/or a slot (2- or 3-index assignment, any order).
    tof: dict[str, set[str]] = {k: set() for k in courses}
    sof: dict[str, set[str]] = {k: set() for k in courses}
    bad: list[str] = []
    seen = False
    for r in export_rows(export_csv):
        keys = [v for k, v in r.items() if k.startswith("key") and v]
        ks = [x for x in keys if x in courses]
        ts = [x for x in keys if x in teachers]
        ss = [x for x in keys if x in slots]
        if len(ks) != 1 or len(ks) + len(ts) + len(ss) != len(keys) or len(ts) > 1 or len(ss) > 1 or not (ts or ss):
            continue
        seen = True
        v = float(r["value"])
        if abs(v) > 1e-6 and abs(v - 1) > 1e-6:
            bad.append(f"{r['decision']} {'/'.join(keys)} = {v:g} is not 0 or 1")
        if v > 0.5:
            if ts:
                tof[ks[0]].add(ts[0])
            if ss:
                sof[ks[0]].add(ss[0])
    if not seen:
        return ["no assignment of courses to teachers or slots in the export", "COST 0.000000"]
    score = 0.0
    load = {t: 0.0 for t in teachers}
    busy: dict[tuple[str, str], list[str]] = {}
    for k, r in courses.items():
        if len(tof[k]) != 1:
            bad.append(f"{k}: {len(tof[k])} teachers")
        if len(sof[k]) != 1:
            bad.append(f"{k}: {len(sof[k])} slots")
        for t in tof[k]:
            if (t, k) not in qual:
                bad.append(f"{k}: {t} is not qualified")
            score += qual.get((t, k), 0.0)
            load[t] += float(r["weekly_hours"])
            for s in sof[k]:
                busy.setdefault((t, s), []).append(k)
                if (t, s) in unavail:
                    bad.append(f"{k}: {t} is unavailable in {s}")
        for s in sof[k]:
            score -= pen if slots[s] else 0.0
    bad += [f"{t}: {h:g} weekly hours above {teachers[t]:g}" for t, h in load.items() if h > teachers[t] + 1e-6]
    bad += [f"{t} teaches {', '.join(ks)} together in {s}" for (t, s), ks in busy.items() if len(ks) > 1]
    for s in slots:
        here = [k for k in courses if s in sof[k]]
        coh: dict[str, list[str]] = {}
        for k in here:
            coh.setdefault(courses[k]["cohort"], []).append(k)
        bad += [f"{s}: cohort {g} has {', '.join(ks)} together" for g, ks in coh.items() if len(ks) > 1]
        for kind, n in rooms.items():
            used = sum(1 for k in here if courses[k]["room_type"] == kind)
            if used > n + 1e-6:
                bad.append(f"{s}: {used} {kind} courses, {n:g} rooms")
    return bad + [f"COST {score:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
