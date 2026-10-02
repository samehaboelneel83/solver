"""Two items of one set compared ("a != b", "a < b") in a rule's conditions (benchmark, October
2026): minimum distance between chosen sites needed a workaround, as nothing could say "another"."""

from __future__ import annotations

import json

from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.service import solve_compiled

FIXTURES = json.load(open("tests/ir_fixtures.json"))


def _pairs():
    return next(v["ir"] for v in FIXTURES["valid"] if v["name"] == "pairs_apart")


def test_each_pair_is_one_row_and_no_item_meets_itself():
    data = {"sets": {"employee": [{"id": k} for k in ("ann", "bob", "cy")]}, "parameters": {}, "parameter_defaults": {}}
    compiled = compile_model(_pairs(), data)
    rows = [c for c in compiled.constraints if c.id == "c_apart"]
    assert len(rows) == 3  # (bob, ann), (cy, ann), (cy, bob): each unordered pair once


def test_no_two_together_lets_one_be_chosen():
    ir = _pairs()
    ir["objective"] = {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
        "sum": {"var": "x", "index": ["e"]}, "over": [{"index": "e", "set": "employee"}]}}]}
    data = {"sets": {"employee": [{"id": k} for k in ("ann", "bob", "cy")]}, "parameters": {}, "parameter_defaults": {}}
    result, _ = solve_compiled(by_name("highs"), compile_model(ir, data), time_limit=10, seed=1)
    assert result.status == "optimal" and round(float(result.objective)) == 1
