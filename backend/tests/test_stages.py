"""The build protocol's stages (app/agent/stages.py; build-protocol plan, Phase 3.1 and 3.6's first bullet):
each gold model replayed stage by stage -- the data, the decisions, every rule one at a time, the goal -- is
accepted at every stage, and the plan assembled from the stage calls is the gold model again. Case ids only in
the messages: the hidden golds go through here too, when captured."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent import draft as agent_draft
from app.agent import stages

BENCH = Path(__file__).resolve().parents[1] / "bench"
GOLD_DIRS = (BENCH / "phase1" / "gold", BENCH / "hidden" / "gold")


def _golds() -> list[Path]:
    return sorted(p for d in GOLD_DIRS if d.is_dir() for p in d.glob("*.json"))


def seed_of(data: dict, ir: dict) -> dict:
    """A gold's frozen dataset as the seed its data stage would carry."""
    entity_types = []
    entities = []
    for kind, rows in (data.get("sets") or {}).items():
        fields = sorted({k for r in rows if isinstance(r, dict) for k in r if k != "id"})
        entity_types.append({"name": kind, "attributes": [{"name": f, "data_type": "number"} for f in fields]})
        for r in rows:
            if isinstance(r, dict):
                entities.append({"type": kind, "key": str(r.get("id")), "attrs": {f: r.get(f) for f in fields if f in r}})
    parameters = []
    values = []
    for name, rows in (data.get("parameters") or {}).items():
        index = list(((ir.get("parameters") or {}).get(name) or {}).get("index") or [])
        parameters.append({"name": name, "index": index, "default_value": (data.get("parameter_defaults") or {}).get(name, 0)})
        for r in rows or []:
            if isinstance(r, dict):
                values.append({"parameter": name, "entities": [[s, str(r.get(s))] for s in index], "value": r.get("value")})
    relationship_types = [{"name": name, "from": "?", "to": "?"} for name in (data.get("relationships") or {})]
    return {"entity_types": entity_types, "entities": entities, "parameters": parameters, "parameter_values": values,
            "relationship_types": relationship_types}


def _call(cid: str, name: str, args: dict) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"id": cid, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args)}}]}


def _replay(gold: dict) -> tuple[list[dict], list[str]]:
    """The gold through the stages, as the Assistant's conversation would hold it: the calls, and what each
    stage said. Raises StageRefused where a stage refuses."""
    ir, data = gold["ir"], gold["data"]
    messages: list[dict] = []
    said: list[str] = []
    messages.append(_call("d", "stage_data", seed_of(data, ir)))
    messages.append(_call("v", "stage_decisions", {"variables": ir["variables"], "parameters": ir.get("parameters") or {}}))
    draft = agent_draft.draft_from(messages, before=None)  # everything before the call being checked
    # The decisions are checked against the data staged before them.
    said.append(stages.check_decisions(agent_draft.merge(draft, agent_draft.stage_patch(
        "stage_decisions", {"variables": ir["variables"], "parameters": ir.get("parameters") or {}}))))
    for i, rule in enumerate(ir["constraints"]):
        cid = f"r{i}"
        messages.append(_call(cid, "add_rule", {"sentence": rule.get("note") or "", "rule": rule}))
        draft = agent_draft.draft_from(messages, before=cid)
        _, line = stages.check_rule(draft, rule, rule.get("note") or "")
        said.append(line)
    messages.append(_call("g", "stage_goal", {"objective": ir["objective"]}))
    draft = agent_draft.draft_from(messages, before="g")
    said.append(stages.check_goal(draft, ir["objective"]))
    messages.append(_call("p", "propose_plan", {"summary": "the plan"}))
    return messages, said


