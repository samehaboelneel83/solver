"""Every sentence of the request mapped (app/agent/sentences.py; build-protocol plan, Phase 3.2)."""

from __future__ import annotations

import json

from app.agent import sentences

REQUEST = ("We run three sites and want the cheapest plan. Each site must take at most 40 units a day. "
           "No site may be left without a supervisor.\n"
           "W01,204,233\nW02,120,98\n"
           "Thanks for your help with this!\n"
           "- Deliveries happen before noon.")


def _call(cid: str, name: str, args: dict) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"id": cid, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args)}}]}


def test_the_request_is_split_into_its_prose_sentences():
    got = sentences.sentences_of(REQUEST)
    assert got == ["We run three sites and want the cheapest plan.", "Each site must take at most 40 units a day.",
                   "No site may be left without a supervisor.", "Thanks for your help with this!",
                   "Deliveries happen before noon."]
    assert [sentences.states_a_rule(s) for s in got] == [False, True, True, False, True]
    assert [sentences.states_a_goal(s) for s in got] == [True, False, False, False, False]


def test_a_rule_sentence_no_rule_holds_is_a_card_line_on_the_protocol_path():
    messages = [{"role": "user", "content": REQUEST},
                _call("v", "stage_decisions", {"variables": {"x": {"index": ["site"], "domain": "integer"}}}),
                _call("r1", "add_rule", {"sentence": "Each site must take at most 40 units a day.",
                                         "rule": {"id": "c_cap"}}),
                _call("g", "stage_goal", {"objective": {"sense": "minimize", "terms": []}})]
    missing = sentences.unmatched(messages)
    assert missing["rules"] == ["No site may be left without a supervisor.", "Deliveries happen before noon."]
    assert missing["goal"] == []  # a goal is staged
    card = sentences.sentences_for_person(messages)
    assert card.count("CHECK THIS: no rule holds") == 2 and "supervisor" in card
    # The goal sentence is named when no goal is staged.
    missing = sentences.unmatched(messages[:3])
    assert missing["goal"] == ["We run three sites and want the cheapest plan."]


def test_a_claim_in_other_words_still_holds_the_sentence():
    messages = [{"role": "user", "content": "Each site must take at most 40 units a day."},
                _call("r1", "add_rule", {"sentence": "a site takes at most 40 units a day", "rule": {"id": "c"}})]
    assert sentences.unmatched(messages)["rules"] == []
    assert sentences.alike("No site may be left without a supervisor.", "no site without a supervisor")
    assert not sentences.alike("No site may be left without a supervisor.", "the cheapest plan")


def test_a_rules_note_in_the_spec_claims_its_sentence_too():
    messages = [{"role": "user", "content": "Each site must take at most 40 units a day."},
                _call("r1", "add_rule", {"sentence": "", "rule": {"id": "c"}})]
    spec = {"ir": {"constraints": [{"id": "c", "note": "Each site must take at most 40 units a day."}],
                   "objective": {"sense": "minimize", "terms": []}}}
    assert sentences.unmatched(messages, spec) == {"rules": [], "goal": []}
    assert sentences.mapping(messages, spec) == [("Each site must take at most 40 units a day.", "c")]


def test_nothing_is_said_off_the_protocol_path():
    messages = [{"role": "user", "content": REQUEST},
                _call("p", "propose_plan", {"summary": "s", "spec": {"seed": {}, "ir": {"variables": {}}}})]
    assert sentences.unmatched(messages) == {"rules": [], "goal": []}
    assert sentences.sentences_for_person(messages) == ""
