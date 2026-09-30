"""Walks narrowed four ways, and filters that say "this or that".

A `via` says how far (`steps`: from `min` to `max`), which way (`from`, `to`,
or `both`), over which links (`where` on the links' own attributes), and on
which day (`on`, against each link's `valid_from` / `valid_to`). A binding's
`where` may hold a group, `{"any": [...]}`, that holds when any of its
filters does.

The hierarchy is small enough to check by eye:

    root -> a -> a1 -> a11
         -> b           (the root -> b link is valid only until 2026-06-30)

Each test reads which units a walk from `root` lands on, as the objective's
coefficients: one per unit reached.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ir.validate import check_shape
from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.compile import Unsupported

EDGES = [
    {"from": "root", "to": "a", "attrs": {"share": 1}},
    {"from": "a", "to": "a1", "attrs": {"share": 0}},
    {"from": "a1", "to": "a11", "attrs": {"share": 2}},
    {"from": "root", "to": "b", "valid_to": "2026-06-30", "attrs": {"share": 3}},
]
UNITS = [
    {"id": "root", "top": True, "kind": "hq"},
    {"id": "a", "top": False, "kind": "region"},
    {"id": "a1", "top": False, "kind": "depot"},
    {"id": "a11", "top": False, "kind": "shop"},
    {"id": "b", "top": False, "kind": "region"},
]


def _data(edges=EDGES):
    return {"sets": {"unit": UNITS}, "parameters": {}, "parameter_defaults": {}, "relationships": {"reports_to": edges}}


def _ir(via, where=None, read=None):
    """Maximise the units a walk from the top unit reaches (each counted once)."""
    reached = {"index": "u", "set": "unit", "via": {"rel": "reports_to", **via}}
    if where:
        reached["where"] = where
    body = {"var": "pick", "index": ["u"]}
    if read:
        body = {"mul": [read, body]}
    return {
        "version": 2, "sets": ["unit"], "parameters": {}, "relationships": ["reports_to"],
        "variables": {"pick": {"index": ["unit"], "domain": "binary"}},
        "constraints": [],
        "objective": {"sense": "maximize", "terms": [{"id": "o_reach", "weight": 1, "expression": {
            "sum": body,
            "over": [{"index": "top", "set": "unit", "where": [{"attr": "top", "op": "=", "value": True}]}, reached]}}]},
    }


def _reached(ir, data=None):
    assert check_shape(ir) is None, check_shape(ir)
    objective = compile_model(ir, data or _data()).objective
    return {key[1][0]: value for key, value in objective.coeffs.items()}


@pytest.mark.parametrize("steps, expected", [
    ({"min": 1, "max": 1}, {"a", "b"}),
    ({"min": 2, "max": 2}, {"a1"}),
    ({"min": 2, "max": 3}, {"a1", "a11"}),
    ({"min": 2}, {"a1", "a11"}),
    ({"min": 0, "max": 1}, {"root", "a", "b"}),
    ({"min": 3, "max": 9}, {"a11"}),
    ({"min": 4}, set()),
])
def test_steps_land_between_min_and_max_steps_away(steps, expected):
    assert set(_reached(_ir({"from": "top", "steps": steps}))) == expected


@pytest.mark.parametrize("depth, steps", [
    ("one", {"min": 1, "max": 1}),
    ("any", {"min": 1}),
    ("any_or_self", {"min": 0}),
])
def test_each_depth_is_a_range_of_steps(depth, steps):
    assert _reached(_ir({"from": "top", "depth": depth})) == _reached(_ir({"from": "top", "steps": steps}))


def test_the_links_conditions_prune_the_walk_below_a_failing_link():
    # a -> a1 has share 0: neither a1 nor what lies beyond it is reached.
    ir = _ir({"from": "top", "depth": "any", "where": [{"attr": "share", "op": ">", "value": 0}]})
    assert set(_reached(ir)) == {"a", "b"}


def test_on_a_day_only_the_links_valid_that_day_are_walked():
    assert "b" in _reached(_ir({"from": "top", "depth": "any", "on": "2026-06-30"}))
    assert "b" not in _reached(_ir({"from": "top", "depth": "any", "on": "2026-07-01"}))
    # A link valid from a later day is not there yet.
    later = [*EDGES, {"from": "b", "to": "a11", "valid_from": "2027-01-01"}]
    assert _reached(_ir({"from": "top", "depth": "any", "on": "2026-01-01"}), _data(later)) == _reached(
        _ir({"from": "top", "depth": "any", "on": "2026-01-01"}))


def test_both_ways_reaches_siblings_through_the_parent():
    # From a, both ways: one step is root and a1; two steps adds b and a11.
    ir = _ir({"both": "top", "steps": {"min": 2, "max": 2}})
    ir["objective"]["terms"][0]["expression"]["over"][0]["where"] = [{"attr": "id", "op": "=", "value": "a"}]
    assert set(_reached(ir)) == {"b", "a11"}


def test_both_ways_the_path_never_steps_straight_back():
    # With the links named, a walk both ways from a still has one path to each unit.
    read = {"attr": {"of": "l", "name": "share", "along": "sum"}}
    ir = _ir({"both": "top", "depth": "any", "as": "l"}, read=read)
    ir["objective"]["terms"][0]["expression"]["over"][0]["where"] = [{"attr": "id", "op": "=", "value": "a"}]
    # a1's path is the one link a -> a1 (share 0): a zero coefficient, so it drops out.
    assert _reached(ir) == {"root": Decimal(1), "b": Decimal(4), "a11": Decimal(2)}


def test_a_path_read_along_steps_combines_its_links():
    read = {"attr": {"of": "l", "name": "share", "along": "sum"}}
    assert _reached(_ir({"from": "top", "steps": {"min": 2}, "as": "l"}, read=read)) == {"a1": Decimal(1), "a11": Decimal(3)}


def test_a_group_holds_when_any_of_its_filters_does():
    where = [{"any": [{"attr": "kind", "op": "=", "value": "depot"}, {"attr": "kind", "op": "=", "value": "shop"}]}]
    assert set(_reached(_ir({"from": "top", "depth": "any"}, where=where))) == {"a1", "a11"}
    # A group beside a filter: both must hold.
    where = [*where, {"attr": "id", "op": "!=", "value": "a11"}]
    assert set(_reached(_ir({"from": "top", "depth": "any"}, where=where))) == {"a1"}


def test_a_cycle_both_ways_terminates():
    cycle = [*EDGES, {"from": "a11", "to": "root", "attrs": {"share": 1}}]
    assert set(_reached(_ir({"both": "top", "steps": {"min": 1}}), _data(cycle))) == {"root", "a", "a1", "a11", "b"}


def test_a_path_reached_two_ways_is_refused_for_numbers_along_it():
    diamond = [*EDGES, {"from": "b", "to": "a1", "attrs": {"share": 1}}]
    read = {"attr": {"of": "l", "name": "share", "along": "sum"}}
    with pytest.raises(Unsupported, match="more than one way"):
        _reached(_ir({"from": "top", "steps": {"min": 1}, "as": "l"}, read=read), _data(diamond))


def test_it_solves():
    ir = _ir({"from": "top", "steps": {"min": 2}, "where": [{"attr": "share", "op": ">=", "value": 0}]})
    result = by_name("highs").solve(compile_model(ir, _data()), time_limit=10, workers=1, seed=1)
    assert result.status == "optimal" and float(result.objective) == pytest.approx(2)
