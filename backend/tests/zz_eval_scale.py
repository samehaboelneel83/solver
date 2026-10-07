"""Evaluation at scale (not part of the suite): bigger instances through the platform's full path, against the same
or a known reference. Writes eval_scale.json (or $EVAL_OUT).  ONLY=name1,name2 to pick."""
from __future__ import annotations

import json
import math
import os
import random
import time

import numpy as np
from fastapi.testclient import TestClient
from scipy.optimize import linear_sum_assignment, linprog

from app.main import app
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401
from tests.zz_eval_battery import A, C, MUL, P, S, V, data, goal, platform_solve, rule

OUT = __import__("os").environ.get("EVAL_OUT", "eval_scale.json")


def big_transport(np_=60, nm=400):
    rng = np.random.default_rng(21)
    supply = rng.integers(80, 160, np_)
    demand = rng.multinomial(int(supply.sum() * .9), [1 / nm] * nm)
    cost = rng.integers(1, 100, (np_, nm))
    t = time.monotonic()
    A_ub = np.zeros((np_ + nm, np_ * nm)); b = []
    for i in range(np_):
        A_ub[i, i * nm:(i + 1) * nm] = 1; b.append(supply[i])
    for j in range(nm):
        A_ub[np_ + j, j::nm] = -1; b.append(-demand[j])
    ref = linprog(cost.ravel(), A_ub=A_ub, b_ub=b, method="highs")
    ref_s = time.monotonic() - t
    ir = {"version": 2, "sets": ["plant", "market"], "parameters": {"cost": {"index": ["plant", "market"]}},
          "variables": {"ship": {"index": ["plant", "market"], "domain": "continuous", "lower": 0}},
          "constraints": [rule("c_sup", S(V("ship", "p", "m"), ("m", "market")), "<=", A("p", "supply"), [("p", "plant")]),
                          rule("c_dem", S(V("ship", "p", "m"), ("p", "plant")), ">=", A("m", "demand"), [("m", "market")])],
          "objective": goal("minimize", (1, S(MUL(P("cost", "p", "m"), V("ship", "p", "m")), ("p", "plant"), ("m", "market"))))}
    d = data({"plant": [{"id": f"p{i}", "supply": int(supply[i])} for i in range(np_)],
              "market": [{"id": f"m{j}", "demand": int(demand[j])} for j in range(nm)]},
             {"cost": [{"plant": f"p{i}", "market": f"m{j}", "value": int(cost[i, j])} for i in range(np_) for j in range(nm)]})
    return f"Transportation LP {np_}x{nm} ({np_ * nm:,} variables)", ir, d, None, float(ref.fun), ref_s


def big_assignment(n=150):
    rng = np.random.default_rng(22)
    cost = rng.integers(1, 1000, (n, n))
    t = time.monotonic(); r, c = linear_sum_assignment(cost); ref_s = time.monotonic() - t
    ir = {"version": 2, "sets": ["worker", "task"], "parameters": {"cost": {"index": ["worker", "task"]}},
          "variables": {"x": {"index": ["worker", "task"], "domain": "binary"}},
          "constraints": [rule("c_w", S(V("x", "w", "t"), ("t", "task")), "=", C(1), [("w", "worker")]),
                          rule("c_t", S(V("x", "w", "t"), ("w", "worker")), "=", C(1), [("t", "task")])],
          "objective": goal("minimize", (1, S(MUL(P("cost", "w", "t"), V("x", "w", "t")), ("w", "worker"), ("t", "task"))))}
    d = data({"worker": [{"id": f"w{i}"} for i in range(n)], "task": [{"id": f"t{j}"} for j in range(n)]},
             {"cost": [{"worker": f"w{i}", "task": f"t{j}", "value": int(cost[i, j])} for i in range(n) for j in range(n)]})
    return f"Assignment {n}x{n} ({n * n:,} binaries)", ir, d, None, float(cost[r, c].sum()), ref_s


