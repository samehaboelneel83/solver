"""Problem 9: cloud workload placement (large-scale bin packing with costs, separation and togetherness).

    python -m bench.phase1.p09_cloud gen [S M L]
    python -m bench.phase1.p09_cloud check <case> <export.csv>

Each workload goes to exactly one server in a region it allows (its latency requirement). A server's CPU,
memory and storage cover the workloads on it. A server with any workload is on and costs its running cost plus
its power x the energy price. Pairs marked "apart" run in different failure domains (zones); pairs marked
"together" run on the same server. Least cost. S and M have an exact reference (CP-SAT); L, 10,000 workloads,
has a constructed known-feasible placement and a lower bound (every server's cost per CPU at best).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import HERE, csv_text, read_csv, write_case, write_csv, export_rows

SIZES = {"S": (12, 4), "M": (300, 20), "L": (10000, 200)}  # workloads, servers
OUT = HERE / "cases" / "p09"
ENERGY = 1.5  # EGP per kWh, per hour of running
REGIONS = ["CAI", "ALX", "SUZ"]


def make(size: str, seed: int = 9) -> dict:
    n_w, n_s = SIZES[size]
    rng = np.random.default_rng(seed + n_w)
    S = [f"SRV{i + 1:03d}" for i in range(n_s)]
    W = [f"WL{i + 1:05d}" for i in range(n_w)]
    region = [REGIONS[i % len(REGIONS)] for i in range(n_s)]
    zone = [f"{region[i]}-Z{(i // len(REGIONS)) % 2 + 1}" for i in range(n_s)]
    big = rng.random(n_s) < 0.4
    wc = rng.integers(1, 9, n_w)
    wm = wc * rng.integers(2, 6, n_w)
    ws = rng.integers(20, 300, n_w)
    # Servers sized from the demand: about 1.8 times what all workloads need, so some can be shut down.
    unit = 1.8 * wc.sum() / (n_s * (0.6 + 0.4 * 2))
    cpu = np.rint(np.where(big, 2, 1) * unit).astype(int)
    mem = cpu * 5
    sto = np.rint(np.where(big, 2, 1) * 1.8 * ws.sum() / (n_s * 1.4)).astype(int)
    run_cost = np.rint(np.where(big, 40, 22) * rng.uniform(0.85, 1.15, n_s)).astype(int)
    power = np.round(np.where(big, 0.9, 0.5) * rng.uniform(0.8, 1.2, n_s), 2)
    allowed = [sorted(set(rng.choice(REGIONS, int(rng.integers(1, 3)), replace=False).tolist())) for _ in range(n_w)]
    pairs_apart, pairs_together = set(), set()
    for _ in range(max(1, n_w // 10)):
        a, b = sorted(rng.choice(n_w, 2, replace=False).tolist())
        if len({z for z, r in zip(zone, region) if r in set(allowed[a]) | set(allowed[b])}) > 1:
            pairs_apart.add((a, b))
    for _ in range(max(1, n_w // 20)):
        a, b = sorted(rng.choice(n_w, 2, replace=False).tolist())
        if set(allowed[a]) & set(allowed[b]) and (a, b) not in pairs_apart and wc[a] + wc[b] <= 32:
            pairs_together.add((a, b))
    return dict(S=S, W=W, region=region, zone=zone, cpu=cpu, mem=mem, sto=sto, run_cost=run_cost, power=power,
                wc=wc, wm=wm, ws=ws, allowed=allowed, apart=pairs_apart, together=pairs_together)


def cost_of(d: dict, s: int) -> float:
    return float(d["run_cost"][s] + d["power"][s] * ENERGY)


def solve(d: dict, seconds: float) -> dict:
    from ortools.sat.python import cp_model

    S, W = d["S"], d["W"]
    md = cp_model.CpModel()
    ok = {(w, s) for w in range(len(W)) for s in range(len(S)) if d["region"][s] in d["allowed"][w]}
    x = {k: md.NewBoolVar("") for k in ok}
    on = [md.NewBoolVar("") for _ in S]
    for w in range(len(W)):
        md.AddExactlyOne([x[w, s] for s in range(len(S)) if (w, s) in ok])
    for s in range(len(S)):
        here = [w for w in range(len(W)) if (w, s) in ok]
        for res, capv in (("wc", d["cpu"][s]), ("wm", d["mem"][s]), ("ws", d["sto"][s])):
            md.Add(sum(int(d[res][w]) * x[w, s] for w in here) <= int(capv) * on[s])
    for a, b in d["together"]:
        for s in range(len(S)):
            if (a, s) in ok and (b, s) in ok:
                md.Add(x[a, s] == x[b, s])
            elif (a, s) in ok:
                md.Add(x[a, s] == 0)
            elif (b, s) in ok:
                md.Add(x[b, s] == 0)
    zones = sorted(set(d["zone"]))
    for a, b in d["apart"]:
        for z in zones:
            za = [x[a, s] for s in range(len(S)) if d["zone"][s] == z and (a, s) in ok]
            zb = [x[b, s] for s in range(len(S)) if d["zone"][s] == z and (b, s) in ok]
            if za and zb:
                md.Add(sum(za) + sum(zb) <= 1)
    md.Minimize(sum(int(round(cost_of(d, s) * 100)) * on[s] for s in range(len(S))))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = seconds
    sv.parameters.num_workers = 8
    st = sv.Solve(md)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": sv.StatusName(st)}
    plan = {W[w]: S[s] for (w, s), v in x.items() if sv.Value(v)}
    return {"goal": sv.ObjectiveValue() / 100, "bound": sv.BestObjectiveBound() / 100,
            "optimal": st == cp_model.OPTIMAL, "plan": plan}


def write(size: str) -> Path:
    for seed in range(9, 60):  # the first seed whose pairs and capacities admit a placement
        d = make(size, seed)
        ref = solve(d, 900 if size == "L" else 300)
        if "goal" in ref:
            break
    folder = OUT / size
    S, W = d["S"], d["W"]
    # The current allocation: every server on, workloads spread round-robin -- the baseline to compare.
    baseline = sum(cost_of(d, s) for s in range(len(S)))
    write_csv(folder / "servers.csv", ["id", "region", "zone", "cpu", "memory_gb", "storage_gb", "running_cost_per_hour",
                                       "power_kw"],
              [(S[s], d["region"][s], d["zone"][s], int(d["cpu"][s]), int(d["mem"][s]), int(d["sto"][s]),
                int(d["run_cost"][s]), float(d["power"][s])) for s in range(len(S))])
    write_csv(folder / "workloads.csv", ["id", "cpu", "memory_gb", "storage_gb", "allowed_regions"],
              [(W[w], int(d["wc"][w]), int(d["wm"][w]), int(d["ws"][w]), " ".join(d["allowed"][w])) for w in range(len(W))])
    write_csv(folder / "pairs.csv", ["workload_a", "workload_b", "rule"],
              [(W[a], W[b], "apart") for a, b in sorted(d["apart"])] + [(W[a], W[b], "together") for a, b in sorted(d["together"])])
    names = ["servers.csv", "workloads.csv", "pairs.csv"]
    rules = ("Rules: every workload runs on exactly one server, in one of its allowed regions (its latency "
             "requirement). On each server the workloads' CPU, memory and storage together fit the server's. A "
             "server running any workload is on and costs its running cost per hour plus its power kW x "
             f"{ENERGY} EGP per kWh; a server with no workload is shut down and costs nothing. Two workloads in "
             "pairs.csv marked apart must run in different zones (failure domains); two marked together must run on "
             "the same server. Goal: the lowest cost per hour. Report the placement of every workload, the servers "
             "on and off, CPU, memory, storage and energy use, a check that every rule holds, and the saving "
             f"against today, when all {len(S)} servers are on at {baseline:,.2f} EGP per hour.")
    head = (f'Please build this in a new workspace called "{{workspace}}". Call the problem "Workload placement". '
            f"Place {len(W)} workloads on {len(S)} servers at the least running cost.\n\n")
    if size == "S":
        body = "\n\n".join(f"{label}:\n{csv_text(folder / n)}" for label, n in [
            ("Servers", names[0]), ("Workloads (allowed regions separated by spaces)", names[1]), ("Pairs", names[2])])
        files = []
    else:
        body = "The data are in the attached files: servers.csv, workloads.csv (allowed regions separated by spaces), pairs.csv."
        files = names
    message = head + body + "\n\n" + rules + "\n\nEverything you need is here: please propose the model without further questions, then solve it."
    report = [["placement", r"WL\d{5}.{0,40}SRV\d{3}"], ["servers on and off", r"\b(on|off|shut|active)\b"],
              ["utilization", r"utili[sz]|cpu|memory"], ["energy", r"energy|kW"],
              ["rules hold / SLA", r"every rule|SLA|violation|satisf"],
              ["saving against today", r"sav(e|ing)|" + f"{baseline:,.0f}".replace(",", ",?")]]
    write_case(folder, message, {"problem": "p09", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": ref["goal"] if ref["optimal"] else None, "known_feasible": ref["goal"],
                                 "bound": ref["bound"], "sense": "minimize", "baseline": baseline, "report": report,
                                 "files": files, "rows": {"workloads": len(W), "servers": len(S), "pairs": len(d["apart"]) + len(d["together"])}})
    (folder / "reference_plan.csv").write_text("workload,server\n" + "".join(f"{w},{s}\n" for w, s in sorted(ref["plan"].items())))
    # The goal exactly as the checker counts it (the reference solver works in whole cents).
    exact = float(check(folder, "decision,key1,key2,value\n" + "".join(
        f"place,{w},{s},1\n" for w, s in ref["plan"].items()))[-1].split()[1])
    expected = __import__("json").loads((folder / "expected.json").read_text())
    expected["known_feasible"] = exact
    if expected["goal"] is not None:
        expected["goal"] = exact
    (folder / "expected.json").write_text(__import__("json").dumps(expected, indent=2))
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    srv = {r["id"]: r for r in read_csv(folder / "servers.csv")}
    wl = {r["id"]: r for r in read_csv(folder / "workloads.csv")}
    pairs = read_csv(folder / "pairs.csv")
    where: dict[str, list[str]] = {}
    for r in export_rows(export_csv):
        if r.get("key1") in wl and r.get("key2") in srv and float(r["value"]) > 0.5:
            where.setdefault(r["key1"], []).append(r["key2"])
        elif r.get("key1") in srv and r.get("key2") in wl and float(r["value"]) > 0.5:
            where.setdefault(r["key2"], []).append(r["key1"])
    if not where:
        return ["no decision placing workloads on servers in the export"]
    bad: list[str] = []
    load: dict[str, list[float]] = {s: [0, 0, 0] for s in srv}
    for w, r in wl.items():
        got = where.get(w, [])
        if len(got) != 1:
            bad.append(f"{w} on {len(got)} servers")
            continue
        s = got[0]
        if srv[s]["region"] not in r["allowed_regions"].split():
            bad.append(f"{w} on {s} in {srv[s]['region']}, not an allowed region")
        for i, k in enumerate(("cpu", "memory_gb", "storage_gb")):
            load[s][i] += float(r[k])
    for s, (c, m, st) in load.items():
        for v, k in ((c, "cpu"), (m, "memory_gb"), (st, "storage_gb")):
            if v > float(srv[s][k]) + 1e-6:
                bad.append(f"{s}: {k} {v:g} above {srv[s][k]}")
    for p in pairs:
        a, b = where.get(p["workload_a"], [None])[0], where.get(p["workload_b"], [None])[0]
        if a is None or b is None:
            continue
        if p["rule"] == "apart" and srv[a]["zone"] == srv[b]["zone"]:
            bad.append(f"{p['workload_a']} and {p['workload_b']} must be apart, both in {srv[a]['zone']}")
        if p["rule"] == "together" and a != b:
            bad.append(f"{p['workload_a']} and {p['workload_b']} must be together, on {a} and {b}")
    cost = sum(float(srv[s]["running_cost_per_hour"]) + float(srv[s]["power_kw"]) * ENERGY
               for s in srv if any(load[s]))
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:220])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
