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


def test_room_given_only_to_a_decision_that_never_helps_does_not_count():
    """Phase 1, security S (10 October 2026): protection written as *at least* what the chosen controls give,
    `prot >= 68 pick`, so picking never helps; the dependency `pick_a <= pick_b` gave pick_b room, which used to be
    enough to call it helpful."""
    pick_a, pick_b, prot = ({"var": n, "index": []} for n in ("pick_a", "pick_b", "prot"))

    def model(protection_rule):
        return {"version": 2, "sets": [], "parameters": {},
                "variables": {"pick_a": {"index": [], "domain": "binary"}, "pick_b": {"index": [], "domain": "binary"},
                              "prot": {"index": [], "domain": "continuous", "lower": 0, "upper": 100}},
                "constraints": [{"id": "c_budget", "left": {"add": [{"mul": [{"const": 50}, pick_a]}, {"mul": [{"const": 40}, pick_b]}]},
                                 "relation": "<=", "right": {"const": 60}, "severity": "hard"},
                                {"id": "c_needs", "left": pick_a, "relation": "<=", "right": pick_b, "severity": "hard"},
                                {"id": "c_prot", "severity": "hard", **protection_rule}],
                "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": prot}]}}

    wrong = model({"left": prot, "relation": ">=", "right": {"mul": [{"const": 68}, pick_a]}})
    found = {f["decision"] for f in lint.never_helps(compile_model(wrong, DATA))}
    assert found == {"pick_a", "pick_b"}, found
    right = model({"left": prot, "relation": "<=", "right": {"mul": [{"const": 68}, pick_a]}})
    assert lint.never_helps(compile_model(right, DATA)) == []  # pick_a gives prot room; pick_b gives pick_a room


def test_a_rule_no_plan_keeps_at_its_least_makes_what_gives_it_room_helpful():
    """Demand to be met: shipping costs and is held back by nothing, yet the plan needs it."""
    ship = {"var": "ship", "index": []}
    ir = {"version": 2, "sets": [], "parameters": {}, "variables": {"ship": {"index": [], "domain": "continuous", "lower": 0}},
          "constraints": [{"id": "c_demand", "left": ship, "relation": ">=", "right": {"const": 9}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 3, "expression": ship}]}}
    assert lint.never_helps(compile_model(ir, DATA)) == []


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


def test_a_parameter_given_only_its_default_is_named():
    """The evaluation, 11 October 2026: allowed[c, w] = 1 for the one pair listed, default 1 -- nothing restricted."""
    seed = {"parameters": [{"name": "allowed", "index": ["c", "w"], "default_value": 1},
                           {"name": "cost", "index": ["c", "w"], "default_value": 999999},
                           {"name": "budget", "index": [], "default_value": 5}],
            "parameter_values": [{"parameter": "allowed", "entities": [["c", "C4"], ["w", "W3"]], "value": 1},
                                 {"parameter": "cost", "entities": [["c", "C4"], ["w", "W3"]], "value": 32}]}
    found = lint.as_default(seed)
    assert [f["what"] for f in found] == ["allowed"]
    assert "every value given for allowed is 1, its default" in found[0]["said"]
    seed["parameters"][0]["default_value"] = 0
    assert lint.as_default(seed) == []


def test_a_pair_parameter_given_one_way_round_only_is_named():
    """The evaluation, 11 October 2026: shared[e1, e2] for e1 < e2 only, read in one order by the rule."""
    seed = {"parameters": [{"name": "shared", "index": ["exam", "exam"], "default_value": 0},
                           {"name": "dist", "index": ["site", "site"], "default_value": 0}],
            "parameter_values": [{"parameter": "shared", "entities": [["exam", a], ["exam", b]], "value": 3}
                                 for a, b in (("E1", "E2"), ("E1", "E3"), ("E2", "E3"))]
            + [{"parameter": "dist", "entities": [["site", a], ["site", b]], "value": 5}
               for a, b in (("S1", "S2"), ("S2", "S1"))]}
    found = lint.one_way(seed)
    assert [f["what"] for f in found] == ["shared"]
    assert "given one way round only (3 pairs" in found[0]["said"]


def test_one_number_given_only_as_a_default_and_never_read_is_named():
    """16 Oct mission, Phase D (p07, R3 run 1): battery_initial = 600 was declared as ONE number for the whole
    problem -- a default, no cell -- and no rule read it; the first hour's stock started at 0 and the answer broke
    the battery's limit with no warning. The cells-only check never saw it."""
    seed = {"parameters": [{"name": "battery_initial", "index": [], "default_value": 600},
                           {"name": "battery_capacity", "index": [], "default_value": 1200},
                           {"name": "spare", "index": [], "default_value": 0}]}
    ir = {"version": 2, "sets": ["hour"], "parameters": {"battery_capacity": {"index": []}},
          "variables": {"level": {"index": ["hour"], "domain": "continuous", "lower": 0}},
          "constraints": [{"id": "c_cap", "forall": [{"index": "h", "set": "hour"}],
                           "left": {"var": "level", "index": ["h"]}, "relation": "<=",
                           "right": {"par": "battery_capacity"}, "severity": "hard"}],
          "objective": {"sense": "minimize", "terms": []}}
    found = lint.unread(ir, seed)
    assert [f["what"] for f in found] == ["battery_initial"]
    assert "battery_initial = 600 is given and no rule or goal reads it" in found[0]["said"]
    ir["constraints"][0]["right"] = {"add": [{"par": "battery_capacity"}, {"par": "battery_initial"}]}
    assert lint.unread(ir, seed) == []
    # Given as a cell, it is counted once, as before.
    seed["parameter_values"] = [{"parameter": "battery_initial", "entities": [], "value": 600}]
    ir["constraints"][0]["right"] = {"par": "battery_capacity"}
    assert [f["what"] for f in lint.unread(ir, seed)] == ["battery_initial"]
