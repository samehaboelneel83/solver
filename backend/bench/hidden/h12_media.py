"""Hidden problem 12: media budget across channels and weeks (LP with diminishing returns by tiers).

    python -m bench.hidden.h12_media gen [S M]
    python -m bench.hidden.h12_media check <case> <export.csv>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (4, 4), "M": (10, 26)}  # channels, weeks
OUT = Path(__file__).parent / "cases" / "h12"
DIGITAL_SHARE = 40  # percent of the total spend, at least
CHANNELS = [("TV", "traditional"), ("SEARCH", "digital"), ("RADIO", "traditional"), ("SOCIAL", "digital"),
            ("OUTDOOR", "traditional"), ("VIDEO", "digital"), ("PRINT", "traditional"), ("DISPLAY", "digital"),
            ("CINEMA", "traditional"), ("INFLUENCER", "digital")]


def make(size: str, seed: int = 12) -> dict:
    nc, nw = SIZES[size]
    rng = np.random.default_rng(seed * 13 + nw)
    C = []
    for i in range(nc):
        name, kind = CHANNELS[i]
        w1 = int(rng.integers(20, 60)) * 10
        w2 = int(rng.integers(20, 60)) * 10
        w3 = int(rng.integers(20, 80)) * 10
        r1 = round(float(rng.uniform(4, 12)), 1)
        r2 = round(r1 * float(rng.uniform(0.45, 0.75)), 1)
        r3 = round(r2 * float(rng.uniform(0.3, 0.6)), 1)
        C.append(dict(id=name, kind=kind, t=[(w1, r1), (w2, r2), (w3, r3)]))
    W = [f"W{i + 1:02d}" for i in range(nw)]
    season = np.round(rng.uniform(0.7, 1.3, nw), 2)
    full = sum(sum(w for w, _ in c["t"]) for c in C)  # per week
    budget = int(full * nw * 0.35 / 100) * 100
    for c in C:
        c["min"] = int(budget * rng.uniform(0.0, 0.06) / 100) * 100
        c["max"] = int(budget * rng.uniform(0.25, 0.45) / 100) * 100
    weekcap = [int(budget / nw * rng.uniform(1.1, 1.6) / 10) * 10 for _ in W]
    black = sorted({(C[int(rng.integers(nc))]["id"], W[int(rng.integers(nw))]) for _ in range(max(2, nc * nw // 12))})
    return dict(C=C, W=W, season=season, budget=budget, weekcap=weekcap, black=black)


def solve(d: dict, seconds: float) -> dict:
    from scipy.optimize import linprog

    C, W = d["C"], d["W"]
    black = set(d["black"])
    idx = {}
    for ci, c in enumerate(C):
        for wi, w in enumerate(W):
            if (c["id"], w) in black:
                continue
            for k in range(3):
                idx[(ci, wi, k)] = len(idx)
    n = len(idx)
    cost = np.zeros(n)
    bounds = []
    for (ci, wi, k), j in idx.items():
        width, rate = C[ci]["t"][k]
        cost[j] = -rate * d["season"][wi]
        bounds.append((0, width))
    A, b = [], []

    def row(terms, rhs):
        r = np.zeros(n)
        for j, v in terms:
            r[j] += v
        A.append(r); b.append(rhs)

    row([(j, 1) for j in idx.values()], d["budget"])
    for wi in range(len(W)):
        row([(j, 1) for (ci, ww, k), j in idx.items() if ww == wi], d["weekcap"][wi])
    for ci, c in enumerate(C):
        mine = [(j, 1) for (cc, wi, k), j in idx.items() if cc == ci]
        row(mine, c["max"])
        row([(j, -v) for j, v in mine], -c["min"])
    share = DIGITAL_SHARE / 100
    row([(j, share - (1 if C[ci]["kind"] == "digital" else 0)) for (ci, wi, k), j in idx.items()], 0)
    res = linprog(cost, A_ub=np.array(A), b_ub=b, bounds=bounds, method="highs", options={"time_limit": seconds})
    if res.status != 0:
        return {"feasible": False}
    spend = {}
    for (ci, wi, k), j in idx.items():
        spend[(ci, wi)] = spend.get((ci, wi), 0.0) + res.x[j]
    exp = ["decision,key1,key2,value"]
    for (ci, wi), x in spend.items():
        if x > 1e-9:
            exp.append(f"spend,{C[ci]['id']},{W[wi]},{x:.9f}")
    return {"feasible": True, "goal": -float(res.fun), "bound": -float(res.fun), "optimal": True,
            "export": "\n".join(exp) + "\n"}


def instance(size: str) -> tuple[dict, dict]:
    for seed in range(12, 80):
        d = make(size, seed)
        ref = solve(d, 120)
        if ref["feasible"]:
            return d, ref
    raise RuntimeError("no feasible instance")


def write(size: str) -> Path:
    d, ref = instance(size)
    folder = OUT / size
    write_csv(folder / "channels.csv", ["channel", "type", "min_total_spend", "max_total_spend",
                                         "tier1_spend", "tier1_reach_per_k", "tier2_spend", "tier2_reach_per_k",
                                         "tier3_spend", "tier3_reach_per_k"],
              [[c["id"], c["kind"], c["min"], c["max"]] + [x for t in c["t"] for x in t] for c in d["C"]])
    write_csv(folder / "weeks.csv", ["week", "max_spend", "seasonality"],
              [(w, d["weekcap"][i], float(d["season"][i])) for i, w in enumerate(d["W"])])
    write_csv(folder / "unavailable.csv", ["channel", "week"], d["black"])
    names = ["channels.csv", "weeks.csv", "unavailable.csv"]
    rules = (f"All money is in thousand EGP. The campaign has a total budget of {d['budget']:,} (thousand EGP); "
             "it does not have to be spent in full. Rules (all hard): the spend on a channel in a week may be any "
             "amount (fractions are fine) from 0 up to tier1_spend + tier2_spend + tier3_spend of that channel; a "
             "channel listed as unavailable in a week gets nothing that week. The total spend in a week is at most "
             "the week's max_spend. Each channel's total over all weeks is between its min_total_spend and its "
             f"max_total_spend. Digital channels together get at least {DIGITAL_SHARE}% of the total spend. Reach "
             "has diminishing returns within each channel and week: the first tier1_spend thousand EGP bring "
             "tier1_reach_per_k thousand people per thousand EGP, the next tier2_spend bring tier2_reach_per_k, "
             "and the next tier3_spend bring tier3_reach_per_k; this reach is then multiplied by the week's "
             "seasonality. Goal, as large as possible: the total reach (thousand people) over all channels and "
             "weeks. Report the spend per channel and week, the total spend per channel and its share, the total "
             "reach, the digital share, and which limits are binding.")
    head = ('Please build this in a new workspace called "{workspace}". Call the problem "Media plan". '
            f"Marketing must split the campaign budget across {len(d['C'])} channels over {len(d['W'])} weeks "
            "to reach as many people as possible.\n\n")
    if size == "S":
        body = "\n\n".join(f"{lab}:\n{csv_text(folder / n)}" for lab, n in zip(
            ["Channels (spend in thousand EGP, reach in thousand people per thousand EGP)", "Weeks",
             "Channel unavailable in a week"], names))
        files = []
    else:
        body = ("The data are in the attached files: channels.csv (type, limits on the total spend and the reach "
                "tiers per channel), weeks.csv (spend limit and seasonality per week), unavailable.csv (channels "
                "that cannot be booked in a week).")
        files = names
    message = (head + body + "\n\n" + rules +
               "\n\nEverything you need is here: please propose the model without further questions, then solve it.")
    write_case(folder, message, {})
    cost = float(check(folder, ref["export"])[-1].split()[1])
    lead = f"{cost:,.0f}"[:-2].replace(",", ",?")
    report = [["spend per channel and week", r"W\d\d"],
              ["spend per channel", r"(" + "|".join(c["id"] for c in d["C"]) + r")[^\n]{0,60}\d"],
              ["total reach", lead + r"\d\d"],
              ["digital share", r"digital[^\n]{0,60}%|%[^\n]{0,60}digital"],
              ["binding limits", r"\bbind|tight|at (its|the) (limit|max|cap)"]]
    write_case(folder, message, {"problem": "h12", "size": size, "kind": "exact", "goal": cost,
                                 "known_feasible": cost, "bound": cost, "sense": "maximize",
                                 "report": report, "files": files})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    ch = {r["channel"]: r for r in read_csv(folder / "channels.csv")}
    weeks = {r["week"]: r for r in read_csv(folder / "weeks.csv")}
    black = {(r["channel"], r["week"]) for r in read_csv(folder / "unavailable.csv")}
    msg = (folder / "message.txt").read_text(encoding="utf-8")
    budget = float(re.search(r"total budget of ([\d,]+)", msg).group(1).replace(",", ""))
    share = float(re.search(r"at least (\d+)% of the total spend", msg).group(1)) / 100
    wl = list(weeks)

    def week(x: str):
        if x in weeks:
            return x
        m = re.fullmatch(r"[A-Za-z_]*0*(\d+)", (x or "").strip())
        if m and 1 <= int(m.group(1)) <= len(wl):
            return wl[int(m.group(1)) - 1]
        return None

    by: dict[str, dict[tuple, float]] = {}
    for r in export_rows(export_csv):
        a, b = r.get("key1") or "", r.get("key2") or ""
        if a in weeks and b in ch:
            a, b = b, a
        w = week(b)
        if a not in ch or w is None:
            continue
        cell = by.setdefault(r["decision"], {})
        # A model may keep the spend per tier (a third key): the spend in the week is the sum.
        cell[(a, w)] = cell.get((a, w), 0.0) + float(r["value"])
    if not by:
        return ["no decision over (channel, week) in the export"]
    name = max(by, key=lambda n: (any(v not in (0.0, 1.0) for v in by[n].values()), len(by[n])))
    x = by[name]
    bad: list[str] = []
    reach = 0.0
    total = 0.0
    digital = 0.0
    per_c = {c: 0.0 for c in ch}
    per_w = {w: 0.0 for w in weeks}
    for (c, w), q in x.items():
        if abs(q) <= 1e-9:
            continue
        r = ch[c]
        if q < -1e-6:
            bad.append(f"{c} {w}: negative spend {q:g}")
        if (c, w) in black:
            bad.append(f"{c} {w}: spend {q:g} in a week the channel is unavailable")
        tiers = [(float(r[f"tier{k}_spend"]), float(r[f"tier{k}_reach_per_k"])) for k in (1, 2, 3)]
        top = sum(t for t, _ in tiers)
        if q > top + 1e-6:
            bad.append(f"{c} {w}: spend {q:g} above the {top:g} the tiers allow")
        left, got = max(q, 0.0), 0.0
        for width, rate in tiers:
            use = min(left, width)
            got += use * rate
            left -= use
        reach += got * float(weeks[w]["seasonality"])
        total += q
        per_c[c] += q
        per_w[w] += q
        if r["type"] == "digital":
            digital += q
    if total > budget + 1e-6:
        bad.append(f"total spend {total:g} above the budget {budget:g}")
    for w, r in weeks.items():
        if per_w[w] > float(r["max_spend"]) + 1e-6:
            bad.append(f"{w}: spend {per_w[w]:g} above {r['max_spend']}")
    for c, r in ch.items():
        if per_c[c] < float(r["min_total_spend"]) - 1e-6 or per_c[c] > float(r["max_total_spend"]) + 1e-6:
            bad.append(f"{c}: total {per_c[c]:g} outside {r['min_total_spend']}..{r['max_total_spend']}")
    if digital < share * total - 1e-6:
        bad.append(f"digital spend {digital:g} below {share:.0%} of {total:g}")
    return bad + [f"COST {reach:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