def big_knapsack(n=2000):
    rnd = random.Random(23)
    items = [{"id": f"i{k}", "w": rnd.randint(10, 300), "v": rnd.randint(10, 400)} for k in range(n)]
    cap = sum(i["w"] for i in items) // 4
    t = time.monotonic()
    best = np.zeros(cap + 1, dtype=np.int64)
    for it in items:
        w, v = it["w"], it["v"]
        best[w:] = np.maximum(best[w:], best[:-w] + v) if w <= cap else best[w:]
    ref_s = time.monotonic() - t
    ir = {"version": 2, "sets": ["item"], "parameters": {},
          "variables": {"take": {"index": ["item"], "domain": "binary"}},
          "constraints": [rule("c_cap", S(MUL(A("i", "w"), V("take", "i")), ("i", "item")), "<=", C(cap))],
          "objective": goal("maximize", (1, S(MUL(A("i", "v"), V("take", "i")), ("i", "item"))))}
    return f"Knapsack {n:,} items", ir, data({"item": items}), None, float(best[cap]), ref_s


# Fisher & Thompson 10x10 (ft10): (machine, duration) per job, optimum 930.
FT10 = """0 29 1 78 2 9 3 36 4 49 5 11 6 62 7 56 8 44 9 21
0 43 2 90 4 75 9 11 3 69 1 28 6 46 5 46 7 72 8 30
1 91 0 85 3 39 2 74 8 90 5 10 7 12 6 89 9 45 4 33
1 81 2 95 0 71 4 99 6 9 8 52 7 85 3 98 9 22 5 43
2 14 0 6 1 22 5 61 3 26 4 69 8 21 7 49 9 72 6 53
2 84 1 2 5 52 3 95 8 48 9 72 0 47 6 65 4 6 7 25
1 46 0 37 3 61 2 13 6 32 5 21 9 32 8 89 7 30 4 55
2 31 0 86 1 46 5 74 4 32 6 88 8 19 9 48 7 36 3 79
0 76 1 69 3 76 5 51 2 85 9 11 6 40 7 89 4 26 8 74
1 85 0 13 2 61 6 7 8 64 9 76 5 47 3 52 4 90 7 45"""


def ft10():
    ops = []
    for j, line in enumerate(FT10.splitlines()):
        nums = list(map(int, line.split()))
        for k in range(10):
            ops.append({"id": f"j{j}o{k}", "job": j, "k": k, "machine": f"m{nums[2 * k]}", "dur": nums[2 * k + 1]})
    H = sum(o["dur"] for o in ops)
    rels = {"then": [{"from": a["id"], "to": b["id"]} for a in ops for b in ops if a["job"] == b["job"] and b["k"] == a["k"] + 1],
            "on": [{"from": o["id"], "to": o["machine"]} for o in ops]}
    op = {"index": ["op"]}
    ir = {"version": 2, "sets": ["op", "machine"], "relationships": ["then", "on"], "parameters": {"dur": {"index": ["op"]}},
          "variables": {"begin": {**op, "domain": "integer", "lower": 0, "upper": H},
                        "finish": {**op, "domain": "integer", "lower": 0, "upper": H},
                        "makespan": {"index": [], "domain": "integer", "lower": 0, "upper": H},
                        "task": {**op, "domain": "interval", "start": "begin", "end": "finish", "size": "dur"}},
          "constraints": [
              {"id": "c_machine", "forall": [{"index": "m", "set": "machine"}],
               "no_overlap": {"interval": V("task", "o"), "over": [{"index": "o", "set": "op", "via": {"rel": "on", "to": "m"}}]},
               "severity": "hard"},
              rule("c_order", V("finish", "a"), "<=", V("begin", "b"), [("a", "op"), ("b", "op", {"rel": "then", "from": "a"})]),
              rule("c_span", V("finish", "o"), "<=", V("makespan"), [("o", "op")])],
          "objective": goal("minimize", (1, V("makespan")))}
    d = data({"op": [{"id": o["id"], "k": o["k"]} for o in ops], "machine": [{"id": f"m{k}"} for k in range(10)]},
             {"dur": [{"op": o["id"], "value": o["dur"]} for o in ops]}, rels=rels)
    return "Job shop FT10 (10x10, classic; proven optimum 930)", ir, d, {"then": ("op", "op"), "on": ("op", "machine")}, 930.0, None


