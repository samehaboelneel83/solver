"""Summarizing a long Assistant conversation (app.agent.compact) instead of dropping its oldest part."""

from __future__ import annotations

import json
from dataclasses import replace

from app.agent import compact, core
from app.api import agent as agent_api


def _conversation(turns: int = 12, result_chars: int = 3000) -> list[dict]:
    msgs = [{"role": "user", "content": "Maximise beds of 1.5 x 0.5 m in the camps; corridors 0.35 m."}]
    for i in range(turns):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": "run_python", "arguments": json.dumps({"code": "x" * 500})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": "run_python",
                     "content": f"usable area {2071 + i}.8 m2 " + "r" * result_chars})
        msgs.append({"role": "user", "content": f"step {i}: keep going with grid 0.25"})
    return msgs


def _fake(calls):
    def summarize(piece, so_far):
        calls.append((len(piece), so_far))
        return (so_far + " | " if so_far else "") + f"notes on {piece.count('RESULT of')} results"
    return summarize


def test_the_older_part_becomes_one_summary_and_the_recent_part_stays_word_for_word():
    msgs = _conversation()
    tail_before = msgs[-5:]
    calls = []
    done = compact.compact(msgs, summarize=_fake(calls), keep_chars=8000, piece_chars=10**6, numbers=core._numbers_from)
    assert done and done["chars_after"] < done["chars_before"] / 2
    assert compact.is_summary(msgs[0])
    assert msgs[-5:] == tail_before  # the recent messages, untouched
    text = msgs[0]["content"]
    # The brief, word for word, and the numbers on record carried by code.
    assert "Maximise beds of 1.5 x 0.5 m in the camps; corridors 0.35 m." in text
    assert 2071.8 in compact.recorded_numbers(msgs[0]) and 0.35 in compact.recorded_numbers(msgs[0])
    # Never a tool result without its call at the start of what is kept.
    assert msgs[1]["role"] != "tool" and (msgs[1]["role"] == "assistant" or msgs[1]["content"] == compact.ACK or True)
    roles = [m["role"] for m in msgs]
    assert all(not (a == "user" and b == "user") for a, b in zip(roles, roles[1:]))


def test_a_transcript_longer_than_the_context_is_summarized_in_pieces_and_rolls_forward():
    msgs = _conversation(turns=20)
    calls = []
    compact.compact(msgs, summarize=_fake(calls), keep_chars=6000, piece_chars=12000, numbers=core._numbers_from)
    assert len(calls) > 2 and calls[0][1] == "" and calls[1][1]  # each piece folds into the notes so far
    first = msgs[0]["content"]
    # A second compaction folds the first summary in, keeps the brief and the numbers.
    msgs += _conversation(turns=10)[1:]
    calls2 = []
    compact.compact(msgs, summarize=_fake(calls2), keep_chars=6000, piece_chars=10**6, numbers=core._numbers_from)
    assert calls2[0][1] and "notes on" in calls2[0][1]
    assert "Maximise beds of 1.5 x 0.5 m" in msgs[0]["content"]
    assert compact.recorded_numbers(msgs[0]) >= {2071.8, 0.25}
    assert first != msgs[0]["content"]


def test_the_build_is_carried_so_solving_stays_allowed():
    msgs = _conversation(turns=6)
    msgs.insert(3, {"role": "assistant", "content": "", "tool_calls": [{"id": "p", "type": "function",
                    "function": {"name": "propose_plan", "arguments": "{}"}}]})
    msgs.insert(4, {"role": "tool", "tool_call_id": "p", "name": "propose_plan",
                    "content": 'BUILT {"domain_id": 2, "scenario_id": 9} Now explain what was built.'})
    compact.compact(msgs, summarize=_fake([]), keep_chars=3000, piece_chars=10**6, numbers=core._numbers_from)
    assert compact.recorded_build(msgs[0]) == {"domain_id": 2, "scenario_id": 9}


def test_too_short_a_conversation_is_left_alone():
    msgs = _conversation(turns=1, result_chars=10)
    assert compact.compact(msgs, summarize=_fake([]), keep_chars=10**6, piece_chars=10**6, numbers=core._numbers_from) is None


def _agent(monkeypatch, context=16000, summary="## Problem\nbeds"):
    seen = {"summaries": 0, "prompts": []}

    def llm(settings, messages, native, tools=None, max_tokens=None):
        if messages[0]["role"] == "system" and messages[0]["content"].startswith("You compress"):
            seen["summaries"] += 1
            assert settings.thinking == "off" and tools is None
            return {"role": "assistant", "content": summary, "_finish": "stop"}, False
        seen["prompts"].append(sum(len(json.dumps(m)) for m in messages))
        return {"role": "assistant", "content": "Done.", "_finish": "stop"}, True

    monkeypatch.setattr(core, "llm_chat", llm)
    monkeypatch.setattr(core, "server_context", lambda s: context)
    from app.main import app

    index = agent_api._index or core.ApiIndex(app.openapi())
    agent = core.Agent(replace(core.Settings(), context=context), index, lambda *a, **k: {},
                       core.Context("x"))
    return agent, seen


