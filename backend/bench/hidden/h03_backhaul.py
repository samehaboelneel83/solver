"""Hidden problem h03 (network flow).

    python -m bench.hidden.h03_backhaul gen [S M]
    python -m bench.hidden.h03_backhaul check <case> <export.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import csv_text, decision_over, export_rows, read_csv, write_csv
from bench.hidden._util_a import CLOSE, OPEN, Model, export_text, finish, num_re, search, tol

SIZES = {"S": (6, 2, 2), "M": (150, 12, 3)}  # towers, hubs, core sites
OUT = Path(__file__).parent / "cases" / "h03"


def make(size: str, seed: int = 3) -> dict:
    nt, nh, nc = SIZES[size]
    rng = np.random.default_rng(seed * 15485863 + nt)
    w = 3 if nt >= 100 else 2
    T = [f"TW{i + 1:0{w}d}" for i in range(nt)]
    H = [f"HUB{i + 1:02d}" for i in range(nh)]
    C = [f"CORE{i + 1}" for i in range(nc)]
    pos = {x: rng.uniform(0, 100, 2) for x in T + H}
    for i, c in enumerate(C):
        pos[c] = np.array([100.0 * (i + 0.5) / nc, 50.0])
    traffic = {t: int(rng.integers(2, 11)) for t in T}
    links = {}

    def dist(a, b):
        return float(np.hypot(*(pos[a] - pos[b])))

    for t in T:
        near = sorted(H, key=lambda h: dist(t, h))[: (3 if rng.random() < 0.3 else 2)]
        for h in near:
            links[(t, h)] = (int(rng.integers(6, 21)), int(round(20 + dist(t, h) * rng.uniform(1.5, 3.0))))
    # some towers relay through a neighbouring tower
    for t in T:
        if rng.random() < 0.15:
            u = min((x for x in T if x != t), key=lambda x: dist(t, x))
            if (u, t) not in links:
                links[(t, u)] = (int(rng.integers(5, 13)), int(round(10 + dist(t, u) * 2)))
    total = sum(traffic.values())
    for h in H:
        for g in sorted(H, key=lambda g: dist(h, g))[1:3]:
            cap = int(round(total / nh * rng.uniform(0.4, 0.9)))
            links[(h, g)] = (cap, int(round(5 + dist(h, g) * 0.8)))
        for c in sorted(C, key=lambda c: dist(h, c))[:2]:
            cap = int(round(total / nh * rng.uniform(0.6, 1.2)))
            links[(h, c)] = (cap, int(round(8 + dist(h, c) * 0.6)))
    hubcap = {h: int(round(total / nh * rng.uniform(1.0, 1.6))) for h in H}
    corecap = {c: int(round(total / nc * rng.uniform(1.05, 1.4))) for c in C}
    return dict(T=T, H=H, C=C, traffic=traffic, links=links, hubcap=hubcap, corecap=corecap)


def solve(d: dict, seconds: float = 300):
    m = Model()
    for (a, b), (cap, cost) in d["links"].items():
        m.var((a, b), 0, cap, cost=cost)
    for t in d["T"]:
        m.add([((a, b), 1 if a == t else -1) for (a, b) in d["links"] if t in (a, b)], lo=d["traffic"][t], hi=d["traffic"][t])
    for h in d["H"]:
        m.add([((a, b), 1 if b == h else -1) for (a, b) in d["links"] if h in (a, b)], lo=0, hi=0)
        m.add([((a, b), 1) for (a, b) in d["links"] if b == h], hi=d["hubcap"][h])
    for c in d["C"]:
        m.add([((a, b), 1) for (a, b) in d["links"] if b == c], hi=d["corecap"][c])
    r = m.solve(maximize=False, seconds=seconds)
    if r is None:
        return None
    rows = [("flow", k, v) for k, v in r["x"].items() if v > 1e-9]
    return {"goal": r["obj"], "bound": r["bound"], "optimal": r["optimal"], "export": export_text(rows)}


def write(size: str) -> Path:
    seed, d, ref = search(make, solve, size, 3, 300)
    folder = OUT / size
    nodes = ([(t, "tower", d["traffic"][t], "") for t in d["T"]] + [(h, "hub", "", d["hubcap"][h]) for h in d["H"]]
             + [(c, "core", "", d["corecap"][c]) for c in d["C"]])
    write_csv(folder / "nodes.csv", ["node", "type", "traffic_gbps", "capacity_gbps"], nodes)
    links = sorted(d["links"].items())
    write_csv(folder / "links.csv", ["link", "from", "to", "capacity_gbps", "cost_per_gbps"],
              [(f"L{i + 1:03d}", a, b, cap, cost) for i, ((a, b), (cap, cost)) in enumerate(links)])
    names = ["nodes.csv", "links.csv"]
    head = (OPEN.format(name="Backhaul routing") + f"Our mobile network must carry the peak traffic of {len(d['T'])} "
            f"cell towers through {len(d['H'])} aggregation hubs to {len(d['C'])} core sites over leased "
            "microwave and fibre links, at the lowest monthly lease cost.\n\n")
    if size == "S":
        body = ("Nodes (towers with their peak traffic; hubs and core sites with their capacity):\n"
                + csv_text(folder / "nodes.csv") + "\n\nLinks (one direction only, from -> to):\n" + csv_text(folder / "links.csv"))
        files: list[str] = []
    else:
        body = ("The data are in the attached files: nodes.csv (every tower, hub and core site: a tower's peak traffic, "
                "a hub's switching capacity, a core site's intake capacity) and links.csv (the usable links, each in "
                "one direction from -> to, with its capacity and lease cost per Gbps).")
        files = names
    rules = ("Rules (all hard): traffic moves only along the listed links and only in the from -> to direction; the "
             "Gbps on a link are at most its capacity and may be fractional. Every tower sends out exactly its own "
             "peak traffic plus whatever it relays for other towers (Gbps leaving a tower minus Gbps entering it = "
             "its traffic). A hub keeps nothing: Gbps entering a hub = Gbps leaving it, and the Gbps entering a hub "
             "are at most its capacity. All traffic must end at the core sites, and the Gbps entering a core site "
             "are at most its capacity. Goal: the lowest total monthly lease cost = for every link, Gbps carried x "
             "cost per Gbps. Report the Gbps on each link used, the total cost, the load of each hub against its "
             "capacity, the traffic arriving at each core site, and the links that are full.")
    message = head + body + "\n\n" + rules + "\n\n" + CLOSE
    report = [["flow per link", r"(TW\d+|HUB\d\d|L\d{3})[^\n]{0,60}\d"], ["total cost", num_re(ref["goal"])],
              ["hub loads", r"HUB\d\d[^\n]{0,80}(%|capacity|load|utili)"], ["core intake", r"CORE\d"],
              ["full links", r"\bfull|saturat|at capacity|bottleneck|congest|binding"]]
    finish(folder, "h03", size, "minimize", ref, seed, check, message, report, files)
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    nodes = {r["node"]: r for r in read_csv(folder / "nodes.csv")}
    links = {(r["from"], r["to"]): r for r in read_csv(folder / "links.csv")}
    by_id = {r["link"]: (r["from"], r["to"]) for r in links.values()}
    rows = export_rows(export_csv)
    name, flow = decision_over(rows, set(nodes), set(nodes))
    if not name:
        name, f1 = decision_over(rows, set(by_id))
        flow = {by_id[k[0]]: v for k, v in f1.items()}
    if not name:
        return ["no flow decision over (from, to) or over links in the export", "COST 0.000000"]
    bad: list[str] = []
    cost = 0.0
    net = {n: 0.0 for n in nodes}
    inflow = {n: 0.0 for n in nodes}
    for (a, b), v in flow.items():
        if v < -1e-6:
            bad.append(f"{a}->{b}: negative flow {v:g}")
        if (a, b) not in links:
            if abs(v) > 1e-6:
                bad.append(f"{a}->{b}: {v:g} Gbps on a link that does not exist")
            continue
        cap = float(links[(a, b)]["capacity_gbps"])
        if v > cap + tol(cap):
            bad.append(f"{a}->{b}: {v:g} Gbps above capacity {cap:g}")
        cost += v * float(links[(a, b)]["cost_per_gbps"])
        net[a] += v
        net[b] -= v
        inflow[b] += v
    for n, r in nodes.items():
        if r["type"] == "tower":
            tr = float(r["traffic_gbps"])
            if abs(net[n] - tr) > tol(tr):
                bad.append(f"{n}: sends out net {net[n]:g} Gbps, traffic {tr:g}")
        elif r["type"] == "hub":
            if abs(net[n]) > 1e-6 * max(1.0, inflow[n]):
                bad.append(f"{n}: in and out differ by {net[n]:g}")
            cap = float(r["capacity_gbps"])
            if inflow[n] > cap + tol(cap):
                bad.append(f"{n}: {inflow[n]:g} Gbps in, capacity {cap:g}")
        else:
            cap = float(r["capacity_gbps"])
            if -net[n] > cap + tol(cap):
                bad.append(f"{n}: {-net[n]:g} Gbps arrive, capacity {cap:g}")
            if net[n] > 1e-6:
                bad.append(f"{n}: a core site sends out more than it receives")
    return bad + [f"COST {cost:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:200])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
