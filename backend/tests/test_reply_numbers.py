"""Every number in an answer comes from the results, the person, or one step of arithmetic on them
(app.agent.core.unsupported_numbers; plan of 8 October 2026, honest answers, step 2)."""
from __future__ import annotations

import pytest

from app.agent.core import unsupported_numbers

RESULTS = ["STATUS optimal. GOAL 3,020 (cost).\nDECISION ship\nfrom | to | units | cost\nA | X | 120 | 600\n"
           "B | Y | 80 | 2420\nRULES lane cap 150, used 120; supply 400", "Before: goal 3,180. Spare: 30 units."]
PERSON = ["Plants A and B, a budget of 5000, lanes take 150 at most"]


@pytest.mark.parametrize("answer", [
    "The best plan costs 3,020, shipping 120 units from A to X.",
    "That saves 160 compared with before (3,180).",
    "That is 5.0% cheaper than before.",
    "In total 200 units are shipped.",
    "It costs about 3,000.",
    "Well within your budget of 5,000.",
    "Run 132 on 2026-10-07 at 21:30 for plant P3, as planned for 2027.",
    "Three lanes and 2 plants.",
])
def test_numbers_the_results_support_pass(answer):
    assert unsupported_numbers(answer, RESULTS, PERSON) == []


def test_numbers_nothing_gives_are_named():
    assert unsupported_numbers("The plan costs 3,120 and ships 215 units.", RESULTS, PERSON) == ["3,120", "215"]


def test_rounding_is_allowed_only_as_shown():
    assert unsupported_numbers("It costs 3,021.", RESULTS, PERSON) == ["3,021"]
    exact = ["GOAL 3,020.37"]
    assert unsupported_numbers("It costs 3,020.4, or 3,020 rounded.", exact, []) == []
    assert unsupported_numbers("It costs 3,020.5.", exact, []) == ["3,020.5"]


def test_scaled_amounts_are_read_with_their_scale():
    results = ["GOAL 2,450,000"]
    assert unsupported_numbers("about 2.45 million in total", results, []) == []
    assert unsupported_numbers("2.9 million in total", results, []) == ["2.9 million"]


def test_without_any_results_nothing_is_checked():
    assert unsupported_numbers("It costs 3,120.", [], []) == []


FEASIBLE = ["RUN 9: feasible; goal (maximize) = 1,939; solver cp-sat.\nNOT PROVEN OPTIMAL: the solver stopped."]


@pytest.mark.parametrize("answer", ["This is the optimal layout with 1,939 beds.", "1,939 beds, the best possible plan.",
                                    "No better plan exists than these 1,939 beds."])
def test_an_unproven_answer_may_not_be_called_optimal(answer):
    from app.agent.core import reply_contradictions

    assert any("without proving it best" in w for w in reply_contradictions(answer, FEASIBLE))


@pytest.mark.parametrize("answer", ["It is not proven optimal: 1,939 beds.", "1,939 beds, within 20% of the best possible."])
def test_saying_it_is_unproven_is_fine(answer):
    from app.agent.core import reply_contradictions

    assert reply_contradictions(answer, FEASIBLE) == []
    assert reply_contradictions("The optimal plan.", ["RUN 9: optimal; goal (maximize) = 7"]) == []
