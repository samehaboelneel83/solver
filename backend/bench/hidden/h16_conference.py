"""Hidden problem 16: conference session scheduling into rooms and time slots (3-index assignment, clash costs).

    python -m bench.hidden.h16_conference gen [S M]
    python -m bench.hidden.h16_conference check <case> <export.csv>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (8, 3, 3), "M": (44, 5, 10)}  # sessions, rooms, slots
OUT = Path(__file__).parent / "cases" / "h16"
CLASH_W = 20  # EGP per attendee who wanted two sessions held in the same slot
ROOMS = [("NILE_HALL", 400, True, 3000), ("LUXOR", 220, True, 1800), ("ASWAN", 150, False, 900),
         ("SIWA", 120, True, 1100), ("DAHAB", 80, False, 500), ("FAYOUM", 60, True, 600)]


def make(size: str, seed: int = 16) -> dict:
    ns, nr, nt = SIZES[size]
    rng = np.random.default_rng(seed * 29 + ns)
    pick = [0, 2, 4] if nr == 3 else list(range(nr))
    R = [dict(id=ROOMS[i][0], cap=ROOMS[i][1], av=ROOMS[i][2], cost=ROOMS[i][3]) for i in pick]
    T = [f"T{t + 1:02d}" for t in range(nt)]
    caps = sorted((r["cap"] for r in R), reverse=True)
    n_speakers = max(2, int(ns * 0.75))
    P = [f"SPK{i + 1:02d}" for i in range(n_speakers)]
    S = []
    for i in range(ns):
        cap = caps[int(rng.integers(len(caps)))]
        S.append(dict(id=f"SES{i + 1:02d}", speaker=P[i] if i < n_speakers else P[int(rng.integers(n_speakers))],
                      att=int(cap * rng.uniform(0.5, 0.98)), av=bool(rng.random() < 0.4)))
    unav = sorted({(P[int(rng.integers(n_speakers))], T[int(rng.integers(nt))]) for _ in range(max(2, ns // 4))})
    clash = {}
    for _ in range(int(ns * 2.5)):
        a, b = sorted(rng.choice(ns, 2, replace=False).tolist())
        clash[(S[a]["id"], S[b]["id"])] = int(rng.integers(5, 60))
    return dict(S=S, R=R, T=T, unav=unav, clash=clash)


def solve(d: dict, seconds: float) -> dict:
    from ortools.sat.python import cp_model

    S, R, T = d["S"], d["R"], d["T"]
    unav = set(d["unav"])
    m = cp_model.CpModel()
    x = {}
    for s in S:
        for r in R:
            if r["cap"] < s["att"] or (s["av"] and not r["av"]):
                continue
            for t in T:
                if (s["speaker"], t) in unav:
                    continue
                x[(s["id"], r["id"], t)] = m.NewBoolVar("")
    for s in S:
        opts = [v for k, v in x.items() if k[0] == s["id"]]
        if not opts:
            return {"feasible": False}
        m.AddExactlyOne(opts)
    for r in R:
        for t in T:
            m.AddAtMostOne([v for k, v in x.items() if k[1] == r["id"] and k[2] == t])
    at = {(s["id"], t): sum(v for k, v in x.items() if k[0] == s["id"] and k[2] == t) for s in S for t in T}
    speakers = {}
    for s in S:
        speakers.setdefault(s["speaker"], []).append(s["id"])
    for sp, mine in speakers.items():
        if len(mine) > 1:
            for t in T:
                m.Add(sum(at[(i, t)] for i in mine) <= 1)
    obj = [r["cost"] * v for k, v in x.items() for r in R if r["id"] == k[1]]
    for (a, b), w in d["clash"].items():
        for t in T:
            y = m.NewBoolVar("")
            m.Add(at[(a, t)] + at[(b, t)] - 1 <= y)
            obj.append(CLASH_W * w * y)
    m.Minimize(sum(obj))
    sol = cp_model.CpSolver()
    sol.parameters.max_time_in_seconds = seconds
    sol.parameters.num_workers = 8
    st = sol.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"feasible": False}
    exp = ["decision,key1,key2,key3,value"]
    for k, v in x.items():
        if sol.Value(v):
            exp.append(f"schedule,{k[0]},{k[1]},{k[2]},1")
    return {"feasible": True, "goal": sol.ObjectiveValue(), "bound": sol.BestObjectiveBound(),
            "optimal": st == cp_model.OPTIMAL, "export": "\n".join(exp) + "\n"}


def instance(size: str) -> tuple[dict, dict]:
    for seed in range(16, 90):
        d = make(size, seed)
        ref = solve(d, 240)
        if ref["feasible"]:
            return d, ref
    raise RuntimeError("no feasible instance")


def write(size: str) -> Path:
    d, ref = instance(size)
    folder = OUT / size
    write_csv(folder / "sessions.csv", ["session", "speaker", "expected_attendance", "needs_av"],
              [(s["id"], s["speaker"], s["att"], "yes" if s["av"] else "no") for s in d["S"]])
    write_csv(folder / "rooms.csv", ["room", "capacity", "has_av", "hire_cost_per_slot"],
              [(r["id"], r["cap"], "yes" if r["av"] else "no", r["cost"]) for r in d["R"]])
    write_csv(folder / "slots.csv", ["slot", "order"], [(t, i + 1) for i, t in enumerate(d["T"])])
    write_csv(folder / "speaker_unavailable.csv", ["speaker", "slot"], d["unav"])
    write_csv(folder / "shared_interest.csv", ["session_a", "session_b", "shared_attendees"],
              [(a, b, w) for (a, b), w in sorted(d["clash"].items())])
    names = ["sessions.csv", "rooms.csv", "slots.csv", "speaker_unavailable.csv", "shared_interest.csv"]
    rules = ("Rules (all hard): every session is held exactly once, in one room and one time slot. A room holds at "
             "most one session per slot. A session's expected attendance must fit the room's capacity, and a "
             "session that needs AV must be in a room that has AV. Sessions given by the same speaker must be in "
             "different slots, and no session may be in a slot its speaker is listed as unavailable for. Goal, as "
             "small as possible, in EGP: the hire cost of the rooms (the room's hire cost per slot for every "
             f"session held in it) plus {CLASH_W} EGP for every shared attendee of two sessions held in the same slot "
             "(the shared_interest list gives, for pairs of sessions, how many attendees want to attend both). "
             "Report the room and slot of each session, the programme by slot, the total cost split into room hire "
             "and clash penalty, the pairs of sessions that still clash, and how full each session's room is.")
    head = ('Please build this in a new workspace called "{workspace}". Call the problem "Conference programme". '
            f"We are organising a conference with {len(d['S'])} sessions and must place each one in one of "
            f"{len(d['R'])} rooms and one of {len(d['T'])} time slots.\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in zip(
            ["Sessions", "Rooms (hire cost in EGP per slot)", "Time slots", "Speakers unavailable in a slot",
             "Shared interest between sessions"], names))
        files = []
    else:
        body = ("The data are in the attached files: sessions.csv (speaker, expected attendance, AV need), "
                "rooms.csv (capacity, AV, hire cost per slot), slots.csv, speaker_unavailable.csv, "
                "shared_interest.csv (attendees who want both sessions of a pair).")
        files = names
    message = (head + body + "\n\n" + rules +
               "\n\nEverything you need is here: please propose the model without further questions, then solve it.")
    write_case(folder, message, {})
    cost = float(check(folder, ref["export"])[-1].split()[1])
    report = [["room and slot per session", r"SES\d\d\W+.{0,40}(" + "|".join(r["id"] for r in d["R"]) + r"|T\d\d)"],
              ["programme by slot", r"T\d\d"],
              ["total cost", f"{cost:,.0f}".replace(",", ",?")],
              ["hire vs clash penalty", r"clash|penalt"],
              ["room fill", r"%|full|utili[sz]|occupan"]]
    write_case(folder, message, {"problem": "h16", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": cost if ref["optimal"] else None, "known_feasible": cost,
                                 "bound": cost if ref["optimal"] else ref["bound"], "sense": "minimize", "report": report, "files": files})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    ses = {r["session"]: r for r in read_csv(folder / "sessions.csv")}
    rooms = {r["room"]: r for r in read_csv(folder / "rooms.csv")}
    slots = [r["slot"] for r in sorted(read_csv(folder / "slots.csv"), key=lambda r: int(r["order"]))]
    unav = {(r["speaker"], r["slot"]) for r in read_csv(folder / "speaker_unavailable.csv")}
    clash = {(r["session_a"], r["session_b"]): float(r["shared_attendees"])
             for r in read_csv(folder / "shared_interest.csv")}

    def slot(k: str):
        if k in slots:
            return k
        m = re.fullmatch(r"[A-Za-z_]*0*(\d+)", (k or "").strip())
        if m and 1 <= int(m.group(1)) <= len(slots):
            return slots[int(m.group(1)) - 1]
        return None

    by: dict[str, dict[tuple, float]] = {}
    for r in export_rows(export_csv):
        keys = [r.get(f"key{i}") or "" for i in (1, 2, 3)]
        if r.get("key4"):
            continue
        s_ = next((k for k in keys if k in ses), None)
        r_ = next((k for k in keys if k in rooms), None)
        rest = [k for k in keys if k not in (s_, r_)]
        t_ = slot(rest[0]) if len(rest) == 1 else None
        if s_ and r_ and t_:
            by.setdefault(r["decision"], {})[(s_, r_, t_)] = float(r["value"])
    if not by:
        return ["no decision over (session, room, slot) in the export"]
    name = max(by, key=lambda n: (all(v in (0.0, 1.0) for v in by[n].values()), len([v for v in by[n].values() if v > 1e-6])))
    x = {k: v for k, v in by[name].items() if abs(v) > 1e-6}
    bad: list[str] = []
    cost = 0.0
    where: dict[str, list[tuple[str, str]]] = {}
    used: dict[tuple[str, str], str] = {}
    for (s, r, t), v in x.items():
        if abs(v - 1) > 1e-6:
            bad.append(f"{s} {r} {t}: value {v:g}, expected yes/no")
        where.setdefault(s, []).append((r, t))
        if (r, t) in used:
            bad.append(f"{r} {t}: holds {used[(r, t)]} and {s}")
        used[(r, t)] = s
        sr, rr = ses[s], rooms[r]
        if float(sr["expected_attendance"]) > float(rr["capacity"]):
            bad.append(f"{s} ({sr['expected_attendance']}) does not fit {r} ({rr['capacity']})")
        if sr["needs_av"] == "yes" and rr["has_av"] != "yes":
            bad.append(f"{s} needs AV, {r} has none")
        if (sr["speaker"], t) in unav:
            bad.append(f"{s}: speaker {sr['speaker']} unavailable in {t}")
        cost += float(rr["hire_cost_per_slot"])
    slot_of = {}
    for s in ses:
        got = where.get(s, [])
        if len(got) != 1:
            bad.append(f"{s} held {len(got)} times, exactly once is needed")
        if got:
            slot_of[s] = got[0][1]
    seen: dict[tuple[str, str], str] = {}
    for s, t in slot_of.items():
        sp = ses[s]["speaker"]
        if (sp, t) in seen:
            bad.append(f"speaker {sp} has {seen[(sp, t)]} and {s} both in {t}")
        seen[(sp, t)] = s
    for (a, b), w in clash.items():
        if a in slot_of and b in slot_of and slot_of[a] == slot_of[b]:
            cost += CLASH_W * w
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
