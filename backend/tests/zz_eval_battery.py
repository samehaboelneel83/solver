"""Evaluation battery (not part of the suite): problem classes built and solved through the platform's full path
(from-spec -> queued run -> selector/race -> verify), each compared with an independent reference.

    pytest -q -s tests/zz_eval_battery.py   ->  writes eval_battery.json (or $EVAL_OUT)
"""
from __future__ import annotations

import itertools
import json
import math
import random
import time
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.optimize import Bounds, LinearConstraint, linear_sum_assignment, milp, minimize

from app.main import app
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

OUT = __import__("os").environ.get("EVAL_OUT", "eval_battery.json")


# -- an independent MILP helper (scipy + HiGHS), for references ----------------------------------------------
class M:
    def __init__(self):
        self.names, self.lb, self.ub, self.integ, self.rows, self.c = [], [], [], [], [], {}

    def var(self, name, lb=0.0, ub=np.inf, integer=False):
        self.names.append(name); self.lb.append(lb); self.ub.append(ub); self.integ.append(1 if integer else 0)
        return name

    def con(self, coefs, lo=-np.inf, hi=np.inf):
        self.rows.append((coefs, lo, hi))

    def solve(self, sense="min"):
        idx = {n: i for i, n in enumerate(self.names)}
        c = np.zeros(len(self.names))
        for n, v in self.c.items():
            c[idx[n]] += v
        if sense == "max":
            c = -c
        A = np.zeros((len(self.rows), len(self.names)))
        lo, hi = [], []
        for r, (coefs, l, h) in enumerate(self.rows):
            for n, v in coefs.items():
                A[r, idx[n]] += v
            lo.append(l); hi.append(h)
        res = milp(c, constraints=LinearConstraint(A, lo, hi) if self.rows else None, integrality=np.array(self.integ),
                   bounds=Bounds(np.array(self.lb), np.array(self.ub)), options={"time_limit": 300})
        assert res.status == 0, res.message
        val = res.fun if sense == "min" else -res.fun
        return val, {n: res.x[i] for n, i in idx.items()}


# -- (ir, data) -> a platform spec ------------------------------------------------------------------------------
def to_spec(name, ir, data, rel_ends=None):
    sets = data["sets"]
    types = []
    for s in ir["sets"]:
        rows = sets.get(s, [])
        keys = []
        for r in rows:
            for k in r:
                if k != "id" and k not in keys:
                    keys.append(k)
        attrs = []
        for k in keys:
            vals = [r[k] for r in rows if k in r]
            numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals)
            attrs.append({"name": k, "data_type": "number" if numeric else "text"})
        types.append({"name": s, "attributes": attrs})
    entities = [{"type": s, "key": str(r["id"]), "attrs": {k: v for k, v in r.items() if k != "id"}}
                for s in ir["sets"] for r in sets.get(s, [])]
    rel_types, rels = [], []
    for rname, edges in (data.get("relationships") or {}).items():
        a, b = (rel_ends or {})[rname]
        rel_types.append({"name": rname, "from": a, "to": b})
        rels += [{"type": rname, "from": [a, str(e["from"])], "to": [b, str(e["to"])]} for e in edges]
    params, values = [], []
    for pname, pdef in (ir.get("parameters") or {}).items():
        index = pdef.get("index") or []
        params.append({"name": pname, "index": index, "default_value": (data.get("parameter_defaults") or {}).get(pname, 0)})
        distinct = len(set(index)) == len(index)
        for row in (data.get("parameters") or {}).get(pname, []):
            keys = [row[s] if distinct else row[str(k)] for k, s in enumerate(index)]
            values.append({"parameter": pname, "entities": [[s, str(k)] for s, k in zip(index, keys)], "value": row["value"]})
    return {"domain_name": f"eval {name} {uuid.uuid4().hex[:6]}", "problem_name": name,
            "seed": {"entity_types": types, "relationship_types": rel_types, "entities": entities,
                     "relationships": rels, "parameters": params, "parameter_values": values},
            "ir": ir}


def platform_solve(client, headers, db, name, ir, data, rel_ends=None, time_limit=60, body=None, settings=None):
    from app.worker import work_once

    t0 = time.monotonic()
    built = client.post("/api/v1/problems/from-spec", json=to_spec(name, ir, data, rel_ends), headers=headers)
    build_s = round(time.monotonic() - t0, 2)
    if built.status_code != 200:
        return {"status": "build refused", "detail": built.text[:600]}
    if settings:
        from sqlalchemy import text as _t
        for key, value in settings.items():
            db.execute(_t("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, :k, CAST(:v AS jsonb))"),
                       {"p": built.json()["problem_id"], "k": key, "v": json.dumps(value)})
        db.commit()
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs",
                      json={"time_limit_s": time_limit, **(body or {})}, headers=headers)
    if run.status_code not in (200, 201):
        return {"status": "run refused", "detail": run.text[:600]}
    for _ in range(10):
        if work_once(db) is None:
            break
    got = client.get(f"/api/v1/runs/{run.json()['id']}", headers=headers).json()
    p = got.get("params") or {}
    return {"status": got["status"], "objective": got.get("objective"), "bound": got.get("best_bound"),
            "solver": got.get("solver"), "solve_s": got.get("wall_time_s"), "total_s": round(time.monotonic() - t0, 2),
            "build_s": build_s, "phases": p.get("phases"), "class": p.get("classified_as"), "reused_from": got.get("reused_from"), "why": (p.get("why_solver") or "")[:200], "error": got.get("error"),
            "assignments": got.get("assignments"), "amounts": got.get("amounts"), "params_keys": sorted(p)[:200],
            "notes": {k: p.get(k) for k in ("stochastic", "stochastic_run", "stochastic_samples", "uncertainty", "warnings",
                                             "notes", "out_of_sample") if p.get(k) not in (None, 0, [], {})}}


