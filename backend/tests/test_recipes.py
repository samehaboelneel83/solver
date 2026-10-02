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
