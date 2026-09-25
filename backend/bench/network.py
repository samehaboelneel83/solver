"""Does a network model solve faster as a network? (queue R15a)

    python -m bench.network --time-limit 120

Four network families, S to XL, written as ordinary models (the network
lane reads them off the compiled rows; nothing marks them as networks):

- `transport`: plants ship to customers, each plant within its supply, each
  customer's demand met, least cost (continuous flows);
- `assignment`: each person to one task and each task to one person, least
  cost (yes/no);
- `max_flow`: as much as a grid carries from one corner to the other, each
  arc within its capacity (a circulation with a return arc);
- `shortest_path`: one unit from one corner of a grid to the other, least
  cost.

Each solved by the network lane (min-cost flow, in-process) and, sandboxed as
a run, by the backend the rules choose and by HiGHS. The verdict: the same
objective as the proven one (0 wrong), and how much faster.
"""

from __future__ import annotations

import argparse
import random
import time

SIZES = {
    "transport": {"S": (5, 10), "M": (20, 50), "L": (60, 200), "XL": (150, 600)},
    "assignment": {"S": 10, "M": 50, "L": 150, "XL": 400},
    "max_flow": {"S": 6, "M": 15, "L": 40, "XL": 80},
    "shortest_path": {"S": 6, "M": 15, "L": 40, "XL": 80},
}
NO_DATA = {"parameter_defaults": {}, "relationships": {}}


def _sum(body, *over):
    return {"sum": body, "over": [{"index": i, "set": s} for i, s in over]}


def transport(size, instance=0):
    plants, customers = SIZES["transport"][size]
    rnd = random.Random(f"transport-{size}-{instance}")
    demand = [rnd.randint(5, 40) for _ in range(customers)]
    total = sum(demand)
    supply = [total // plants + rnd.randint(0, total // plants) for _ in range(plants)]
    ship = {"var": "ship", "index": ["p", "c"]}
    ir = {
        "version": 2, "sets": ["plant", "customer"],
        "parameters": {"cost": {"index": ["plant", "customer"]}},
        "variables": {"ship": {"index": ["plant", "customer"], "domain": "continuous", "lower": 0}},
        "constraints": [
            {"id": "c_supply", "forall": [{"index": "p", "set": "plant"}], "left": _sum(ship, ("c", "customer")),
             "relation": "<=", "right": {"attr": {"of": "p", "name": "supply"}}, "severity": "hard"},
            {"id": "c_demand", "forall": [{"index": "c", "set": "customer"}], "left": _sum(ship, ("p", "plant")),
             "relation": ">=", "right": {"attr": {"of": "c", "name": "demand"}}, "severity": "hard"},
        ],
        "objective": {"sense": "minimize", "terms": [{"id": "o_cost", "weight": 1, "expression": _sum(
            {"mul": [{"par": "cost", "index": ["p", "c"]}, ship]}, ("p", "plant"), ("c", "customer"))}]},
    }
    data = {**NO_DATA, "sets": {"plant": [{"id": f"p{i}", "supply": s} for i, s in enumerate(supply)],
                                "customer": [{"id": f"c{j}", "demand": d} for j, d in enumerate(demand)]},
            "parameters": {"cost": [{"plant": f"p{i}", "customer": f"c{j}", "value": rnd.randint(1, 99)}
                                    for i in range(plants) for j in range(customers)]}}
    return ir, data


def assignment(size, instance=0):
    n = SIZES["assignment"][size]
    rnd = random.Random(f"assignment-{size}-{instance}")
    x = {"var": "assign", "index": ["p", "t"]}
    ir = {
        "version": 2, "sets": ["person", "task"],
        "parameters": {"cost": {"index": ["person", "task"]}},
        "variables": {"assign": {"index": ["person", "task"], "domain": "binary"}},
        "constraints": [
            {"id": "c_one_task", "forall": [{"index": "p", "set": "person"}], "left": _sum(x, ("t", "task")),
             "relation": "=", "right": {"const": 1}, "severity": "hard"},
            {"id": "c_one_person", "forall": [{"index": "t", "set": "task"}], "left": _sum(x, ("p", "person")),
             "relation": "=", "right": {"const": 1}, "severity": "hard"},
        ],
        "objective": {"sense": "minimize", "terms": [{"id": "o_cost", "weight": 1, "expression": _sum(
            {"mul": [{"par": "cost", "index": ["p", "t"]}, x]}, ("p", "person"), ("t", "task"))}]},
    }
    data = {**NO_DATA, "sets": {"person": [{"id": f"w{i}"} for i in range(n)], "task": [{"id": f"t{j}"} for j in range(n)]},
            "parameters": {"cost": [{"person": f"w{i}", "task": f"t{j}", "value": rnd.randint(1, 999)}
                                    for i in range(n) for j in range(n)]}}
    return ir, data


def _grid(k, rnd):
    nodes = [f"n{r}_{c}" for r in range(k) for c in range(k)]
    arcs = []
    for r in range(k):
        for c in range(k):
            for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0)):
                if 0 <= r + dr < k and 0 <= c + dc < k:
                    arcs.append((f"n{r}_{c}", f"n{r + dr}_{c + dc}", rnd.randint(1, 20)))
    inc = []
    for i, (a, b, _) in enumerate(arcs):
        inc.append({"node": a, "arc": f"a{i}", "value": -1})
        inc.append({"node": b, "arc": f"a{i}", "value": 1})
    return nodes, arcs, inc