@pytest.mark.parametrize("path", _golds(), ids=lambda p: p.stem)
def test_a_gold_replayed_stage_by_stage_is_accepted_and_assembled_whole(path: Path):
    gold = json.loads(path.read_text(encoding="utf-8"))
    try:
        messages, said = _replay(gold)
    except stages.StageRefused as exc:
        pytest.fail(f"{path.stem}: a stage refused ({str(exc)[:160]})")
    assert all("ranges over" in s for s in said[1:-1]), f"{path.stem}: a rule line lacks its range"
    assert not any("ranges over 0 " in s for s in said), f"{path.stem}: a rule ranges over nothing"
    draft = agent_draft.draft_from(messages, before="p")
    spec = stages.assemble(draft)
    ir = gold["ir"]
    assert spec["ir"]["variables"] == ir["variables"], f"{path.stem}: the decisions differ"
    assert spec["ir"]["parameters"] == (ir.get("parameters") or {}), f"{path.stem}: the parameters differ"
    assert spec["ir"]["objective"] == ir["objective"], f"{path.stem}: the goal differs"
    assert [c for c in spec["ir"]["constraints"]] == ir["constraints"], f"{path.stem}: the rules differ"
    assert set(spec["ir"]["sets"]) <= set(ir["sets"]) and set(ir["sets"]) - set(spec["ir"]["sets"]) == \
        {s for s in ir["sets"] if s not in stages._index_sets(ir)}, f"{path.stem}: the sets differ"
    assert set(spec["ir"]["relationships"]) >= set(stages._relationships_read(ir)), f"{path.stem}: a walked relationship is missing"


def test_the_stage_order_is_held():
    with pytest.raises(stages.StageRefused, match="declare the decisions first"):
        stages.check_rule({"seed": {}, "ir": {}}, {"id": "c", "left": {"const": 1}, "relation": "<=", "right": {"const": 2}})
    with pytest.raises(stages.StageRefused, match="declare the decisions first"):
        stages.check_goal({"seed": {}, "ir": {}}, {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"const": 1}}]})
    with pytest.raises(stages.StageRefused, match="has no records"):
        stages.check_decisions({"seed": {"entity_types": [{"name": "a"}]},
                                "ir": {"variables": {"x": {"index": ["a"], "domain": "continuous", "lower": 0}}}})


def test_a_rule_is_read_back_with_its_sentence_range_and_data():
    draft = {"seed": {"entity_types": [{"name": "a", "attributes": [{"name": "cost", "data_type": "number"}]}],
                      "entities": [{"type": "a", "key": k, "attrs": {"cost": 1}} for k in ("a1", "a2", "a3")]},
             "ir": {"variables": {"x": {"index": ["a"], "domain": "continuous", "lower": 0}}}}
    rule = {"id": "c_cap", "forall": [{"index": "i", "set": "a"}], "left": {"var": "x", "index": ["i"]},
            "relation": "<=", "right": {"attr": {"of": "i", "name": "cost"}}}
    kept, said = stages.check_rule(draft, rule, "each one at most its cost")
    assert said.startswith('rule c_cap holds "each one at most its cost": c_cap ranges over 3 records; reads cost')
    assert kept["severity"] == "hard" and kept["note"] == "each one at most its cost"
    # A construct is expanded and every rule it became is read back.
    rule = {"id": "c_one", "exactly_one": {"over": [{"index": "i", "set": "a"}], "pick": {"var": "x", "index": ["i"]}}}
    _, said = stages.check_rule(draft, rule, "exactly one")
    assert "c_one ranges over once" in said
    # A rule read with the wrong number of indices is refused with what to write.
    with pytest.raises(stages.StageRefused, match="write it as"):
        stages.check_rule(draft, {"id": "c_bad", "left": {"var": "x", "index": []}, "relation": "<=", "right": {"const": 1}})


def test_the_fold_takes_the_call_being_checked_by_id():
    messages = [_call("d", "stage_data", {"entity_types": [{"name": "a"}], "entities": [{"type": "a", "key": "a1"}]}),
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "v", "type": "function", "function": {"name": "stage_decisions", "arguments": json.dumps(
                        {"variables": {"x": {"index": ["a"], "domain": "binary"}}})}},
                    {"id": "r1", "type": "function", "function": {"name": "add_rule", "arguments": json.dumps(
                        {"sentence": "s1", "rule": {"id": "c1", "left": {"var": "x", "index": ["i"]}, "relation": "<=",
                                                    "right": {"const": 1}, "forall": [{"index": "i", "set": "a"}]}})}},
                    {"id": "r2", "type": "function", "function": {"name": "add_rule", "arguments": json.dumps(
                        {"drop": "c1"})}}]}]
    at_r1 = agent_draft.draft_from(messages, before="r1")
    assert at_r1["ir"]["variables"] == {"x": {"index": ["a"], "domain": "binary"}} and at_r1["ir"]["constraints"] == []
    assert at_r1["ir"]["sets"] == ["a"] and at_r1["ir"]["version"] == 2  # assembled: the sets derived
    at_r2 = agent_draft.draft_from(messages, before="r2")
    assert [c["id"] for c in at_r2["ir"]["constraints"]] == ["c1"] and at_r2["ir"]["constraints"][0]["note"] == "s1"
    after = agent_draft.draft_from(messages + [_call("p", "propose_plan", {"summary": "s"})], before="p")
    assert after["ir"]["constraints"] == []


