"""A reply that repeats itself is stopped as it streams (16 Oct mission, E3).

Evidence (exp1 hidden run, first ten cases): all 27 replies cut at the 8,192-token limit had no tool call and were
the same lines over and over (11 to 121 distinct of 164 to 334 lines; the last 200 characters seen 11 to 46 times),
about 107 s each, ten in one case."""

from __future__ import annotations

import io
import json
from pathlib import Path

from app.agent import core

GOLD = sorted((Path(__file__).resolve().parents[1] / "bench" / "phase1" / "gold").glob("*.json"))


class _Stream(io.BytesIO):
    headers = {"Content-Type": "text/event-stream"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _sse(chunks: list[dict]) -> bytes:
    return b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"


def _text_chunks(text: str, finish: str = "stop", size: int = 40) -> list[dict]:
    out = [{"choices": [{"delta": {"content": text[i:i + size]}, "finish_reason": None}]}
           for i in range(0, len(text), size)]
    out.append({"choices": [{"delta": {}, "finish_reason": finish}]})
    out.append({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": len(text) // 4}})
    return out


def _call(monkeypatch, body: bytes, **settings):
    sent = {}

    def urlopen(req, timeout=None):
        sent["payload"] = json.loads(req.data)
        return _Stream(body)

    monkeypatch.setattr(core.urllib.request, "urlopen", urlopen)
    msg, _ = core.llm_chat(core.Settings(tool_mode="text", **settings), [{"role": "user", "content": "hi"}], False, [],
                           8192)
    return msg, sent["payload"]


def test_a_reply_going_in_circles_is_stopped_early_and_comes_back_cut(monkeypatch):
    lap = ("Wait, the capacity rule must hold for every depot and every day, so let me write it again "
           "carefully with the right index over the depots.\n") * 400
    msg, payload = _call(monkeypatch, _sse(_text_chunks(lap, finish="length")))
    assert payload["stream"] is True
    assert msg["_finish"] == "length" and not msg.get("tool_calls")
    assert len(msg["content"]) < 8000  # stopped soon after the fourth lap, not at the end (~50,000)


def test_a_long_reply_that_does_not_repeat_is_not_stopped(monkeypatch):
    text = "".join(f"Row {i}: warehouse W{i:03d} ships {i * 7 % 113} tons to customer C{i * 13 % 97:03d}.\n"
                   for i in range(800))
    msg, _ = _call(monkeypatch, _sse(_text_chunks(text)))
    assert msg["content"] == text and msg["_finish"] == "stop"


def test_no_gold_model_written_as_text_reads_as_a_loop():
    """A plan written into the reply (pretty-printed JSON repeats short lines a lot) is never taken for a loop."""
    for path in GOLD:
        spec = json.dumps(json.loads(path.read_text(encoding="utf-8"))["ir"], indent=2)
        text = "Here is the spec:\n```json\n" + spec + "\n```\n"
        for end in range(core.LOOP_FROM, len(text), 1000):
            assert not core.in_a_loop(text[:end]), path.stem


def test_a_streamed_tool_call_is_joined_from_its_pieces(monkeypatch):
    args = json.dumps({"summary": "s", "spec": {"seed": {}, "ir": {"version": 2}}})
    chunks = [{"choices": [{"delta": {"content": "Proposing."}, "finish_reason": None}]},
              {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                                     "function": {"name": "propose_plan", "arguments": ""}}]},
                            "finish_reason": None}]}]
    chunks += [{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": args[i:i + 7]}}]},
                             "finish_reason": None}]} for i in range(0, len(args), 7)]
    chunks += [{"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
               {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 30}}]
    msg, _ = _call(monkeypatch, _sse(chunks))
    assert msg["content"] == "Proposing." and msg["_finish"] == "tool_calls"
    assert msg["tool_calls"][0]["id"] == "call_1" and msg["tool_calls"][0]["function"]["name"] == "propose_plan"
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == json.loads(args)


def test_with_the_setting_off_nothing_is_streamed(monkeypatch):
    body = json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}).encode()
    sent = {}

    def urlopen(req, timeout=None):
        sent["payload"] = json.loads(req.data)
        return _Stream(body)

    monkeypatch.setattr(core.urllib.request, "urlopen", urlopen)
    msg, _ = core.llm_chat(core.Settings(tool_mode="text", stream_loops=False), [{"role": "user", "content": "hi"}],
                           False, [], 100)
    assert "stream" not in sent["payload"] and msg["content"] == "ok"