# -- term helpers -------------------------------------------------------------------------------------------------
def S(body, *over, where=None):
    return {"sum": body, "over": [{"index": i, "set": s, **({"via": v} if v else {})} for i, s, *rest in over
                                  for v in [rest[0] if rest else None]]}


def V(n, *ix):
    return {"var": n, "index": list(ix)}


def P(n, *ix):
    return {"par": n, "index": list(ix)}


def A(of, n):
    return {"attr": {"of": of, "name": n}}


def MUL(a, b):
    return {"mul": [a, b]}


def C(v):
    return {"const": v}


def rule(id_, left, rel, right, forall=(), **kw):
    scope = [{"index": i, "set": s, **({"via": v} if v else {})} for i, s, *rest in forall
             for v in [rest[0] if rest else None]]
    return {"id": id_, **({"forall": scope} if scope else {}),
            "left": left, "relation": rel, "right": right, "severity": "hard", **kw}


def goal(sense, *terms, mode=None):
    return {"sense": sense, **({"mode": mode} if mode else {}),
            "terms": [{"id": f"o{k}", "weight": w, "expression": e} for k, (w, e) in enumerate(terms)]}


def data(sets, params=None, defaults=None, rels=None):
    return {"sets": sets, "parameters": params or {}, "parameter_defaults": defaults or {}, "relationships": rels or {}}


# -- the cases -----------------------------------------------------------------------------------------------------
def case_transport():
    rnd = random.Random(1)
    plants = [{"id": f"p{i}", "supply": rnd.randint(80, 140)} for i in range(4)]
    tot = sum(p["supply"] for p in plants)
    markets = [{"id": f"m{j}", "demand": d} for j, d in enumerate(np.random.default_rng(1).multinomial(int(tot * .85), [1 / 7] * 7))]
    markets = [{**m, "demand": int(m["demand"])} for m in markets]
    cost = {(p["id"], m["id"]): rnd.randint(3, 30) for p in plants for m in markets}
    ir = {"version": 2, "sets": ["plant", "market"], "parameters": {"cost": {"index": ["plant", "market"]}},
          "variables": {"ship": {"index": ["plant", "market"], "domain": "continuous", "lower": 0}},
          "constraints": [rule("c_sup", S(V("ship", "p", "m"), ("m", "market")), "<=", A("p", "supply"), [("p", "plant")]),
                          rule("c_dem", S(V("ship", "p", "m"), ("p", "plant")), ">=", A("m", "demand"), [("m", "market")])],
          "objective": goal("minimize", (1, S(MUL(P("cost", "p", "m"), V("ship", "p", "m")), ("p", "plant"), ("m", "market"))))}
    d = data({"plant": plants, "market": markets}, {"cost": [{"plant": a, "market": b, "value": v} for (a, b), v in cost.items()]})
    m = M()
    for (a, b), v in cost.items():
        m.var(f"{a},{b}"); m.c[f"{a},{b}"] = v
    for p in plants:
        m.con({f"{p['id']},{mm['id']}": 1 for mm in markets}, hi=p["supply"])
    for mm in markets:
        m.con({f"{p['id']},{mm['id']}": 1 for p in plants}, lo=mm["demand"])
    return "Transportation (LP)", ir, d, None, m.solve()[0]


def case_assignment():
    rng = np.random.default_rng(2)
    n = 10
    cost = rng.integers(5, 99, size=(n, n))
    ir = {"version": 2, "sets": ["worker", "task"], "parameters": {"cost": {"index": ["worker", "task"]}},
          "variables": {"x": {"index": ["worker", "task"], "domain": "binary"}},
          "constraints": [rule("c_w", S(V("x", "w", "t"), ("t", "task")), "=", C(1), [("w", "worker")]),
                          rule("c_t", S(V("x", "w", "t"), ("w", "worker")), "=", C(1), [("t", "task")])],
          "objective": goal("minimize", (1, S(MUL(P("cost", "w", "t"), V("x", "w", "t")), ("w", "worker"), ("t", "task"))))}
    d = data({"worker": [{"id": f"w{i}"} for i in range(n)], "task": [{"id": f"t{j}"} for j in range(n)]},
             {"cost": [{"worker": f"w{i}", "task": f"t{j}", "value": int(cost[i, j])} for i in range(n) for j in range(n)]})
    r, c = linear_sum_assignment(cost)
    return "Assignment (IP)", ir, d, None, float(cost[r, c].sum())


