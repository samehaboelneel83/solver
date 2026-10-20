"""R2 (20 Oct): one row of each rule written out on the data, beside check_spec's result and in the send-backs a
plan already gets -- never a gate of its own (R1, a gate, cost the hidden set 4 to 5 right answers)."""

from __future__ import annotations

import json

from app.agent import core
from tests.test_agent import _chat, _spec
from tests.test_agent_field_test import _install, _roster_files, _roster_spec
from tests.test_agent_kit import RawLLM, _block, raw  # noqa: F401
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _check(tenants, monkeypatch, on: str):
    monkeypatch.setenv("LLM_RULE_ROWS", on)
    model = _install(monkeypatch, [("native", "check_spec", json.dumps({"spec": _roster_spec("rows")})),
                                   ("text", "It checks out.")])
    _chat(tenants["b"], mode="model", text="check it; night pays 1.3", files=_roster_files())
    return [str(m["content"]) for m in model.requests[-1]["messages"] if m["role"] == "tool"]


def test_check_spec_shows_one_row_of_each_rule(tenants, monkeypatch):
    told = _check(tenants, monkeypatch, "1")
    said = next(t for t in told if t.startswith("SPEC_OK"))
    assert "ONE ROW OF EACH RULE" in said
    rows = said.split("ONE ROW OF EACH RULE", 1)[1]
    assert rows.count("\n- ") >= 1 and ("<=" in rows or ">=" in rows or " = " in rows)


def test_with_the_setting_off_check_spec_is_as_before(tenants, monkeypatch):
    told = _check(tenants, monkeypatch, "0")
    assert any(t.startswith("SPEC_OK") for t in told)
    assert not any("ONE ROW OF EACH RULE" in t for t in told)


def test_a_plan_that_solves_is_shown_at_once(tenants, db, raw, monkeypatch):
    monkeypatch.setenv("LLM_RULE_ROWS", "1")
    call = _block("propose_plan", {"summary": "**Sets** project", "spec": _spec("rows-quiet")})
    raw([("text", "1. What is the budget?"), ("text", call)])
    first = _chat(tenants["b"], mode="model", text="Pick city projects to fund.")
    second = _chat(tenants["b"], messages=first[-1]["messages"], mode="model", text="500k; two in district A at most.")
    assert any(e["type"] == "plan" for e in second)


def test_rows_listed_reads_as_the_platform_wrote_them():
    said = core.rows_listed([{"rule": "c_dependency", "where": "c=CTL006, n=CTL004", "rows": 3,
                              "row": "pick[CTL006] <= pick[CTL004]"}])
    assert "- c_dependency (c=CTL006, n=CTL004; 1 of 3): pick[CTL006] <= pick[CTL004]" in said
    assert core.rows_listed([]) == "" and core.rows_listed(None) == ""
