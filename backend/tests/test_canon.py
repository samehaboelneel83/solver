"""The canonical form (app/agent/canon.py; build-protocol plan, Phase 1.2): the fixed point on the gold corpus,
and the shape of the pass. Each rule's own behaviour is tested where its incident was (test_agent_blend,
test_agent_field_test, test_files_load); here is what holds of the pass as a whole.

The hidden golds (bench/hidden/gold, when captured) go through the fixed-point test too: the messages name the
case id only, never the model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent import canon

BENCH = Path(__file__).resolve().parents[1] / "bench"
GOLD_DIRS = (BENCH / "phase1" / "gold", BENCH / "hidden" / "gold")


def _golds() -> list[Path]:
    return sorted(p for d in GOLD_DIRS if d.is_dir() for p in d.glob("*.json"))


@pytest.mark.parametrize("path", _golds(), ids=lambda p: p.stem)
def test_a_gold_model_is_a_fixed_point(path: Path):
    """canonical(gold) == gold: a model that reached its reference is already in the canonical form, so the
    pass changes nothing and says nothing. A rule that fails this changed a gold model's meaning."""
    gold = json.loads(path.read_text(encoding="utf-8"))
    spec, notes = canon.canonical({"spec": {"ir": gold["ir"], "seed": {}}})
    assert spec["ir"] == gold["ir"], f"{path.stem}: canonical() changed the gold model"
    assert notes == [], f"{path.stem}: canonical() had {len(notes)} note(s) on the gold model"


def test_the_golds_are_there():
    assert len(_golds()) >= 8


def test_every_rule_is_named_and_documented():
    """Each rule of the pass is a small named function whose docstring says what it rewrites and the incident
    it came from (docs/plans/canonical-form.md)."""
    names = [r.__name__ for r in canon.RULES]
    assert len(names) == len(set(names)) and not any(n.startswith("_") for n in names)
    for rule in canon.RULES:
        assert rule.__doc__ and len(rule.__doc__.strip()) > 60, rule.__name__


def test_the_pass_reaches_a_fixed_point_in_one_step():
    """A spec written every wrong way at once: one pass puts it right and says so; a second pass on the result
    changes nothing (each rewrite lands in the canonical form, not in another spelling)."""
    args = {"spec": {
        "seed": {"parameters": [{"name": "rate", "default_value": 2}]},
        "ir": {"version": 2,
               "variables": {"x": {"domain": "integer", "upper": None}},
               "constraints": [{"id": "c", "forall": [],
                                "left": {"sub": [{"var": "x", "index": ["a"]}, 3]}, "relation": "<=", "right": 1}],
               "objective": {"sense": "minimize",
                             "terms": [{"id": "o", "weight": 1, "note": "the goal",
                                        "expression": {"mul": [{"par": "rate", "index": ["a"]}, {"var": "x"}, 2]}}]}}}}
    once, notes = canon.canonical(args)
    assert notes and once["ir"]["sets"] == [] and once["ir"]["variables"]["x"]["index"] == []
    rule = once["ir"]["constraints"][0]
    assert "forall" not in rule and rule["severity"] == "hard" and rule["right"] == {"const": 1}
    assert rule["left"] == {"add": [{"var": "x", "index": []}, {"mul": [{"const": -1}, {"const": 3}]}]}
    term = once["ir"]["objective"]["terms"][0]
    assert "note" not in term and term["expression"]["mul"][0] == {"par": "rate", "index": []}
    twice, again = canon.canonical({"spec": json.loads(json.dumps(once))})
    assert twice == once and again == []


def test_the_notes_said_before_a_refusal_stay_in_the_callers_list():
    """The Assistant reads the notes beside a refusal: what the pass said before it refused is kept."""
    said = ["earlier"]
    with pytest.raises(canon.FileRefused, match="has no \"ir\""):
        canon.canonical({"seed": {"entities": []}}, notes=said)
    assert said[0] == "earlier" and any("taken as the spec" in n for n in said[1:])


def test_a_partial_plan_is_completed_from_the_draft():
    """The draft merge is a step of the pass: a patch with only rules is completed from the last plan proposed."""
    whole = {"seed": {"entities": []},
             "ir": {"version": 2, "sets": [], "variables": {"x": {"index": [], "domain": "integer"}},
                    "constraints": [], "objective": {"sense": "minimize", "terms": []}}}
    patch = {"spec": {"ir": {"constraints": [{"id": "c", "left": {"var": "x", "index": []}, "relation": ">=",
                                              "right": {"const": 1}, "severity": "hard"}]}}}

    def call(args: dict) -> dict:
        return {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function", "function": {
            "name": "propose_plan", "arguments": json.dumps(args)}}]}

    # The conversation as the Assistant holds it when the patch is checked: the patch's own call is the last.
    messages = [call({"spec": whole}), {"role": "tool", "name": "propose_plan", "content": "Not valid yet"}, call(patch)]
    spec, notes = canon.canonical(patch, messages=messages)
    assert spec["ir"]["variables"] == whole["ir"]["variables"] and len(spec["ir"]["constraints"]) == 1
    assert any("completed from your last one" in n for n in notes)
