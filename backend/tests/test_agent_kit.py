"""The assistant runs what it decides, instead of printing it (the audit's "General assistant" plan,
general_assistant_kit wired into app/agent).

- tool calls a model writes as text -- after prose, as Qwen3-Coder XML, in a fence -- are run;
- a broken call (bad JSON, duplicate keys, unknown tool) goes back to the model, never runs half-read;
- a reply cut off at the length limit never runs its call;
- a final reply may not carry unrun calls, nor claim work no tool did;
- describe_workspace, check_spec, relationships_from_file and run_python, against the real platform.
"""

from __future__ import annotations

import copy
import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agent import core, sandbox, toolcall
from app.api import agent as agent_api
from app.main import app
from tests.test_agent import SHOPS_CSV, _bakery_spec, _chat, _in_process_caller, _spec
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


class RawLLM:
    """Plays the model with exact replies: ("text", content[, finish]) or ("native", name, arguments-as-string)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, settings, messages, native, tools=None, max_tokens=None):
        self.requests.append({"messages": copy.deepcopy(messages), "tools": [t["function"]["name"] for t in tools or []]})
        kind, *rest = self.replies.pop(0)
        if kind == "text":
            content, finish = rest[0], (rest[1] if len(rest) > 1 else "stop")
            return {"role": "assistant", "content": content, "_finish": finish}, True
        name, arguments = rest
        return {"role": "assistant", "content": None, "_finish": "tool_calls", "tool_calls": [
            {"id": f"n{len(self.requests)}", "type": "function", "function": {"name": name, "arguments": arguments}}]}, True


@pytest.fixture
def raw(monkeypatch):
    monkeypatch.setattr(agent_api, "make_caller", _in_process_caller)

    def install(replies):
        llm = RawLLM(replies)
        monkeypatch.setattr(core, "llm_chat", llm)
        return llm

    return install


def _block(name, arguments):
    return "<tool_call>\n" + json.dumps({"name": name, "arguments": arguments}) + "\n</tool_call>"


def _platform_messages(llm):
    return [m["content"] for m in llm.requests[-1]["messages"] if m["role"] == "user"
            and str(m["content"]).startswith(core.PLATFORM)]


# -- reading what the model wrote ---------------------------------------------------------


def test_calls_written_as_text_are_found_in_every_form_the_model_uses():
    names = {"read_file", "call_api", "propose_plan"}
    calls, prose, errors = toolcall.extract_tool_calls(
        "I need to fix the spec first, so here it is again.\n" + _block("read_file", {"file": "a.csv"}), names)
    assert calls == [{"name": "read_file", "arguments": {"file": "a.csv"}}] and prose.startswith("I need") and not errors
    calls, _, _ = toolcall.extract_tool_calls(
        "<tool_call><function=call_api><parameter=method>GET</parameter><parameter=path>/api/v1/runs</parameter>"
        "<parameter=query>{\"limit\": 5}</parameter></function></tool_call>", names)
    assert calls == [{"name": "call_api", "arguments": {"method": "GET", "path": "/api/v1/runs", "query": {"limit": 5}}}]
    calls, _, _ = toolcall.extract_tool_calls('```json\n{"name": "read_file", "arguments": {"file": "b"}}\n```', names)
    assert calls[0]["arguments"] == {"file": "b"}


def test_a_broken_call_is_refused_with_its_reason_never_half_read():
    names = {"propose_plan"}
    # A list split over two same-named keys is joined, and the model is told (October 2026 test: Qwen
    # repeated "entity_types" three times in a row and gave up); two different values are refused.
    calls, _, errors = toolcall.extract_tool_calls(
        '<tool_call>{"name": "propose_plan", "arguments": {"spec": {"seed": {"entities_from_file": [1], '
        '"entities_from_file": [2]}}}}</tool_call>', names)
    assert calls[0]["arguments"]["spec"]["seed"]["entities_from_file"] == [1, 2]
    assert errors == ['note: "entities_from_file" was given twice; its two lists were joined (1 + 1 items)']
    calls, _, errors = toolcall.extract_tool_calls(
        '<tool_call>{"name": "propose_plan", "arguments": {"spec": {"domain_id": 1, "domain_id": 2}}}</tool_call>',
        names)
    assert not calls and "duplicate key" in errors[0] and "(1 and 2)" in errors[0]
    _, _, errors = toolcall.extract_tool_calls('<tool_call>{"name": "drop_tables", "arguments": {}}</tool_call>', names)
    assert "unknown tool" in errors[0]
    calls, _, errors = toolcall.extract_tool_calls('<tool_call>{"name": "propose_plan", "arguments": {"spec": {',
                                                   names, allow_repair=False)
    assert not calls and errors


# -- the loop -------------------------------------------------------------------------------


def test_a_long_plan_written_after_prose_is_run_not_shown(tenants, db, raw):
    """The audit's case: propose_plan as text, with reasoning before it, used to reach the person as text."""
    spec = _spec("text-call")
    llm = raw([
        ("text", "1. What is the budget? 2. Any limit per district?"),
        ("text", "Thanks. I checked everything against your answers, and here is the plan with every rule spelled "
                 "out so that you can review it carefully before anything is built.\n"
         + _block("propose_plan", {"summary": "**Sets** project", "spec": spec})),
    ])
    first = _chat(tenants["b"], mode="model", text="Pick city projects to fund.")
    second = _chat(tenants["b"], messages=first[-1]["messages"], mode="model", text="500k; two in district A at most.")
    plan = next(e for e in second if e["type"] == "plan")
    assert plan["counts"]["entities"] == 4
    assert not any(e["type"] == "answer" and "<tool_call>" in e["text"] for e in second)
    pending = second[-1]["messages"][-1]
    assert pending["role"] == "assistant" and pending["tool_calls"][0]["function"]["name"] == "propose_plan"
    assert "<tool_call>" not in (pending["content"] or "")


