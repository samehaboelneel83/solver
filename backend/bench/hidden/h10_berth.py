"""Hidden problem 10: berth allocation over a planning horizon (time-indexed scheduling).

    python -m bench.hidden.h10_berth gen [S M]
    python -m bench.hidden.h10_berth check <case> <export.csv>
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (6, 2, 16), "M": (40, 4, 48)}  # vessels, berths, periods
OUT = Path(__file__).parent / "cases" / "h10"


def make(size: str, seed: int = 10) -> dict:
    nv, nb, T = SIZES[size]
    rng = np.random.default_rng(seed * 31 + nv)
    B = [dict(id=f"B{i + 1}", length=int(L), cranes=int(c))
         for i, (L, c) in enumerate(zip(rng.choice([220, 260, 300, 350, 400], nb), rng.integers(2, 5, nb)))]
    B[0]["length"] = 400
    V = []
    for i in range(nv):
        length = int(rng.integers(120, 380))
        moves = int(rng.integers(4, 15))  # crane-periods of work
        V.append(dict(id=f"V{i + 1:02d}", arrival=int(rng.integers(1, int(T * 0.6) + 1)), length=length,
                      work=moves, weight=int(rng.choice([1, 1, 2, 3]))))
    hand = {}
    for v in V:
        for b in B:
            if v["length"] <= b["length"]:
                hand[(v["id"], b["id"])] = int(math.ceil(v["work"] / b["cranes"]))
    return dict(V=V, B=B, T=T, hand=hand)


def solve(d: dict, seconds: float) -> dict:
    """Time-indexed: x[v, b, s] = vessel v starts at berth b in period s (a strong formulation for HiGHS)."""
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import lil_matrix

    V, B, T, hand = d["V"], d["B"], d["T"], d["hand"]
    cols = []
    for v in V:
        for b in B:
            dur = hand.get((v["id"], b["id"]))
            if dur is None:
                continue
            for s in range(v["arrival"], T - dur + 2):
                cols.append((v["id"], b["id"], s, dur, v["weight"] * (s + dur - v["arrival"])))
    n = len(cols)
    vid = {v["id"]: i for i, v in enumerate(V)}
    bid = {b["id"]: i for i, b in enumerate(B)}
    A = lil_matrix((len(V) + len(B) * T, n))
    for j, (v, b, s, dur, _) in enumerate(cols):
        A[vid[v], j] = 1
        for p in range(s, s + dur):
            A[len(V) + bid[b] * T + (p - 1), j] = 1
    lo = np.r_[np.ones(len(V)), np.full(len(B) * T, -np.inf)]
    hi = np.ones(len(V) + len(B) * T)
    if any(A[i].nnz == 0 for i in range(len(V))):
        return {"feasible": False}
    c = np.array([col[4] for col in cols], dtype=float)
    res = milp(c, constraints=LinearConstraint(A.tocsr(), lo, hi), integrality=np.ones(n),
               bounds=Bounds(np.zeros(n), np.ones(n)), options={"time_limit": seconds, "disp": False, "mip_rel_gap": 0})
    if res.x is None:
        return {"feasible": False}
    exp = ["decision,key1,key2,key3,value"]
    for (v, b, s, _, _), x in zip(cols, res.x):
        if x > 0.5:
            exp.append(f"start,{v},{b},{s},1")
    return {"feasible": True, "goal": float(res.fun), "bound": float(getattr(res, "mip_dual_bound", None) or res.fun),
            "optimal": res.status == 0, "export": "\n".join(exp) + "\n"}


def instance(size: str) -> tuple[dict, dict]:
    for seed in range(10, 60):
        d = make(size, seed)
        ref = solve(d, 200)
        if ref["feasible"]:
            return d, ref
    raise RuntimeError("no feasible instance")


def write(size: str) -> Path:
    d, ref = instance(size)
    folder = OUT / size
    T = d["T"]
    write_csv(folder / "vessels.csv", ["vessel", "arrival_period", "length_m", "priority_weight"],
              [(v["id"], v["arrival"], v["length"], v["weight"]) for v in d["V"]])
    write_csv(folder / "berths.csv", ["berth", "length_m"], [(b["id"], b["length"]) for b in d["B"]])
    write_csv(folder / "handling_periods.csv", ["vessel", "berth", "periods"],
              [(v, b, p) for (v, b), p in sorted(d["hand"].items())])
    names = ["vessels.csv", "berths.csv", "handling_periods.csv"]
    rules = (f"The planning horizon is periods 1 to {T} (each period is two hours). Rules (all hard): every vessel "
             "is berthed exactly once, at one berth, and stays there for the whole handling time given for that "
             "vessel at that berth (the handling time differs by berth because the berths have different cranes). "
             "A vessel can only use a berth at least as long as the vessel; a vessel-berth pair missing from the "
             "handling table is not allowed. A vessel cannot start before its arrival period. A vessel starting in "
             "period s with a handling time of h periods occupies the berth in periods s to s+h-1, and must finish "
             f"by period {T}. A berth serves at most one vessel in any period. The time in port of a vessel is "
             "s + h - arrival period (waiting plus handling). Goal, as small as possible: the sum over vessels of "
             "priority weight times time in port (in periods). Report the berth and start period of each vessel, "
             "each vessel's waiting time, the total weighted time in port, berth utilisation, and which vessels "
             "wait the longest.")
    head = ('Please build this in a new workspace called "{workspace}". Call the problem "Berth plan". '
            f"Our container terminal must plan which berth each of {len(d['V'])} expected vessels uses and when, "
            f"on {len(d['B'])} berths.\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in
                           zip(["Vessels", "Berths", "Handling time in periods per vessel and berth"], names))
        files = []
    else:
        body = ("The data are in the attached files: vessels.csv (arrival period, length and priority weight), "
                "berths.csv (length), handling_periods.csv (handling time in periods for each allowed "
                "vessel-berth pair).")
        files = names
    message = (head + body + "\n\n" + rules +
               "\n\nEverything you need is here: please propose the model without further questions, then solve it.")
    write_case(folder, message, {})
    cost = float(check(folder, ref["export"])[-1].split()[1])
    report = [["berth and start per vessel", r"V\d\d\W+.{0,40}B\d"],
              ["total weighted time in port", rf"\b{cost:.0f}\b"],
              ["waiting time", r"wait"],
              ["berth utilisation", r"utili[sz]|occup|busy"],
              ["longest waits", r"longest|most (waiting|delay)"]]
    write_case(folder, message, {"problem": "h10", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": cost if ref["optimal"] else None, "known_feasible": cost,
                                 "bound": cost if ref["optimal"] else ref["bound"], "sense": "minimize", "report": report, "files": files})
    return folder


def _period(x: str, T: int) -> int | None:
    m = re.fullmatch(r"[A-Za-z_]*0*(\d+)", (x or "").strip())
    if not m:
        return None
    p = int(m.group(1))
    return p if 1 <= p <= T else None


def check(folder: Path, export_csv: str) -> list[str]:
    vessels = {r["vessel"]: r for r in read_csv(folder / "vessels.csv")}
    berths = {r["berth"]: r for r in read_csv(folder / "berths.csv")}
    hand = {(r["vessel"], r["berth"]): int(r["periods"]) for r in read_csv(folder / "handling_periods.csv")}
    msg = (folder / "message.txt").read_text(encoding="utf-8")
    T = int(re.search(r"periods 1 to (\d+)", msg).group(1))
    rows = export_rows(export_csv)
    # (vessel, berth, period) cells with value 1: either the start period, or every occupied period.
    by: dict[str, dict[tuple[str, str, int], float]] = {}
    for r in rows:
        a, b, p = r.get("key1") or "", r.get("key2") or "", _period(r.get("key3") or "", T)
        if r.get("key4"):
            continue
        if a in berths and b in vessels:
            a, b = b, a
        if a in vessels and b in berths and p is not None:
            by.setdefault(r["decision"], {})[(a, b, p)] = float(r["value"])
    starts: dict[str, list[tuple[str, int]]] = {}
    bad: list[str] = []
    if by:
        name = max(by, key=lambda n: (all(v in (0.0, 1.0) for v in by[n].values()), len([v for v in by[n].values() if v > 1e-6])))
        cells = {k: v for k, v in by[name].items() if abs(v) > 1e-6}
        for (v, b, p), val in cells.items():
            if abs(val - 1) > 1e-6:
                bad.append(f"{v} {b} period {p}: value {val:g}, expected yes/no")
        per: dict[tuple[str, str], list[int]] = {}
        for (v, b, p) in cells:
            per.setdefault((v, b), []).append(p)
        for (v, b), ps in per.items():
            ps.sort()
            h = hand.get((v, b))
            if len(ps) > 1 and h is not None and len(ps) == h and ps == list(range(ps[0], ps[0] + h)):
                starts.setdefault(v, []).append((b, ps[0]))  # occupancy cells
            else:
                starts.setdefault(v, []).extend((b, p) for p in ps)
    else:
        # A berth choice (vessel, berth) and a start period per vessel.
        choice: dict[str, dict] = {}
        st: dict[str, dict] = {}
        for r in rows:
            a, b = r.get("key1") or "", r.get("key2") or ""
            if r.get("key3"):
                continue
            if a in vessels and b in berths:
                choice.setdefault(r["decision"], {})[(a, b)] = float(r["value"])
            elif a in vessels and not b:
                st.setdefault(r["decision"], {})[a] = float(r["value"])
        sname = next((n for n in st if "start" in n.lower() or "begin" in n.lower()), None)
        if not choice or sname is None:
            return ["no decision over (vessel, berth, period) in the export"]
        cname = max(choice, key=lambda n: len([v for v in choice[n].values() if v > 0.5]))
        for (v, b), val in choice[cname].items():
            if val > 0.5:
                s = st[sname].get(v, 0.0)
                if abs(s - round(s)) > 1e-6:
                    bad.append(f"{v}: start {s:g} is not a whole period")
                starts.setdefault(v, []).append((b, int(round(s))))
    cost = 0.0
    busy: dict[tuple[str, int], str] = {}
    for v, vr in vessels.items():
        got = starts.get(v, [])
        if len(got) != 1:
            bad.append(f"{v} is berthed {len(got)} times, exactly once is needed")
        for b, s in got:
            if (v, b) not in hand:
                bad.append(f"{v} at {b}: pair not allowed")
                continue
            if int(vr["length_m"]) > int(berths[b]["length_m"]):
                bad.append(f"{v} longer than {b}")
            h = hand[(v, b)]
            if s < int(vr["arrival_period"]):
                bad.append(f"{v} starts in period {s}, before its arrival {vr['arrival_period']}")
            if s + h - 1 > T or s < 1:
                bad.append(f"{v} at {b} runs outside periods 1 to {T}")
            for p in range(s, s + h):
                if (b, p) in busy:
                    bad.append(f"{b} period {p}: {busy[(b, p)]} and {v} overlap")
                busy[(b, p)] = v
            cost += float(vr["priority_weight"]) * (s + h - int(vr["arrival_period"]))
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
