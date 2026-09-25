"""Time windows on a `route` (queue R15c): exact rows checked against every split and order."""

from __future__ import annotations

import itertools
import math
import random

import pytest

from app.ir.validate import check_shape
from app.solve import compile_model, routing
from app.solve.backends import by_name
from app.solve.compile import Unsupported
from app.solve.evolve import holds
from bench.routing import vrp

SERVICE = 2


def _windowed(seed: int, tight: bool = False):
    """Five stops, two vehicles; distance is also the travel time; each stop a random window."""
    ir, data = vrp("S", seed, load=False)
    keep = {"depot", "s1", "s2", "s3", "s4", "s5"}
    data["sets"]["stop"] = [r for r in data["sets"]["stop"] if r["id"] in keep]
    data["sets"]["vehicle"] = data["sets"]["vehicle"][:2]
    data["parameters"]["distance"] = [r for r in data["parameters"]["distance"] if r["0"] in keep and r["1"] in keep]
    rnd = random.Random(f"windows-{seed}")
    for row in data["sets"]["stop"]:
        if row["id"] == "depot":
            row["open"], row["close"] = 0, 1000
            continue
        opens = rnd.randint(0, 120)
        row["open"], row["close"], row["serve"] = opens, opens + (25 if tight else 80), SERVICE
    ir["constraints"][0]["route"].update(travel="distance", earliest="open", latest="close", service="serve")
    return ir, data


def _brute(ir, data) -> float:
    """The least distance over every split of the stops between the vehicles and every order of each
    share that keeps every window: arriving early waits, arriving late is not allowed."""
    rows = {r["id"]: r for r in data["sets"]["stop"]}
    dist = {(r["0"], r["1"]): r["value"] for r in data["parameters"]["distance"]}
    stops = [s for s in rows if s != "depot"]

    def cost(order):
        clock = rows["depot"]["open"]
        for a, b in zip(("depot", *order), order):
            clock += rows[a].get("serve", 0) + dist[(a, b)]
            if clock > rows[b]["close"]:
                return None
            clock = max(clock, rows[b]["open"])
        total = sum(dist[(a, b)] for a, b in zip(("depot", *order), (*order, "depot")))
        return total

    best = math.inf
    for owner in itertools.product(range(2), repeat=len(stops)):
        total = 0
        for k in range(2):
            mine = [s for s, o in zip(stops, owner) if o == k]
            if not mine:
                continue
            costs = [c for c in (cost(order) for order in itertools.permutations(mine)) if c is not None]
            if not costs:
                break
            total += min(costs)
        else:
            best = min(best, total)
    return best


@pytest.mark.parametrize("tight", [False, True])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_the_rows_hold_exactly_the_routes_that_keep_every_window(seed, tight):
    ir, data = _windowed(seed, tight)
    assert check_shape(ir) is None
    expected = _brute(ir, data)
    result = by_name("cp-sat").solve(compile_model(ir, data), time_limit=30, workers=8, seed=1)
    if expected == math.inf:
        assert result.status == "infeasible"
    else:
        assert result.status == "optimal" and float(result.objective) == pytest.approx(expected)


def test_windows_can_make_a_shorter_route_wrong():
    """A window forces an order: without it the shortest tour is cheaper."""
    ir, data = _windowed(0, tight=True)
    unwindowed_ir, unwindowed_data = _windowed(0, tight=True)
    for key in ("travel", "earliest", "latest", "service"):
        unwindowed_ir["constraints"][0]["route"].pop(key)
    windowed = by_name("cp-sat").solve(compile_model(ir, data), time_limit=30, workers=8, seed=1)
    loose = by_name("cp-sat").solve(compile_model(unwindowed_ir, unwindowed_data), time_limit=30, workers=8, seed=1)
    assert loose.status == "optimal"
    assert windowed.status == "infeasible" or float(windowed.objective) >= float(loose.objective)


def test_the_routing_start_keeps_the_windows():
    ir, data = _windowed(1)
    compiled = compile_model(ir, data)
    hint, record = routing.start(ir, data, compiled, seconds=2)
    if record["feasible"]:
        assert set(hint) == set(compiled.variables) and holds(compiled, hint)
    result = by_name("cp-sat").solve(compiled, time_limit=30, workers=8, seed=1, hint=hint)
    assert result.status == "optimal" and float(result.objective) == pytest.approx(_brute(ir, data))


def test_a_window_needs_travel_and_travel_is_a_stop_to_stop_parameter():
    ir, _ = _windowed(0)
    route = ir["constraints"][0]["route"]
    route.pop("travel")
    assert check_shape(ir).code == "route_malformed"
    route["travel"] = "nowhere"
    refusal = check_shape(ir)
    assert refusal.code == "route_travel_invalid" and refusal.loc[-1] == "travel"


def test_a_window_that_closes_before_it_opens_is_refused():
    ir, data = _windowed(0)
    data["sets"]["stop"][1]["close"] = data["sets"]["stop"][1]["open"] - 1
    with pytest.raises(Unsupported, match="opens at .* after it closes"):
        compile_model(ir, data)
