"""Problem 4: multi-product factory production planning (mixed-integer).

    python -m bench.phase1.p04_factory gen
    python -m bench.phase1.p04_factory check <case> <export.csv>

Products run on machines in shifts. A product can run only on the machines listed for it, taking hours per unit
there; each machine has a number of hours per shift. Each unit takes labour hours, and each shift has a labour
limit; each unit uses raw materials, and each material has a week's stock. Each product's total over the week is
between its minimum and maximum demand. Running a product on a machine in a shift costs its setup cost once.
Some pairs of products cannot run on the same machine in the same shift. Profit = (price - unit cost) x units -
setup costs, to be made as large as possible. Units are whole.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from bench.phase1.common import HERE, csv_text, decision_over, export_rows, read_csv, write_case, write_csv

SIZES = {"S": (4, 2, 2, 2), "M": (20, 10, 3, 3), "L": (60, 20, 3, 4)}  # products, machines, shifts, materials
OUT = HERE / "cases" / "p04"
SECONDS = {"S": 60, "M": 300, "L": 600}


def make(size: str, seed: int = 4) -> dict:
    n_p, n_m, n_s, n_k = SIZES[size]
    rng = np.random.default_rng(seed + n_p * 100 + n_m)
    P = [f"P{i + 1:02d}" for i in range(n_p)]
    M = [f"M{i + 1:02d}" for i in range(n_m)]
    S = ["MORNING", "EVENING", "NIGHT"][:n_s]
    K = [f"MAT{i + 1}" for i in range(n_k)]
    price = rng.integers(40, 120, n_p)
    unit_cost = np.rint(price * rng.uniform(0.35, 0.65, n_p)).astype(int)
    setup = rng.integers(150, 600, n_p)
    labour = np.round(rng.uniform(0.2, 0.8, n_p), 2)
    # Each product on 1-3 machines, hours per unit there.
    route = {}
    for i in range(n_p):
        for m in rng.choice(n_m, int(rng.integers(1, min(3, n_m) + 1)), replace=False):
            route[(i, int(m))] = round(float(rng.uniform(0.05, 0.25)), 3)
    hours = 8
    labour_cap = {s: int(rng.integers(40, 70) * n_m / 4) for s in S}
    usage = np.round(rng.uniform(0.0, 2.0, (n_p, n_k)) * (rng.random((n_p, n_k)) < 0.7), 2)
    # Demand: maxima that together need more than the week's hours, so not everything can be made.
    week_hours = hours * n_m * n_s
    mean_time = np.array([np.mean([route[(i, m)] for m in range(n_m) if (i, m) in route]) for i in range(n_p)])
    dmax = np.rint(week_hours * 1.4 / n_p / mean_time * rng.uniform(0.6, 1.4, n_p)).astype(int)
    dmin = np.rint(dmax * rng.uniform(0.1, 0.3, n_p)).astype(int)
    stock = np.rint(usage.T @ ((dmin + dmax) / 2) * 0.9).astype(int) + 1
    pairs = set()
    while len(pairs) < max(1, n_p // 4):
        a, b = sorted(rng.choice(n_p, 2, replace=False).tolist())
        if any((a, m) in route and (b, m) in route for m in range(n_m)):
            pairs.add((a, b))
    return dict(P=P, M=M, S=S, K=K, price=price, unit_cost=unit_cost, setup=setup, labour=labour, route=route,
                hours=hours, labour_cap=labour_cap, usage=usage, stock=stock, dmin=dmin, dmax=dmax, pairs=pairs)


def solve(d: dict, seconds: float) -> dict:
    """The reference by OR-Tools' CP-SAT on the same rules, written from the problem's words (not the platform's)."""
    from ortools.sat.python import cp_model

    P, M, S, K = d["P"], d["M"], d["S"], d["K"]
    md = cp_model.CpModel()
    x, y = {}, {}
    big = {i: int(d["dmax"][i]) for i in range(len(P))}
    for (i, m), t in d["route"].items():
        for s in S:
            x[i, m, s] = md.NewIntVar(0, big[i], f"x{i}_{m}_{s}")
            y[i, m, s] = md.NewBoolVar(f"y{i}_{m}_{s}")
            md.Add(x[i, m, s] <= big[i] * y[i, m, s])
    scale = 1000
    for m in range(len(M)):
        for s in S:
            md.Add(sum(int(round(t * scale)) * x[i, mm, s] for (i, mm), t in d["route"].items() if mm == m)
                   <= d["hours"] * scale)
    for s in S:
        md.Add(sum(int(round(d["labour"][i] * 100)) * x[i, m, ss] for (i, m, ss) in x if ss == s) <= d["labour_cap"][s] * 100)
    for k in range(len(K)):
        md.Add(sum(int(round(d["usage"][i, k] * 100)) * x[i, m, s] for (i, m, s) in x) <= int(d["stock"][k]) * 100)
    for i in range(len(P)):
        tot = sum(x[key] for key in x if key[0] == i)
        md.Add(tot >= int(d["dmin"][i]))
        md.Add(tot <= int(d["dmax"][i]))
    for a, b in d["pairs"]:
        for m in range(len(M)):
            for s in S:
                if (a, m, s) in y and (b, m, s) in y:
                    md.Add(y[a, m, s] + y[b, m, s] <= 1)
    md.Maximize(sum(int(d["price"][i] - d["unit_cost"][i]) * x[key] for key in x for i in [key[0]])
                - sum(int(d["setup"][key[0]]) * y[key] for key in y))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = 8
    st = solver.Solve(md)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": solver.StatusName(st)}
    plan = {(P[i], M[m], s): solver.Value(v) for (i, m, s), v in x.items() if solver.Value(v)}
    return {"goal": solver.ObjectiveValue(), "bound": solver.BestObjectiveBound(), "optimal": st == cp_model.OPTIMAL,
            "plan": plan}


def write(size: str) -> Path:
    d = make(size)
    folder = OUT / size
    P, M, S, K = d["P"], d["M"], d["S"], d["K"]
    ref = solve(d, SECONDS[size])
    while "goal" not in ref:  # the minimums need more than the week holds: lower them until a plan exists
        d["dmin"] = d["dmin"] // 2
        ref = solve(d, SECONDS[size])
    write_csv(folder / "products.csv", ["id", "price", "unit_cost", "setup_cost", "labour_hours_per_unit",
                                        "min_demand", "max_demand"],
              [(P[i], int(d["price"][i]), int(d["unit_cost"][i]), int(d["setup"][i]), float(d["labour"][i]),
                int(d["dmin"][i]), int(d["dmax"][i])) for i in range(len(P))])
    write_csv(folder / "machines.csv", ["id", "hours_per_shift"], [(m, d["hours"]) for m in M])
    write_csv(folder / "shifts.csv", ["id", "labour_hours"], [(s, d["labour_cap"][s]) for s in S])
    write_csv(folder / "machine_times.csv", ["product", "machine", "hours_per_unit"],
              [(P[i], M[m], t) for (i, m), t in sorted(d["route"].items())])
    write_csv(folder / "materials.csv", ["id", "stock"], [(K[k], int(d["stock"][k])) for k in range(len(K))])
    write_csv(folder / "material_use.csv", ["product", "material", "per_unit"],
              [(P[i], K[k], float(d["usage"][i, k])) for i in range(len(P)) for k in range(len(K)) if d["usage"][i, k]])
    write_csv(folder / "incompatible.csv", ["product_a", "product_b"], [(P[a], P[b]) for a, b in sorted(d["pairs"])])
    names = ["products.csv", "machines.csv", "shifts.csv", "machine_times.csv", "materials.csv", "material_use.csv",
             "incompatible.csv"]
    rules = ("Rules: a product can run only on the machines listed for it in machine times, and a unit there takes "
             "the hours listed. On each machine, in each shift, the hours used are at most its hours per shift. In "
             "each shift the labour hours used (units times labour hours per unit, over all products and machines) "
             "are at most that shift's labour hours. Over the week, each material used (units times use per unit) is "
             "at most its stock. Each product's total over all machines and shifts is at least its minimum and at "
             "most its maximum demand. A product run on a machine in a shift costs its setup cost once for that "
             "machine and shift. The two products of an incompatible pair can never run on the same machine in the "
             "same shift. Units are whole numbers. Goal: the largest profit = (price - unit cost) x units, minus all "
             "setup costs. Report production per product, machine and shift, revenue, production cost, setup cost "
             "and net profit, machine utilization, unmet demand (below the maximum), and how profit changes if "
             "demand changes.")
    head = (f'Please build this in a new workspace called "{{workspace}}". Call the problem "Weekly production plan". '
            f"Our factory makes {len(P)} products on {len(M)} machines over {len(S)} shifts this week.\n\n")
    if size == "S":
        body = "\n\n".join(f"{label}:\n{csv_text(folder / n)}" for label, n in [
            ("Products (price, unit cost and setup cost in EGP; labour hours per unit; demand range in units)", names[0]),
            ("Machines", names[1]), ("Shifts (labour hours available)", names[2]),
            ("Machine times (which machines can make each product, hours per unit)", names[3]),
            ("Materials (stock for the week)", names[4]), ("Material use per unit", names[5]),
            ("Incompatible products (never on the same machine in the same shift)", names[6])])
        files = []
    else:
        body = ("The data are in the attached files: products.csv, machines.csv, shifts.csv, machine_times.csv (which "
                "machines can make each product and hours per unit), materials.csv, material_use.csv, "
                "incompatible.csv (pairs never on the same machine in the same shift).")
        files = names
    message = head + body + "\n\n" + rules + "\n\nEverything you need is here: please propose the model without further questions, then solve it."
    report = [
        ["production per product, machine and shift", r"P\d\d[^\n]{0,60}M\d\d[^\n]{0,60}(MORNING|EVENING|NIGHT)"],
        ["revenue", r"revenue"], ["production cost", r"production cost|unit cost"],
        ["net profit", f"{ref['goal']:,.0f}".replace(",", ",?")],
        ["machine utilization", r"utili[sz]|hours used|% of"],
        ["unmet demand", r"unmet|below (its|the) max|not (fully )?met|short"],
        ["sensitivity to demand", r"if demand|sensitiv|demand (rises|falls|changes|increase|decrease)"]]
    write_case(folder, message, {"problem": "p04", "size": size, "kind": "exact" if ref["optimal"] else "bounded",
                                 "goal": ref["goal"] if ref["optimal"] else None, "known_feasible": ref["goal"],
                                 "bound": ref["bound"], "sense": "maximize", "report": report, "files": files,
                                 "binaries": len(d["route"]) * len(S)})
    return folder


def check(folder: Path, export_csv: str) -> list[str]:
    pr = {r["id"]: r for r in read_csv(folder / "products.csv")}
    mh = {r["id"]: float(r["hours_per_shift"]) for r in read_csv(folder / "machines.csv")}
    sh = {r["id"]: float(r["labour_hours"]) for r in read_csv(folder / "shifts.csv")}
    tm = {(r["product"], r["machine"]): float(r["hours_per_unit"]) for r in read_csv(folder / "machine_times.csv")}
    st = {r["id"]: float(r["stock"]) for r in read_csv(folder / "materials.csv")}
    use = {(r["product"], r["material"]): float(r["per_unit"]) for r in read_csv(folder / "material_use.csv")}
    bad_pairs = [(r["product_a"], r["product_b"]) for r in read_csv(folder / "incompatible.csv")]
    name, x = decision_over(export_rows(export_csv), set(pr), set(mh), set(sh))
    if not name:
        return ["no decision over (product, machine, shift) in the export"]
    bad: list[str] = []
    x = {k: v for k, v in x.items() if abs(v) > 1e-6}
    for (p, m, s), q in x.items():
        if (p, m) not in tm:
            bad.append(f"{p} made on {m}, which cannot make it ({q:g})")
        if abs(q - round(q)) > 1e-6 or q < 0:
            bad.append(f"{p},{m},{s} = {q:g} is not a whole number >= 0")
    for m in mh:
        for s in sh:
            used = sum(q * tm.get((p, m), 0) for (p, mm, ss), q in x.items() if mm == m and ss == s)
            if used > mh[m] + 1e-6:
                bad.append(f"{m} in {s} uses {used:.3f} h of {mh[m]:g}")
    for s in sh:
        used = sum(q * float(pr[p]["labour_hours_per_unit"]) for (p, _, ss), q in x.items() if ss == s)
        if used > sh[s] + 1e-6:
            bad.append(f"{s} uses {used:.3f} labour hours of {sh[s]:g}")
    for k in st:
        used = sum(q * use.get((p, k), 0) for (p, _, _), q in x.items())
        if used > st[k] + 1e-6:
            bad.append(f"{k}: {used:.2f} used of {st[k]:g}")
    profit = 0.0
    for p, r in pr.items():
        tot = sum(q for (pp, _, _), q in x.items() if pp == p)
        if tot < float(r["min_demand"]) - 1e-6 or tot > float(r["max_demand"]) + 1e-6:
            bad.append(f"{p} total {tot:g} outside [{r['min_demand']}, {r['max_demand']}]")
        profit += tot * (float(r["price"]) - float(r["unit_cost"]))
    runs = {(p, m, s) for (p, m, s) in x}
    profit -= sum(float(pr[p]["setup_cost"]) for (p, _, _) in runs)
    for a, b in bad_pairs:
        for (p, m, s) in runs:
            if p == a and (b, m, s) in runs:
                bad.append(f"{a} and {b} both run on {m} in {s}")
    return bad + [f"COST {profit:.6f}"]


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        for s in (sys.argv[2:] or list(SIZES)):
            f = write(s)
            print(s, f, (f / "expected.json").read_text().replace("\n", " ")[:260])
    elif sys.argv[1] == "check":
        print("\n".join(check(Path(sys.argv[2]), Path(sys.argv[3]).read_text(encoding="utf-8"))))
