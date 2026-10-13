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
    assert at_r1["ir"]["variables"] == {"x": {"index": ["a"], "domain": "binary"}} and "constraints" not in at_r1["ir"]
    at_r2 = agent_draft.draft_from(messages, before="r2")
    assert [c["id"] for c in at_r2["ir"]["constraints"]] == ["c1"] and at_r2["ir"]["constraints"][0]["note"] == "s1"
    after = agent_draft.draft_from(messages + [_call("p", "propose_plan", {"summary": "s"})], before="p")
    assert after["ir"]["constraints"] == []
