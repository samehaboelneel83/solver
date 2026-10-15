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


def test_the_draft_survives_the_conversation_being_summarized():
    """12 October 2026: after a summary the folded propose_plan calls were gone and every patch had no draft."""
    from app.agent import compact as agent_compact

    patch = {"summary": "s", "spec": {"ir": {"constraints": [{"id": "c_two", "drop": True}]}}}
    messages = [{"role": "user", "content": "plan it " + "x" * 300}, _call({"summary": "s", "spec": FULL}),
                {"role": "tool", "name": "propose_plan", "content": "sent back"}, _call(patch),
                {"role": "tool", "name": "propose_plan", "content": "sent back"}, {"role": "assistant", "content": "y" * 300},
                {"role": "user", "content": "go on"}, {"role": "assistant", "content": "z" * 300}]
    done = agent_compact.compact(messages, summarize=lambda piece, notes: "notes", keep_chars=1, piece_chars=100_000,
                                 numbers=lambda ms: set(), force=True)
    assert done and agent_compact.is_summary(messages[0])
    folded = messages[0]["draft"]
    assert [c["id"] for c in folded["ir"]["constraints"]] == ["c_one"] and folded["seed"] == FULL["seed"]
    # A patch after the summary completes from it.
    later = {"ir": {"variables": {"y": {"index": [], "domain": "binary"}}}}
    messages.append(_call({"summary": "s", "spec": later}))
    spec, note = draft.complete(later, messages)
    assert "y" in spec["ir"]["variables"] and [c["id"] for c in spec["ir"]["constraints"]] == ["c_one"]
    from app.agent import core
    assert all("draft" not in m for m in core.to_wire(messages, True))


def test_a_seed_alone_is_a_patch():
    """12 October 2026: a patch carrying new data and no ir was taken whole and refused for having no model."""
    seed_only = {"seed": {"parameters": [{"name": "q", "index": ["a"], "default_value": 0}]}}
    assert draft.is_partial(seed_only)
    messages = [_call({"summary": "s", "spec": FULL}), {"role": "tool", "name": "propose_plan", "content": "sent back"},
                _call({"summary": "s", "spec": seed_only})]
    spec, note = draft.complete(seed_only, messages)
    assert spec["ir"] == FULL["ir"] and [p["name"] for p in spec["seed"]["parameters"]] == ["q"]
    assert note == "the plan was completed from your last one: the seed changed, everything else kept"


def test_a_copied_placeholder_is_no_plan_and_the_last_whole_plan_is_kept():
    """15 Oct, native tool calls: the model copied the history's placeholder ("spec": "(superseded by a later
    attempt)") as its next plan, refused as "the spec has no ir" again and again."""
    import copy as _copy

    from app.agent import core, repair
    from app.api import agent as agent_api

    def call(cid, args):
        return {"role": "assistant", "content": "", "tool_calls": [{"id": cid, "type": "function", "function": {
            "name": "propose_plan", "arguments": json.dumps(args)}}]}

    first = {"summary": "s1", "spec": _copy.deepcopy(FULL)}
    second = {"summary": "s2", "spec": _copy.deepcopy(FULL)}
    messages = [call("a", first), {"role": "tool", "tool_call_id": "a", "name": "propose_plan", "content": "x" * 500},
                call("b", second), {"role": "tool", "tool_call_id": "b", "name": "propose_plan", "content": "y" * 500}]
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": False}, core.Context("x", mode="model"))
    agent._compact_attempts(messages)
    kept_first = json.loads(messages[0]["tool_calls"][0]["function"]["arguments"])
    assert "spec" not in kept_first and kept_first["superseded"]  # no plan-shaped placeholder to copy
    assert json.loads(messages[2]["tool_calls"][0]["function"]["arguments"])["spec"] == FULL  # the latest whole one
    spec, notes = repair.spec_of({"summary": "s3", "spec": "(superseded by a later attempt)"})
    assert spec == {}
    copied = messages + [call("c", {"summary": "s3", "spec": "(superseded by a later attempt)"})]
    from app.agent import draft

    done, note = draft.complete(spec, copied)
    assert done.get("ir") == FULL["ir"] and note