def case_knapsack():
    rnd = random.Random(3)
    items = [{"id": f"i{k}", "w": rnd.randint(3, 40), "v": rnd.randint(5, 90)} for k in range(35)]
    cap = sum(i["w"] for i in items) // 3
    ir = {"version": 2, "sets": ["item"], "parameters": {},
          "variables": {"take": {"index": ["item"], "domain": "binary"}},
          "constraints": [rule("c_cap", S(MUL(A("i", "w"), V("take", "i")), ("i", "item")), "<=", C(cap))],
          "objective": goal("maximize", (1, S(MUL(A("i", "v"), V("take", "i")), ("i", "item"))))}
    best = [0] * (cap + 1)
    for it in items:
        for w in range(cap, it["w"] - 1, -1):
            best[w] = max(best[w], best[w - it["w"]] + it["v"])
    return "0-1 knapsack (IP)", ir, data({"item": items}), None, float(best[cap])


def case_setcover():
    rnd = random.Random(4)
    elems = [f"e{k}" for k in range(30)]
    sets_ = []
    for k in range(45):
        mem = rnd.sample(elems, rnd.randint(3, 8))
        sets_.append({"id": f"s{k}", "cost": rnd.randint(5, 25), "members": mem})
    for e in elems:  # every element coverable
        if not any(e in s["members"] for s in sets_):
            sets_[0]["members"].append(e)
    rels = {"covers": [{"from": s["id"], "to": e} for s in sets_ for e in s["members"]]}
    ir = {"version": 2, "sets": ["subset", "element"], "relationships": ["covers"], "parameters": {},
          "variables": {"pick": {"index": ["subset"], "domain": "binary"}},
          "constraints": [rule("c_cover", S(V("pick", "s"), ("s", "subset", {"rel": "covers", "to": "e"})), ">=", C(1), [("e", "element")])],
          "objective": goal("minimize", (1, S(MUL(A("s", "cost"), V("pick", "s")), ("s", "subset"))))}
    d = data({"subset": [{"id": s["id"], "cost": s["cost"]} for s in sets_], "element": [{"id": e} for e in elems]}, rels=rels)
    m = M()
    for s in sets_:
        m.var(s["id"], 0, 1, True); m.c[s["id"]] = s["cost"]
    for e in elems:
        m.con({s["id"]: 1 for s in sets_ if e in s["members"]}, lo=1)
    return "Set cover (IP)", ir, d, {"covers": ("subset", "element")}, m.solve()[0]


def case_binpacking():
    rnd = random.Random(5)
    items = [{"id": f"i{k}", "size": rnd.randint(10, 60)} for k in range(14)]
    bins = [{"id": f"b{k}"} for k in range(8)]
    cap = 100
    ir = {"version": 2, "sets": ["item", "bin"], "parameters": {},
          "variables": {"put": {"index": ["item", "bin"], "domain": "binary"}, "use": {"index": ["bin"], "domain": "binary"}},
          "constraints": [rule("c_one", S(V("put", "i", "b"), ("b", "bin")), "=", C(1), [("i", "item")]),
                          rule("c_cap", S(MUL(A("i", "size"), V("put", "i", "b")), ("i", "item")), "<=", MUL(C(cap), V("use", "b")), [("b", "bin")])],
          "objective": goal("minimize", (1, S(V("use", "b"), ("b", "bin"))))}
    m = M()
    for b in bins:
        m.var(b["id"], 0, 1, True); m.c[b["id"]] = 1
        for i in items:
            m.var(f"{i['id']}@{b['id']}", 0, 1, True)
    for i in items:
        m.con({f"{i['id']}@{b['id']}": 1 for b in bins}, 1, 1)
    for b in bins:
        m.con({**{f"{i['id']}@{b['id']}": i["size"] for i in items}, b["id"]: -cap}, hi=0)
    return "Bin packing (IP)", ir, data({"item": items, "bin": bins}), None, m.solve()[0]


def case_facility():
    from bench.families import facility
    ir, d = facility("M", 0)
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
    return f"Capacitated facility location (MILP, {len(sites)}x{len(cust)})", ir, d, None, m.solve()[0]


def case_mincostflow(seed=6, want_feasible=True):
    import networkx as nx
    for attempt in range(50):
        rnd = random.Random(seed * 100 + attempt)
        made = _flow_instance(rnd)
        nodes, supply, arcs = made
        G = nx.DiGraph()
        for n in nodes:
            G.add_node(n, demand=-supply[n])
        for a in arcs:
            G.add_edge(a["tail"], a["head"], capacity=a["cap"], weight=a["cost"])
        try:
            ref = float(nx.min_cost_flow_cost(G))
            feasible = True
        except nx.NetworkXUnfeasible:
            ref, feasible = "infeasible", False
        if feasible == want_feasible:
            break
    return _flow_case(nodes, supply, arcs, ref, "Min-cost network flow (LP)" if want_feasible
                      else "Infeasible network flow (must be reported as infeasible)")


def case_infeasible_flow():
    return case_mincostflow(7, want_feasible=False)


