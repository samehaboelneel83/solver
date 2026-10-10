"""Hidden problem h05 (scheduling with precedence written as linear rules).

    python -m bench.hidden.h05_site gen [S M]
    python -m bench.hidden.h05_site check <case> <export.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, export_rows, read_csv, write_csv
from bench.hidden._util_a import CLOSE, OPEN, export_text, finish, num_re, search

SIZES = {"S": 7, "M": 28}  # activities
OUT = Path(__file__).parent / "cases" / "h05"


def make(size: str, seed: int = 5) -> dict:
    n = SIZES[size]
    rng = np.random.default_rng(seed * 49979687 + n)
    A = [f"A{i + 1:02d}" for i in range(n)]
    dur = {a: int(rng.integers(1, 4 if n < 10 else 6)) for a in A}
    crews = {a: int(rng.integers(1, 5)) for a in A}
    crane = {a: bool(rng.random() < 0.3) for a in A}
    preds = []
    for i in range(1, n):
        for j in sorted(set(rng.choice(i, min(i, int(rng.integers(1, 3))), replace=False).tolist())):
            if j >= i - 6 or rng.random() < 0.3:
                preds.append((A[i], A[j]))
    release = {a: 1 for a in A}
    for a in A:
        if rng.random() < 0.2:
            release[a] = int(rng.integers(2, 5))
    # earliest finish (critical path)
    es = {}
    for a in A:
        es[a] = max([release[a]] + [es[p] + dur[p] for (b, p) in preds if b == a])
    cp = max(es[a] + dur[a] - 1 for a in A)
    H = max(int(cp * 1.5) + 2, sum(dur[a] for a in A if crane[a]) + 2)
    W = [f"W{t + 1:02d}" for t in range(H)]
    avg = sum(dur[a] * crews[a] for a in A) / cp
    base = max(max(crews.values()), int(round(avg * 0.8)))
    avail = {w: base - (1 if rng.random() < 0.15 else 0) for w in W}
    return dict(A=A, W=W, dur=dur, crews=crews, crane=crane, preds=preds, release=release, avail=avail,
                target=cp + 1, late_penalty=60000, crew_cost=15000, max_extra=2)


def solve(d: dict, seconds: float = 300):
    from ortools.sat.python import cp_model

    A, W = d["A"], d["W"]
    H = len(W)
    md = cp_model.CpModel()
    x = {(a, s): md.NewBoolVar(f"x{a}{s}") for a in A for s in range(d["release"][a], H - d["dur"][a] + 2)}
    start = {}
    for a in A:
        md.AddExactlyOne([v for (aa, _), v in x.items() if aa == a])
        start[a] = sum(s * v for (aa, s), v in x.items() if aa == a)
    for b, p in d["preds"]:
        md.Add(start[b] >= start[p] + d["dur"][p])
    extra = {}
    for t, w in enumerate(W, start=1):
        on = [(a, v) for (a, s), v in x.items() if s <= t <= s + d["dur"][a] - 1]
        extra[w] = md.NewIntVar(0, d["max_extra"], f"e{w}")
        md.Add(sum(d["crews"][a] * v for a, v in on) <= d["avail"][w] + extra[w])
        md.Add(sum(v for a, v in on if d["crane"][a]) <= 1)
    fin = md.NewIntVar(0, H, "fin")
    for a in A:
        md.Add(fin >= start[a] + d["dur"][a] - 1)
    late = md.NewIntVar(0, H, "late")
    md.Add(late >= fin - d["target"])
    md.Minimize(d["crew_cost"] * sum(extra.values()) + d["late_penalty"] * late)
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = seconds
    sv.parameters.num_workers = 8
    st = sv.Solve(md)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    rows = [("start", (a, W[s - 1]), 1.0) for (a, s), v in x.items() if sv.Value(v)]
    return {"goal": sv.ObjectiveValue(), "bound": sv.BestObjectiveBound(), "optimal": st == cp_model.OPTIMAL,
            "export": export_text(rows)}


def write(size: str) -> Path:
    seed, d, ref = search(make, solve, size, 5, 280)
    folder = OUT / size
    A, W = d["A"], d["W"]
    write_csv(folder / "activities.csv", ["activity", "duration_weeks", "crews_per_week", "uses_crane", "earliest_start_week"],
              [(a, d["dur"][a], d["crews"][a], "yes" if d["crane"][a] else "no", W[d["release"][a] - 1]) for a in A])
    write_csv(folder / "precedence.csv", ["activity", "predecessor"], d["preds"])
    write_csv(folder / "weeks.csv", ["week", "crews_available"], [(w, d["avail"][w]) for w in W])
    write_csv(folder / "project.csv", ["target_finish_week", "late_penalty_per_week", "extra_crew_cost_per_week",
                                       "max_extra_crews_per_week"],
              [(W[d["target"] - 1] if d["target"] <= len(W) else f"W{d['target']:02d}", d["late_penalty"], d["crew_cost"], d["max_extra"])])
    names = ["activities.csv", "precedence.csv", "weeks.csv", "project.csv"]
    head = (OPEN.format(name="Site schedule") + f"We are building a commercial block and must schedule its "
            f"{len(A)} activities week by week over a {len(W)}-week window ({W[0]} to {W[-1]}), deciding the start week "
            "of each activity.\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in [
            ("Activities", names[0]), ("Precedence (an activity starts only after its predecessor has finished)", names[1]),
            ("Own crews available per week", names[2]), ("Project terms", names[3])])
        files: list[str] = []
    else:
        body = ("The data are in the attached files: activities.csv (duration in weeks, crews needed in every week it "
                "runs, whether it uses the tower crane, earliest start week), precedence.csv (activity - predecessor "
                "pairs), weeks.csv (our own crews available in each week), project.csv (target finish week, late "
                "penalty, cost of an extra crew-week, maximum extra crews per week).")
        files = names
    rules = ("Rules (all hard): every activity starts once, in a whole week no earlier than its earliest start week, "
             "and then runs without a break for its duration (an activity of 3 weeks starting in W04 runs in W04, W05 "
             f"and W06) and must end by {W[-1]}. An activity may start only in a week after all its predecessors "
             "have ended (start week >= predecessor's start week + predecessor's duration). In every week, the "
             "crews needed by the activities running are at most our own crews available plus the extra crews we "
             "hire that week, and we can hire at most the maximum extra crews per week. There is one tower crane: "
             "at most one crane activity runs in any week. Goal: the lowest cost = extra crew cost per crew-week x "
             "extra crews hired over all weeks + late penalty x the number of weeks the last activity ends after "
             "the target finish week (0 if it ends on or before it). Report the start and end week of every "
             "activity, the project finish week, the extra crews hired per week, the total cost split into crews "
             "and lateness, and the critical activities.")
    message = head + body + "\n\n" + rules + "\n\n" + CLOSE
    report = [["start week per activity", r"A\d\d[^\n]{0,60}W\d\d"], ["total cost", num_re(ref["goal"])],
              ["finish week", r"finish|complet"], ["extra crews", r"extra crew|hire"],
              ["lateness", r"\blate|delay|penalt"], ["critical activities", r"critical"]]
    finish(folder, "h05", size, "minimize", ref, seed, check, message, report, files)
    return folder


def _starts(rows: list[dict], acts: dict, weeks: list[str]) -> dict[str, int] | None:
    """Start week (1-based) per activity from an (activity, week) indicator: a start indicator (one week) or a
    running indicator (its whole duration); or from an integer start week over the activity."""
    wi = {w: i + 1 for i, w in enumerate(weeks)}
    cand: dict[str, dict[str, dict[str, float]]] = {}
    single: dict[str, dict[str, float]] = {}
    for r in rows:
        k1, k2 = r.get("key1") or "", r.get("key2") or ""
        if any(r.get(k) for k in r if k.startswith("key") and k not in ("key1", "key2")):
            continue
        a, w = (k1, k2) if k1 in acts and k2 in wi else (k2, k1) if k2 in acts and k1 in wi else (None, None)
        if a:
            cand.setdefault(r["decision"], {}).setdefault(a, {})[w] = float(r["value"])
        elif k1 in acts and not k2:
            single.setdefault(r["decision"], {})[k1] = float(r["value"])
    order = sorted(cand, key=lambda n: (0 if "start" in n.lower() else 1, n))
    for n in order:
        got = {}
        for a in acts:
            on = sorted(wi[w] for w, v in cand[n].get(a, {}).items() if v > 0.5)
            dur = int(acts[a]["duration_weeks"])
            if len(on) == 1:
                got[a] = on[0]
            elif len(on) == dur and on == list(range(on[0], on[0] + dur)):
                got[a] = on[0]
            else:
                break
        else:
            return got
    for n in sorted(single, key=lambda n: (0 if "start" in n.lower() else 1, n)):
        vals = single[n]
        if set(vals) == set(acts) or len(vals) >= len(acts) - 1:
            off = 1 if min(vals.values()) < 0.5 else 0
            if all(abs(v - round(v)) < 1e-6 for v in vals.values()):
                return {a: int(round(vals.get(a, 0.0))) + off for a in acts}
    return None


def check(folder: Path, export_csv: str) -> list[str]:
    acts = {r["activity"]: r for r in read_csv(folder / "activities.csv")}
    preds = [(r["activity"], r["predecessor"]) for r in read_csv(folder / "precedence.csv")]
    wk = read_csv(folder / "weeks.csv")
    weeks = [r["week"] for r in wk]
    avail = [float(r["crews_available"]) for r in wk]
    pr = read_csv(folder / "project.csv")[0]
    target = int(pr["target_finish_week"].lstrip("W"))
    st = _starts(export_rows(export_csv), acts, weeks)
    if st is None:
        return ["no start week per activity could be read from the export", "COST 0.000000"]
    H = len(weeks)
    bad: list[str] = []
    for r in export_rows(export_csv):
        ks = {r.get("key1"), r.get("key2")}
        if ks & set(acts) and ks & set(weeks):
            v = float(r["value"])
            if abs(v) > 1e-6 and abs(v - 1) > 1e-6:
                bad.append(f"{r['decision']} {r.get('key1')}/{r.get('key2')} = {v:g} is not 0 or 1")
    for a, r in acts.items():
        s, dur = st[a], int(r["duration_weeks"])
        rel = weeks.index(r["earliest_start_week"]) + 1
        if s < rel:
            bad.append(f"{a} starts in week {s}, earliest {rel}")
        if s < 1 or s + dur - 1 > H:
            bad.append(f"{a} runs weeks {s}-{s + dur - 1}, outside the window")
    for b, p in preds:
        if st[b] < st[p] + int(acts[p]["duration_weeks"]):
            bad.append(f"{b} starts in week {st[b]} before {p} ends (week {st[p] + int(acts[p]['duration_weeks']) - 1})")
    extra_total = 0.0
    for t in range(1, H + 1):
        on = [a for a in acts if st[a] <= t <= st[a] + int(acts[a]["duration_weeks"]) - 1]
        need = sum(float(acts[a]["crews_per_week"]) for a in on)
        extra = max(0.0, need - avail[t - 1])
        if extra > float(pr["max_extra_crews_per_week"]) + 1e-6:
            bad.append(f"week {t}: {need:g} crews needed, {avail[t - 1]:g} own + at most {pr['max_extra_crews_per_week']} extra")
        extra_total += extra
        cr = [a for a in on if acts[a]["uses_crane"] == "yes"]
        if len(cr) > 1:
            bad.append(f"week {t}: crane used by {', '.join(cr)}")
    finish_wk = max(st[a] + int(acts[a]["duration_weeks"]) - 1 for a in acts)
    cost = extra_total * float(pr["extra_crew_cost_per_week"]) + max(0, finish_wk - target) * float(pr["late_penalty_per_week"])
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
