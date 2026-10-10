"""What a model's shape gives away even when it solves (app.solve.lint): the same two checks for every model."""

from __future__ import annotations

from app.agent import core
from app.solve import compile_model, lint

DATA = {"sets": {}, "parameters": {}, "parameter_defaults": {}, "relationships": {}}
MAKE = {"var": "make", "index": []}
OVER = {"var": "overtime", "index": []}


def _plan(capacity_rule: dict) -> dict:
    """Make at least 9 with 8 hours and overtime that costs 5 an hour: the least cost."""
    return {"version": 2, "sets": [], "parameters": {},
            "variables": {"make": {"index": [], "domain": "continuous", "lower": 0},
                          "overtime": {"index": [], "domain": "continuous", "lower": 0, "upper": 4}},
            "constraints": [{"id": "c_demand", "left": MAKE, "relation": ">=", "right": {"const": 9}, "severity": "hard"},
                            {"id": "c_hours", "severity": "hard", **capacity_rule}],
            "objective": {"sense": "minimize", "terms": [
                {"id": "o_cost", "weight": 1, "expression": {"add": [MAKE, {"mul": [{"const": 5}, OVER]}]}}]}}


def test_a_decision_written_where_it_only_uses_room_up_is_found_and_the_right_way_round_is_not():
    """The evaluation's wrong production plan: hours + overtime <= capacity. Overtime costs and only tightens."""
    wrong = _plan({"left": {"add": [MAKE, OVER]}, "relation": "<=", "right": {"const": 8}})
    found = lint.never_helps(compile_model(wrong, DATA))
    assert [(f["kind"], f["decision"], f["rules"]) for f in found] == [("never_helps", "overtime", ["c_hours"])]
    assert "overtime can never help" in found[0]["said"] and "c_hours" in found[0]["said"]
    right = _plan({"left": MAKE, "relation": "<=", "right": {"add": [{"const": 8}, OVER]}})
    assert lint.never_helps(compile_model(right, DATA)) == []
    # The same rule with the sides and the relation turned round says the same thing.
    turned = _plan({"left": {"add": [{"const": 8}, OVER]}, "relation": ">=", "right": MAKE})
    assert lint.never_helps(compile_model(turned, DATA)) == []


def test_a_decision_in_an_equation_or_one_the_goal_wants_more_of_is_left_alone():
    balance = _plan({"left": {"add": [MAKE, OVER]}, "relation": "=", "right": {"const": 9}})
    assert lint.never_helps(compile_model(balance, DATA)) == []
    wanted = _plan({"left": {"add": [MAKE, OVER]}, "relation": "<=", "right": {"const": 12}})
    wanted["objective"] = {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": OVER}]}
    assert lint.never_helps(compile_model(wanted, DATA)) == []


def test_a_decision_in_no_rule_and_no_goal_is_named():
    idle = _plan({"left": MAKE, "relation": "<=", "right": {"const": 12}})
    idle["objective"]["terms"][0]["expression"] = MAKE
    assert [(f["kind"], f["decision"]) for f in lint.never_helps(compile_model(idle, DATA))] == [("idle", "overtime")]


def test_data_given_and_never_read_is_named_but_not_an_order_or_a_text():
    """The same wrong plan never read the opening stock; a position 1, 2, 3 is the weeks' order, not an amount."""
    seed = {"entity_types": [
        {"name": "product", "attributes": [{"name": "name", "data_type": "text"},
                                           {"name": "opening_stock", "data_type": "number"},
                                           {"name": "holding_cost", "data_type": "number"}]},
        {"name": "week", "attributes": [{"name": "position", "data_type": "number"}]}],
        "entities": [{"type": "product", "key": "A", "attrs": {"name": "A", "opening_stock": 12, "holding_cost": 55}},
                     {"type": "product", "key": "B", "attrs": {"name": "B", "opening_stock": 6, "holding_cost": 60}},
                     {"type": "week", "key": "W1", "attrs": {"position": 1}},
                     {"type": "week", "key": "W2", "attrs": {"position": 2}}],
        "parameters": [{"name": "demand", "index": ["product", "week"]}, {"name": "price", "index": ["product"]}],
        "parameter_values": [{"parameter": "demand", "entities": [["product", "A"], ["week", "W1"]], "value": 3},
                             {"parameter": "price", "entities": [["product", "A"]], "value": 9}]}
    ir = {"version": 2, "sets": ["product", "week"], "parameters": {"demand": {"index": ["product", "week"]}},
          "variables": {"stock": {"index": ["product", "week"], "domain": "continuous", "lower": 0}},
          "constraints": [{"id": "c", "forall": [{"index": "p", "set": "product"}, {"index": "w", "set": "week"}],
                           "left": {"var": "stock", "index": ["p", "w"]}, "relation": ">=",
                           "right": {"par": "demand", "index": ["p", "w"]}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {
              "sum": {"mul": [{"attr": {"of": "p", "name": "holding_cost"}}, {"var": "stock", "index": ["p", "w"]}]},
              "over": [{"index": "p", "set": "product"}, {"index": "w", "set": "week"}]}}]}}
    assert [f["what"] for f in lint.unread(ir, seed)] == ["product.opening_stock", "price"]
    ir["constraints"][0]["right"] = {"add": [{"par": "demand", "index": ["p", "w"]},
                                             {"attr": {"of": "p", "name": "opening_stock"}},
                                             {"par": "price", "index": ["p"]}]}
    assert lint.unread(ir, seed) == []
    # The same numbers given as a field and as a parameter the model reads: read. A placement rule reads fields
    # by what it is: nothing is said.
    ir["constraints"][0]["right"] = {"add": [{"par": "demand", "index": ["p", "w"]}, {"par": "opening", "index": ["p"]}]}
    seed["parameter_values"] = [{"parameter": "opening", "entities": [["product", "A"]], "value": 12},
                                {"parameter": "opening", "entities": [["product", "B"]], "value": 6}]
    assert lint.unread(ir, seed) == []
    seed["parameter_values"][1]["value"] = 7
    assert [f["what"] for f in lint.unread(ir, seed)] == ["product.opening_stock"]
    seed["parameter_values"] = []
    # Each record's number written into the model as a constant is in the model too.
    ir["constraints"][0]["right"] = {"add": [{"par": "demand", "index": ["p", "w"]}, {"const": 12}, {"const": 6}]}
    assert lint.unread(ir, seed) == []
    ir["constraints"][0]["right"] = {"par": "demand", "index": ["p", "w"]}
    ir["constraints"].append({"id": "c_place", "place": {"items": "product"}})
    assert lint.unread(ir, seed) == []


def test_the_findings_go_back_to_the_assistant_and_onto_the_plan_card():
    wrong = _plan({"left": {"add": [MAKE, OVER]}, "relation": "<=", "right": {"const": 8}})
    shape = lint.findings(wrong, {}, compile_model(wrong, DATA))
    back = core.shape_sent_back(shape)
    assert back.startswith("The plan was NOT shown") and "overtime can never help" in back
    assert core.shape_for_person(shape).startswith("\n- CHECK THIS: overtime can never help")
    assert core.shape_sent_back([]) == "" and core.shape_for_person(None) == ""
