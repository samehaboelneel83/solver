"""Problem 6: university examination timetabling.

    python -m bench.phase1.p06_timetable gen [S M L]
    python -m bench.phase1.p06_timetable check <case> <export.csv>

Each exam goes to one room in one time slot. Hard: two exams that share students never in the same slot; a
room holds one exam per slot; an exam's students fit the room; an exam marked "needs hall" goes to a hall; an
instructor's exam never in a slot that instructor is unavailable. Soft, in the goal: 10 per student who sits two
exams in consecutive slots of one day, 1 per empty seat, 20 per exam the busiest day has above the quietest.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import HERE, csv_text, decision_over, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (8, 4, 2, 2), "M": (40, 10, 5, 3), "L": (150, 30, 5, 3)}  # exams, rooms, days, slots a day
OUT = HERE / "cases" / "p06"
SECONDS = {"S": 60, "M": 300, "L": 600}
W_CONSEC, W_SEAT, W_BALANCE = 10, 1, 20


def make(size: str, seed: int = 6) -> dict:
    n_e, n_r, n_d, n_t = SIZES[size]
    rng = np.random.default_rng(seed + n_e)
    E = [f"EX{i + 1:03d}" for i in range(n_e)]
    R = [f"R{i + 1:02d}" for i in range(n_r)]
    T = [f"D{d + 1}S{t + 1}" for d in range(n_d) for t in range(n_t)]
    day = {s: int(s[1]) for s in T}
    n_i = max(2, n_e // 5)
    I = [f"INS{i + 1:02d}" for i in range(n_i)]
    hall = np.zeros(n_r, bool)
    hall[: max(1, n_r // 5)] = True
    cap = np.where(hall, rng.integers(150, 300, n_r), rng.integers(30, 90, n_r))
    size_ = rng.integers(15, 80, n_e)
    big = rng.random(n_e) < 0.12
    size_[big] = rng.integers(100, int(cap[hall].max()), int(big.sum()))
    needs_hall = size_ > cap[~hall].max() if (~hall).any() else np.ones(n_e, bool)
    needs_hall |= big
    instr = rng.integers(0, n_i, n_e)
    # Shared students: exams of one "programme" share many; random pairs share a few.
    prog = rng.integers(0, max(2, n_e // 6), n_e)
    conflicts = {}
    for a in range(n_e):
        for b in range(a + 1, n_e):
            shared = 0
            if prog[a] == prog[b]:
                shared = int(rng.integers(5, 25))
            elif rng.random() < 0.04:
                shared = int(rng.integers(1, 5))
            if shared:
                conflicts[(a, b)] = shared
    unavailable = {(i, s) for i in range(n_i) for s in T if rng.random() < 0.15}
    return dict(E=E, R=R, T=T, I=I, day=day, hall=hall, cap=cap, size=size_, needs_hall=needs_hall, instr=instr,
                conflicts=conflicts, unavailable=unavailable, n_t=n_t)


def solve(d: dict, seconds: float) -> dict:
    from ortools.sat.python import cp_model

    E, R, T = d["E"], d["R"], d["T"]
    md = cp_model.CpModel()
    x = {}
    for e in range(len(E)):
        for r in range(len(R)):
            if d["cap"][r] < d["size"][e] or (d["needs_hall"][e] and not d["hall"][r]):
                continue
            for t, s in enumerate(T):
                if (int(d["instr"][e]), s) in d["unavailable"]:
                    continue
                x[e, r, t] = md.NewBoolVar(f"x{e}_{r}_{t}")
    if any(not any(k[0] == e for k in x) for e in range(len(E))):
        return {"status": "no room or slot fits an exam"}
    for e in range(len(E)):
        md.AddExactlyOne([v for k, v in x.items() if k[0] == e])
    for r in range(len(R)):
        for t in range(len(T)):
            md.AddAtMostOne([v for k, v in x.items() if k[1] == r and k[2] == t])
    at = {}
    for e in range(len(E)):
        for t in range(len(T)):
            at[e, t] = md.NewBoolVar(f"at{e}_{t}")
            md.Add(at[e, t] == sum(v for k, v in x.items() if k[0] == e and k[2] == t))
    for (a, b) in d["conflicts"]:
        for t in range(len(T)):
            md.AddBoolOr([at[a, t].Not(), at[b, t].Not()])
    consec = []
    for (a, b), n in d["conflicts"].items():
        for t in range(len(T) - 1):
            if d["day"][T[t]] == d["day"][T[t + 1]]:
                for (p, q) in ((a, b), (b, a)):
                    z = md.NewBoolVar("")
                    md.AddBoolOr([at[p, t].Not(), at[q, t + 1].Not(), z])
                    consec.append(n * z)
    seats = sum(int(d["cap"][k[1]] - d["size"][k[0]]) * v for k, v in x.items())
    days = sorted(set(d["day"].values()))
    per_day = {dd: sum(at[e, t] for e in range(len(E)) for t in range(len(T)) if d["day"][T[t]] == dd) for dd in days}
    hi, lo = md.NewIntVar(0, len(E), "hi"), md.NewIntVar(0, len(E), "lo")
    for dd in days:
        md.Add(hi >= per_day[dd])
        md.Add(lo <= per_day[dd])
    md.Minimize(W_CONSEC * sum(consec) + W_SEAT * seats + W_BALANCE * (hi - lo))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = 8
    st = solver.Solve(md)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": solver.StatusName(st)}
    plan = {(E[e], R[r], T[t]) for (e, r, t), v in x.items() if solver.Value(v)}
    return {"goal": solver.ObjectiveValue(), "bound": solver.BestObjectiveBound(), "optimal": st == cp_model.OPTIMAL,
            "plan": plan}


def write(size: str) -> Path:
    for seed in range(6, 60):  # the first seed whose timetable exists (a group of exams that all share
        d = make(size, seed)    # students cannot have more members than there are slots)
        ref = solve(d, SECONDS[size])
        if "goal" in ref:
            break
    assert "goal" in ref, ref
    folder = OUT / size
    E, R, T, I = d["E"], d["R"], d["T"], d["I"]
    write_csv(folder / "exams.csv", ["id", "students", "instructor", "needs_hall"],
              [(E[e], int(d["size"][e]), I[int(d["instr"][e])], "yes" if d["needs_hall"][e] else "no")
               for e in range(len(E))])
    write_csv(folder / "rooms.csv", ["id", "capacity", "hall"],
              [(R[r], int(d["cap"][r]), "yes" if d["hall"][r] else "no") for r in range(len(R))])
    write_csv(folder / "slots.csv", ["id", "day", "position_in_day", "order"],
              [(s, d["day"][s], int(s.split("S")[1]), i + 1) for i, s in enumerate(T)])
    write_csv(folder / "shared_students.csv", ["exam_a", "exam_b", "students"],
              [(E[a], E[b], n) for (a, b), n in sorted(d["conflicts"].items())])
    write_csv(folder / "unavailable.csv", ["instructor", "slot"], sorted((I[i], s) for i, s in d["unavailable"]))
    names = ["exams.csv", "rooms.csv", "slots.csv", "shared_students.csv", "unavailable.csv"]
    rules = ("Rules (never broken): every exam is held once, in one room and one slot. Two exams that share "
             "students are never in the same slot. A room holds at most one exam per slot. An exam's students fit "
             "in its room's capacity. An exam with needs_hall = yes is held in a room with hall = yes. An exam is "
             "never in a slot its instructor is unavailable. Goal, as small as possible: 10 for every student who "
             "sits two exams in consecutive slots of the same day (the shared students of the two exams), plus 1 "
             "for every empty seat (room capacity minus the exam's students), plus 20 for each exam the busiest "
             "day has more than the quietest day. Report the timetable, the conflict count and a check that every "
             "rule holds, room utilization, students with consecutive exams, and alternative timetables ranked by "
             "this score.")
    head = (f'Please build this in a new workspace called "{{workspace}}". Call the problem "Exam timetable". '
            f"Schedule {len(E)} exams into {len(R)} rooms over {len(set(d['day'].values()))} days "
            f"({d['n_t']} slots a day).\n\n")
    if size == "S":
        body = "\n\n".join(f"{label}:\n{csv_text(folder / n)}" for label, n in [
            ("Exams (students, instructor, whether it needs a hall)", names[0]), ("Rooms", names[1]),
            ("Slots (day and position in the day; order runs through the week)", names[2]),
            ("Exams that share students (how many)", names[3]), ("Instructor unavailability", names[4])])
        files = []
    else:
        body = ("The data are in the attached files: exams.csv, rooms.csv, slots.csv, shared_students.csv (pairs "
                "of exams with students in common, and how many), unavailable.csv (slots an instructor cannot do).")
        files = names
    message = head + body + "\n\n" + rules + "\n\nEverything you need is here: please propose the model without further questions, then solve it."
    report = [["timetable (exam, room, slot)", r"EX\d{3}.{0,40}R\d\d.{0,40}D\dS\d"],
              ["conflict count / rules hold", r"conflict|clash|every rule (holds|is met)|no student"],
              ["room utilization", r"utili[sz]|empty seats?|seats? (used|wasted)"],
              ["consecutive exams", r"consecutive|back-to-back"],
              ["alternative timetables", r"alternative|other timetable"]]
    write_case(folder, message, {"problem": "p06", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": ref["goal"] if ref["optimal"] else None, "known_feasible": ref["goal"],
                                 "bound": ref["bound"], "sense": "minimize", "report": report, "files": files})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    ex = {r["id"]: r for r in read_csv(folder / "exams.csv")}
    rooms = {r["id"]: r for r in read_csv(folder / "rooms.csv")}
    slots = {r["id"]: r for r in read_csv(folder / "slots.csv")}
    shared = {(r["exam_a"], r["exam_b"]): int(r["students"]) for r in read_csv(folder / "shared_students.csv")}
    off = {(r["instructor"], r["slot"]) for r in read_csv(folder / "unavailable.csv")}
    name, x = decision_over(export_rows(export_csv), set(ex), set(rooms), set(slots))
    if not name:
        return ["no decision over (exam, room, slot) in the export"]
    on = [k for k, v in x.items() if v > 0.5]
    bad: list[str] = []
    where: dict[str, tuple[str, str]] = {}
    for e, r, s in on:
        if e in where:
            bad.append(f"{e} held more than once")
        where[e] = (r, s)
        if int(ex[e]["students"]) > int(rooms[r]["capacity"]):
            bad.append(f"{e} ({ex[e]['students']}) does not fit {r} ({rooms[r]['capacity']})")
        if ex[e]["needs_hall"] == "yes" and rooms[r]["hall"] != "yes":
            bad.append(f"{e} needs a hall, held in {r}")
        if (ex[e]["instructor"], s) in off:
            bad.append(f"{e} in {s}, when {ex[e]['instructor']} is unavailable")
    bad += [f"{e} not held" for e in ex if e not in where]
    used: dict[tuple[str, str], str] = {}
    for e, (r, s) in where.items():
        if (r, s) in used:
            bad.append(f"{r} in {s} holds {used[(r, s)]} and {e}")
        used[(r, s)] = e
    for (a, b), n in shared.items():
        if a in where and b in where and where[a][1] == where[b][1]:
            bad.append(f"{a} and {b} share {n} students and are both in {where[a][1]}")
    order = {s: int(v["order"]) for s, v in slots.items()}
    consec = sum(n for (a, b), n in shared.items() if a in where and b in where
                 and slots[where[a][1]]["day"] == slots[where[b][1]]["day"]
                 and abs(order[where[a][1]] - order[where[b][1]]) == 1)
    seats = sum(int(rooms[r]["capacity"]) - int(ex[e]["students"]) for e, (r, _) in where.items())
    per_day: dict[str, int] = {v["day"]: 0 for v in slots.values()}
    for _, s in where.values():
        per_day[slots[s]["day"]] += 1
    score = W_CONSEC * consec + W_SEAT * seats + W_BALANCE * (max(per_day.values()) - min(per_day.values()))
    return bad + [f"COST {score:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:260])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