def cvrp(stops, fleet, seconds_ref=60):
    from bench.routing import vrp
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    size = {15: "M", 30: "L", 60: "XL"}[stops]
    ir, d = vrp(size, 0)
    names = [r["id"] for r in d["sets"]["stop"]]
    dist = {(r["0"], r["1"]): r["value"] for r in d["parameters"]["distance"]}
    dem = [r["demand"] for r in d["sets"]["stop"]]
    cap = d["sets"]["vehicle"][0]["capacity"]
    k = len(d["sets"]["vehicle"])
    mgr = pywrapcp.RoutingIndexManager(len(names), k, 0)
    rt = pywrapcp.RoutingModel(mgr)
    cb = rt.RegisterTransitCallback(lambda a, b: dist[(names[mgr.IndexToNode(a)], names[mgr.IndexToNode(b)])])
    rt.SetArcCostEvaluatorOfAllVehicles(cb)
    dcb = rt.RegisterUnaryTransitCallback(lambda a: dem[mgr.IndexToNode(a)])
    rt.AddDimensionWithVehicleCapacity(dcb, 0, [cap] * k, True, "load")
    prm = pywrapcp.DefaultRoutingSearchParameters()
    prm.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    prm.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    prm.time_limit.seconds = seconds_ref
    t = time.monotonic(); sol = rt.SolveWithParameters(prm); ref_s = time.monotonic() - t
    return (f"Capacitated vehicle routing {stops} stops, {k} trucks (reference: OR-Tools routing {seconds_ref} s, not proven)",
            ir, d, None, float(sol.ObjectiveValue()), ref_s)


def big_facility():
    from bench.families import facility
    from tests.zz_eval_battery import M
    ir, d = facility("L", 0)
    ir = {**ir, "version": 2}
    sites, cust = d["sets"]["site"], d["sets"]["customer"]
    cost = {(r["site"], r["customer"]): r["value"] for r in d["parameters"]["ship_cost"]}
    m = M()
    for s in sites:
        m.var("o" + s["id"], 0, 1, True); m.c["o" + s["id"]] = s["fixed"]
        for c in cust:
            k = f"{s['id']},{c['id']}"; m.var(k, 0, 1); m.c[k] = cost[(s["id"], c["id"])]
            m.con({k: 1, "o" + s["id"]: -1}, hi=0)
        m.con({**{f"{s['id']},{c['id']}": c["demand"] for c in cust}, "o" + s["id"]: -s["capacity"]}, hi=0)
    for c in cust:
        m.con({f"{s['id']},{c['id']}": 1 for s in sites}, 1, 1)
    t = time.monotonic(); ref = m.solve()[0]; ref_s = time.monotonic() - t
    return f"Capacitated facility location {len(sites)}x{len(cust)} (MILP)", ir, d, None, ref, ref_s


CASES = {"transport": big_transport, "assignment": big_assignment, "knapsack": big_knapsack, "ft10": ft10,
         "cvrp15": lambda: cvrp(15, 3, 30), "cvrp30": lambda: cvrp(30, 5, 60), "facility": big_facility}


def test_scale(tenants, db, empty_queue):  # noqa: F811
    client = TestClient(app)
    only = os.environ.get("ONLY")
    out = json.load(open(OUT)) if os.path.exists(OUT) and only else []
    for name, make in CASES.items():
        if only and name not in only.split(","):
            continue
        label, ir, d, ends, ref, ref_s = make()
        got = platform_solve(client, tenants["b"], db, "scale_" + name, ir, d, ends, time_limit=int(os.environ.get("LIMIT", 120)))
        row = {"case": name, "label": label, "reference": ref, "reference_s": None if ref_s is None else round(ref_s, 2),
               **{k: v for k, v in got.items() if k not in ("assignments", "amounts", "params_keys")}}
        out = [r for r in out if r["case"] != name] + [row]
        print(json.dumps(row, default=str))
        json.dump(out, open(OUT, "w"), default=str, indent=1)