def test_a_long_conversation_is_summarized_before_the_model_is_asked(monkeypatch):
    agent, seen = _agent(monkeypatch)
    msgs = _conversation(turns=12)
    events = list(agent.run(msgs))
    assert seen["summaries"] >= 1, [e for e in events if e["type"] != "state"]
    note = next(e for e in events if e["type"] == "note")
    assert "summarized the earlier part" in note["text"]
    state = events[-1]["messages"]
    assert compact.is_summary(state[0]) and "## Problem\nbeds" in state[0]["content"]
    # The browser keeps the short version: the next turn sends it.
    assert compact.size(state) < compact.size(_conversation(turns=12)) / 2


def test_slash_compact_summarizes_now_and_shows_the_summary(monkeypatch):
    agent, seen = _agent(monkeypatch, context=262144, summary="## Problem\nbeds\n## Open\nthe grid")
    msgs = _conversation(turns=6) + [{"role": "user", "content": "/compact"}]
    events = list(agent.run(msgs))
    answer = next(e for e in events if e["type"] == "answer")["text"]
    assert "I summarized our conversation" in answer and "## Open\nthe grid" in answer
    state = events[-1]["messages"]
    assert compact.is_summary(state[0]) and not any(m.get("content") == "/compact" for m in state)
    assert seen["prompts"] == []  # no model turn: only the summary


def test_numbers_on_record_count_for_the_data_values_check(monkeypatch):
    agent, _ = _agent(monkeypatch)
    msgs = _conversation(turns=12)
    compact.compact(msgs, summarize=_fake([]), keep_chars=3000, piece_chars=10**6, numbers=core._numbers_from)
    agent.messages = msgs
    assert 2071.8 in agent._known_numbers()


def test_a_failed_summary_leaves_the_history_to_fit(monkeypatch):
    agent, _ = _agent(monkeypatch)

    def broken(piece, so_far):
        raise core.LlmError(500, "down")

    monkeypatch.setattr(agent, "_summarize", broken)
    msgs = _conversation(turns=12)
    assert agent._maybe_compact({"role": "system", "content": "s"}, msgs) is None
    assert not compact.is_summary(msgs[0])


def test_the_summary_marker_is_a_platform_message():
    assert compact.SUMMARY_MARK.startswith(core.PLATFORM)


def test_slash_reset_clears_the_conversation_on_the_server_too(monkeypatch):
    agent, seen = _agent(monkeypatch)
    msgs = _conversation(turns=3) + [{"role": "user", "content": "/reset"}]
    events = list(agent.run(msgs))
    assert next(e for e in events if e["type"] == "answer")["text"].startswith("Started a new conversation")
    assert events[-1]["messages"] == [] and seen["prompts"] == []


def test_sizes_follow_the_server_context(monkeypatch):
    big, _ = _agent(monkeypatch, context=262144)
    assert big.s.result_chars == 262144 // 2  # kept whole on disk; the conversation gets a preview
    small, _ = _agent(monkeypatch, context=32768)
    assert small.s.result_chars == 32768 // 2
    many = replace(core.Settings(), max_tokens=16384, plan_max_tokens=32768)
    monkeypatch.setattr(core, "server_context", lambda s: 32768)
    from app.main import app
    a = core.Agent(many, core.ApiIndex(app.openapi()), lambda *a, **k: {}, core.Context("x", mode="model"))
    assert a.reply_tokens == 8192  # a quarter of 32k, not the configured 32k
    monkeypatch.setattr(core, "server_context", lambda s: 262144)
    b = core.Agent(many, core.ApiIndex(app.openapi()), lambda *a, **k: {}, core.Context("x", mode="model"))
    assert b.reply_tokens == 32768


def test_a_long_result_is_previewed_and_read_in_parts(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_SANDBOX_ROOT", str(tmp_path))
    agent, _ = _agent(monkeypatch)
    agent.ctx.user_id, agent.ctx.conversation_id = "u1", "conv1"
    big = "".join(f"row {i}: cell_{i} -> door_{i % 7}\n" for i in range(5000))
    shown = agent._preview(big)
    assert len(shown) < core.PREVIEW_CHARS + 300 and "output 1:" in shown and big[:200] in shown and big[-100:] in shown
    part = agent.run_tool("read_output", {"output": 1, "find": "row 2500:"})
    assert part.startswith("row 2500:") and "characters more" in part
    assert agent.run_tool("read_output", {"output": 9}).startswith("No such output")
    assert agent._preview("short") == "short"


def test_thinking_is_used_where_it_pays():
    tool = lambda name, content: {"role": "tool", "name": name, "content": content}  # noqa: E731
    assert core.thinking_for([{"role": "user", "content": "beds please"}]) == "on"
    assert core.thinking_for([{"role": "assistant", "tool_calls": []}, tool("run_python", '{"exit_code": 0, "stdout": "ok"}')]) == "off"
    assert core.thinking_for([tool("run_python", '{"exit_code": 1, "stderr": "boom"}')]) == "on"
    assert core.thinking_for([tool("check_spec", "SPEC_OK")]) == "on"
    assert core.thinking_for([tool("call_api", '{"ok": false, "status": 422}')]) == "on"


def test_the_working_window_triggers_a_summary_long_before_the_context_is_full(monkeypatch):
    agent, seen = _agent(monkeypatch, context=262144)
    agent.s = replace(agent.s, working_tokens=6000)
    msgs = _conversation(turns=12)
    note = agent._maybe_compact({"role": "system", "content": "s"}, msgs)
    assert note and compact.is_summary(msgs[0]) and seen["summaries"] >= 1