def _flow_instance(rnd):
    nodes = [f"n{k}" for k in range(12)]
    supply = {n: 0 for n in nodes}
    supply["n0"], supply["n1"], supply["n10"], supply["n11"] = 40, 25, -30, -35
    arcs = []
    for a in nodes:
        for b in nodes:
            if a != b and rnd.random() < 0.25:
                arcs.append({"id": f"{a}>{b}", "tail": a, "head": b, "cap": rnd.randint(10, 40), "cost": rnd.randint(1, 12)})
    return nodes, supply, arcs


def _flow_case(nodes, supply, arcs, ref, label):
    rels = {"out_of": [{"from": a["id"], "to": a["tail"]} for a in arcs], "into": [{"from": a["id"], "to": a["head"]} for a in arcs]}
    ir = {"version": 2, "sets": ["arc", "node"], "relationships": ["out_of", "into"], "parameters": {},
          "variables": {"flow": {"index": ["arc"], "domain": "continuous", "lower": 0}},
          "constraints": [
              rule("c_cap", V("flow", "a"), "<=", A("a", "cap"), [("a", "arc")]),
              rule("c_balance", {"add": [S(V("flow", "a"), ("a", "arc", {"rel": "out_of", "to": "n"})),
                                         MUL(C(-1), S(V("flow", "b"), ("b", "arc", {"rel": "into", "to": "n"})))]},
                   "=", A("n", "supply"), [("n", "node")])],
          "objective": goal("minimize", (1, S(MUL(A("a", "cost"), V("flow", "a")), ("a", "arc"))))}
    d = data({"arc": [{k: v for k, v in a.items() if k not in ("tail", "head")} for a in arcs],
              "node": [{"id": n, "supply": supply[n]} for n in nodes]}, rels=rels)
    return label, ir, d, {"out_of": ("arc", "node"), "into": ("arc", "node")}, ref


def case_lotsizing():
    rnd = random.Random(7)
    T = 8
    periods = [{"id": f"t{k}", "demand": rnd.randint(20, 80), "k": k} for k in range(T)]
    setup, hold, cap = 300, 2, 150
    rels = {"next": [{"from": f"t{k}", "to": f"t{k + 1}"} for k in range(T - 1)]}
    ir = {"version": 2, "sets": ["period"], "relationships": ["next"], "parameters": {},
          "variables": {"make": {"index": ["period"], "domain": "continuous", "lower": 0, "upper": cap},
                        "stock": {"index": ["period"], "domain": "continuous", "lower": 0},
                        "on": {"index": ["period"], "domain": "binary"}},
          "constraints": [
              rule("c_first", {"add": [V("make", "t"), MUL(C(-1), V("stock", "t"))]}, "=", A("t", "demand"),
                   [("t", "period")], ),
              rule("c_setup", V("make", "t"), "<=", MUL(C(cap), V("on", "t")), [("t", "period")])],
          "objective": goal("minimize", (setup, S(V("on", "t"), ("t", "period"))), (hold, S(V("stock", "t"), ("t", "period"))))}
    # balance: stock[prev] + make[t] - stock[t] = demand[t]; the first period has no prev
    ir["constraints"][0]["forall"] = [{"index": "t", "set": "period", "where": [{"attr": "k", "op": "=", "value": 0}]}]
    ir["constraints"].append(rule("c_flow", {"add": [V("stock", "s"), V("make", "t"), MUL(C(-1), V("stock", "t"))]}, "=",
                                  A("t", "demand"), [("s", "period"), ("t", "period", {"rel": "next", "from": "s"})]))
    m = M()
    for p in periods:
        for n in ("make", "stock", "on"):
            m.var(f"{n}{p['k']}", 0, cap if n == "make" else (1 if n == "on" else np.inf), n == "on")
        m.c[f"on{p['k']}"] = setup; m.c[f"stock{p['k']}"] = hold
        m.con({f"make{p['k']}": 1, f"on{p['k']}": -cap}, hi=0)
        prev = {f"stock{p['k'] - 1}": 1} if p["k"] else {}
        m.con({**prev, f"make{p['k']}": 1, f"stock{p['k']}": -1}, p["demand"], p["demand"])
    return "Lot sizing over periods (MILP)", ir, data({"period": periods}, rels=rels), {"next": ("period", "period")}, m.solve()[0]


def _vrp(n_stops, fleet, seed, load=True):
    from bench.routing import vrp
    ir, d = vrp("S", seed, load=load)
    keep = {"depot", *(f"s{k}" for k in range(1, n_stops + 1))}
    d["sets"]["stop"] = [r for r in d["sets"]["stop"] if r["id"] in keep]
    d["sets"]["vehicle"] = d["sets"]["vehicle"][:fleet]
    d["parameters"]["distance"] = [r for r in d["parameters"]["distance"] if r["0"] in keep and r["1"] in keep]
    if load:
        tot = sum(r["demand"] for r in d["sets"]["stop"])
        for v in d["sets"]["vehicle"]:
            v["capacity"] = math.ceil(tot / fleet * 1.25)
    return ir, d


