"""A routing start: OR-Tools' routing search, handed to the exact rows (queue R15b).

A `route` rule's exact rows (`app.solve.route`) are proven by CP-SAT on a
handful of stops; past that the search space outruns any proof in minutes.
OR-Tools' routing library is built for exactly this model: a first set of
routes by cheapest arc, then guided local search (moving stops between and
within routes) for as long as it is given. It proves nothing. So, as the
connected start does (R13): it runs first, for a share of the time, and its
routes -- visits and the load each vehicle carries on each arc, so every row
holds -- are handed to the exact solver as a start. The solver may improve
or prove them; if it ends with nothing, the routes are the run's answer,
`feasible` and claiming nothing.

**When it applies**: one `route` rule; a goal to minimise that reads only the
visits, with whole, non-negative costs; whole demands and capacities. Other
rules may sit beside it -- the search does not see them, so its routes are
kept as an answer only if every compiled row holds at them.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from app.solve.compile import Compiled, VarKey
from app.solve.route import ARRIVE, LOAD

#: The share of the run's time the search takes, and its ceiling in seconds.
SHARE, CEILING = 0.2, 30.0


def _rule(ir: dict[str, Any]) -> dict[str, Any] | None:
    rules = [c for c in ir.get("constraints") or [] if isinstance(c, dict) and "route" in c]
    return rules[0] if len(rules) == 1 else None


def applies(ir: dict[str, Any], compiled: Compiled) -> str | None:
    rules = [c for c in ir.get("constraints") or [] if isinstance(c, dict) and "route" in c]
    if not rules:
        return "the model has no route rule"
    if len(rules) > 1:
        return "more than one route rule is left to the solver"
    if compiled.sense != "minimize":
        return "the routing search minimises; this goal is maximised"
    if compiled.objective_quadratic:
        return "the goal multiplies decisions together"
    var = rules[0]["route"]["visit"]["var"]
    other = next((k for k in compiled.objective.coeffs if k[0] != var), None)
    if other is not None:
        return f"the goal reads {other[0]!r} as well as the visits"
    if any(v < 0 for v in compiled.objective.coeffs.values()):
        return "the routing search takes non-negative costs"
    return None


def _scale(costs) -> int:
    """Costs as the whole numbers the routing search takes: as they are when whole, else in
    thousandths -- 2.35 km is 2350 (benchmark, October 2026: fractional distances got no start)."""
    return 1 if all(c == c.to_integral_value() for c in costs) else 1000


def start(ir: dict[str, Any], data: dict[str, Any], compiled: Compiled, *, seconds: float) -> tuple[dict[VarKey, int], dict[str, Any]]:
    """Routes from the routing search as a complete start (visits and loads), and what it found."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    began = time.monotonic()
    rule = _rule(ir)
    body, rule_id = rule["route"], rule["id"]
    var = body["visit"]["var"]
    vehicles = [row["id"] for row in data["sets"].get(body["vehicles"]["set"], [])]
    stop_rows = data["sets"].get(body["stops"]["set"], [])
    stops = [row["id"] for row in stop_rows]
    from app.solve.route import depots_of

    home = depots_of(body, data["sets"].get(body["vehicles"]["set"], []), stops, rule_id, data.get("relationships"))
    starts = [stops.index(home[v]) for v in vehicles]
    depot_nodes = set(starts)
    if "demand" in body:
        demand = [0 if n in depot_nodes else int(Decimal(str(row[body["demand"]])))
                  for n, row in enumerate(stop_rows)]
        capacity = [int(Decimal(str(row[body["capacity"]]))) for row in data["sets"][body["vehicles"]["set"]]]
    else:
        demand = [0 if n in depot_nodes else 1 for n in range(len(stops))]
        capacity = [len(stops) - len(depot_nodes)] * len(vehicles)
    scale = _scale(compiled.objective.coeffs.values())
    cost = {v: [[int(round(compiled.objective.coeffs.get((var, (v, a, b)), 0) * scale)) for b in stops] for a in stops]
            for v in vehicles}

    manager = pywrapcp.RoutingIndexManager(len(stops), len(vehicles), starts, starts)
    model = pywrapcp.RoutingModel(manager)
    for k, v in enumerate(vehicles):
        table = cost[v]
        callback = model.RegisterTransitCallback(
            lambda i, j, t=table: t[manager.IndexToNode(i)][manager.IndexToNode(j)])
        model.SetArcCostEvaluatorOfVehicle(callback, k)
    load = model.RegisterUnaryTransitCallback(lambda i: demand[manager.IndexToNode(i)])
    model.AddDimensionWithVehicleCapacity(load, 0, capacity, True, "load")
    times = None
    if "travel" in body:
        # Queue R15c: the windows as a time dimension, from the compiled arrivals' own bounds.
        leg = {(a, b): 0 for a in stops for b in stops}
        # Indexed [stop, stop], a type twice: the dataset keys its cells by position.
        table = {(r["0"], r["1"]): r["value"] for r in (data.get("parameters") or {}).get(body["travel"], [])}
        fallback = (data.get("parameter_defaults") or {}).get(body["travel"], 0) or 0
        serve = {s: int(Decimal(str(row.get(body["service"], 0) or 0))) if body.get("service") else 0
                 for s, row in zip(stops, stop_rows)}
        for a in stops:
            for b in stops:
                if a != b:
                    leg[(a, b)] = serve[a] + int(Decimal(str(table.get((a, b), fallback))))
        bounds = {s: compiled.variables[(ARRIVE, (rule_id, s))] for s in stops}
        horizon = int(max(b.upper for b in bounds.values()))
        transit = model.RegisterTransitCallback(
            lambda i, j: leg[(stops[manager.IndexToNode(i)], stops[manager.IndexToNode(j)])])
        model.AddDimension(transit, horizon, horizon + max(leg.values(), default=0) + 1, False, "time")
        times = model.GetDimensionOrDie("time")
        for n, s in enumerate(stops):
            if n in depot_nodes:
                for k in range(len(vehicles)):
                    if starts[k] == n:
                        times.CumulVar(model.Start(k)).SetRange(int(bounds[s].lower), int(bounds[s].upper))
            else:
                times.CumulVar(manager.NodeToIndex(n)).SetRange(int(bounds[s].lower), int(bounds[s].upper))
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    # Guided local search runs until told to stop: half a second a stop is plenty on a small model
    # (the bench found each optimum well inside it), and the rest of the time is the exact solver's.
    seconds = min(seconds, max(1.0, 0.5 * len(stops)))
    params.time_limit.FromMilliseconds(max(100, int(seconds * 1000)))
    solution = model.SolveWithParameters(params)
    record: dict[str, Any] = {"rule": rule_id, "stops": len(stops), "vehicles": len(vehicles)}
    if solution is None:
        return {}, {**record, "feasible": False, "why": "the routing search found no routes within the capacities",
                    "seconds": round(time.monotonic() - began, 3)}

    hint: dict[VarKey, int] = {}
    for v in vehicles:
        for a in stops:
            for b in stops:
                hint[(var, (v, a, b))] = 0
                if a != b:
                    hint[(LOAD, (rule_id, v, a, b))] = 0
    used = 0
    departure: dict[int, int] = {}
    for k, v in enumerate(vehicles):
        index, path = model.Start(k), []
        while not model.IsEnd(index):
            path.append(manager.IndexToNode(index))
            if times is not None:
                at = solution.Value(times.CumulVar(index))
                node = manager.IndexToNode(index)
                if node in depot_nodes:
                    # One departure time per depot: the earliest any leaves, so no arrival is early.
                    departure[node] = min(departure.get(node, at), at)
                else:
                    hint[(ARRIVE, (rule_id, stops[node]))] = at
            index = solution.Value(model.NextVar(index))
        path.append(manager.IndexToNode(index))
        if len(path) <= 2:
            continue
        used += 1
        carried = sum(demand[n] for n in path)
        for a, b in zip(path, path[1:]):
            hint[(var, (v, stops[a], stops[b]))] = 1
            hint[(LOAD, (rule_id, v, stops[a], stops[b]))] = carried - demand[a] if a not in depot_nodes else carried
            if a not in depot_nodes:
                carried -= demand[a]
    if times is not None:
        for n in depot_nodes:
            key = (ARRIVE, (rule_id, stops[n]))
            hint[key] = departure.get(n, int(compiled.variables[key].lower))
    hint = {k: val for k, val in hint.items() if k in compiled.variables}
    from app.solve.evolve import holds, objective_at

    return hint, {**record, "used_vehicles": used, "objective": objective_at(compiled, hint),
                  "feasible": holds(compiled, hint), "seconds": round(time.monotonic() - began, 3)}
