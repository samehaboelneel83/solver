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


SENSITIVITY = ("SENSITIVITY (from the solver; exact only inside each range -- for a bigger change call what_if):\n"
               "- c_capacity (<= limit 100): each +1 on the limit changes the goal by -50 (goal falls); holds while "
               "the limit stays from 90 to 110.")


def test_a_what_if_amount_from_a_rate_inside_its_range_passes():
    from app.agent.core import unsupported_what_ifs

    # +5 on a limit of 100 that holds to 110: 5 x 50 = 250 is what the rate says.
    assert unsupported_what_ifs("Cost would fall by 250 if the capacity limit rose to 105.", [SENSITIVITY], []) == []


def test_a_rate_taken_past_its_range_is_sent_back():
    from app.agent.core import unsupported_what_ifs

    # +20 on a limit that holds only to 110: 1,000 is the rate extrapolated, not an answer (the blend test).
    assert unsupported_what_ifs("If the capacity limit rose by 20, cost would fall by 1,000.", [SENSITIVITY], []) == ["1,000"]


def test_a_what_if_runs_difference_passes_and_plain_sentences_are_not_checked():
    from app.agent.core import unsupported_what_ifs

    run = ("WHAT-IF 'more capacity' (scenario 9, from scenario 8; changes: limit 150)\n"
           "BASE goal 12,800.00 (run 3) -> WHAT-IF goal 12,300.00 (run 4): -500.00")
    assert unsupported_what_ifs("You would save 500 if capacity were 150 (12,300 instead of 12,800).", [run], []) == []
    # Not a what-if: the number check covers it, this one does not.
    assert unsupported_what_ifs("The plan costs 4,321 in all.", [SENSITIVITY], []) == []
    # A what-if amount with nothing behind it.
    assert unsupported_what_ifs("With an extra truck you could save 7,400.", [SENSITIVITY], []) == ["7,400"]
