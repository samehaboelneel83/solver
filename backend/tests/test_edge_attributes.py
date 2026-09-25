"""Rules reading relationship (edge) attributes (queue R19): a `via` names the edge it
walks (`as`), `attr of` that edge reads its own attributes, and on a repeated walk the
path's edges combine as `along` says -- exact on a hierarchy, refused where a cycle or a
second route makes "the path" more than one."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ir.validate import check_shape
from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.compile import Unsupported


def _arcs_ir():
    """Ship from plants to markets over `lane` arcs; each arc carries its own cost per unit."""
    ship = {"var": "ship", "index": ["p", "m"]}
    lanes = [{"index": "m", "set": "market", "via": {"rel": "lane", "from": "p", "as": "e"}}]
    return {
        "version": 2, "sets": ["plant", "market"], "parameters": {}, "relationships": ["lane"],
        "variables": {"ship": {"index": ["plant", "market"], "domain": "continuous", "upper": 100}},
        "constraints": [
            {"id": "c_supply", "forall": [{"index": "p", "set": "plant"}],
             "left": {"sum": ship, "over": [{"index": "m", "set": "market"}]}, "relation": "<=",
             "right": {"attr": {"of": "p", "name": "supply"}}, "severity": "hard"},
            {"id": "c_demand", "forall": [{"index": "m", "set": "market"}],
             "left": {"sum": ship, "over": [{"index": "p", "set": "plant"}]}, "relation": ">=",
             "right": {"attr": {"of": "m", "name": "demand"}}, "severity": "hard"},
            # Only a lane carries goods, and no more than its own capacity.
            {"id": "c_lane", "forall": [{"index": "p", "set": "plant"}, *lanes],
             "left": ship, "relation": "<=", "right": {"attr": {"of": "e", "name": "capacity"}}, "severity": "hard"},
        ],
        "objective": {"sense": "minimize", "terms": [{"id": "o_cost", "weight": 1, "expression": {
            "sum": {"mul": [{"attr": {"of": "e", "name": "cost"}}, ship]},
            "over": [{"index": "p", "set": "plant"}, *lanes]}}]},
    }


def _arcs_data():
    return {
        "sets": {"plant": [{"id": "a", "supply": 50}, {"id": "b", "supply": 50}],
                 "market": [{"id": "x", "demand": 30}, {"id": "y", "demand": 40}]},
        "parameters": {}, "parameter_defaults": {},
        "relationships": {"lane": [
            {"from": "a", "to": "x", "attrs": {"cost": 1, "capacity": 20}},
            {"from": "a", "to": "y", "attrs": {"cost": 4, "capacity": 50}},
            {"from": "b", "to": "x", "attrs": {"cost": 3, "capacity": 50}},
            {"from": "b", "to": "y", "attrs": {"cost": 2, "capacity": 50}},
        ]},
    }


def test_the_document_names_its_edge_and_reads_it():
    assert check_shape(_arcs_ir()) is None


def test_an_edge_attribute_is_a_coefficient_per_arc():
    compiled = compile_model(_arcs_ir(), _arcs_data())
    lanes = [c for c in compiled.constraints if c.id == "c_lane"]
    # One row per arc, its right side the arc's own capacity; the edge is not an index of the row.
    assert sorted((c.index["p"], c.index["m"], c.right.const) for c in lanes) == [
        ("a", "x", 20), ("a", "y", 50), ("b", "x", 50), ("b", "y", 50)]
    assert all(set(c.index) == {"p", "m"} for c in lanes)
    result = by_name("highs").solve(compiled, time_limit=10, workers=1, seed=1)
    # a->x is cheapest but holds 20; b->x covers the other 10; b->y (2) beats a->y (4).
    assert result.status == "optimal" and float(result.objective) == pytest.approx(20 * 1 + 10 * 3 + 40 * 2)


def _chain_ir(along: str, depth: str = "any"):
    """A unit's reach up its `reports_to` hierarchy, the path's `weight` combined `along`."""
    return {
        "version": 2, "sets": ["unit"], "parameters": {}, "relationships": ["reports_to"],
        "variables": {"pick": {"index": ["unit"], "domain": "binary"}},
        "constraints": [],
        "objective": {"sense": "maximize", "terms": [{"id": "o_up", "weight": 1, "expression": {
            "sum": {"mul": [{"attr": {"of": "e", "name": "weight", "along": along}}, {"var": "pick", "index": ["u"]}]},
            "over": [{"index": "top", "set": "unit", "where": [{"attr": "top", "op": "=", "value": True}]},
                     {"index": "u", "set": "unit", "via": {"rel": "reports_to", "from": "top", "depth": depth, "as": "e"}}]}}]},
    }


def _chain_data(extra=()):
    # root -> mid (2) -> leaf (3); root -> side (5)
    edges = [{"from": "root", "to": "mid", "attrs": {"weight": 2}},
             {"from": "mid", "to": "leaf", "attrs": {"weight": 3}},
             {"from": "root", "to": "side", "attrs": {"weight": 5}}, *extra]
    units = [{"id": "root", "top": True}, {"id": "mid", "top": False}, {"id": "leaf", "top": False},
             {"id": "side", "top": False}]
    return {"sets": {"unit": units}, "parameters": {}, "parameter_defaults": {}, "relationships": {"reports_to": edges}}


def _coefficients(ir, data):
    objective = compile_model(ir, data).objective
    return {key[1][0]: value for key, value in objective.coeffs.items()}


@pytest.mark.parametrize("along, expected", [
    ("sum", {"mid": 2, "leaf": 5, "side": 5}),
    ("product", {"mid": 2, "leaf": 6, "side": 5}),
    ("min", {"mid": 2, "leaf": 2, "side": 5}),
    ("max", {"mid": 2, "leaf": 3, "side": 5}),
    ("count", {"mid": 1, "leaf": 2, "side": 1}),
])
def test_along_a_hierarchy_the_path_combines_exactly(along, expected):
    assert check_shape(_chain_ir(along)) is None
    assert _coefficients(_chain_ir(along), _chain_data()) == {k: Decimal(v) for k, v in expected.items()}


def test_the_self_path_has_no_edges():
    ir = _chain_ir("sum", depth="any_or_self")
    coefficients = _coefficients(ir, _chain_data())
    assert "root" not in coefficients  # its path is empty: a sum of nothing is zero
    with pytest.raises(Unsupported, match="to itself has no edges"):
        compile_model(_chain_ir("min", depth="any_or_self"), _chain_data())


def test_two_routes_to_one_unit_are_refused_with_the_reason():
    diamond = [{"from": "side", "to": "leaf", "attrs": {"weight": 1}}]
    with pytest.raises(Unsupported, match="more than one way"):
        compile_model(_chain_ir("sum"), _chain_data(diamond))
    cycle = [{"from": "leaf", "to": "root", "attrs": {"weight": 1}}]
    with pytest.raises(Unsupported, match="more than one way"):
        compile_model(_chain_ir("sum"), _chain_data(cycle))


def test_an_edge_without_the_attribute_is_named():
    data = _arcs_data()
    del data["relationships"]["lane"][2]["attrs"]["cost"]
    with pytest.raises(Unsupported, match="'b' -> 'x' carries no number 'cost'"):
        compile_model(_arcs_ir(), data)


def test_fractional_edge_attributes_make_the_data_fractional():
    from app.solve.classify import _fractional

    data = _arcs_data()
    data["relationships"]["lane"][0]["attrs"]["cost"] = 1.5
    assert "lane.cost" in (_fractional(_arcs_ir(), data) or "")
