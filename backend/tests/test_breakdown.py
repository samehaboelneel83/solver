"""What the goal is made of (benchmark, October 2026, G5a): each term's value and share, and the
records each comes from, worked out by hand on the network recipe."""

from __future__ import annotations

import json

from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.breakdown import objective_breakdown
from app.solve.service import solve_compiled

IR = next(v["ir"] for v in json.load(open("tests/ir_fixtures.json"))["valid"] if v["name"] == "recipe_network")
DATA = {
    "sets": {
        "depot": [{"id": "north", "capacity": 100, "fixed_cost": 50}, {"id": "south", "capacity": 100, "fixed_cost": 80}],
        "store": [{"id": "s1", "demand": 30}, {"id": "s2", "demand": 40}],
        "truck_type": [{"id": "small", "load": 20, "price": 5}, {"id": "big", "load": 50, "price": 9}],
    },
    "parameters": {"unit_cost": [{"depot": "north", "store": "s1", "value": 1}, {"depot": "north", "store": "s2", "value": 2},
                                 {"depot": "south", "store": "s1", "value": 1}, {"depot": "south", "store": "s2", "value": 1}]},
    "parameter_defaults": {"unit_cost": 0},
}


def test_each_goal_term_its_share_and_the_records_it_comes_from():
    compiled = compile_model(IR, DATA)
    result, _ = solve_compiled(by_name("highs"), compiled, time_limit=20, seed=1)
    made = objective_breakdown(IR, compiled, result.assignments)
    terms = {t["id"]: t for t in made["terms"]}
    # South alone (164): shipping 70, opening 80, trucks 14, no shortage.
    assert (terms["shipping_cost"]["value"], terms["opening_cost"]["value"], terms["fleet_cost"]["value"]) == (70, 80, 14)
    assert terms["shortage"]["contribution"] == 0
    assert round(sum(t["share"] for t in made["terms"]), 3) == 1 and terms["opening_cost"]["share"] == round(80 / 164, 4)
    assert terms["opening_cost"]["records"] == [{"kind": "depot", "key": "south", "value": 80}]
    assert terms["shipping_cost"]["records"] == [{"kind": "depot", "key": "south", "value": 70}]


def test_a_long_tail_is_summed_as_one_line():
    compiled = compile_model(IR, DATA)
    result, _ = solve_compiled(by_name("highs"), compiled, time_limit=20, seed=1)
    made = objective_breakdown(IR, compiled, result.assignments, top=0)
    shipping = next(t for t in made["terms"] if t["id"] == "shipping_cost")
    assert shipping["records"] == [] and shipping["rest"] == {"records": 1, "value": 70}


def test_the_exports_say_what_the_goal_is_made_of():
    from datetime import datetime
    from io import BytesIO

    from openpyxl import load_workbook

    from app.api.run_export import to_html, to_xlsx

    made = {"sense": "minimize", "mode": "weighted", "terms": [
        {"id": "shipping_cost", "weight": 1, "value": 70, "contribution": 70, "share": 0.4268, "records": [{"kind": "depot", "key": "south", "value": 70}]},
        {"id": "opening_cost", "weight": 1, "value": 80, "contribution": 80, "share": 0.4878, "records": [{"kind": "depot", "key": "south", "value": 80}]},
        {"id": "shortage", "weight": 600, "value": 0.02, "contribution": 12, "share": 0.0732, "records": []}]}
    rec = {"id": 8, "problem": "p", "scenario": "Base", "status": "optimal", "solver": "highs", "finished_at": datetime(2026, 10, 1),
           "params": {"objective_breakdown": made}, "objective": 150, "error": None, "ir": {},
           "data": {"sets": {"depot": [{"id": "south", "label": "South depot"}]}}, "assignments": None, "amounts": None, "results": []}
    html = to_html(rec)
    assert "What the goal is made of" in html and "opening cost" in html and "48.8%" in html and "South depot 80" in html
    sheet = load_workbook(BytesIO(to_xlsx(rec)))["Goal"]
    rows = [list(r) for r in sheet.iter_rows(values_only=True)]
    assert rows[1][:5] == ["shipping_cost", 1, 70, 70, 0.4268] and rows[2][5:] == ["depot", "south", 70]
    # A weighted term says its weight and what it counts in the goal (benchmark round 3).
    assert ["shortage", 600, 0.02, 12, 0.0732] in [r[:5] for r in rows]
    assert "shortage × 600</td><td>0.02</td><td>12</td>" in html


def test_report_numbers_are_written_as_people_read_them():
    """Benchmark re-test, October 2026: the PDF said 6.52646e+07."""
    from app.api.run_export import _num

    assert [_num(65264600.4), _num(1234.5), _num(0.375), _num(3), _num(-247000)] == ["65,264,600", "1,234.50", "0.375", "3", "-247,000"]
