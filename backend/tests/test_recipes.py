"""The recipes the model editor writes (benchmark, October 2026, G3d) -- selection under a budget,
network design and phasing over periods -- solve, and to the answer worked out by hand. The models
are the ones `frontend/src/model/recipes.ts` writes, kept in the shared fixtures."""

from __future__ import annotations

import json

from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.service import solve_compiled

FIXTURES = {v["name"]: v["ir"] for v in json.load(open("tests/ir_fixtures.json"))["valid"]}


def _solve(name, data):
    data = {"parameters": {}, "parameter_defaults": {}, **data}
    result, _ = solve_compiled(by_name("highs"), compile_model(FIXTURES[name], data), time_limit=20, seed=1)
    assert result.status == "optimal", result
    return result


def test_selection_takes_the_most_value_within_the_budget():
    projects = [{"id": "a", "benefit": 10, "capex": 300, "committed": False}, {"id": "b", "benefit": 7, "capex": 200, "committed": False},
                {"id": "c", "benefit": 6, "capex": 200, "committed": False}, {"id": "d", "benefit": 1, "capex": 50, "committed": True}]
    # Budget 500, at most 3, d always: d + a (350) leaves 150 -- or d + b + c (450) for 14 > 11.
    assert round(float(_solve("recipe_selection", {"sets": {"project": projects}}).objective)) == 14


def test_network_opens_ships_and_buys_trucks_at_the_least_cost():
    data = {
        "sets": {
            "depot": [{"id": "north", "capacity": 100, "fixed_cost": 50}, {"id": "south", "capacity": 100, "fixed_cost": 80}],
            "store": [{"id": "s1", "demand": 30}, {"id": "s2", "demand": 40}],
            "truck_type": [{"id": "small", "load": 20, "price": 5}, {"id": "big", "load": 50, "price": 9}],
        },
        "parameters": {"unit_cost": [{"depot": "north", "store": "s1", "value": 1}, {"depot": "north", "store": "s2", "value": 2},
                                     {"depot": "south", "store": "s1", "value": 1}, {"depot": "south", "store": "s2", "value": 1}]},
        "parameter_defaults": {"unit_cost": 0},
    }
    # North alone: 50 open + 30*1 + 40*2 = 160, plus trucks for 70 (big + small = 14) = 174; south alone 80 + 70 + 14 = 164.
    assert round(float(_solve("recipe_network", data).objective)) == 164


def test_phasing_keeps_each_year_within_its_budget_and_starts_the_best_first():
    data = {"sets": {
        "project": [{"id": "a", "benefit": 10, "capex": 100}, {"id": "b", "benefit": 8, "capex": 100}, {"id": "c", "benefit": 1, "capex": 100}],
        "year": [{"id": "y1", "budget": 100, "weight": 2}, {"id": "y2", "budget": 100, "weight": 1}],
    }}
    # One project a year: a in year 1 (20), b in year 2 (8).
    assert round(float(_solve("recipe_phasing", data).objective)) == 28


def test_allocation_puts_the_land_where_it_is_worth_most_within_water_suitability_and_shares():
    """Benchmark re-test, October 2026: crop planning matched no recipe."""
    data = {
        "sets": {
            "parcel": [{"id": "p1", "area": 10}, {"id": "p2", "area": 10}],
            "crop": [{"id": "rice", "profit": 5, "water": 8, "max_share": 0.5}, {"id": "wheat", "profit": 3, "water": 2, "max_share": 1}],
        },
        "parameters": {"suitable": [{"0": "p1", "1": "rice", "value": 1}, {"0": "p1", "1": "wheat", "value": 1},
                                    {"0": "p2", "1": "wheat", "value": 1}]},
        "parameter_defaults": {"suitable": 0},
    }
    # Rice is suitable on p1 only and worth more: all 10 of p1 (its share cap is 10 of 20), using 80 water.
    # The other 20 water grows 10 wheat on p2. Profit 10*5 + 10*3 = 80.
    assert round(float(_solve("recipe_allocation", data).objective), 6) == 80


def test_flow_routes_trips_over_the_quickest_roads_within_capacity_and_widens_within_budget():
    """Benchmark re-test, October 2026: traffic over a road network with a table of trips had no recipe."""
    roads = {"ab": ("a", "b", 1, 10, 5), "bc": ("b", "c", 1, 10, 5), "ac": ("a", "c", 5, 100, 99)}
    data = {
        "sets": {
            "junction": [{"id": j} for j in "abc"],
            "road": [{"id": r, "minutes": t, "capacity": cap, "extra": 10, "widen_cost": cost} for r, (_, _, t, cap, cost) in roads.items()],
        },
        "relationships": {"road_from": [{"from": r, "to": s} for r, (s, _, _, _, _) in roads.items()],
                          "road_to": [{"from": r, "to": e} for r, (_, e, _, _, _) in roads.items()]},
        "parameters": {"trips": [{"0": "a", "1": "c", "value": 15}, {"0": "a", "1": "b", "value": 2}]},
        "parameter_defaults": {"trips": 0},
    }
    # 2 trips a->b (2 minutes) and 15 a->c. Unwidened, a-b carries 10 in all, so 8 go a-b-c (16) and 7 the slow road (35): 53.
    # Widening a-b and b-c (5 + 5 within 10) lets all 15 go a-b-c: 2 + 30 = 32.
    assert round(float(_solve("recipe_flow", data).objective), 6) == 32
    data["sets"]["road"] = [{**r, "widen_cost": 6} if r["id"] == "bc" else r for r in data["sets"]["road"]]
    # Widening b-c too is now beyond the budget. a-b alone carries the 2 to b and 10 on over b-c (its limit); 5 take
    # the slow road: 2 + 20 + 25 = 47.
    assert round(float(_solve("recipe_flow", data).objective), 6) == 47


def test_inventory_orders_ahead_within_the_order_limit_and_storage_and_counts_lost_sales():
    """Benchmark re-test, October 2026: stock per product over periods had no recipe."""
    data = {
        "sets": {
            "product": [{"id": "a", "on_hand": 5, "unit_cost": 1, "hold_cost": 1, "max_order": 6, "size": 1},
                        {"id": "b", "on_hand": 0, "unit_cost": 1, "hold_cost": 1, "max_order": 15, "size": 2}],
            "depot": [{"id": "d", "capacity": 100}],
            "week": [{"id": "w1"}, {"id": "w2"}, {"id": "w3"}],
        },
        "parameters": {"forecast": [{"week": "w1", "product": "a", "depot": "d", "value": 10},
                                    {"week": "w2", "product": "a", "depot": "d", "value": 10},
                                    {"week": "w2", "product": "b", "depot": "d", "value": 20}]},
        "parameter_defaults": {"forecast": 0},
    }
    # a: 5 on hand, 6 a week at most. Week 1 orders 6 (1 left, held a week), week 2 orders 6 and is 3 short:
    # 12 + 1 + 3*50 = 163. b: 20 in week 2, 15 at most, so 5 are ordered in week 1 and held: 20 + 5 = 25.
    assert round(float(_solve("recipe_inventory", data).objective), 6) == 188
    # Room for 9: a's 1 and 4 of b (size 2) are held over; b is 1 short: 163 + (19 + 4 + 50) = 236.
    data["sets"]["depot"] = [{"id": "d", "capacity": 9}]
    assert round(float(_solve("recipe_inventory", data).objective), 6) == 236