def _vrp_brute(ir, d, windows=False):
    rows = {r["id"]: r for r in d["sets"]["stop"]}
    dist = {(r["0"], r["1"]): r["value"] for r in d["parameters"]["distance"]}
    stops = [s for s in rows if s != "depot"]
    vehicles = d["sets"]["vehicle"]
    load = "demand" in ir["constraints"][0]["route"]

    def cost(order):
        if windows:
            clock = rows["depot"]["open"]
            for a, b in zip(("depot", *order), order):
                clock += rows[a].get("serve", 0) + dist[(a, b)]
                if clock > rows[b]["close"]:
                    return None
                clock = max(clock, rows[b]["open"])
        return sum(dist[(a, b)] for a, b in zip(("depot", *order), (*order, "depot")))

    best = math.inf
    for owner in itertools.product(range(len(vehicles)), repeat=len(stops)):
        total = 0
        for k, v in enumerate(vehicles):
            mine = [s for s, o in zip(stops, owner) if o == k]
            if not mine:
                continue
            if load and sum(rows[s]["demand"] for s in mine) > v["capacity"]:
                break
            cs = [c for c in (cost(o) for o in itertools.permutations(mine)) if c is not None]
            if not cs:
                break
            total += min(cs)
        else:
            best = min(best, total)
    return float(best)


def case_tsp():
    ir, d = _vrp(8, 1, 3, load=False)
    return "Travelling salesman (route, 8 stops)", ir, d, None, _vrp_brute(ir, d)


def case_cvrp():
    ir, d = _vrp(7, 2, 4, load=True)
    return "Capacitated vehicle routing (route, 7 stops, 2 trucks)", ir, d, None, _vrp_brute(ir, d)


def case_vrptw():
    ir, d = _vrp(6, 2, 5, load=False)
    rnd = random.Random("tw5")
    for row in d["sets"]["stop"]:
        if row["id"] == "depot":
            row["open"], row["close"], row["serve"] = 0, 1000, 0
            continue
        o = rnd.randint(0, 120)
        row["open"], row["close"], row["serve"] = o, o + 60, 3
    ir["constraints"][0]["route"].update(travel="distance", earliest="open", latest="close", service="serve")
    return "Vehicle routing with time windows (route, 6 stops)", ir, d, None, _vrp_brute(ir, d, windows=True)


def case_jobshop():
    from ortools.sat.python import cp_model
    # ft06-like: 5 jobs x 4 machines, own CP-SAT model as the reference
    rnd = random.Random(8)
    jobs, machines = 5, 4
    ops = []
    for j in range(jobs):
        order = rnd.sample(range(machines), machines)
        for k, mch in enumerate(order):
            ops.append({"id": f"j{j}o{k}", "job": f"j{j}", "k": k, "machine": f"m{mch}", "dur": rnd.randint(2, 9)})
    H = sum(o["dur"] for o in ops)
    mdl = cp_model.CpModel()
    s = {o["id"]: mdl.NewIntVar(0, H, "") for o in ops}
    e = {o["id"]: mdl.NewIntVar(0, H, "") for o in ops}
    iv = {o["id"]: mdl.NewIntervalVar(s[o["id"]], o["dur"], e[o["id"]], "") for o in ops}
    for mm in range(machines):
        mdl.AddNoOverlap([iv[o["id"]] for o in ops if o["machine"] == f"m{mm}"])
    for a in ops:
        for b in ops:
            if a["job"] == b["job"] and b["k"] == a["k"] + 1:
                mdl.Add(s[b["id"]] >= e[a["id"]])
    mk = mdl.NewIntVar(0, H, "")
    mdl.AddMaxEquality(mk, list(e.values())); mdl.Minimize(mk)
    sol = cp_model.CpSolver(); sol.parameters.max_time_in_seconds = 60
    assert sol.Solve(mdl) == cp_model.OPTIMAL
    ref = sol.ObjectiveValue()
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
    d = data({"op": [{"id": o["id"], "k": o["k"]} for o in ops], "machine": [{"id": f"m{k}"} for k in range(machines)]},
             {"dur": [{"op": o["id"], "value": o["dur"]} for o in ops]}, rels=rels)
    return "Job-shop scheduling (intervals, 5x4)", ir, d, {"then": ("op", "op"), "on": ("op", "machine")}, ref


