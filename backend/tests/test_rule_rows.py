"""The one-time rule-row review (17 Oct, next action after the hidden-accuracy mission): before a plan that builds
and solves is shown, the model gets one row of each rule written out on the data, and proposes again."""

from __future__ import annotations

from app.agent import core
from tests.test_agent import _chat, _spec
from tests.test_agent_kit import RawLLM, _block, raw  # noqa: F401
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _turns(tenants, llm_replies, raw):
    llm = raw(llm_replies)
    first = _chat(tenants["b"], mode="model", text="Pick city projects to fund.")
    second = _chat(tenants["b"], messages=first[-1]["messages"], mode="model", text="500k; two in district A at most.")
    return llm, second


def test_a_plan_that_solves_goes_back_once_with_its_rules_written_out(tenants, db, raw, monkeypatch):
    monkeypatch.setenv("LLM_RULE_ROWS", "1")
    spec = _spec("rows")
    call = _block("propose_plan", {"summary": "**Sets** project", "spec": spec})
    llm, second = _turns(tenants, [("text", "1. What is the budget? 2. Any limit per district?"),
                                   ("text", call), ("text", call)], raw)
    plan = next(e for e in second if e["type"] == "plan")
    assert plan["counts"]["entities"] == 4
    told = [m["content"] for m in llm.requests[-1]["messages"] if m["role"] == "tool"]
    review = next(t for t in told if "ONE row of each rule" in t)
    assert "The plan was NOT shown to the user yet" in review and "propose_plan again with the same spec" in review
    assert sum("ONE row of each rule" in t for t in told) == 1  # once a turn: the same plan again is shown


def test_with_the_setting_off_the_plan_is_shown_at_once(tenants, db, raw, monkeypatch):
    monkeypatch.setenv("LLM_RULE_ROWS", "0")
    call = _block("propose_plan", {"summary": "**Sets** project", "spec": _spec("rows-off")})
    llm, second = _turns(tenants, [("text", "1. What is the budget?"), ("text", call)], raw)
    assert any(e["type"] == "plan" for e in second)
    assert not any("ONE row of each rule" in str(m.get("content")) for m in llm.requests[-1]["messages"])


def test_the_rows_read_as_the_platform_wrote_them():
    said = core.rows_sent_back([{"rule": "c_dependency", "where": "c=CTL006, n=CTL004", "rows": 3,
                                 "row": "pick[CTL006] <= pick[CTL004]"}])
    assert "- c_dependency (c=CTL006, n=CTL004; 1 of 3): pick[CTL006] <= pick[CTL004]" in said
    assert core.rows_sent_back([]) == "" and core.rows_sent_back(None) == ""