def test_propose_with_no_spec_is_the_draft_assembled_from_the_stages():
    from app.agent import canon

    messages = [_call("d", "stage_data", {"entity_types": [{"name": "a"}], "entities": [{"type": "a", "key": "a1"}]}),
                _call("v", "stage_decisions", {"variables": {"x": {"index": ["a"], "domain": "binary"}}}),
                _call("r", "add_rule", {"sentence": "at most one", "rule": {
                    "id": "c1", "forall": [{"index": "i", "set": "a"}], "left": {"var": "x", "index": ["i"]},
                    "relation": "<=", "right": {"const": 1}}}),
                _call("g", "stage_goal", {"objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
                    "sum": {"var": "x", "index": ["i"]}, "over": [{"index": "i", "set": "a"}]}}]}}),
                _call("p", "propose_plan", {"summary": "the plan"})]
    spec, notes = canon.canonical({"summary": "the plan"}, messages=messages, call_id="p")
    assert spec["ir"]["sets"] == ["a"] and [c["id"] for c in spec["ir"]["constraints"]] == ["c1"]
    assert spec["ir"]["constraints"][0]["severity"] == "hard" and spec["ir"]["constraints"][0]["note"] == "at most one"
    assert spec["ir"]["objective"]["sense"] == "maximize" and spec["seed"]["entities"] == [{"type": "a", "key": "a1"}]
    assert any("assembled from the stages: 1 rule(s), 1 decision(s), the goal" in n for n in notes)


def test_the_assistant_runs_the_stages_as_tools(monkeypatch):
    """The four tools through the Assistant's dispatch, each reading the draft the calls before it left, with the
    call being executed named by its id (with the protocol on: LLM_BUILD_STAGES)."""
    from app.agent import core

    monkeypatch.setenv("LLM_BUILD_STAGES", "on")
    from app.api import agent as agent_api

    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": False, "status": 404, "body": {}},
                       core.Context("x", mode="model"))
    assert {"stage_data", "stage_decisions", "add_rule", "stage_goal"} <= agent.tool_names
    data = {"entity_types": [{"name": "a", "attributes": [{"name": "cost", "data_type": "number"}]}],
            "entities": [{"type": "a", "key": k, "attrs": {"cost": c}} for k, c in (("a1", 2), ("a2", 5))],
            "parameters": [{"name": "most", "index": [], "default_value": 1}]}
    agent.messages.append(_call("d", "stage_data", data))
    agent._call_id = "d"
    said = agent.run_tool("stage_data", data)
    assert said.startswith("Data staged:") and "- a: 2 record(s)" in said and "- most: 0 cell(s) (one number), default 1" in said
    decisions = {"variables": {"x": {"index": ["a"], "domain": "binary"}}, "parameters": {"most": {"index": []}}}
    agent.messages.append(_call("v", "stage_decisions", decisions))
    agent._call_id = "v"
    said = agent.run_tool("stage_decisions", decisions)
    assert said.startswith("Decisions staged:") and "- x: binary per a (2)" in said
    rule = {"sentence": "at most one chosen", "rule": {"id": "c_most", "left": {"sum": {"var": "x", "index": ["i"]},
            "over": [{"index": "i", "set": "a"}]}, "relation": "<=", "right": {"par": "most", "index": []}}}
    agent.messages.append(_call("r", "add_rule", rule))
    agent._call_id = "r"
    said = agent.run_tool("add_rule", rule)
    assert said.startswith('rule c_most holds "at most one chosen": c_most ranges over once; reads most')
    bad = {"sentence": "s", "rule": {"id": "c_bad", "left": {"var": "x", "index": []}, "relation": "<=", "right": {"const": 1}}}
    agent.messages.append(_call("b", "add_rule", bad))
    agent._call_id = "b"
    refusal = agent.run_tool("add_rule", bad)
    assert refusal.startswith("Not staged: ") and "write it as" in refusal
    agent.messages.append({"role": "tool", "tool_call_id": "b", "name": "add_rule", "content": refusal})
    goal = {"objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
        "sum": {"mul": [{"attr": {"of": "i", "name": "cost"}}, {"var": "x", "index": ["i"]}]}, "over": [{"index": "i", "set": "a"}]}}]}}
    agent.messages.append(_call("g", "stage_goal", goal))
    agent._call_id = "g"
    said = agent.run_tool("stage_goal", goal)
    assert said.startswith("Goal staged: maximize") and "reads cost" in said
    # The draft at propose: the refused rule never joined it.
    agent.messages.append(_call("p", "propose_plan", {"summary": "s"}))
    agent._call_id = "p"
    spec = agent._spec({"summary": "s"}, expand=False)
    assert [c["id"] for c in spec["ir"]["constraints"]] == ["c_most"]