def case_rcpsp():
    from ortools.sat.python import cp_model
    rnd = random.Random(9)
    n, crew = 10, 4
    acts = [{"id": f"a{k}", "dur": rnd.randint(2, 7), "need": rnd.randint(1, 3)} for k in range(n)]
    prec = [(f"a{a}", f"a{b}") for a in range(n) for b in range(a + 1, n) if rnd.random() < 0.15]
    H = sum(a["dur"] for a in acts)
    mdl = cp_model.CpModel()
    s = {a["id"]: mdl.NewIntVar(0, H, "") for a in acts}
    e = {a["id"]: mdl.NewIntVar(0, H, "") for a in acts}
    iv = {a["id"]: mdl.NewIntervalVar(s[a["id"]], a["dur"], e[a["id"]], "") for a in acts}
    mdl.AddCumulative([iv[a["id"]] for a in acts], [a["need"] for a in acts], crew)
    for a, b in prec:
        mdl.Add(s[b] >= e[a])
    mk = mdl.NewIntVar(0, H, ""); mdl.AddMaxEquality(mk, list(e.values())); mdl.Minimize(mk)
    sol = cp_model.CpSolver(); sol.parameters.max_time_in_seconds = 60
    assert sol.Solve(mdl) == cp_model.OPTIMAL
    act = {"index": ["act"]}
    ir = {"version": 2, "sets": ["act"], "relationships": ["before"], "parameters": {"dur": {"index": ["act"]}, "need": {"index": ["act"]}},
          "variables": {"begin": {**act, "domain": "integer", "lower": 0, "upper": H},
                        "finish": {**act, "domain": "integer", "lower": 0, "upper": H},
                        "makespan": {"index": [], "domain": "integer", "lower": 0, "upper": H},
                        "task": {**act, "domain": "interval", "start": "begin", "end": "finish", "size": "dur"}},
          "constraints": [
              {"id": "c_crew", "cumulative": {"interval": V("task", "a"), "over": [{"index": "a", "set": "act"}],
                                              "demand": P("need", "a"), "capacity": C(crew)}, "severity": "hard"},
              rule("c_prec", V("finish", "a"), "<=", V("begin", "b"), [("a", "act"), ("b", "act", {"rel": "before", "from": "a"})]),
              rule("c_span", V("finish", "a"), "<=", V("makespan"), [("a", "act")])],
          "objective": goal("minimize", (1, V("makespan")))}
    d = data({"act": [{"id": a["id"]} for a in acts]},
             {"dur": [{"act": a["id"], "value": a["dur"]} for a in acts], "need": [{"act": a["id"], "value": a["need"]} for a in acts]},
             rels={"before": [{"from": a, "to": b} for a, b in prec]})
    return "Resource-constrained project scheduling (cumulative)", ir, d, {"before": ("act", "act")}, sol.ObjectiveValue()


def case_coloring():
    rnd = random.Random(10)
    nodes = [f"v{k}" for k in range(11)]
    edges = [(a, b) for i, a in enumerate(nodes) for b in nodes[i + 1:] if rnd.random() < 0.35]
    colours = [f"c{k}" for k in range(6)]
    m = M()
    for c in colours:
        m.var("u" + c, 0, 1, True); m.c["u" + c] = 1
        for v in nodes:
            m.var(f"{v}{c}", 0, 1, True); m.con({f"{v}{c}": 1, "u" + c: -1}, hi=0)
        for a, b in edges:
            m.con({f"{a}{c}": 1, f"{b}{c}": 1}, hi=1)
    for v in nodes:
        m.con({f"{v}{c}": 1 for c in colours}, 1, 1)
    ref = m.solve()[0]
    ir = {"version": 2, "sets": ["node", "colour"], "relationships": ["edge"], "parameters": {},
          "variables": {"x": {"index": ["node", "colour"], "domain": "binary"}, "used": {"index": ["colour"], "domain": "binary"}},
          "constraints": [rule("c_one", S(V("x", "v", "c"), ("c", "colour")), "=", C(1), [("v", "node")]),
                          rule("c_used", V("x", "v", "c"), "<=", V("used", "c"), [("v", "node"), ("c", "colour")]),
                          rule("c_edge", {"add": [V("x", "a", "c"), V("x", "b", "c")]}, "<=", C(1),
                               [("a", "node"), ("b", "node", {"rel": "edge", "from": "a"}), ("c", "colour")])],
          "objective": goal("minimize", (1, S(V("used", "c"), ("c", "colour"))))}
    d = data({"node": [{"id": v} for v in nodes], "colour": [{"id": c} for c in colours]},
             rels={"edge": [{"from": a, "to": b} for a, b in edges]})
    return "Graph colouring (IP)", ir, d, {"edge": ("node", "node")}, ref


def case_portfolio():
    rng = np.random.default_rng(11)
    n = 8
    mu = rng.uniform(0.03, 0.15, n)
    B = rng.normal(size=(n, n)) * 0.1
    cov = B @ B.T + np.diag(rng.uniform(0.001, 0.01, n))
    target = float(np.quantile(mu, 0.6))
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}, {"type": "ineq", "fun": lambda w: mu @ w - target}]
    res = minimize(lambda w: w @ cov @ w, np.ones(n) / n, jac=lambda w: 2 * cov @ w, constraints=cons,
                   bounds=[(0, 1)] * n, method="SLSQP", options={"ftol": 1e-14, "maxiter": 1000})
    names = [f"a{k}" for k in range(n)]
    ir = {"version": 2, "sets": ["asset"], "parameters": {"cov": {"index": ["asset", "asset"]}},
          "variables": {"w": {"index": ["asset"], "domain": "continuous", "lower": 0, "upper": 1}},
          "constraints": [rule("c_all", S(V("w", "i"), ("i", "asset")), "=", C(1)),
                          rule("c_ret", S(MUL(A("i", "mu"), V("w", "i")), ("i", "asset")), ">=", C(target))],
          "objective": goal("minimize", (1, S(MUL(P("cov", "i", "j"), MUL(V("w", "i"), V("w", "j"))), ("i", "asset"), ("j", "asset"))))}
    d = data({"asset": [{"id": a, "mu": float(mu[k])} for k, a in enumerate(names)]},
             {"cov": [{"0": a, "1": b, "value": float(cov[i, j])} for i, a in enumerate(names) for j, b in enumerate(names)]})
    return "Mean-variance portfolio (QP)", ir, d, None, float(res.fun)


