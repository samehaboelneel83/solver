"""A plan sent as a JSON string that does not parse (the 16 Oct mission, Phase E: the "plan has no ir" refusals).

Evidence (hidden run of 15 Oct, content-free log lines): about 40 proposals were refused "the spec has no ir"
because the model -- with native tool calls -- sent `spec` as a JSON string of 4,000-10,000 characters that did
not parse (15 "Expecting ',' delimiter", 7 "Expecting property name", 2 "Extra data"), and the model, told the plan
had no model, sent the same broken string again (one case: the same 5,163 characters four times). The practice
runs show the slips: a closer of the wrong kind ("set": "zone"]] where }] was meant), a doubled closer, a rule
closed early ("relation": "<="}, "right": ...).

These tests build the slips into the gold practice models (a model that reached its reference) and require:
the mender restores exactly the model; a string it cannot restore is refused with the JSON error and where it
is -- never "has no ir", and never taken as a plan; and every other path is as it was.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent import repair, toolcall
from app.agent.files import FileRefused

GOLD = sorted((Path(__file__).resolve().parents[1] / "bench" / "phase1" / "gold").glob("*.json"))


def _spec(path: Path) -> dict:
    gold = json.loads(path.read_text(encoding="utf-8"))
    return {"domain_name": "W", "problem_name": "P", "seed": {}, "ir": gold["ir"]}


def _closer_positions(text: str) -> list[int]:
    out, in_str, esc = [], False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "}]":
            out.append(i)
    return out


def _slips(text: str):
    """The slips of the evidence, each at a few places in the text: a closer of the wrong kind, a closer doubled,
    a closer dropped."""
    pos = _closer_positions(text)
    for i in pos[len(pos) // 3:: max(1, len(pos) // 6)][:5]:
        other = "]" if text[i] == "}" else "}"
        yield "wrong kind", text[:i] + other + text[i + 1:]
        yield "doubled", text[:i] + text[i] + text[i:]
        yield "dropped", text[:i] + text[i + 1:]


@pytest.mark.parametrize("path", GOLD, ids=lambda p: p.stem)
def test_the_mender_restores_or_lets_the_contract_refuse_every_slip_of_the_evidence(path):
    """A closer of the wrong kind (the commonest slip) is restored exactly; a doubled or dropped closer can often be
    put back in more than one place, so the mender may make a different model -- which the contract must then
    refuse: no slip ever turns into a different model that passes as a plan."""
    from app.ir.validate import check_shape

    original = json.dumps(_spec(path))
    gold_ir = json.loads(original)["ir"]
    for kind, broken in _slips(original):
        try:
            json.loads(broken)
            continue  # a slip that leaves valid JSON is not this defect
        except json.JSONDecodeError:
            pass
        fixed = toolcall.fix_spec(broken)
        if kind == "wrong kind":
            assert fixed is not None and json.loads(fixed) == json.loads(original), f"{path.stem}: {kind}"
        if fixed is None or json.loads(fixed) == json.loads(original):
            continue
        ir = json.loads(fixed).get("ir")
        assert not isinstance(ir, dict) or ir == gold_ir or check_shape(ir) is not None,             f"{path.stem}: a {kind} slip was mended into a different model the contract accepts"


def test_a_plan_string_that_cannot_be_read_is_refused_with_the_json_error_and_where_it_is():
    broken = '{"seed": {}, ir: {"version": 2, "sets": ["a"], "variables": {}}}'  # a key left unquoted
    with pytest.raises(FileRefused) as got:
        repair.spec_of({"summary": "s", "spec": broken}, strict=True)
    said = str(got.value)
    assert "not valid JSON" in said and "character" in said and "<<HERE>> ir:" in said
    assert 'has no "ir"' not in said


def test_the_fold_of_earlier_calls_never_raises_on_a_broken_string():
    broken = '{"seed": {}, ir: {"version": 2}}'
    spec, _ = repair.spec_of({"summary": "s", "spec": broken})
    assert spec == {}


def test_other_paths_are_as_they_were():
    good = {"seed": {}, "ir": {"version": 2, "sets": []}}
    assert repair.spec_of({"summary": "s", "spec": good}, strict=True)[0]["ir"] == good["ir"]
    assert repair.spec_of({"summary": "s", "spec": json.dumps(good)}, strict=True)[0]["ir"] == good["ir"]
    # A placeholder copied from the history is no plan, as before (not a JSON error).
    assert repair.spec_of({"summary": "s", "spec": "(superseded by a later attempt)"}, strict=True)[0] == {}
    # A dict with no ir stays a plan with no model (refused later as "has no ir", which it is).
    assert "ir" not in repair.spec_of({"summary": "s", "spec": {"seed": {}}}, strict=True)[0]
    # A string that is mended is read, and the note says so.
    slip = json.dumps(good)[:-1] + "}}"  # one closer doubled at the end
    spec, notes = repair.spec_of({"summary": "s", "spec": slip}, strict=True)
    assert spec["ir"] == good["ir"] and any("JSON slips" in n for n in notes)


def test_a_mended_string_that_is_still_not_a_valid_model_is_refused_by_the_contract_not_passed():
    """The mender only makes JSON; what it makes is checked like any plan (a broken structure stays refused)."""
    from app.ir.validate import check_shape

    odd = {"version": 2, "sets": ["a"], "variables": {"x": {"index": ["a"], "domain": "binary"}},
           "constraints": [{"id": "c", "left": {"var": "x", "index": ["i"]}, "relation": "<=", "right": {"const": 1}}],
           "objective": {"sense": "minimize", "terms": []}}
    assert check_shape(odd) is not None  # the index i is bound by nothing: refused, mended or not


def test_the_assistant_refuses_an_unparseable_plan_string_by_its_json_error():
    """The Assistant's own plan path: a propose_plan whose spec is a broken string goes back with the JSON fault
    (the model can fix it), and a plan dict with no ir still goes back as having no model."""
    from app.agent import core
    from app.api import agent as agent_api

    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {"ok": False}, core.Context("x", mode="model"))
    agent._user_turns = lambda: 9
    said = agent._check_plan_whole({"summary": "s", "spec": '{"seed": {}, ir: {"version": 2}}'})
    assert "not valid JSON" in said and 'has no "ir"' not in said
    said = agent._check_plan_whole({"summary": "s", "spec": {"seed": {}}})
    assert 'has no "ir"' in said