def test_the_plan_proposed_after_the_stages_carries_the_last_stage():
    """The turn loop handles propose_plan itself: the draft must be every stage call before the plan, the last
    one included (14 Oct: the fold stopped at the last stage call executed and dropped the goal)."""
    from app.agent import canon

    goal = {"objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
        "sum": {"var": "x", "index": ["i"]}, "over": [{"index": "i", "set": "a"}]}}]}}
    messages = [_call("d", "stage_data", {"entity_types": [{"name": "a"}], "entities": [{"type": "a", "key": "a1"}]}),
                _call("v", "stage_decisions", {"variables": {"x": {"index": ["a"], "domain": "binary"}}}),
                _call("g", "stage_goal", goal), _call("p", "propose_plan", {"summary": "s"})]
    stale, _ = canon.canonical({"summary": "s"}, messages=messages, call_id="g")
    assert "objective" not in stale["ir"]  # what the stale id gave
    spec, _ = canon.canonical({"summary": "s"}, messages=messages, call_id="p")
    assert spec["ir"]["objective"]["sense"] == "maximize"


def test_a_goal_staged_after_a_construct_rule_is_checked_with_the_construct_expanded():
    """14 Oct: stage_goal after an only_if rule was refused, "only_if is not a key a constraint carries"."""
    draft = {"seed": {"entity_types": [{"name": "a"}], "entities": [{"type": "a", "key": k} for k in ("a1", "a2")]},
             "ir": {"variables": {"x": {"index": ["a"], "domain": "continuous", "lower": 0, "upper": 5},
                                  "y": {"index": ["a"], "domain": "binary"}},
                    "constraints": [{"id": "c_open", "only_if": {"for": [{"index": "i", "set": "a"}],
                                                                 "amount": {"var": "x", "index": ["i"]},
                                                                 "chosen": {"var": "y", "index": ["i"]}}}]}}
    said = stages.check_goal(draft, {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
        "sum": {"var": "x", "index": ["i"]}, "over": [{"index": "i", "set": "a"}]}}]})
    assert said.startswith("Goal staged: maximize")
    assert stages.check_decisions(draft).startswith("Decisions staged:")


def test_a_plan_built_in_stages_names_its_workspace_and_problem_beside_the_summary():
    from app.agent import canon

    messages = [_call("d", "stage_data", {"entity_types": [{"name": "a"}], "entities": [{"type": "a", "key": "a1"}]}),
                _call("v", "stage_decisions", {"variables": {"x": {"index": ["a"], "domain": "binary"}}}),
                _call("p", "propose_plan", {"summary": "s", "domain_name": "New one", "problem_name": "P"})]
    spec, _ = canon.canonical({"summary": "s", "domain_name": "New one", "problem_name": "P"}, messages=messages,
                              call_id="p", domain_id=7)
    assert spec["domain_name"] == "New one" and spec["problem_name"] == "P" and "domain_id" not in spec


