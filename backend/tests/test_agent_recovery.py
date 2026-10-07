import json
from app.agent import core


def agent(caller):
    return core.Agent(core.Settings(enabled=False), core.ApiIndex({"paths": {
        "/api/domain/": {"post": {}}, "/api/v1/entity-types": {"post": {}}
    }}), caller, core.Context(username="test", mode="assistant"))


def test_dispatch_uses_documented_slash_convention():
    calls = []
    a = agent(lambda *args: calls.append(args) or {"ok": True, "status": 201, "body": {"id": 1}})
    a.run_tool("call_api", {"method": "POST", "path": "/api/domain/", "body": {"name": "QA"}})
    a.run_tool("call_api", {"method": "POST", "path": "/api/v1/entity-types/", "body": {}})
    assert [c[1] for c in calls] == ["/api/domain/", "/api/v1/entity-types"]


def test_stop_prevents_new_calls():
    calls = []
    a = agent(lambda *args: calls.append(args))
    a.cancelled.set()
    assert a.run_tool("call_api", {"method": "POST", "path": "/api/domain/"}).startswith("Refused")
    assert calls == []


def test_compaction_keeps_discussion_turns():
    from app.agent import compact
    messages = [
        {"role": "user", "content": "Choose projects"},
        {"role": "assistant", "content": "Budget?"},
        {"role": "user", "content": "Seven"},
        {"role": "assistant", "content": "Understood"},
        {"role": "user", "content": "Proceed"},
    ]
    compact.compact(messages, summarize=lambda *a: "Budget agreed", keep_chars=1,
                    piece_chars=10000, numbers=lambda m: set(), force=True)
    a = agent(lambda *args: {})
    a.messages = messages
    assert a._user_turns() == 3


def test_redirect_loop_stops_even_with_discovery_between_failures():
    a = agent(lambda *args: {})
    call = {"id": "test", "function": {"name": "call_api", "arguments": json.dumps({"method": "POST", "path": "/api/domain/"})}}
    messages = [{"role": "tool", "tool_call_id": "test", "content": json.dumps({"status": 307, "ok": False, "body": ""})}]
    for _ in range(core.MAX_API_REJECTIONS - 1):
        assert a._stuck([call], messages) is None
        assert a._stuck([], messages) is None
    assert a._stuck([call], messages)