def test_qwen3_coder_calls_run_too(tenants, raw):
    raw([
        ("text", "<tool_call>\n<function=describe_workspace>\n</function>\n</tool_call>"),
        ("text", "Your workspace is empty."),
    ])
    events = _chat(tenants["b"], text="what is in my workspace?")
    assert next(e for e in events if e["type"] == "tool")["name"] == "describe_workspace"


def test_a_reply_cut_off_at_the_length_limit_never_runs_its_call(tenants, db, raw):
    spec = _spec("cut-off")
    half = _block("propose_plan", {"summary": "plan", "spec": spec})[:400]
    llm = raw([
        ("text", "1. Budget? 2. Districts?"),
        ("text", "Here is the plan.\n" + half, "length"),
        ("text", _block("propose_plan", {"summary": "plan", "spec": spec})),
    ])
    first = _chat(tenants["b"], mode="model", text="Pick projects.")
    second = _chat(tenants["b"], messages=first[-1]["messages"], mode="model", text="500k, two in A.")
    assert any(e["type"] == "note" and "cut off" in e["text"] for e in second)
    assert any("cut off at the length limit" in m for m in _platform_messages(llm))
    assert next(e for e in second if e["type"] == "plan")  # the whole call, sent again, went through
    # The platform's note is not the person's answer: it does not count as a turn of the conversation.
    agent = core.Agent(core.Settings(), agent_api._index, lambda *a, **k: {}, core.Context("x"))
    agent.messages = second[-1]["messages"]
    assert agent._user_turns() == 2


def test_native_arguments_with_duplicate_keys_go_back_to_the_model(tenants, raw):
    llm = raw([
        ("native", "call_api", '{"method": "GET", "path": "/api/v1/runs", "path": "/api/domain/"}'),
        ("native", "call_api", '{"method": "GET", "path": "/api/v1/runs"}'),
        ("text", "You have no runs."),
    ])
    events = _chat(tenants["b"], text="list my runs")
    assert any(e["type"] == "result" and "duplicate key" in e["preview"] for e in events)
    assert any("NOT run" in m for m in _platform_messages(llm))
    assert [e["args"]["path"] for e in events if e["type"] == "tool"] == ["/api/v1/runs"]


def test_a_reply_may_not_claim_work_no_tool_did(tenants, raw):
    llm = raw([
        ("text", "I have built your model and solved it: the best plan uses two vans."),
        ("text", "Nothing has been built yet: I need your approval of a plan first."),
    ])
    events = _chat(tenants["b"], text="build it")
    assert any("do not say it was done" in m for m in _platform_messages(llm))
    assert next(e for e in events if e["type"] == "answer")["text"].startswith("Nothing has been built")


def test_a_final_reply_with_an_unreadable_call_is_sent_back(tenants, raw):
    llm = raw([
        ("text", 'Running it: {"name": "call_api", "arguments": {"method": "GET", "path": '),
        ("text", "Sorry, here is the answer: there are no runs."),
    ])
    events = _chat(tenants["b"], text="runs?")
    assert any("did NOT run" in m for m in _platform_messages(llm))
    assert events[-2]["text"].startswith("Sorry")


