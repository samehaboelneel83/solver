"""The Assistant's conversations kept on the server (app.agent.store, migration 0109): the browser sends only
the new message, never the history (a layout problem's history passed 1 MB: "413 Request Entity Too Large")."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app
from app.api import agent as agent_api
from app.agent import core, store as agent_store
from tests.test_agent import _chat
from tests.test_agent_field_test import _install, _parsed
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_the_history_stays_on_the_server_and_the_browser_sends_only_the_new_message(tenants, monkeypatch):
    model = _install(monkeypatch, [("text", "Which camps?"), ("text", "Noted: all of them.")])
    first = _chat(tenants["b"], text="maximise beds", server_history=True, conversation_id="conv_store_1",
                  mode="model")
    state = first[-1]
    assert state["messages"] == [] and state["stored"]["messages"] == 2  # not sent back whole
    second = _chat(tenants["b"], text="all of them", server_history=True, conversation_id="conv_store_1",
                   mode="model")
    sent = model.requests[-1]["messages"]
    words = [m.get("content") for m in sent if m["role"] in ("user", "assistant")]
    assert "maximise beds" in words and "Which camps?" in words and "all of them" in words
    assert second[-1]["stored"]["messages"] == 4


def test_attached_files_are_kept_and_detached_by_name(tenants, monkeypatch):
    model = _install(monkeypatch, [("text", "Read."), ("text", "Still have them."), ("text", "Gone.")])
    files = _parsed()
    _chat(tenants["b"], text="read these", server_history=True, conversation_id="conv_store_2", files=files)
    # Next turn: no files sent, all kept.
    _chat(tenants["b"], text="and now?", server_history=True, conversation_id="conv_store_2")
    assert all(f["name"] in json.dumps(model.requests[-1]["messages"]) for f in files[:1])
    # Detach all: keep_files [].
    _chat(tenants["b"], text="forget them", server_history=True, conversation_id="conv_store_2", keep_files=[])
    assert files[0]["name"] not in json.dumps(model.requests[-1]["messages"][0])


def test_incoming_files_are_saved_before_a_turn_can_be_interrupted(tenants, monkeypatch):
    files = _parsed()
    saved = []
    real_save = agent_store.save

    def capture(db, conversation_id, owner_id, organization_id, mode, messages, kept_files, turned=True):
        saved.append((conversation_id, messages, kept_files, turned))
        return real_save(db, conversation_id, owner_id, organization_id, mode, messages, kept_files, turned)

    def interrupted(self, messages, allow=None):
        yield {"type": "error", "text": "simulated interrupted turn"}

    monkeypatch.setattr(agent_store, "save", capture)
    monkeypatch.setattr(core.Agent, "run", interrupted)
    response = TestClient(app).post("/api/v1/agent/chat", headers=tenants["b"], json={
        "text": "continue using the attached file", "mode": "model", "files": files,
        "server_history": True, "conversation_id": "conv_store_interrupted",
    })

    assert response.status_code == 200
    assert saved and len(saved) == 1  # no terminal state was yielded to trigger the old save path
    conversation_id, messages, kept_files, turned = saved[0]
    assert conversation_id == "conv_store_interrupted" and not turned
    assert messages[-1]["content"] == ("continue using the attached file\n\n"
                                       "[Attached with this message: warehouses.csv, customers.csv, lanes.csv]")
    assert kept_files[0]["name"] == files[0]["name"]


def test_someone_elses_conversation_is_refused(tenants, monkeypatch):
    _install(monkeypatch, [("text", "Hello.")])
    _chat(tenants["b"], text="mine", server_history=True, conversation_id="conv_store_3")
    other = TestClient(app).post("/api/v1/agent/chat", headers=tenants["a"],
                                 json={"text": "peek", "server_history": True, "conversation_id": "conv_store_3"})
    assert other.status_code == 403


def test_a_new_chat_forgets_the_old_one(tenants, monkeypatch):
    model = _install(monkeypatch, [("text", "Noted."), ("text", "Fresh start.")])
    _chat(tenants["b"], text="secret brief", server_history=True, conversation_id="conv_store_4")
    gone = TestClient(app).delete("/api/v1/agent/conversations/conv_store_4", headers=tenants["b"])
    assert gone.status_code == 204
    _chat(tenants["b"], text="hello", server_history=True, conversation_id="conv_store_4")
    assert "secret brief" not in json.dumps(model.requests[-1]["messages"])


def test_the_old_way_still_works_for_other_clients(tenants, monkeypatch):
    _install(monkeypatch, [("text", "Hi.")])
    events = _chat(tenants["b"], text="hello", messages=[])
    assert events[-1]["messages"]  # the history comes back whole when the client keeps it
