"""The reply cap (16 Oct mission, E2): a reply that runs away stops at 8,192 tokens, not 16,384.

Evidence (15 Oct log, content-free lines): 27 replies ran to the 16,384-token limit with no tool call, about 220 s
each, up to four in a row in one case; of 1,337 replies that finished, 7 wrote more than 8,192 tokens (p99 6,256)."""

from __future__ import annotations

import logging

from app.agent import core


def _agent(mode: str, **env) -> core.Agent:
    from app.api import agent as agent_api

    return core.Agent(core.Settings(**env), agent_api._index, lambda *a, **k: {"ok": False}, core.Context("x", mode=mode))


def test_the_reply_cap_bounds_every_kind_of_reply():
    big = dict(context=262144, max_tokens=16384, plan_max_tokens=32768)
    assert _agent("chat", reply_cap=8192, **big).reply_tokens == 8192
    assert _agent("model", reply_cap=8192, **big).reply_tokens == 8192


def test_a_smaller_setting_still_wins_and_zero_means_no_cap():
    assert _agent("chat", reply_cap=8192, context=262144, max_tokens=4096).reply_tokens == 4096
    assert _agent("chat", reply_cap=0, context=262144, max_tokens=16384).reply_tokens == 16384


def test_the_default_cap_is_8192(monkeypatch):
    monkeypatch.delenv("LLM_REPLY_CAP", raising=False)
    assert core.Settings().reply_cap == 8192


def test_a_cut_reply_is_logged_by_its_shape_never_its_words():
    loop = "Wait, let me reconsider the capacity of the depot.\n" * 300
    shape = core.cut_shape(loop)
    assert "depot" not in shape and "capacity" not in shape
    assert "top_repeat=300" in shape and "distinct=1" in shape
    assert core.cut_shape("").startswith("chars=0")


def test_the_cut_shape_line_is_written_for_a_reply_at_the_limit(monkeypatch, caplog):
    import io
    import json as _json

    body = {"choices": [{"message": {"content": "x\n" * 50}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8192}}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(core.urllib.request, "urlopen", lambda *a, **k: _Resp(_json.dumps(body).encode()))
    with caplog.at_level(logging.INFO, logger="solver.assistant"):
        core.llm_chat(core.Settings(tool_mode="text"), [{"role": "user", "content": "hi"}], False, [], 8192)
    assert any("assistant.cut_shape chars=100" in r.getMessage() for r in caplog.records)