def case_nlp_log():
    rng = np.random.default_rng(12)
    n, budget = 6, 10.0
    a = rng.uniform(0.5, 3, n)
    # maximise sum log(a_i + x_i), sum x = budget, x >= 0: water filling
    lo, hi = 0, 100
    for _ in range(200):
        level = (lo + hi) / 2
        if np.maximum(level - a, 0).sum() > budget:
            hi = level
        else:
            lo = level
    x = np.maximum(lo - a, 0)
    ref = float(np.log(a + x).sum())
    ir = {"version": 2, "sets": ["chan"], "parameters": {},
          "variables": {"x": {"index": ["chan"], "domain": "continuous", "lower": 0, "upper": budget}},
          "constraints": [rule("c_budget", S(V("x", "i"), ("i", "chan")), "=", C(budget))],
          "objective": goal("maximize", (1, S({"fn": "log", "of": {"add": [A("i", "a"), V("x", "i")]}}, ("i", "chan"))))}
    return "Water-filling (concave NLP, log)", ir, data({"chan": [{"id": f"c{k}", "a": float(a[k])} for k in range(n)]}), None, ref


def case_pwl():
    # buy from suppliers with quantity discounts (concave piecewise cost) to cover demand
    pts = {"s0": [[0, 0], [100, 900], [300, 2100], [600, 3600]], "s1": [[0, 0], [150, 1200], [400, 2600], [600, 3400]],
           "s2": [[0, 0], [50, 600], [250, 1800], [600, 3900]]}
    demand = 520
    m = M()  # reference: lambda formulation with segment binaries
    for s, p in pts.items():
        for k in range(len(p)):
            m.var(f"l{s}{k}", 0, 1)
        for k in range(len(p) - 1):
            m.var(f"z{s}{k}", 0, 1, True)
        m.con({f"z{s}{k}": 1 for k in range(len(p) - 1)}, 1, 1)
        m.con({f"l{s}{k}": 1 for k in range(len(p))}, 1, 1)
        for k in range(len(p)):
            near = {f"z{s}{j}": -1 for j in (k - 1, k) if 0 <= j < len(p) - 1}
            m.con({f"l{s}{k}": 1, **near}, hi=0)
        for k, (x, y) in enumerate(p):
            m.c[f"l{s}{k}"] = y
    m.con({f"l{s}{k}": p[k][0] for s, p in pts.items() for k in range(len(p))}, lo=demand)
    ref = m.solve()[0]
    q = {"var": "q", "index": []}
    ir = {"version": 2, "sets": [], "parameters": {},
          "variables": {f"q_{s}": {"index": [], "domain": "continuous", "lower": 0, "upper": 600} for s in pts},
          "constraints": [rule("c_dem", {"add": [V(f"q_{s}") for s in pts]}, ">=", C(demand))],
          "objective": goal("minimize", *[(1, {"pwl": V(f"q_{s}"), "points": p}) for s, p in pts.items()])}
    return "Quantity discounts (concave piecewise-linear)", ir, data({}), None, ref


def case_lex():
    # nurses: first cover as many requested-off wishes as possible, then the cheapest
    rnd = random.Random(13)
    people = [{"id": f"p{k}", "wage": rnd.randint(80, 140)} for k in range(6)]
    days = [{"id": f"d{k}", "need": rnd.randint(2, 3)} for k in range(5)]
    off = {(p["id"], d["id"]): 1 for p in people for d in days if rnd.random() < 0.3}
    ir = {"version": 2, "sets": ["person", "day"], "parameters": {"off": {"index": ["person", "day"]}},
          "variables": {"w": {"index": ["person", "day"], "domain": "binary"}},
          "constraints": [rule("c_need", S(V("w", "p", "d"), ("p", "person")), ">=", A("d", "need"), [("d", "day")]),
                          rule("c_max", S(V("w", "p", "d"), ("d", "day")), "<=", C(3), [("p", "person")])],
          "objective": goal("minimize", (1, S(MUL(P("off", "p", "d"), V("w", "p", "d")), ("p", "person"), ("d", "day"))),
                            (1, S(MUL(A("p", "wage"), V("w", "p", "d")), ("p", "person"), ("d", "day"))), mode="lex")}

    def base():
        m = M()
        for p in people:
            for d in days:
                m.var(p["id"] + d["id"], 0, 1, True)
        for d in days:
            m.con({p["id"] + d["id"]: 1 for p in people}, lo=d["need"])
        for p in people:
            m.con({p["id"] + d["id"]: 1 for d in days}, hi=3)
        return m
    m1 = base(); m1.c = {p + d: 1 for (p, d) in off}
    first = m1.solve()[0]
    m2 = base(); m2.con({p + d: 1 for (p, d) in off}, hi=first + 1e-6)
    m2.c = {p["id"] + d["id"]: p["wage"] for p in people for d in days}
    second = m2.solve()[0]
    d = data({"person": people, "day": days}, {"off": [{"person": p, "day": dd, "value": 1} for (p, dd) in off]})
    return "Ranked goals (lexicographic)", ir, d, None, (first, second)


