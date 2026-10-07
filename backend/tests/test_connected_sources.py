"""`connected` with `sources`: every chosen unit reached from a chosen source unit (October 2026).

The camp field test: beds must reach a door through free corridor cells, which the language could not say --
`connected` made each group one piece around a root of its own choosing. With `sources` (a 0/1 field of the units)
the network is rooted at those units, and `groups` is optional. Checked exactly against brute force on small grids,
on every exact backend, as the unsourced rule is.
"""

from __future__ import annotations

import itertools
import random

import pytest

from app.ir.validate import check_shape
from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.service import solve_compiled
from tests.test_connected import _grid


def _model(keys, edges, sources, value, banned=frozenset()):
    """Choose cells for the network (worth `value` each), never the banned ones; all must reach a source."""
    ir = {
        "version": 2, "sets": ["cell"], "relationships": ["adjacent"],
        "parameters": {"worth": {"index": ["cell"]}, "banned": {"index": ["cell"]}},
        "variables": {"open": {"index": ["cell"], "domain": "binary"}},
        "constraints": [
            {"id": "c_banned", "forall": [{"index": "u", "set": "cell"}],
             "left": {"mul": [{"par": "banned", "index": ["u"]}, {"var": "open", "index": ["u"]}]},
             "relation": "<=", "right": {"const": 0}, "severity": "hard"},
            {"id": "c_reach", "severity": "hard",
             "connected": {"assign": {"var": "open", "index": ["u"]}, "units": {"index": "u", "set": "cell"},
                           "via": "adjacent", "sources": "door"}},
        ],
        "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
            "sum": {"mul": [{"par": "worth", "index": ["u"]}, {"var": "open", "index": ["u"]}]},
            "over": [{"index": "u", "set": "cell"}]}}]},
    }
    data = {
        "sets": {"cell": [{"id": k, "door": 1 if k in sources else 0} for k in keys]},
        "parameters": {"worth": [{"cell": k, "value": value[k]} for k in keys],
                       "banned": [{"cell": k, "value": 1 if k in banned else 0} for k in keys]},
        "parameter_defaults": {}, "relationships": {"adjacent": edges},
    }
    return ir, data


def _reached(chosen, edges, sources):
    adj = {u: set() for u in chosen}
    for e in edges:
        if e["from"] in adj and e["to"] in adj:
            adj[e["from"]].add(e["to"]); adj[e["to"]].add(e["from"])
    seen = {u for u in chosen if u in sources}
    stack = list(seen)
    while stack:
        for v in adj[stack.pop()]:
            if v not in seen:
                seen.add(v); stack.append(v)
    return seen == set(chosen)


def _brute(keys, edges, sources, value, banned):
    best = 0
    for bits in itertools.product((0, 1), repeat=len(keys)):
        chosen = [k for k, b in zip(keys, bits) if b]
        if any(k in banned for k in chosen) or not _reached(chosen, edges, sources):
            continue
        best = max(best, sum(value[k] for k in chosen))
    return best


def _case(seed):
    rng = random.Random(seed)
    keys, edges = _grid(3, 3)
    sources = set(rng.sample(keys, rng.choice((1, 2))))
    banned = set(rng.sample([k for k in keys if k not in sources], rng.choice((2, 3))))
    value = {k: rng.choice((-2, 1, 3)) for k in keys}
    return keys, edges, sources, value, banned


def test_the_rule_is_valid_and_the_old_shapes_still_are():
    keys, edges, sources, value, banned = _case(0)
    ir, _ = _model(keys, edges, sources, value, banned)
    assert check_shape(ir) is None
    bad = dict(ir["constraints"][1]["connected"], assign={"var": "open", "index": ["u", "z"]})
    ir["constraints"][1]["connected"] = bad
    refused = check_shape(ir)
    assert refused.code == "connected_index_mismatch" and "units alone" in refused.message
    no_groups_no_sources = {k: v for k, v in bad.items() if k != "sources"}
    no_groups_no_sources["assign"] = {"var": "open", "index": ["u"]}
    ir["constraints"][1]["connected"] = no_groups_no_sources
    refused = check_shape(ir)
    assert refused.code == "connected_malformed" and refused.loc[-1] == "groups"


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("backend", ["cp-sat", "highs", "milp"])
def test_the_flow_agrees_with_every_choice(seed, backend):
    keys, edges, sources, value, banned = _case(seed)
    ir, data = _model(keys, edges, sources, value, banned)
    result, _ = solve_compiled(by_name(backend), compile_model(ir, data), time_limit=30, seed=1, workers=1)
    assert result.status == "optimal", (seed, result.status)
    expected = _brute(keys, edges, sources, value, banned)
    assert round(float(result.objective)) == expected, (seed, result.objective, expected)
    chosen = [i[0] for i in result.chosen("open")]
    assert _reached(chosen, edges, sources), (seed, chosen)


def test_cells_behind_a_wall_of_banned_cells_are_not_opened():
    keys, edges = _grid(1, 4)
    ir, data = _model(keys, edges, {"c00"}, {k: 1 for k in keys}, banned={"c01"})
    result, _ = solve_compiled(by_name("cp-sat"), compile_model(ir, data), time_limit=10, seed=1)
    assert result.status == "optimal" and round(float(result.objective)) == 1


@pytest.mark.parametrize("seed", range(4))
def test_sources_picked_by_a_where_list_agree_with_the_field(seed):
    """The fibre test: the exchange was marked kind = "exchange", not by a 0/1 field."""
    keys, edges, sources, value, banned = _case(seed)
    ir, data = _model(keys, edges, sources, value, banned)
    by_field, _ = solve_compiled(by_name("cp-sat"), compile_model(ir, data), time_limit=30, seed=1, workers=1)
    for row in data["sets"]["cell"]:
        row["kind"] = "exchange" if row["door"] else "village"
    rule = next(c for c in ir["constraints"] if "connected" in c)
    rule["connected"]["sources"] = [{"attr": "kind", "op": "=", "value": "exchange"}]
    assert check_shape(ir) is None
    by_where, _ = solve_compiled(by_name("cp-sat"), compile_model(ir, data), time_limit=30, seed=1, workers=1)
    assert by_where.status == by_field.status == "optimal"
    assert by_where.objective == by_field.objective
    rule["connected"]["sources"] = []
    assert check_shape(ir).code == "connected_malformed"
