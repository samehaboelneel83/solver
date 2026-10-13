"""The trial's card lines for a decision that decides nothing: 0 everywhere (the plan does nothing) and, since
13 October 2026, 1 everywhere (a yes/no decision that is always yes). The second came from the covering
construct's mistake written by hand (chosen >= covers for every pair), which forced every option on and which no
check saw; no tuning gold has a yes/no decision at 1 on every cell, so the warning is safe on the corpus."""

from __future__ import annotations

from app.agent import core


def test_a_yes_no_decision_at_1_everywhere_is_named():
    used = {"open": {"non_zero": 3, "cells": 3, "ones": 3}, "amount": {"non_zero": 5, "cells": 9}}
    assert core.always_yes_decisions(used) == ["open"]
    said = core.trial_said({"status": "optimal", "objective": 10, "used": used, "seconds": 1})
    assert "open is 1 on every one of its 3 cells" in said and "always yes" in said
    card = core.trial_for_person({"status": "optimal", "objective": 10, "used": used})
    assert "CHECK THIS: open is yes on every one of its 3 cells" in card


def test_the_warning_needs_two_cells_and_a_yes_no_decision():
    # One cell at 1 is a choice, not a decision that is always yes; a quantity has no "ones".
    assert core.always_yes_decisions({"open": {"non_zero": 1, "cells": 1, "ones": 1}}) == []
    assert core.always_yes_decisions({"amount": {"non_zero": 4, "cells": 4}}) == []
    assert core.always_yes_decisions({"open": {"non_zero": 3, "cells": 4, "ones": 3}}) == []
    card = core.trial_for_person({"status": "optimal", "objective": 1,
                                  "used": {"open": {"non_zero": 3, "cells": 4, "ones": 3}}})
    assert "always yes" not in card
