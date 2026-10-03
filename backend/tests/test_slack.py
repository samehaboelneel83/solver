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
