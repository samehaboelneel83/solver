"""Every number of the request mapped to the model (neutrality plan, step 5): a number the person wrote that the
model holds nowhere is named on the plan card."""

from __future__ import annotations

from app.agent.core import PLATFORM, numbers_for_person, unused_numbers


def _spec(**ir):
    return {"seed": {"entities": [{"type": "item", "key": k, "attrs": {"size": s}} for k, s in (("a", 40), ("b", 25))],
                     "parameters": [{"name": "limit", "index": [], "default_value": 500}]},
            "ir": {"constraints": [{"id": "c", "note": "at most 70 of the 120", "left": {"var": "x"}, "relation": "<=",
                                    "right": {"const": 0.15}}], **ir}}


def test_a_number_the_model_does_not_hold_is_named():
    messages = [{"role": "user", "content": "Two items (sizes 40 and 25), a limit of 500, at most 15% waste, "
                                            "and no more than 70 per day."}]
    assert unused_numbers(messages, _spec()) == ["70"]
    card = numbers_for_person(messages, _spec())
    assert card.startswith("\n- CHECK THIS: numbers you wrote that the model does not use anywhere: 70")


def test_list_marks_years_zero_one_and_the_platforms_own_messages_are_not_data():
    messages = [{"role": "user", "content": "1. sizes 40 and 25\n2) limit 500 for 2026, 0 or 1 each"},
                {"role": "user", "content": PLATFORM + "Note: 999 things"}]
    assert unused_numbers(messages, _spec()) == []


def test_a_pasted_table_is_data_not_prose():
    messages = [{"role": "user", "content": "Items:\nid,size,weight\nI1,40,77\nI2,25,88\nBudget 172,258 EGP."}]
    assert unused_numbers(messages, _spec()) == ["172,258"]


def test_counts_of_records_and_percent_as_fraction_count_as_used():
    messages = [{"role": "user", "content": "There are 2 items; waste stays under 15%; limit 500."}]
    assert unused_numbers(messages, _spec()) == []
    assert numbers_for_person(messages, _spec()) == ""


def test_a_plan_that_does_nothing_is_named_on_the_card_and_to_the_model():
    """The evaluation, 11 October 2026: open 0 of 3, ship 0 of 54, stock 0 of 9, unmet 18 of 18."""
    from app.agent.core import idle_decisions, trial_for_person, trial_said

    used = {"open": {"non_zero": 0, "cells": 3}, "ship": {"non_zero": 0, "cells": 54},
            "stock": {"non_zero": 0, "cells": 9}, "unmet": {"non_zero": 18, "cells": 18}}
    assert idle_decisions(used) == ["open", "ship", "stock"]
    card = trial_for_person({"status": "optimal", "objective": 335000, "used": used})
    assert "CHECK THIS: the plan does nothing with open, ship, stock (0 everywhere); only unmet is used" in card
    assert "the plan does nothing" in trial_said({"status": "optimal", "objective": 335000, "used": used, "seconds": 1})
    fine = {"open": {"non_zero": 2, "cells": 3}, "ship": {"non_zero": 20, "cells": 54}, "unmet": {"non_zero": 0, "cells": 18}}
    assert idle_decisions(fine) == [] and "CHECK THIS" not in trial_for_person({"status": "optimal", "used": fine})


def test_a_plan_that_does_nothing_goes_back_to_the_model_before_the_person_sees_it():
    from app.agent.core import trial_sent_back

    used = {"open": {"non_zero": 0, "cells": 3}, "ship": {"non_zero": 0, "cells": 54}, "unmet": {"non_zero": 18, "cells": 18}}
    back = trial_sent_back({"status": "optimal", "objective": 1, "used": used})
    assert back.startswith("The plan was NOT shown to the user: solved once on its real data, it does nothing -- open, ship")
    assert "only unmet is used" in back
    assert trial_sent_back({"status": "optimal", "used": {"open": {"non_zero": 2, "cells": 3}, "ship": {"non_zero": 9, "cells": 54}}}) == ""


def test_a_number_given_to_compare_or_report_against_is_not_flagged():
    """The evaluation, 11 October 2026: "compare that cost with our current plan, whose cost is 17,305" was
    flagged on three cards running, and the plan never built."""
    messages = [{"role": "user", "content": "Sizes 40 and 25, limit 500. Goal: the lowest cost. Then compare that "
                                            "cost with our current plan, whose cost is 17,305, and report the "
                                            "saving against today, when all 4 are on. Also at most 70 a day."}]
    assert unused_numbers(messages, _spec()) == ["70"]


