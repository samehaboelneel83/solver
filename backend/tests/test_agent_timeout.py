"""The assistant reports model timeouts as an actionable service failure."""

from dataclasses import replace
from urllib.error import URLError

import pytest

from app.agent import core
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("timed out"), URLError(TimeoutError("timed out"))],
)
def test_llm_timeout_has_service_and_retry_guidance(monkeypatch, failure):
    settings = replace(core.Settings(), base_url="http://model.local/v1", timeout=12)

    def timeout(_request, timeout):
        assert timeout == 12
        raise failure

    monkeypatch.setattr(core.urllib.request, "urlopen", timeout)
    with pytest.raises(core.LlmError, match="model.local.*12 seconds.*healthy"):
        core.llm_chat(settings, [{"role": "user", "content": "test"}], native=False)


def test_a_reply_past_the_reply_cap_is_slow_not_down(monkeypatch):
    """Job-shop retest (October 2026): replies of 3-12 minutes on a 30-minute wait. One reply is now cut at
    LLM_REPLY_SECONDS and reported as too slow, so the turn can ask again for a shorter one."""
    settings = replace(core.Settings(), base_url="http://model.local/v1", timeout=1800, reply_seconds=300)
    seen = []

    def slow(_request, timeout):
        seen.append(timeout)
        raise TimeoutError("timed out")

    monkeypatch.setattr(core.urllib.request, "urlopen", slow)
    with pytest.raises(core.ReplyTooSlow, match="300 seconds"):
        core.llm_chat(settings, [{"role": "user", "content": "test"}], native=False)
    assert seen == [300]


def test_a_slow_reply_is_asked_again_shorter_then_ends_honestly(tenants, monkeypatch):
    from tests.test_agent import _chat

    calls = []

    def llm(settings, wire, native, tools=None, max_tokens=None):
        calls.append(max_tokens)
        if len(calls) == 1:
            raise core.ReplyTooSlow(420)
        return {"role": "assistant", "content": "Here is a short answer.", "_finish": "stop"}, True

    monkeypatch.setattr(core, "llm_chat", llm)
    events = _chat(tenants["b"], mode="model", text="how many requests?")
    assert any(e["type"] == "note" and "shorter" in e["text"] for e in events)
    assert next(e for e in events if e["type"] == "answer")["text"] == "Here is a short answer."
    assert calls[1] <= calls[0] // 2 + 1

    calls.clear()
    monkeypatch.setattr(core, "llm_chat", lambda *a, **k: (_ for _ in ()).throw(core.ReplyTooSlow(420)))
    events = _chat(tenants["b"], mode="model", text="and again?")
    answer = next(e for e in events if e["type"] == "answer")["text"]
    assert "took too long" in answer and not any(e["type"] == "error" for e in events)
