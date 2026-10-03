"""How much room each rule has left (benchmark round 5: a rule idle everywhere read "at its limit")."""

from __future__ import annotations

from decimal import Decimal

from app.solve import compile_model
from app.solve.compile import slack_by_constraint

SHIP = {"var": "ship", "index": ["c"]}
IR = {"version": 2, "sets": ["customer"], "parameters": {},
      "variables": {"ship": {"index": ["customer"], "domain": "continuous", "lower": 0, "upper": 100}},
      "constraints": [
          # hours * ship <= limit * ship: 0 <= 0 wherever nothing ships, whatever the hours.
          {"id": "delivery_time", "forall": [{"index": "c", "set": "customer"}], "severity": "hard",
           "left": {"mul": [{"attr": {"of": "c", "name": "hours"}}, SHIP]}, "relation": "<=",
           "right": {"mul": [{"attr": {"of": "c", "name": "limit"}}, SHIP]}},
          {"id": "most", "forall": [{"index": "c", "set": "customer"}], "severity": "hard",
           "left": SHIP, "relation": "<=", "right": {"const": 50}}]}
DATA = {"sets": {"customer": [{"id": "a", "hours": 3, "limit": 12}, {"id": "b", "hours": 4, "limit": 24}]}}


def test_a_rule_idle_where_nothing_is_used_is_not_at_its_limit():
    compiled = compile_model(IR, DATA)
    nothing = {("ship", ("a",)): Decimal(0), ("ship", ("b",)): Decimal(0)}
    slack = slack_by_constraint(compiled, nothing)
    assert "delivery_time" not in slack  # idle everywhere: no room to report, and not "at its limit"
    assert slack["most"] == 50
    some = {("ship", ("a",)): Decimal(10), ("ship", ("b",)): Decimal(0)}
    assert slack_by_constraint(compiled, some)["delivery_time"] == 12 * 10 - 3 * 10


def test_an_empty_part_of_a_sum_beside_parts_that_count_is_not_counting_nobody():
    """Benchmark round 5: per district, intersections + car parks >= 1; a district with intersections
    but no car park was said to have "counted nobody"."""
    def pick(var, s, rel):
        return {"sum": {"var": var, "index": ["x"]}, "over": [{"index": "x", "set": s, "via": {"rel": rel, "to": "d"}}]}

    ir = {"version": 2, "sets": ["district", "junction", "car_park"], "parameters": {}, "relationships": ["junction_in", "park_in"],
          "variables": {"signal": {"index": ["junction"], "domain": "binary"}, "build": {"index": ["car_park"], "domain": "binary"}},
          "constraints": [{"id": "every_district", "forall": [{"index": "d", "set": "district"}], "severity": "hard",
                           "left": {"add": [pick("signal", "junction", "junction_in"), pick("build", "car_park", "park_in")]},
                           "relation": ">=", "right": {"const": 1}}]}
    data = {"sets": {"district": [{"id": "z1"}, {"id": "z2"}, {"id": "z3"}], "junction": [{"id": "j1"}, {"id": "j2"}],
                     "car_park": [{"id": "p1"}]},
            "relationships": {"junction_in": [{"from": "j1", "to": "z1"}, {"from": "j2", "to": "z2"}], "park_in": [{"from": "p1", "to": "z1"}]}}
    compiled = compile_model(ir, data)
    # z2 has a junction and no car park: it counts someone; z3 has neither: nobody.
    assert {tuple(e["index"].items()) for e in compiled.empty_ranges} == {(("d", "z3"),)}
