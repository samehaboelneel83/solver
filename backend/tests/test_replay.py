"""The replay set (app/agent/replay.py): recorded conversations scored again by today's reply checks."""
from __future__ import annotations

import json

from app.agent import replay

RESULT = ("RUN 7: optimal; goal (minimize) = 3,020; solver glop.\nDECISION ship\nfrom | to | units\nA | X | 120\n"
          "SENSITIVITY (from the solver; exact only inside each range -- for a bigger change call what_if):\n"
          "- c_cap (<= limit 150): each +1 on the limit changes the goal by -4 (goal falls); holds while the limit "
          "stays from 140 to 160.")


def _conversation():
    tool = {"role": "tool", "tool_call_id": "c1", "content": RESULT}
    call = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                                                                  "function": {"name": "read_result", "arguments": "{}"}}]}
    return [
        {"role": "user", "content": "What does run 7 say?"}, call, tool,
        {"role": "assistant", "content": "The plan costs 3,020 and ships 120 units from A to X."},
        {"role": "user", "content": "And the total weight?"}, call, tool,
        {"role": "assistant", "content": "(an answer with numbers the results do not give; not shown)"},
        {"role": "assistant", "content": "It weighs 4,999 kg in all."},
        {"role": "user", "content": "What if the cap were raised?"},
        {"role": "assistant", "content": "If the cap rose to 220, the cost would fall by 280."},
    ]


def test_each_final_answer_is_scored_by_todays_checks_and_live_catches_are_counted():
    got = replay.score_conversation(_conversation())
    assert got["answers"] == 3  # the "(... not shown)" placeholder is not an answer
    # The condition's 220 is an assumption, not a claim: only 4,999 is unsupported.
    assert got["flagged"]["unsupported_number"] == 1 and "4,999" in got["found"]["unsupported_number"][0]["items"][0]
    # +70 on a limit that holds to 160 (70 x 4 = 280): the rate past its range.
    assert got["flagged"]["unsupported_what_if"] == 1
    assert got["caught_live"] == {"unsupported_number": 1}
    assert got["answers_flagged"] == 2


def test_a_set_is_exported_as_lines_and_scored_with_a_report(tmp_path):
    path = tmp_path / "set.jsonl"
    path.write_text("\n".join(json.dumps({"id": f"c{n}", "mode": "ask", "messages": _conversation()}) for n in range(2)))
    report = replay.score(replay.load(str(path)))
    assert report["conversations"] == 2 and report["answers"] == 6 and report["flagged"]["unsupported_number"] == 2
    text = replay.as_text(report)
    assert "2 conversations, 6 final answers; 4 answers would be sent back" in text and "4,999" in text
    assert replay.main(["score", str(path), "--json"]) == 0
