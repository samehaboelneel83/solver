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