def case_soft():
    # exam slots: hard one slot each; soft "not two exams of a student in one slot", weight 10 per clash; prefer early
    rnd = random.Random(14)
    exams = [f"e{k}" for k in range(9)]
    slots = [{"id": f"s{k}", "late": k} for k in range(3)]
    clash = [(a, b) for i, a in enumerate(exams) for b in exams[i + 1:] if rnd.random() < 0.4]
    ir = {"version": 2, "sets": ["exam", "slot"], "relationships": ["clash"], "parameters": {},
          "variables": {"x": {"index": ["exam", "slot"], "domain": "binary"}},
          "constraints": [rule("c_one", S(V("x", "e", "s"), ("s", "slot")), "=", C(1), [("e", "exam")]),
                          {**rule("c_clash", {"add": [V("x", "a", "s"), V("x", "b", "s")]}, "<=", C(1),
                                  [("a", "exam"), ("b", "exam", {"rel": "clash", "from": "a"}), ("s", "slot")]),
                           "severity": "soft", "weight": 10}],
          "objective": goal("minimize", (1, S(MUL(A("s", "late"), V("x", "e", "s")), ("e", "exam"), ("s", "slot"))))}
    m = M()
    for e in exams:
        for s in slots:
            m.var(e + s["id"], 0, 1, True); m.c[e + s["id"]] = s["late"]
        m.con({e + s["id"]: 1 for s in slots}, 1, 1)
    for a, b in clash:
        for s in slots:
            m.var(f"v{a}{b}{s['id']}", 0, 1); m.c[f"v{a}{b}{s['id']}"] = 10
            m.con({a + s["id"]: 1, b + s["id"]: 1, f"v{a}{b}{s['id']}": -1}, hi=1)
    d = data({"exam": [{"id": e} for e in exams], "slot": slots}, rels={"clash": [{"from": a, "to": b} for a, b in clash]})
    return "Soft rules with penalties (timetabling)", ir, d, {"clash": ("exam", "exam")}, m.solve()[0]


def case_newsvendor():
    # order before demand is known: price 3, cost 1, demand +-50% around 100 -> quantile 2/3 of U(50,150) = 116.7
    ir = {"version": 2, "sets": [], "parameters": {"demand": {"index": [], "uncertainty": {"kind": "interval", "deviation": 0.5}}},
          "variables": {"order": {"index": [], "domain": "continuous", "lower": 0, "upper": 300, "stage": 1},
                        "sell": {"index": [], "domain": "continuous", "lower": 0, "upper": 300, "stage": 2}},
          "constraints": [rule("c_stock", V("sell"), "<=", V("order")), rule("c_dem", V("sell"), "<=", P("demand"))],
          "objective": goal("maximize", (3, V("sell")), (-1, V("order")))}
    return "Two-stage stochastic (newsvendor)", ir, data({}, defaults={"demand": 100}), None, 116.67


def case_districting():
    from bench.families import districting
    ir, d = districting("S", 0)
    return "Districting (connected groups)", {**ir, "version": 2}, d, None, None


CASES = [case_transport, case_assignment, case_knapsack, case_setcover, case_binpacking, case_facility, case_mincostflow,
         case_infeasible_flow,
         case_lotsizing, case_tsp, case_cvrp, case_vrptw, case_jobshop, case_rcpsp, case_coloring, case_portfolio,
         case_nlp_log, case_pwl, case_lex, case_soft, case_newsvendor]


def test_battery(tenants, db, empty_queue):  # noqa: F811
    client = TestClient(app)
    out = []
    only = __import__("os").environ.get("ONLY")
    for make in CASES:
        if only and make.__name__ not in only.split(","):
            continue
        try:
            label, ir, d, ends, ref = make()
        except Exception as exc:  # a reference that failed
            out.append({"case": make.__name__, "error": f"reference: {exc!r}"})
            continue
        got = platform_solve(client, tenants["b"], db, make.__name__, ir, d, ends, time_limit=60)
        if make is case_newsvendor:
            on = platform_solve(client, tenants["b"], db, make.__name__ + "_on", ir, d, ends, time_limit=60,
                                settings={"solve.stochastic_samples": 50})
            got["with_50_futures"] = {k: on.get(k) for k in ("status", "objective", "amounts", "reused_from")}
        row = {"case": make.__name__, "label": label, "reference": ref, **{k: v for k, v in got.items() if k != "assignments"}}
        if make is case_lex and got.get("assignments"):
            row["lex_check"] = "see assignments"
            row["assignments_sample"] = str(got["assignments"])[:300]
        out.append(row)
        print(json.dumps(row, default=str))
        json.dump(out, open(OUT, "w"), default=str, indent=1)
