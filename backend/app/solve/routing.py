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
from app.solve.route import LOAD

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
    if any(v < 0 or v != v.to_integral_value() for v in compiled.objective.coeffs.values()):
        return "the routing search takes whole, non-negative costs"
    return None


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
    depot = stops.index(body["depot"])
    if "demand" in body:
        demand = [0 if s == body["depot"] else int(Decimal(str(row[body["demand"]])))
                  for s, row in zip(stops, stop_rows)]
        capacity = [int(Decimal(str(row[body["capacity"]]))) for row in data["sets"][body["vehicles"]["set"]]]
    else:
        demand = [0 if s == body["depot"] else 1 for s in stops]
        capacity = [len(stops) - 1] * len(vehicles)
    cost = {v: [[int(compiled.objective.coeffs.get((var, (v, a, b)), 0)) for b in stops] for a in stops]
            for v in vehicles}

    manager = pywrapcp.RoutingIndexManager(len(stops), len(vehicles), depot)
    model = pywrapcp.RoutingModel(manager)
    for k, v in enumerate(vehicles):
        table = cost[v]
        callback = model.RegisterTransitCallback(
            lambda i, j, t=table: t[manager.IndexToNode(i)][manager.IndexToNode(j)])
        model.SetArcCostEvaluatorOfVehicle(callback, k)
    load = model.RegisterUnaryTransitCallback(lambda i: demand[manager.IndexToNode(i)])
    model.AddDimensionWithVehicleCapacity(load, 0, capacity, True, "load")
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
    for k, v in enumerate(vehicles):
        index, path = model.Start(k), []
        while not model.IsEnd(index):
            path.append(manager.IndexToNode(index))
            index = solution.Value(model.NextVar(index))
        path.append(manager.IndexToNode(index))
        if len(path) <= 2:
            continue
        used += 1
        carried = sum(demand[n] for n in path)
        for a, b in zip(path, path[1:]):
            hint[(var, (v, stops[a], stops[b]))] = 1
            hint[(LOAD, (rule_id, v, stops[a], stops[b]))] = carried - demand[a] if a != depot else carried
            if a != depot:
                carried -= demand[a]
    hint = {k: val for k, val in hint.items() if k in compiled.variables}
    from app.solve.evolve import holds, objective_at

    return hint, {**record, "used_vehicles": used, "objective": objective_at(compiled, hint),
                  "feasible": holds(compiled, hint), "seconds": round(time.monotonic() - began, 3)}