def max_flow(size, instance=0):
    k = SIZES["max_flow"][size]
    rnd = random.Random(f"max_flow-{size}-{instance}")
    nodes, arcs, inc = _grid(k, rnd)
    source, sink = nodes[0], nodes[-1]
    flow = {"var": "flow", "index": ["a"]}
    ir = {
        "version": 2, "sets": ["node", "arc"],
        "parameters": {"inc": {"index": ["node", "arc"]}, "back": {"index": ["node"]}},
        "variables": {"flow": {"index": ["arc"], "domain": "continuous", "lower": 0},
                      "total": {"index": [], "domain": "continuous", "lower": 0}},
        "constraints": [
            {"id": "c_balance", "forall": [{"index": "n", "set": "node"}],
             "left": {"add": [_sum({"mul": [{"par": "inc", "index": ["n", "a"]}, flow]}, ("a", "arc")),
                              {"mul": [{"par": "back", "index": ["n"]}, {"var": "total", "index": []}]}]},
             "relation": "=", "right": {"const": 0}, "severity": "hard"},
            {"id": "c_capacity", "forall": [{"index": "a", "set": "arc"}], "left": flow, "relation": "<=",
             "right": {"attr": {"of": "a", "name": "capacity"}}, "severity": "hard"},
        ],
        "objective": {"sense": "maximize", "terms": [{"id": "o_total", "weight": 1, "expression": {"var": "total", "index": []}}]},
    }
    data = {"parameter_defaults": {"inc": 0, "back": 0}, "relationships": {},
            "sets": {"node": [{"id": n} for n in nodes], "arc": [{"id": f"a{i}", "capacity": cap} for i, (_, _, cap) in enumerate(arcs)]},
            "parameters": {"inc": inc, "back": [{"node": source, "value": 1}, {"node": sink, "value": -1}]}}
    return ir, data


def shortest_path(size, instance=0):
    k = SIZES["shortest_path"][size]
    rnd = random.Random(f"shortest_path-{size}-{instance}")
    nodes, arcs, inc = _grid(k, rnd)
    flow = {"var": "use", "index": ["a"]}
    ir = {
        "version": 2, "sets": ["node", "arc"],
        "parameters": {"inc": {"index": ["node", "arc"]}},
        "variables": {"use": {"index": ["arc"], "domain": "continuous", "lower": 0}},
        "constraints": [{"id": "c_balance", "forall": [{"index": "n", "set": "node"}],
                         "left": _sum({"mul": [{"par": "inc", "index": ["n", "a"]}, flow]}, ("a", "arc")),
                         "relation": "=", "right": {"attr": {"of": "n", "name": "need"}}, "severity": "hard"}],
        "objective": {"sense": "minimize", "terms": [{"id": "o_length", "weight": 1, "expression": _sum(
            {"mul": [{"attr": {"of": "a", "name": "length"}}, flow]}, ("a", "arc"))}]},
    }
    need = {nodes[0]: -1, nodes[-1]: 1}
    data = {"parameter_defaults": {"inc": 0}, "relationships": {}, "parameters": {"inc": inc},
            "sets": {"node": [{"id": n, "need": need.get(n, 0)} for n in nodes],
                     "arc": [{"id": f"a{i}", "length": length} for i, (_, _, length) in enumerate(arcs)]}}
    return ir, data


FAMILIES = {"transport": transport, "assignment": assignment, "max_flow": max_flow, "shortest_path": shortest_path}


def _exact(backend, compiled, time_limit):
    from app.solve import sandbox

    began = time.monotonic()
    try:
        result = sandbox.run("app.solve.sandbox:solve_in_child",
                             {"backend": backend, "compiled": compiled, "time_limit": time_limit, "seed": 1,
                              "workers": 8, "gap_rel": 0.0}, time_limit=time_limit, workers=8)[0]
        return result.status, result.objective, round(time.monotonic() - began, 3)
    except Exception as exc:  # noqa: BLE001 -- recorded as a row
        return f"failed: {str(exc)[:40]}", None, round(time.monotonic() - began, 3)


def main(argv=None) -> int:
    from app.solve import compile_model, network
    from app.solve.backends import choose
    from app.solve.classify import classify
    from app.solve.convexity import refine

    parser = argparse.ArgumentParser(prog="python -m bench.network", description=__doc__.split("\n\n")[0])
    parser.add_argument("--time-limit", type=float, default=120.0)
    parser.add_argument("--sizes", default="S,M,L,XL")
    args = parser.parse_args(argv)
    print("| family | size | decisions | network: status / objective / s | rules' choice: backend / status / objective / s "
          "| highs: status / objective / s | agree |")
    print("|---|---|---|---|---|---|---|")
    for family, make in FAMILIES.items():
        for size in args.sizes.split(","):
            ir, data = make(size)
            compiled = compile_model(ir, data)
            why = network.applies(compiled)
            began = time.monotonic()
            if why is None:
                done = network.solve(compiled).solution
                net = (done.status, done.objective, round(time.monotonic() - began, 3))
            else:
                net = (f"not a network: {why}", None, 0)
            chosen = choose(refine(classify(ir, data), compiled))[0].name
            rules = _exact(chosen, compiled, args.time_limit)
            highs = rules if chosen == "highs" else _exact("highs", compiled, args.time_limit)
            proven = [r for r in (rules, highs) if r[0] == "optimal"]
            agree = "--" if not proven or net[1] is None else (
                "yes" if all(abs(float(r[1]) - float(net[1])) <= 1e-6 * max(1, abs(float(r[1]))) for r in proven) else "**no**")
            fmt = lambda r: f"{r[0]} / {r[1]} / {r[2]}"  # noqa: E731
            print(f"| {family} | {size} | {len(compiled.variables)} | {fmt(net)} | {chosen} / {fmt(rules)} | "
                  f"{fmt(highs)} | {agree} |", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