def test_a_decision_used_where_a_pair_parameter_gives_no_value_is_named():
    """11 October 2026: a product made on a machine the times file never lists (its time defaulted to 0)."""
    from app.agent.core import trial_for_person, trial_said
    from app.api.model_spec import used_without_data

    ir = {"variables": {"produce": {"index": ["product", "machine", "shift"]}, "on": {"index": ["machine"]}},
          "parameters": {"time": {"index": ["product", "machine"]}, "demand": {"index": ["product"]}}}
    data = {"parameters": {"time": [{"product": "P1", "machine": "M2", "value": 0.1}, {"product": "P2", "machine": "M2", "value": 0.2}],
                           "demand": [{"product": "P1", "value": 5}]},
            "parameter_defaults": {"time": 0, "demand": 0}}
    assignments = {("produce", ("P1", "M2", "S1")): 4, ("produce", ("P2", "M1", "S1")): 19, ("produce", ("P2", "M2", "S2")): 0,
                   ("on", ("M1",)): 1}
    found = used_without_data(ir, data, assignments)
    assert found == [{"var": "produce", "parameter": "time", "cells": 1, "default": 0, "examples": ["P2 · M1"]}]
    trial = {"status": "optimal", "objective": 980, "used": {"produce": {"non_zero": 2, "cells": 12}}, "no_data": found, "seconds": 1}
    assert "CHECK THIS: produce is used on 1 cell(s) where time gives no value (P2 · M1): its default 0 applies" in trial_for_person(trial)
    assert "produce is used on 1 cell(s) where time gives no value" in trial_said(trial)
    assert used_without_data(ir, data, {("produce", ("P1", "M2", "S1")): 4}) == []
    # A 0/1 list (closed roads as 1, or allowed pairs as 1) says nothing here: using an unlisted pair is right
    # in one reading and wrong in the other.
    flags = {"parameters": {"closed": [{"product": "P1", "machine": "M2", "value": 1}]}, "parameter_defaults": {"closed": 0}}
    ir2 = {"variables": {"produce": {"index": ["product", "machine", "shift"]}}, "parameters": {"closed": {"index": ["product", "machine"]}}}
    assert used_without_data(ir2, flags, {("produce", ("P2", "M1", "S1")): 3}) == []


def test_a_goal_running_the_other_way_from_the_request_is_named():
    from app.agent.core import goal_sense_for_person, goal_sense_said

    assert goal_sense_said("Goal: the lowest total shipping cost.") == "minimize"
    assert goal_sense_said("Goal: as many beds as possible; among layouts with as many beds, the shortest walk.") is None
    assert goal_sense_said("Goal: the most patients treated in total. Report the cheapest option too.") == "maximize"
    msgs = [{"role": "user", "content": "Rules: ... Goal: the lowest total cost."}]
    assert "CHECK THIS: the goal maximizes, but your words ask for the least" in goal_sense_for_person(msgs, {"objective": {"sense": "maximize"}})
    assert goal_sense_for_person(msgs, {"objective": {"sense": "minimize"}}) == ""


def test_a_layouts_lengths_in_cells_count_as_the_metres_the_person_wrote():
    """11 October 2026: 0.9 and 1.2 flagged on three cards of a layout holding them as 9 and 12 cells."""
    spec = {"seed": {"entities": [{"type": "slot", "key": f"s{i}", "attrs": {"length": 20, "width": 9}} for i in range(63)]},
            "ir": {"constraints": [{"id": "c_layout", "place": {"step": 0.1, "aisle": 12, "slots": {"set": "slot"},
                                                              "length": "length", "width": "width"}}],
                   "variables": {"x": {"index": ["slot"], "upper": 141}}}}
    messages = [{"role": "user", "content": "Beds are 2.0 m x 0.9 m. Corridors at least 1.2 m wide. 63 candidate "
                                            "positions on a 14.1 m site. Also at most 70 beds per zone."}]
    assert unused_numbers(messages, spec) == ["70"]


def test_the_sizes_of_what_was_attached_count_as_held():
    """11 October 2026: "layer PROTECTED holds 14 protected areas" flagged as unused on a right layout."""
    from app.agent.core import attachment_counts, numbers_for_person

    files = [{"name": "site.dxf", "spatial": {"layers": 3, "layer_counts": [{"name": "PROTECTED", "count": 14}]},
              "sheets": [{"name": "site__PROTECTED", "total_rows": 14}]},
             {"name": "rows.csv", "sheets": [{"name": "rows", "total_rows": 63}]}]
    assert attachment_counts(files) == {3.0, 14.0, 63.0}
    messages = [{"role": "user", "content": "layer PROTECTED holds 14 areas and 3 layers; 63 rows; at most 70 beds."}]
    assert numbers_for_person(messages, {"seed": {}, "ir": {}}, files).endswith("anywhere: 70 -- each should be a limit, a value or a goal weight, or the model answers a different question")
