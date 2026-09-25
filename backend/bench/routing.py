"""Vehicle routing: the exact rows against OR-Tools' routing search as a start (queue R15b).

    python -m bench.routing --time-limit 120

Capacitated vehicle routing on random points: a depot in the middle, stops
around it with demands, a fleet of equal vehicles, distances rounded to whole
units, the least total distance. Each instance solved sandboxed, as a run, by
the rules' choice (CP-SAT) on the `route` rule's exact rows from nothing, and
from `app.solve.routing`'s start (its time taken from the solver's); the
routing search's own answer is shown beside them. What decides
`solve.routing_start`: an answer where there was none, and no size where the
start makes the answer worse.
"""

from __future__ import annotations

import argparse
import math
import random
import time

SIZES = {"S": (7, 2), "M": (15, 3), "L": (30, 5), "XL": (60, 8)}


def vrp(size: str, instance: int = 0, *, load: bool = True) -> tuple[dict, dict]:
    stops, fleet = SIZES[size]
    rnd = random.Random(f"vrp-{size}-{instance}")
    points = [(50, 50)] + [(rnd.randint(0, 100), rnd.randint(0, 100)) for _ in range(stops)]
    names = ["depot"] + [f"s{k}" for k in range(1, stops + 1)]
    demand = [0] + [rnd.randint(1, 9) for _ in range(stops)]
    capacity = math.ceil(sum(demand) / fleet * 1.3)
    visit = {"var": "visit", "index": ["v", "i", "j"]}
    route = {"visit": visit, "vehicles": {"index": "v", "set": "vehicle"}, "stops": {"index": "i", "set": "stop"},
             "depot": "depot"}
    if load:
        route.update(demand="demand", capacity="capacity")
    ir = {
        "version": 2, "sets": ["vehicle", "stop"],
        "parameters": {"distance": {"index": ["stop", "stop"]}},
        "variables": {"visit": {"index": ["vehicle", "stop", "stop"], "domain": "binary"}},
        "constraints": [{"id": "c_routes", "severity": "hard", "route": route}],
        "objective": {"sense": "minimize", "terms": [{"id": "o_distance", "weight": 1, "expression": {
            "sum": {"mul": [{"par": "distance", "index": ["i", "j"]}, visit]},
            "over": [{"index": "v", "set": "vehicle"}, {"index": "i", "set": "stop"}, {"index": "j", "set": "stop"}]}}]},
    }
    data = {
        "sets": {"vehicle": [{"id": f"truck{k}", "capacity": capacity} for k in range(fleet)],
                 "stop": [{"id": n, "demand": d, "x": p[0], "y": p[1]} for n, d, p in zip(names, demand, points)]},
        "parameters": {"distance": [{"0": a, "1": b, "value": round(math.dist(pa, pb))}
                                    for a, pa in zip(names, points) for b, pb in zip(names, points)]},
        "parameter_defaults": {}, "relationships": {},
    }
    return ir, data


def main(argv=None) -> int:
    from app.solve import compile_model, routing, sandbox
    from app.solve.service import gap_of

    parser = argparse.ArgumentParser(prog="python -m bench.routing", description=__doc__.split("\n\n")[0])
    parser.add_argument("--time-limit", type=float, default=120.0)
    parser.add_argument("--sizes", default="S,M,L,XL")
    args = parser.parse_args(argv)
    print("| size | stops / vehicles | routing search: objective / s | cp-sat from nothing | cp-sat from the search's start |")
    print("|---|---|---|---|---|")
    for size in args.sizes.split(","):
        ir, data = vrp(size)
        compiled = compile_model(ir, data)
        began = time.monotonic()
        hint, record = routing.start(ir, data, compiled, seconds=min(routing.CEILING, routing.SHARE * args.time_limit))
        took = time.monotonic() - began
        cells = []
        for start in (None, hint):
            left = args.time_limit - (took if start else 0)
            try:
                r = sandbox.run("app.solve.sandbox:solve_in_child",
                                {"backend": "cp-sat", "compiled": compiled, "time_limit": left, "seed": 1, "workers": 8,
                                 "gap_rel": 0.0, "hint": start}, time_limit=left, workers=8)[0]
                gap = 0 if r.status == "optimal" else gap_of(r.objective, r.best_bound)
                cells.append(f"{r.status} / {r.objective} / gap {'--' if gap is None else f'{gap * 100:.3g}%'}")
            except Exception as exc:  # noqa: BLE001 -- recorded as a row
                cells.append(f"failed: {str(exc)[:50]}")
        stops, fleet = SIZES[size]
        print(f"| {size} | {stops} / {fleet} | {record.get('objective')} / {record.get('seconds')} | {cells[0]} | {cells[1]} |",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