# -- the workspace, checking, and loading records into it --------------------------------------


def test_describe_workspace_and_check_spec_read_the_real_platform(tenants, db, raw):
    client = TestClient(app)
    shops = client.post("/api/v1/agent/files", files={"file": ("shops.csv", SHOPS_CSV, "text/csv")},
                        headers=tenants["b"]).json()
    spec = _bakery_spec("workspace")
    spec["seed"] = __import__("app.agent.files", fromlist=["expand"]).expand(spec["seed"], [shops])
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"]).json()

    seen = client.get(f"/api/v1/agent/workspace?domain_id={built['domain_id']}", headers=tenants["b"]).json()
    kinds = {k["name"]: k for k in seen["kinds_of_record"]}
    assert kinds["shop"]["records"] == 4 and kinds["shop"]["fields"]["demand"].startswith("integer (trays)")
    assert kinds["van"]["some_keys"] == ["v1", "v2", "v3"]
    assert seen["problems"][0]["scenarios"][0]["name"] == "Base"

    bad = _spec("check")
    bad["ir"]["constraints"][1]["left"]["sum"]["var"] = "nope"
    raw([
        ("native", "check_spec", json.dumps({"spec": bad})),
        ("text", "The model names a variable that does not exist; fixing it."),
    ])
    events = _chat(tenants["b"], mode="model", text="check it", context={"domain_id": built["domain_id"]})
    result = next(e for e in events if e["type"] == "result" and e["name"] == "check_spec")
    assert result["preview"].startswith("Not valid yet") and not result["ok"]
    assert db.execute(text("SELECT count(*) FROM domain WHERE name = :n"), {"n": bad["domain_name"]}).scalar() == 0


def test_links_load_from_a_two_column_file_and_a_ranked_model_over_them_solves(tenants, db):
    """Loading records into a workspace (records + links from files) and solving with `via` and ranked goals."""
    from app.agent import files as agent_files
    from app.worker import work_once

    client = TestClient(app)
    up = lambda name, body: client.post("/api/v1/agent/files", files={"file": (name, body, "text/csv")},  # noqa: E731
                                        headers=tenants["b"]).json()
    items = up("items.csv", "item,weight,value\na,4,10\nb,3,7\nc,2,4\nd,5,9\n")
    groups = up("groups.csv", "group\ng1\ng2\n")
    links = up("item_group.csv", "item,group\na,g1\nb,g1\nc,g2\nd,g2\n")
    i, g = {"index": "i", "set": "item"}, {"index": "g", "set": "group"}
    pick = {"var": "pick", "index": ["i"]}
    spec = {
        "domain_name": "Groups", "problem_name": "One per group",
        "seed": {
            "entity_types": [{"name": "item", "attributes": [{"name": "weight", "data_type": "number", "required": True},
                                                             {"name": "value", "data_type": "number", "required": True}]},
                             {"name": "group"}],
            "relationship_types": [{"name": "item_group", "from": "item", "to": "group", "cardinality": "many_to_one"}],
            "entities_from_file": [{"file": "items.csv", "type": "item", "key": "item",
                                    "attrs": {"weight": "weight", "value": "value"}},
                                   {"file": "groups.csv", "type": "group", "key": "group"}],
            "relationships_from_file": [{"file": "item_group.csv", "type": "item_group",
                                         "from": ["item", "item"], "to": ["group", "group"]}],
        },
        "ir": {"version": 2, "sets": ["item", "group"], "relationships": ["item_group"], "parameters": {},
               "variables": {"pick": {"index": ["item"], "domain": "binary"}},
               "constraints": [{"id": "one_per_group", "forall": [g],
                                "left": {"sum": pick, "over": [{**i, "via": {"rel": "item_group", "to": "g"}}]},
                                "relation": "=", "right": {"const": 1}, "severity": "hard"}],
               "objective": {"sense": "maximize", "mode": "lex", "terms": [
                   {"id": "value", "weight": 1, "expression": {"sum": {"mul": [pick, {"attr": {"of": "i", "name": "value"}}]}, "over": [i]}},
                   {"id": "weight", "weight": -1, "expression": {"sum": {"mul": [pick, {"attr": {"of": "i", "name": "weight"}}]}, "over": [i]}}]}},
    }
    spec["seed"] = agent_files.expand(spec["seed"], [items, groups, links])
    assert len(spec["seed"]["relationships"]) == 4
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["b"])
    assert built.status_code == 200, built.text
    run = client.post(f"/api/v1/scenarios/{built.json()['scenario_id']}/runs", json={}, headers=tenants["b"]).json()
    for _ in range(5):
        if work_once(db) is None:
            break
    answer = client.get(f"/api/v1/runs/{run['id']}", headers=tenants["b"]).json()
    assert answer["status"] == "optimal", answer
    assert sorted(k[0] for k in answer["assignments"]["pick"]) == ["a", "d"]  # 10 + 9