def test_the_stages_find_what_the_final_proposal_would_refuse():
    """14 Oct, step 9's third start: 7 refusals at propose_plan for faults a stage could have found."""
    seed = {"entity_types": [{"name": "a"}], "entities": [{"type": "a", "key": "a1"}],
            "relationships": [{"type": "next", "from": ["a", "a1"], "to": ["a", "a1"]}],
            "parameter_values": [{"parameter": "rate", "entities": [["a", "a1"]], "value": 2}]}
    faults = stages.seed_faults(seed)
    assert any('link type "next" is used by 1 entry but not declared' in f for f in faults)
    assert any('"rate" has 1 value entry but is not declared' in f for f in faults)
    assert stages.seed_faults(seed, {"relationship_types": [{"name": "next"}], "data_values": [{"name": "rate"}]}) == []
    draft = {"seed": {"entity_types": [{"name": "a"}], "entities": [{"type": "a", "key": "a1"}],
                      "parameters": [{"name": "cost", "index": ["a"], "default_value": 0}]},
             "ir": {"variables": {"x": {"index": ["a"], "domain": "binary"}},
                    "parameters": {"cost": {"index": ["a"]}, "margin": {"index": ["a"]}}}}
    with pytest.raises(stages.StageRefused) as got:
        stages.check_decisions(draft)
    assert "parameter margin is declared for the model but the data stage does not hold it" in str(got.value)
    assert "parameter cost[a] has no values" in str(got.value)
    draft["seed"]["parameters"].append({"name": "margin", "index": ["a"], "default_value": 3})
    draft["seed"]["parameter_values_from_file"] = [{"file": "f.csv", "parameter": "cost"}]
    assert stages.check_decisions(draft).startswith("Decisions staged:")
    # Data no rule or goal reads is named at the goal stage, before the proposal refuses it.
    said = stages.check_goal(draft, {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {
        "sum": {"var": "x", "index": ["i"]}, "over": [{"index": "i", "set": "a"}]}}]})
    assert "BEFORE propose_plan, fix" in said and "parameter cost holds data but no rule or goal reads it" in said


def test_a_plan_proposed_again_after_a_build_is_a_revision_in_the_built_workspace():
    """14 Oct, step 9 run 2: a goal found wrong after the build was never rebuilt (the workspace name and the
    problem name were both taken, then the problem name was left out)."""
    first = {"summary": "s", "domain_name": "W", "problem_name": "Weekly plan"}
    messages = [_call("p1", "propose_plan", first),
                {"role": "tool", "name": "propose_plan", "tool_call_id": "p1", "content": 'BUILT {"domain_id": 9}'}]
    built = {"domain_id": 9, "problem_id": 4}
    again = {"domain_name": "W"}
    notes = stages.as_revision(again, messages, built)
    assert again == {"domain_id": 9, "problem_name": "Weekly plan (version 2)"} and "revises" in notes[0]
    again = {"domain_name": "W", "problem_name": "Weekly plan"}
    stages.as_revision(again, messages, built)
    assert again["problem_name"] == "Weekly plan (version 2)" and again["domain_id"] == 9
    # A new workspace the person asked for is left alone; so is a plan with no build before it.
    fresh = {"domain_name": "Another one", "problem_name": "P"}
    assert stages.as_revision(fresh, messages, built) == [] and fresh == {"domain_name": "Another one", "problem_name": "P"}
    plain = {"domain_name": "W"}
    assert stages.as_revision(plain, messages, None) == [] and plain == {"domain_name": "W"}


def test_a_revision_given_the_built_workspace_by_id_still_gets_the_next_version_name():
    messages = [_call("p1", "propose_plan", {"summary": "s", "domain_name": "W", "problem_name": "Weekly plan"}),
                {"role": "tool", "name": "propose_plan", "tool_call_id": "p1", "content": 'BUILT {"domain_id": 9}'}]
    again = {"domain_id": 9, "problem_name": "Weekly plan"}
    stages.as_revision(again, messages, {"domain_id": 9})
    assert again == {"domain_id": 9, "problem_name": "Weekly plan (version 2)"}
    other = {"domain_id": 12, "problem_name": "Weekly plan"}
    assert stages.as_revision(other, messages, {"domain_id": 9}) == [] and other["problem_name"] == "Weekly plan"


def test_the_protocol_is_a_setting_off_by_default(monkeypatch):
    """14 Oct: measured on this model the protocol did not raise the right answers; it is kept behind a setting."""
    from app.agent import core
    from app.api import agent as agent_api

    monkeypatch.delenv("LLM_BUILD_STAGES", raising=False)
    sheet = core.model_prompt(core.Context("x", mode="model"))
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": False}, core.Context("x", mode="model"))
    assert "PHASE 2 - PROPOSE" in sheet and "stage_data" not in sheet and "CONSTRUCTS:" not in sheet
    assert not {"stage_data", "add_rule"} & agent.tool_names
    monkeypatch.setenv("LLM_BUILD_STAGES", "on")
    sheet = core.model_prompt(core.Context("x", mode="model"))
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": False}, core.Context("x", mode="model"))
    assert "PHASE 2 - BUILD THE PLAN IN STAGES" in sheet and "CONSTRUCTS:" in sheet and '{"drop": "<id>"}' in sheet
    assert {"stage_data", "stage_decisions", "add_rule", "stage_goal"} <= agent.tool_names
