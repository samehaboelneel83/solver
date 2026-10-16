"""E4 (16 Oct mission): turns that ended early in exp2.

- Three different JSON slips, masked to one key, counted as "the same refusal three times" and ended h15's turn four
  times (right in both baseline runs). Only the same string sent again is the same refusal now.
- Of 52 replies stopped as loops, the same request again looped 25 times; the replies after a runaway are sampled
  at LLM_LOOP_TEMPERATURE (0.7)."""

from __future__ import annotations

import json

from app.agent import core
from tests.test_agent import _chat, _in_process_caller
from tests.test_agent_field_test import RAMBLE, _install, _roster_files, _roster_spec
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _broken(n: int) -> str:
    """A plan string with a key left unquoted, at a different place each time."""
    text = json.dumps(_roster_spec("slip"))
    at = [m for m in range(len(text)) if text.startswith('"', m) and text[m - 2:m] == ", "][n]
    end = text.index('"', at + 1)
    return text[:at] + text[at + 1:end] + text[end + 1:]


def test_different_json_slips_do_not_end_the_turn(tenants, monkeypatch):
    replies = [("native", "check_spec", json.dumps({"spec": _broken(n)})) for n in (3, 9, 15, 21)]
    _install(monkeypatch, replies + [("text", "Which shifts?")])
    events = _chat(tenants["b"], mode="model", text="check; night pays 1.3", files=_roster_files())
    answer = next(e for e in events if e["type"] == "answer")["text"]
    assert answer == "Which shifts?"
    assert sum(1 for e in events if e["type"] == "tool" and e["name"] == "check_spec") == 4


def test_the_same_broken_string_sent_again_still_ends_the_turn(tenants, monkeypatch):
    _install(monkeypatch, [("native", "check_spec", json.dumps({"spec": _broken(3)}))] * 5 + [("text", "never")])
    events = _chat(tenants["b"], mode="model", text="check; night pays 1.3", files=_roster_files())
    answer = next(e for e in events if e["type"] == "answer")["text"]
    assert answer.startswith("I could not write one part of the model") and "not valid JSON" in answer
    assert sum(1 for e in events if e["type"] == "tool" and e["name"] == "check_spec") == core.MAX_SAME_ERROR


class _Model:
    def __init__(self, replies):
        self.replies, self.temps = list(replies), []

    def __call__(self, settings, messages, native, tools=None, max_tokens=None):
        self.temps.append(settings.temperature)
        text, finish = self.replies.pop(0)
        return {"role": "assistant", "content": text, "_finish": finish}, True


def test_the_replies_after_a_runaway_are_sampled_hotter_then_back(tenants, monkeypatch):
    from app.api import agent as agent_api

    monkeypatch.setattr(agent_api, "make_caller", _in_process_caller)
    monkeypatch.setenv("LLM_TEMPERATURE", "0.2")
    monkeypatch.setenv("LLM_LOOP_TEMPERATURE", "0.7")
    model = _Model([(RAMBLE, "length"), (RAMBLE, "length"), ("Which warehouses must stay open?", "stop")])
    monkeypatch.setattr(core, "llm_chat", model)
    events = _chat(tenants["b"], text="choose my warehouses")
    assert [e["text"] for e in events if e["type"] == "answer"] == ["Which warehouses must stay open?"]
    assert model.temps == [0.2, 0.7, 0.7]


def test_loop_temperature_zero_keeps_the_temperature(tenants, monkeypatch):
    from app.api import agent as agent_api

    monkeypatch.setattr(agent_api, "make_caller", _in_process_caller)
    monkeypatch.setenv("LLM_TEMPERATURE", "0.2")
    monkeypatch.setenv("LLM_LOOP_TEMPERATURE", "0")
    model = _Model([(RAMBLE, "length"), ("Which warehouses?", "stop")])
    monkeypatch.setattr(core, "llm_chat", model)
    _chat(tenants["b"], text="choose my warehouses")
    assert model.temps == [0.2, 0.2]
