"""The start for a sourced `connected` rule (app.solve.reach): the model without the reach, repaired.

A general shape, nothing camp-specific: sites to open on a grid, each needing one free access cell beside it
(`site <= access`), a cell either occupied by a site or open as access (`access + sites on it <= 1`), and the
open access cells joined to an entrance (`connected` with `sources`). The start keeps every rule, and the run never
returns less than it.
"""

from __future__ import annotations

import random

from app.solve import compile_model
from app.solve import reach
from app.solve.backends import by_name
from app.solve.service import solve_compiled
from tests.test_connected import _grid


def _model(rows: int, cols: int, entrances: set[str], seed: int = 0):
    keys, edges = _grid(rows, cols)
    rng = random.Random(seed)
    # A site sits on one cell and needs a neighbour as its access.
    sites, on, needs = [], [], []
    for e in edges:
        for a, b in ((e["from"], e["to"]), (e["to"], e["from"])):
            s = f"s_{a}_{b}"
            sites.append({"id": s, "worth": rng.choice((1, 2, 3))})
            on.append({"from": s, "to": a})
            needs.append({"from": s, "to": b})
    ir = {
        "version": 2, "sets": ["cell", "site"], "relationships": ["adjacent", "on", "needs"],
        "parameters": {},
        "variables": {"open": {"index": ["site"], "domain": "binary"}, "access": {"index": ["cell"], "domain": "binary"}},
        "constraints": [
            {"id": "c_cell", "severity": "hard", "forall": [{"index": "c", "set": "cell"}],
             "left": {"add": [{"var": "access", "index": ["c"]}, {"sum": {"var": "open", "index": ["s"]},
                      "over": [{"index": "s", "set": "site", "via": {"rel": "on", "to": "c"}}]}]},
             "relation": "<=", "right": {"const": 1}},
            {"id": "c_needs", "severity": "hard",
             "forall": [{"index": "s", "set": "site"}, {"index": "c", "set": "cell", "via": {"rel": "needs", "from": "s"}}],
             "left": {"var": "open", "index": ["s"]}, "relation": "<=", "right": {"var": "access", "index": ["c"]}},
            {"id": "c_reach", "severity": "hard", "connected": {
                "assign": {"var": "access", "index": ["c"]}, "units": {"index": "c", "set": "cell"},
                "via": "adjacent", "sources": "entrance"}},
        ],
        "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
            "sum": {"mul": [{"attr": {"of": "s", "name": "worth"}}, {"var": "open", "index": ["s"]}]},
            "over": [{"index": "s", "set": "site"}]}}]},
    }
    data = {"sets": {"cell": [{"id": k, "entrance": int(k in entrances)} for k in keys], "site": sites},
            "parameters": {}, "parameter_defaults": {},
            "relationships": {"adjacent": edges, "on": on, "needs": needs}}
    return ir, data, keys, edges


def _holds(compiled, assignment) -> bool:
    for c in compiled.constraints:
        lhs = c.left.evaluated_at(assignment)
        rhs = c.right.evaluated_at(assignment)
        lhs, rhs = float(lhs), float(rhs)
        if (c.relation == "<=" and lhs > rhs + 1e-6) or (c.relation == ">=" and lhs < rhs - 1e-6) or (
                c.relation == "=" and abs(lhs - rhs) > 1e-6):
            return False
    return True


def test_the_start_keeps_every_rule_including_the_reach():
    ir, data, keys, edges = _model(5, 6, {"c00", "c45"}, seed=3)
    compiled = compile_model(ir, data)
    assert reach.applies(ir, compiled) is None
    hint, record = reach.start(ir, data, compiled, seconds=10)
    assert record["feasible"] and hint
    assert _holds(compiled, hint), "the start, flows included, keeps every row of the exact model"
    exact, _ = solve_compiled(by_name("cp-sat"), compiled, time_limit=60, seed=1, workers=8)
    assert exact.status == "optimal"
    assert record["objective"] <= float(exact.objective) + 1e-9
    assert record["objective"] >= 0.6 * float(exact.objective)  # a good start, not just a feasible one


def test_shapes_it_cannot_mend_are_left_to_the_solver():
    ir, data, _, _ = _model(2, 2, {"c00"})
    ir["constraints"][0]["relation"] = "="
    assert "not of the 'at most' kind" in reach.applies(ir, compile_model(ir, data))
    ir, data, _, _ = _model(2, 2, {"c00"})
    del ir["constraints"][2]["connected"]["sources"]
    ir["constraints"][2]["connected"]["groups"] = {"index": "z", "set": "zone"}
    assert reach.rule_of(ir) is None