# -- run_python ---------------------------------------------------------------------------------


@pytest.fixture
def python_on(monkeypatch):
    import shutil
    import uuid

    monkeypatch.setenv("AGENT_RUN_PYTHON", "1" if os.geteuid() == 0 else "unsafe")
    folder = f"/tmp/assistant_sandbox_test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("AGENT_SANDBOX_ROOT", folder)
    yield
    shutil.rmtree(folder, ignore_errors=True)


def test_run_python_reads_attachments_writes_files_back_and_cannot_see_the_server(tenants, raw, python_on):
    client = TestClient(app)
    shops = client.post("/api/v1/agent/files", files={"file": ("shops.csv", SHOPS_CSV, "text/csv")},
                        headers=tenants["b"]).json()
    code = (
        "import csv, os, socket\n"
        "rows = list(csv.DictReader(open('shops.csv')))\n"
        "print('total', sum(int(r['demand_trays']) for r in rows))\n"
        "with open('pairs.csv', 'w', newline='') as f:\n"
        "    w = csv.writer(f); w.writerow(['a', 'b'])\n"
        "    [w.writerow([x['shop'], y['shop']]) for x in rows for y in rows if x['shop'] < y['shop']]\n"
        "print('secret' if os.environ.get('JWT_SECRET') else 'no secret')\n"
        "try:\n    open('/proc/%d/environ' % os.getppid()).read(); print('server env READABLE')\n"
        "except Exception as e:\n    print('server env hidden', type(e).__name__)\n"
        "try:\n    socket.create_connection(('127.0.0.1', 5432)); print('NETWORK')\n"
        "except Exception as e:\n    print('no network', type(e).__name__)\n"
    )
    raw([("native", "run_python", json.dumps({"code": code})), ("text", "110 trays in all.")])
    events = _chat(tenants["b"], mode="model", files=[shops], conversation_id="conv1", text="how much demand?")
    result = json.loads(next(m for m in events[-1]["messages"] if m["role"] == "tool")["content"])
    assert result["exit_code"] == 0, result
    out = result["stdout"]
    assert "total 110" in out and "no secret" in out and "no network" in out
    if os.geteuid() == 0:
        assert "server env hidden" in out
    assert result["attached"] == ["pairs.csv"]
    attached = next(e for e in events if e["type"] == "file")["file"]
    assert attached["name"] == "pairs.csv" and attached["sheets"][0]["total_rows"] == 6


def test_run_python_is_off_unless_switched_on(tenants, raw, monkeypatch):
    monkeypatch.delenv("AGENT_RUN_PYTHON", raising=False)
    llm = raw([("native", "run_python", json.dumps({"code": "print(1)"})), ("text", "It is not available.")])
    events = _chat(tenants["b"], mode="model", text="run something")
    assert "run_python" not in llm.requests[0]["tools"]
    assert any(e["type"] == "result" and "unknown tool" in e["preview"] for e in events)
    assert sandbox.available()[0] is False


def test_without_a_network_namespace_python_still_has_no_sockets(python_on, monkeypatch):
    """Docker's default profile refuses a network namespace: the Python guard is then what stops a connection."""
    monkeypatch.setattr(sandbox, "_NET_ISOLATION", False)
    folder = sandbox.workdir("u", "no-namespace")
    result = sandbox.run(
        "import socket, urllib.request\n"
        "for f in (lambda: socket.socket(), lambda: socket.create_connection(('10.125.18.189', 8000)),\n"
        "          lambda: urllib.request.urlopen('http://clickhouse:8123', timeout=2)):\n"
        "    try:\n        f(); print('CONNECTED')\n"
        "    except Exception as e:\n        print('refused', type(e).__name__)\n", folder)
    assert result["isolation"]["network"] == "blocked in Python only"
    assert "CONNECTED" not in result["stdout"] and result["stdout"].count("refused") == 3, result
