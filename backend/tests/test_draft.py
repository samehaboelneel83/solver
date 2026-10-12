"""A plan sent back is patched, not rewritten (app/agent/draft.py; getting-better plan, lever 1.1)."""

from __future__ import annotations

import json

from app.agent import draft


def _call(args: dict) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function", "function": {
        "name": "propose_plan", "arguments": json.dumps(args)}}]}


FULL = {"domain_name": "D", "problem_name": "P", "seed": {"entities": [{"type": "a", "key": "a1"}]},
        "ir": {"version": 2, "sets": ["a"], "parameters": {"p": {"index": ["a"]}},
               "variables": {"x": {"index": ["a"], "domain": "continuous", "lower": 0}},
               "constraints": [{"id": "c_one", "left": {"var": "x", "index": ["a"]}, "relation": "<=", "right": {"const": 1}},
                               {"id": "c_two", "left": {"var": "x", "index": ["a"]}, "relation": ">=", "right": {"const": 0}}],
               "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": ["a"]}}]}}}


def test_a_patch_replaces_the_rules_it_names_and_keeps_the_rest():
    patch = {"ir": {"constraints": [{"id": "c_one", "left": {"var": "x", "index": ["a"]}, "relation": "<=", "right": {"const": 5}},
                                    {"id": "c_two", "drop": True},
                                    {"id": "c_new", "left": {"var": "x", "index": ["a"]}, "relation": ">=", "right": {"const": 2}}],
                    "objective": {"sense": "maximize", "terms": FULL["ir"]["objective"]["terms"]}}}
    assert draft.is_partial(patch) and not draft.is_partial(FULL)
    merged = draft.merge(FULL, patch)
    assert merged["seed"] == FULL["seed"] and merged["ir"]["variables"] == FULL["ir"]["variables"]
    assert [c["id"] for c in merged["ir"]["constraints"]] == ["c_one", "c_new"]
    assert merged["ir"]["constraints"][0]["right"] == {"const": 5} and merged["ir"]["objective"]["sense"] == "maximize"
    assert FULL["ir"]["objective"]["sense"] == "minimize"  # the previous plan is never changed in place


def test_the_draft_is_folded_from_the_conversations_own_calls_and_completes_a_patch():
    first = {"summary": "s", "spec": FULL}
    patch1 = {"summary": "s", "spec": {"ir": {"constraints": [{"id": "c_two", "drop": True}]}}}
    patch2 = {"summary": "s", "spec": {"ir": {"variables": {"y": {"index": [], "domain": "binary"}}}}}
    messages = [{"role": "user", "content": "plan it"}, _call(first), {"role": "tool", "content": "sent back"},
                _call(patch1), {"role": "tool", "content": "sent back"}, _call(patch2)]
    assert draft.draft_from([messages[0], messages[1]]) is None  # only the call being checked
    folded = draft.draft_from(messages)  # the two before the last
    assert [c["id"] for c in folded["ir"]["constraints"]] == ["c_one"] and "y" not in folded["ir"]["variables"]
    spec, note = draft.complete(patch2["spec"], messages)
    assert "y" in spec["ir"]["variables"] and spec["seed"] == FULL["seed"]
    assert note == "the plan was completed from your last one: variables changed, everything else kept"
    assert draft.complete(FULL, messages) == (FULL, None)


def test_a_seed_part_sent_alone_joins_the_drafts_seed_by_key():
    """12 October 2026: a partial seed replaced the whole one; "no value loaded" for everything else, eleven times."""
    previous = {"seed": {"entity_types": [{"name": "a", "attributes": []}],
                         "entities": [{"type": "a", "key": "a1"}, {"type": "a", "key": "a2"}],
                         "parameters": [{"name": "p", "index": ["a"], "default_value": 0}],
                         "parameter_values_from_file": [{"file": "f.csv", "parameter": "p", "entities": [["a", "id"]], "value": "p"}]},
                "ir": {"version": 2, "variables": {"x": {"index": ["a"]}}, "constraints": []}}
    patch = {"seed": {"parameters": [{"name": "q", "index": ["a"], "default_value": 1}],
                      "parameter_values_from_file": [{"file": "f.csv", "parameter": "q", "entities": [["a", "id"]], "value": "q"}],
                      "entities": [{"type": "a", "key": "a2", "drop": True}, {"type": "a", "key": "a3"}]},
             "ir": {"parameters": {"q": {"index": ["a"]}}}}
    assert draft.is_partial(patch)
    merged = draft.merge(previous, patch)
    seed = merged["seed"]
    assert [p["name"] for p in seed["parameters"]] == ["p", "q"]
    assert [e["parameter"] for e in seed["parameter_values_from_file"]] == ["p", "q"]
    assert [e["key"] for e in seed["entities"]] == ["a1", "a3"] and seed["entity_types"] == previous["seed"]["entity_types"]
    assert merged["ir"]["variables"] == previous["ir"]["variables"] and merged["ir"]["parameters"] == {"q": {"index": ["a"]}}
    assert len(previous["seed"]["parameters"]) == 1  # the draft is never changed in place


def test_a_repeated_refusal_after_a_patch_names_the_rules_and_then_asks_for_the_whole_plan():
    """12 October 2026: the same refusal fourteen times -- a rule left out of a patch stays."""
    from app.agent import core

    refusal = "The spec does not build yet; fix these: Parameter p[a] is used by the model but no value is loaded"
    messages = [_call({"summary": "s", "spec": FULL}), {"role": "tool", "name": "propose_plan", "content": refusal},
                _call({"summary": "s", "spec": {"ir": {"constraints": [FULL["ir"]["constraints"][0]]}}})]
    assert draft.repeated(refusal, messages) == 1
    assert draft.repeated("Another problem entirely", messages) == 0
    messages += [{"role": "tool", "name": "propose_plan", "content": refusal + core.REPEATED_HINT.format(rules="c_one, c_two")},
                 _call({"summary": "s", "spec": {"ir": {"constraints": [FULL["ir"]["constraints"][1]]}}})]
    assert draft.repeated(refusal, messages) == 2
    # After the whole-plan hint, a partial spec is taken as it is, no merge.
    messages += [{"role": "tool", "name": "propose_plan", "content": refusal + core.WHOLE_HINT},
                 _call({"summary": "s", "spec": {"ir": {"constraints": []}}})]
    spec, note = draft.complete({"ir": {"constraints": []}}, messages)
    assert spec == {"ir": {"constraints": []}} and note is None
    assert draft.WHOLE_MARK in core.WHOLE_HINT
