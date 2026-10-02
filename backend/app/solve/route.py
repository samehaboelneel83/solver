"""`route`, compiled: exact rows for vehicle routing (queue R15b).

`visit[v, i, j]` is 1 when vehicle v goes from stop i straight to stop j.
The rule holds when every stop but the depot is visited once, each vehicle
leaves every stop it enters, and leaves the depot at most once -- and when
no vehicle runs a loop that misses the depot. That last is held by a load
flow, single-commodity like `app.solve.connected`: each vehicle carries
out of the depot what its stops will take, drops each stop's demand there,
and carries on the rest. A loop away from the depot would have to drop
demand with nothing brought in, so it cannot exist. The flow on an arc is
at most the vehicle's capacity while the arc is used, and nothing when it is
not: the same rows hold the load.

Without `demand` and `capacity` every stop counts as one and a vehicle can
carry all of them. With them, every stop but the depot must take a positive
demand (a stop taking nothing could sit in a loop the flow cannot see), and
the flow is whole when every demand is.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

LOAD = "__load"
#: A stop's arrival time on a route with time windows (queue R15c).
ARRIVE = "__arrive"


def expand(compiler: Any, spec: dict[str, Any]) -> None:
    from app.solve.compile import Constraint, Linear, Unsupported, Variable

    body = spec["route"]
    rule = spec["id"]
    var = body["visit"]["var"]
    vehicles = compiler.sets.get(body["vehicles"]["set"], [])
    stop_rows = compiler.sets.get(body["stops"]["set"], [])
    stops = [row["id"] for row in stop_rows]
    home = depots_of(body, vehicles, stops, rule, compiler.edges)
    depots = set(home.values()) or ({body["depot"]} if body.get("depot") else set())
    one, zero = Decimal(1), Decimal(0)
    others = [s for s in stops if s not in depots]
    if "demand" in body:
        demand: dict[str, Decimal] = {}
        for row in stop_rows:
            if row["id"] in depots:
                continue
            value = row.get(body["demand"])
            if value is None or Decimal(str(value)) <= 0:
                raise Unsupported(f"{rule}: the stop {row['id']!r} has no positive {body['demand']!r}; every stop "
                                  "but the depot must take some load, or a loop could hide from the load flow")
            demand[row["id"]] = Decimal(str(value))
        capacity: dict[str, Decimal] = {}
        for row in vehicles:
            value = row.get(body["capacity"])
            if value is None or Decimal(str(value)) < 0:
                raise Unsupported(f"{rule}: the vehicle {row['id']!r} has no {body['capacity']!r}")
            capacity[row["id"]] = Decimal(str(value))
    else:
        demand = {s: one for s in others}
        capacity = {row["id"]: Decimal(len(others)) for row in vehicles}
    whole = all(d == d.to_integral_value() for d in demand.values()) and all(
        c == c.to_integral_value() for c in capacity.values())

    def row(index: dict[str, str], left: Linear, relation: str, right: Linear) -> None:
        compiler.constraints.append(Constraint(rule, index, left, relation, right))

    v_name, s_name = body["vehicles"]["index"], body["stops"]["index"]
    to_name = body["visit"]["index"][2]
    x = {}
    for vehicle in vehicles:
        v = vehicle["id"]
        for i in stops:
            for j in stops:
                key = (var, (v, i, j))
                if key not in compiler.variables:  # pragma: no cover -- the validator pins the index
                    raise Unsupported(f"{rule}: no variable {key}")
                x[(v, i, j)] = key
    for (v, i, j), key in x.items():
        if i == j:  # nowhere to go from a stop to itself
            row({v_name: v, s_name: i, to_name: j}, Linear(coeffs={key: one}), "=", Linear())
    # Every stop but the depot is entered once, by some vehicle.
    for j in others:
        row({s_name: j}, Linear(coeffs={x[(v["id"], i, j)]: one for v in vehicles for i in stops if i != j}),
            "=", Linear(const=one))
    for vehicle in vehicles:
        v = vehicle["id"]
        # What a vehicle enters, it leaves.
        for j in stops:
            balance = Linear(coeffs={x[(v, i, j)]: one for i in stops if i != j})
            balance.add(Linear(coeffs={x[(v, j, k)]: one for k in stops if k != j}), factor=-1)
            row({v_name: v, s_name: j}, balance, "=", Linear())
        # It leaves its depot once at most, and never goes through another vehicle's depot.
        depot = home[v]
        row({v_name: v}, Linear(coeffs={x[(v, depot, j)]: one for j in others}), "<=", Linear(const=one))
        for d in depots - {depot}:
            for k in stops:
                if k != d:
                    row({v_name: v, s_name: d, to_name: k}, Linear(coeffs={x[(v, d, k)]: one, x[(v, k, d)]: one}), "=", Linear())
        # The load: at most the capacity on an arc in use, nothing on one that is not ...
        load = {}
        for i in stops:
            for j in stops:
                if i == j:
                    continue
                key = (LOAD, (rule, v, i, j))
                compiler.variables[key] = Variable(key, "integer" if whole else "continuous", zero, capacity[v])
                load[(i, j)] = key
                row({v_name: v, s_name: i, to_name: j}, Linear(coeffs={key: one, x[(v, i, j)]: -capacity[v]}),
                    "<=", Linear())
        # ... and each stop it enters keeps its demand of what comes in.
        for j in others:
            balance = Linear(coeffs={load[(i, j)]: one for i in stops if i != j})
            balance.add(Linear(coeffs={load[(j, k)]: one for k in stops if k != j}), factor=-1)
            balance.add(Linear(coeffs={x[(v, i, j)]: demand[j] for i in stops if i != j}), factor=-1)
            row({v_name: v, s_name: j}, balance, "=", Linear())
    if "travel" in body:
        _windows(compiler, spec, stop_rows, x, vehicles, row)
    compiler.connectivity.append(rule)
    compiler.routes.append(rule)


def depots_of(body: dict[str, Any], vehicles: list[dict[str, Any]], stops: list[str], rule: str,
              edges: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, str]:
    """Each vehicle's depot: the one `depot` for all, the stop its `depot_of` field names (several
    depots; benchmark, October 2026), or the stop it is linked to by the relationship `depot_by` --
    placed there by an earlier plan and kept as links (benchmark re-test, October 2026)."""
    from app.solve.compile import Unsupported

    linked: dict[str, set[str]] = {}
    if body.get("depot_by"):
        at = set(stops)
        for edge in (edges or {}).get(body["depot_by"], []):
            a, b = str(edge["from"]), str(edge["to"])
            for vehicle, stop in ((a, b), (b, a)):
                if stop in at and vehicle != stop:
                    linked.setdefault(vehicle, set()).add(stop)
    home: dict[str, str] = {}
    for vehicle in vehicles:
        if body.get("depot_by"):
            found = sorted(linked.get(str(vehicle["id"]), ()))
            if len(found) != 1:
                raise Unsupported(f"{rule}: the vehicle {vehicle['id']} is linked by {body['depot_by']} to "
                                  + (f"{len(found)} {body['stops']['set']} ({', '.join(found)})" if found else f"no {body['stops']['set']}")
                                  + "; each vehicle starts from one")
            home[vehicle["id"]] = found[0]
            continue
        depot = body["depot"] if body.get("depot") else vehicle.get(body["depot_of"])
        if depot is None or str(depot) not in stops:
            where = f"the depot {depot!r}" if body.get("depot") else f"the vehicle {vehicle['id']}'s {body['depot_of']} {depot!r}"
            raise Unsupported(f"{rule}: {where} is not one of the {body['stops']['set']} in the data")
        home[vehicle["id"]] = str(depot)
    return home


def _windows(compiler: Any, spec: dict[str, Any], stop_rows: list[dict[str, Any]], x: dict, vehicles: list,
             row) -> None:
    """Time windows (queue R15c): an arrival time per stop within its window, and on every arc in use
    the next stop's arrival at least this one's plus the time spent here plus the travel between.

    A stop with no `earliest` opens at 0 and one with no `latest` never closes (the horizon: long
    enough for one vehicle to serve every stop after the latest opening, and past every window). The depot's arrival is when
    the vehicles set out; nothing waits on their return. The rows are exact: on an arc not in use
    the big-M lets the arrivals be anything, and M is as small as a route can make it. They also
    rule out a loop that misses the depot -- time cannot go round a circle."""
    from app.solve.compile import Linear, Unsupported, Variable, number

    body, rule = spec["route"], spec["id"]
    stops = [r["id"] for r in stop_rows]
    depots = set(depots_of(body, vehicles, stops, rule, compiler.edges).values())
    one, zero = Decimal(1), Decimal(0)

    def attribute(r: dict[str, Any], name: str | None) -> Decimal | None:
        if not name or r.get(name) is None:
            return None
        value = r[name]
        if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
            raise Unsupported(f"{rule}: the stop {r['id']!r} has {name!r} {value!r}, not a number")
        return number(value)

    table = compiler._params.get(body["travel"], {})
    fallback = number(compiler.defaults.get(body["travel"], 0) or 0)
    travel = {(i, j): number(table.get((i, j), fallback)) for i in stops for j in stops if i != j}
    if any(t < 0 for t in travel.values()):
        raise Unsupported(f"{rule}: a travel time in {body['travel']!r} is negative")
    service = {r["id"]: (attribute(r, body.get("service")) or zero) for r in stop_rows}
    earliest = {r["id"]: attribute(r, body.get("earliest")) for r in stop_rows}
    latest = {r["id"]: attribute(r, body.get("latest")) for r in stop_rows}
    # Long enough for any one vehicle to serve every stop, taking the longest leg out of each,
    # starting at the latest opening -- and no earlier than the latest window closes.
    tour = sum(service.values(), zero) + sum(
        (max((travel[(i, j)] for j in stops if j != i), default=zero) for i in stops), zero)
    horizon = max([v for v in latest.values() if v is not None]
                  + [max((v for v in earliest.values() if v is not None), default=zero) + tour])
    opens = {s: earliest[s] if earliest[s] is not None else zero for s in stops}
    closes = {s: latest[s] if latest[s] is not None else horizon for s in stops}
    for s in stops:
        if opens[s] > closes[s]:
            raise Unsupported(f"{rule}: the stop {s!r} opens at {opens[s]} after it closes at {closes[s]}")
    whole = all(v == v.to_integral_value() for v in [*travel.values(), *service.values(), *opens.values(), *closes.values()])
    arrive = {}
    for s in stops:
        key = (ARRIVE, (rule, s))
        compiler.variables[key] = Variable(key, "integer" if whole else "continuous", opens[s], closes[s])
        arrive[s] = key
    s_name, to_name = body["stops"]["index"], body["visit"]["index"][2]
    for i in stops:
        for j in stops:
            if i == j or j in depots:
                continue
            # The smallest M that frees the row when the arc is not used.
            big = closes[i] + service[i] + travel[(i, j)] - opens[j]
            if big <= 0:
                continue  # the window alone keeps this row
            used = {x[(v["id"], i, j)]: -big for v in vehicles}
            left = Linear(coeffs={arrive[j]: one, arrive[i]: -one, **used})
            row({s_name: i, to_name: j}, left, ">=", Linear(const=service[i] + travel[(i, j)] - big))
