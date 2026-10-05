"""`connected`, exact: checked against every partition of small grids on every backend (GIS 5)."""

from __future__ import annotations

import functools
import itertools
import random

import pytest

from app.ir.validate import check_shape
from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.service import solve_compiled


def _grid(rows: int, cols: int, cut=frozenset()):
    keys = [f"c{r}{c}" for r in range(rows) for c in range(cols)]
    edges = []
    for r in range(rows):
        for c in range(cols):
            for dr, dc in ((0, 1), (1, 0)):
                if r + dr < rows and c + dc < cols:
                    pair = (f"c{r}{c}", f"c{r + dr}{c + dc}")
                    if pair not in cut:
                        edges.append({"from": pair[0], "to": pair[1]})
    return keys, edges


def _model(keys, edges, groups: int, weights: dict[tuple[str, int], int], empty="forbidden"):
    ir = {
        "version": 2, "sets": ["cell", "zone"], "relationships": ["adjacent"],
        "parameters": {"w": {"index": ["cell", "zone"]}},
        "variables": {"assign": {"index": ["cell", "zone"], "domain": "binary"}},
        "constraints": [
            {"id": "c_one_each", "forall": [{"index": "u", "set": "cell"}],
             "left": {"sum": {"var": "assign", "index": ["u", "z"]}, "over": [{"index": "z", "set": "zone"}]},
             "relation": "=", "right": {"const": 1}, "severity": "hard"},
            {"id": "c_connected", "severity": "hard",
             "connected": {"assign": {"var": "assign", "index": ["u", "z"]}, "units": {"index": "u", "set": "cell"},
                           "groups": {"index": "z", "set": "zone"}, "via": "adjacent", "empty": empty}},
        ],
        "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
            "sum": {"mul": [{"par": "w", "index": ["u", "z"]}, {"var": "assign", "index": ["u", "z"]}]},
            "over": [{"index": "u", "set": "cell"}, {"index": "z", "set": "zone"}]}}]},
    }
    data = {
        "sets": {"cell": [{"id": k} for k in keys], "zone": [{"id": f"z{g}"} for g in range(groups)]},
        "parameters": {"w": [{"cell": k, "zone": f"z{g}", "value": weights[(k, g)]} for k in keys for g in range(groups)]},
        "parameter_defaults": {}, "relationships": {"adjacent": edges},
    }
    return ir, data


def _connected(members: list[str], edges) -> bool:
    if not members:
        return True
    adj = {m: set() for m in members}
    for e in edges:
        if e["from"] in adj and e["to"] in adj:
            adj[e["from"]].add(e["to"])
            adj[e["to"]].add(e["from"])
    seen, stack = {members[0]}, [members[0]]
    while stack:
        for n in adj[stack.pop()] - seen:
            seen.add(n)
            stack.append(n)
    return len(seen) == len(members)


def _brute(keys, edges, groups, weights, empty):
    best = None
    for labels in itertools.product(range(groups), repeat=len(keys)):
        parts = [[k for k, l in zip(keys, labels) if l == g] for g in range(groups)]
        if empty == "forbidden" and any(not p for p in parts):
            continue
        if all(_connected(p, edges) for p in parts):
            value = sum(weights[(k, l)] for k, l in zip(keys, labels))
            best = value if best is None else max(best, value)
    return best


@functools.lru_cache(maxsize=None)
def _case(seed: int):
    rnd = random.Random(seed)
    keys, edges = _grid(3, 3)
    groups = rnd.choice([2, 3])
    empty = rnd.choice(["forbidden", "allowed"])
    # Weights that reward scattering, so a model without contiguity would split zones.
    weights = {(k, g): rnd.randint(-5, 9) for k in keys for g in range(groups)}
    ir, data = _model(keys, edges, groups, weights, empty)
    # And without the rule the best answer is disconnected, or the case proves nothing.
    free = max(sum(max(weights[(k, g)] for g in range(groups)) for k in keys), 0)
    return keys, edges, groups, empty, ir, data, _brute(keys, edges, groups, weights, empty), free


def test_the_cases_are_valid_and_the_rule_binds_in_most_of_them():
    binding = 0
    for seed in range(12):
        _, _, _, _, ir, _, expected, free = _case(seed)
        assert check_shape(ir) is None
        binding += expected < free
    assert binding >= 8


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("backend", ["cp-sat", "highs", "milp", "scip"])
def test_the_flow_agrees_with_every_partition(seed, backend):
    keys, edges, groups, empty, ir, data, expected, _ = _case(seed)
    # Keep this exact small-grid cross-check deterministic. CP-SAT's eight-worker
    # portfolio can spend the whole limit proving the same tiny case under load.
    result, _ = solve_compiled(by_name(backend), compile_model(ir, data), time_limit=30, seed=1, workers=1)
    assert result.status == "optimal", (seed, result.status)
    assert round(float(result.objective)) == expected, (seed, result.objective, expected)
    chosen = [tuple(i) for i in result.chosen("assign")]
    assert sorted(u for u, _ in chosen) == sorted(keys)
    for g in range(groups):
        members = [u for u, z in chosen if z == f"z{g}"]
        assert _connected(members, edges), (seed, g, members)
        assert members or empty == "allowed", (seed, g)


def test_two_islands_cannot_be_one_zone():
    """Review Focus 3: a 1x4 strip cut in the middle, one zone."""
    keys, edges = _grid(1, 4, cut={("c01", "c02")})
    ir, data = _model(keys, edges, 1, {(k, 0): 1 for k in keys})
    result, _ = solve_compiled(by_name("cp-sat"), compile_model(ir, data), time_limit=10, seed=1)
    assert result.status == "infeasible"


def test_a_single_unit_zone_and_edges_outside_the_set_are_fine():
    """One cell per zone needs no flow; an edge naming a unit not in the set is ignored."""
    keys, edges = _grid(1, 2)
    edges = [*edges, {"from": "c00", "to": "elsewhere"}, {"from": "c01", "to": "c01"}]
    ir, data = _model(keys, edges, 2, {("c00", 0): 5, ("c00", 1): 0, ("c01", 0): 0, ("c01", 1): 5})
    result, _ = solve_compiled(by_name("highs"), compile_model(ir, data), time_limit=10, seed=1)
    assert result.status == "optimal" and round(float(result.objective)) == 10


def test_the_rows_are_counted_as_connectivity_and_stay_whole():
    from app.solve.classify import classify
    from app.solve.fingerprint import fingerprint

    keys, edges = _grid(2, 2)
    ir, data = _model(keys, edges, 2, {(k, g): 1 for k in keys for g in range(2)})
    compiled = compile_model(ir, data)
    fp = fingerprint(compiled)
    assert fp["version"] == 2 and fp["rows_connectivity"] > 0
    assert compiled.is_integral and compiled.connectivity == ["c_connected"]
    assert "connected" in classify(ir, data).needs
