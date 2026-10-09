"""The platform assistant (app/agent/core.py) over HTTP.

    GET  /api/v1/agent/status   is it on, which model, can the model be reached
    POST /api/v1/agent/chat     advance a conversation; streams NDJSON events
    POST /api/v1/agent/files    read an attached file into tables: CSV / Excel / JSON, or a map file
                                (DXF, GeoJSON, KML/KMZ, GPX, Shapefile .zip, GeoPackage, CSV with shapes)
    POST /api/v1/agent/files/place   a map file again, placed in the coordinate system the person named

`chat` takes the conversation so far and returns the new one in its last
event (`state`), so nothing is kept per session here. Body:

    {"messages": [...],            # as returned in the previous `state` (may be [])
     "text": "solve scenario 4",   # the person's new message, or
     "confirm": {"allow": true},   # the answer to a `confirm` event
     "context": {"page": "/runs", "domain_id": 3, "problem_id": 12},
     "mode": "assistant",           # or "model": describe a problem in words
     "files": [...]}                # attached files, as /agent/files returned them

In `model` mode the assistant interviews the person, proposes a plan (a
`plan` event, already checked by a dry run of POST /problems/from-spec),
and builds it only on `confirm: {"allow": true}` -- a `built` event with the
new ids. A new message instead of an answer is feedback on the plan.

Events, one JSON object a line: `thinking`, `note`, `tool`, `result`,
`confirm`, `plan`, `built`, `answer`, `error`, `ping` (every 10 s of quiet,
so a proxy keeps the line open), then always `state` last.

The assistant calls this same API with the caller's own bearer token, so
it can do exactly what they can and every change is audited as theirs.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Any, Iterator, Literal

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent import core
from app.agent import files as agent_files
from app.agent import sandbox
from app.agent import store as agent_store
from app.api.deps import capabilities_of, get_current_user, oauth2_scheme, requires
from app.core.db import get_db
from app.models.iam import UserAccount

logger = structlog.get_logger("solver.assistant")

router = APIRouter(prefix="/api/v1/agent", tags=["assistant"])

MAX_HISTORY_BYTES = 600_000
MAX_FILES = 8
MAX_FILES_BYTES = 8_000_000


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: dict[str, Any]


class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class Confirm(BaseModel):
    allow: bool


class PageContext(BaseModel):
    page: str | None = Field(default=None, max_length=500)
    domain_id: int | None = None
    problem_id: int | None = None


class ChatRequest(BaseModel):
    messages: list[Message] = Field(default_factory=list, max_length=600)
    text: str | None = Field(default=None, max_length=20_000)
    confirm: Confirm | None = None
    context: PageContext | None = None
    mode: Literal["assistant", "model"] = "assistant"
    files: list[dict[str, Any]] | None = Field(default=None, max_length=MAX_FILES)
    # The conversation is kept on the server (app.agent.store): `messages` is ignored, `files` are only the
    # newly attached ones, and `keep_files` names the attachments still wanted (None: all of them).
    server_history: bool = False
    keep_files: list[str] | None = Field(default=None, max_length=200)
    # The client's id for this conversation: names run_python's working folder.
    conversation_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")


# Turns that keep running after the browser left (the blend test, October 2026: changing page lost a turn
# that was minutes into writing the model, and nothing showed it on return). One web process (the Dockerfile
# runs a single uvicorn worker), so the registry is in memory: conversation id -> its current turn's events.
TURNS: dict[str, dict[str, Any]] = {}
TURN_KEEP_S = 1800
_turns_lock = threading.Lock()


def _turn_start(conversation_id: str, owner: str, agent: Any) -> dict[str, Any]:
    with _turns_lock:
        now = time.time()
        for key in [k for k, t in TURNS.items() if t["done"] and now - t["ended"] > TURN_KEEP_S]:
            TURNS.pop(key, None)
        old = TURNS.get(conversation_id)
        if old and not old["done"]:
            old["agent"].cancelled.set()  # a new message replaces a turn still running
        turn = {"owner": owner, "agent": agent, "events": [], "done": False, "ended": 0.0, "started": now}
        TURNS[conversation_id] = turn
        return turn


# The spec is the app's own; built once per process (FastAPI caches it too).
_index: core.ApiIndex | None = None


def _api_index(request: Request) -> core.ApiIndex:
    global _index
    if _index is None:
        _index = core.ApiIndex(request.app.openapi())
    return _index


# Tests replace this to call the app in-process instead of over the loopback.
def make_caller(settings: core.Settings, token: str) -> core.CallFn:
    return core.loopback_caller(settings, token)


@router.get("/status")
def status(user: UserAccount = Depends(get_current_user)) -> dict:
    s = core.Settings()
    out: dict[str, Any] = {"enabled": s.enabled, "model": s.model, "confirm": s.confirm,
                           "run_python": sandbox.mode()}
    if s.enabled:
        out.update(core.check_llm(s))
    return out


@router.post("/chat")
def chat(
    body: ChatRequest,
    request: Request,
    user: UserAccount = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    settings = core.Settings()
    if not settings.enabled:
        raise HTTPException(status_code=404, detail="the assistant is turned off (AGENT_ENABLED=0)")

    if len(json.dumps(body.files or [], default=str)) > MAX_FILES_BYTES:
        raise HTTPException(status_code=413, detail="the attached files are too large together; attach fewer")
    owner, organization = str(user.id), str(user.organization_id)
    if body.server_history:
        if not body.conversation_id:
            raise HTTPException(status_code=422, detail="server_history needs a conversation_id")
        if agent_store.taken(db, body.conversation_id, owner):
            raise HTTPException(status_code=403, detail="that conversation is someone else's")
        kept = agent_store.load(db, body.conversation_id, owner) or {}
        messages = list(kept.get("messages") or [])
        stored = {f.get("name"): f for f in kept.get("files") or [] if isinstance(f, dict)}
        names = list(stored) if body.keep_files is None else [n for n in body.keep_files if n in stored]
        new = {f.get("name"): f for f in body.files or [] if isinstance(f, dict)}
        files = [stored[n] for n in names if n not in new] + list(new.values())
        replaced = [n for n in new if n in stored]
    else:
        messages = [m.model_dump(exclude_none=True) for m in body.messages]
        files = list(body.files or [])
        replaced = []
        if len(json.dumps(messages)) > MAX_HISTORY_BYTES:
            raise HTTPException(status_code=413, detail="the conversation is too long; start a new one")
    pending = bool(messages) and messages[-1]["role"] == "assistant" and bool(messages[-1].get("tool_calls"))
    if body.confirm is not None and not pending:
        raise HTTPException(status_code=409, detail="nothing is waiting for confirmation")
    if body.confirm is None:
        if not body.text or not body.text.strip():
            raise HTTPException(status_code=422, detail="send `text`, or `confirm` to answer a confirmation")
        if pending:
            # A new message instead of an answer: the waiting calls are not approved, and
            # the message is the person's reply to them (feedback on a plan, say).
            for call in messages[-1]["tool_calls"]:
                messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["function"].get("name"),
                                 "content": "Not approved. The user replied instead; their message follows."})
        said = body.text.strip()
        arrived = [str(f.get("name")) for f in body.files or [] if isinstance(f, dict) and f.get("name")]
        if arrived:
            # Which files came with this message, and which replace an earlier copy of the same name (the file
            # refresh test, October 2026: next quarter's projects.csv, same name and size, was taken for the old
            # one, and the person was asked to attach it again).
            said += "\n\n[Attached with this message: " + ", ".join(
                f"{n} (a NEW copy: it replaces the earlier {n} in this conversation)" if n in replaced else n
                for n in arrived) + "]"
        messages.append({"role": "user", "content": said})

    # The next streamed turn may take minutes and can be interrupted by a worker or API restart.
    # Save the incoming message and its attachments before starting the model so the browser can
    # resume from the same conversation without retaining the full file rows itself.
    if body.server_history:
        agent_store.save(db, body.conversation_id, owner, organization, body.mode, messages, files, turned=False)

    ctx_in = body.context or PageContext()
    # run_python runs model-written code: only where it is switched on, and for people who may publish models.
    can_run_python = sandbox.available()[0] and "model.publish" in capabilities_of(db, user)
    if can_run_python:
        sandbox.cleanup()
    agent = core.Agent(
        settings, _api_index(request), make_caller(settings, token),
        core.Context(username=user.username, page=ctx_in.page,
                     domain_id=ctx_in.domain_id, problem_id=ctx_in.problem_id, mode=body.mode,
                     files=files, user_id=str(user.id), conversation_id=body.conversation_id,
                     can_run_python=can_run_python),
    )
    allow = body.confirm.allow if body.confirm is not None else None
    turn = _turn_start(body.conversation_id, owner, agent) if body.server_history and body.conversation_id else None

    async def stream():
        # The loop runs in a thread so this generator can send a `ping` while a
        # model reply or a solve takes its time.
        events: queue.Queue = queue.Queue()
        done = object()

        def work() -> None:
            # How each turn ended, in the server log (docker compose logs backend | grep assistant.turn):
            # the chat lives in the browser, so "why did it stop?" is otherwise answered by nobody.
            started, steps, last, ending = time.monotonic(), 0, None, "finished"
            try:
                for event in agent.run(messages, allow):
                    kind = event.get("type")
                    if body.server_history and kind == "result" and not agent.cancelled.is_set():
                        _keep(body.conversation_id, owner, organization, body.mode, messages, agent.ctx.files)
                    steps += kind == "tool"
                    if kind in ("answer", "error", "confirm", "plan", "built"):
                        last = event
                    if body.server_history and kind == "state":
                        # Kept here, not sent back whole: the browser shows the turn, the server holds it.
                        if not agent.cancelled.is_set():
                            _keep(body.conversation_id, owner, organization, body.mode, event["messages"],
                                  agent.ctx.files)
                        event = {"type": "state", "messages": [], "wrote": event.get("wrote"),
                                 "stored": {"messages": len(event["messages"]),
                                            "tokens": len(json.dumps(event["messages"], ensure_ascii=False,
                                                                     default=str)) // 2}}
                    elif body.server_history and kind == "file":
                        event = {"type": "file", "file": _light(event["file"])}
                    if turn is not None and kind not in ("thinking", "ping"):
                        turn["events"].append(event)
                    events.put(event)
            except BaseException as exc:  # noqa: BLE001 -- logged, then the stream ends as before
                ending = f"crashed: {type(exc).__name__}: {exc}"
                raise
            finally:
                events.put(done)
                if turn is not None:
                    turn["done"], turn["ended"] = True, time.time()
                text_ = str((last or {}).get("text") or "")
                logger.info("assistant.turn", user=user.username, conversation=body.conversation_id,
                            mode=body.mode, seconds=round(time.monotonic() - started, 1), tool_calls=steps,
                            ended_with=(last or {}).get("type") or "nothing", ending=ending,
                            text=text_[:400], history_messages=len(messages))

        threading.Thread(target=work, daemon=True, name="assistant").start()
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.to_thread(events.get, True, 1)
                except queue.Empty:
                    yield b'{"type": "ping"}\n'
                    continue
                if event is done:
                    return
                yield (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode()
        finally:
            # The browser leaving is not a Stop: a turn whose conversation the server keeps runs on and is
            # picked up again (GET /conversations/{id}/turn). Stop is POST /conversations/{id}/stop.
            # Starlette may cancel this generator on a disconnect instead of letting is_disconnected() say so,
            # so the test is whether the server keeps the conversation, not how the stream ended.
            if turn is None:
                agent.cancelled.set()
    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _light(file: dict[str, Any]) -> dict[str, Any]:
    """An attached file as the browser shows it: names and counts, not rows (the server keeps those)."""
    return {**file, "sheets": [{**s, "rows": []} for s in file.get("sheets") or []]}


def _keep(conversation_id: str, owner: str, organization: str, mode: str, messages: list, files: list) -> None:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        agent_store.save(db, conversation_id, owner, organization, mode, messages, files)


@router.get("/conversations/{conversation_id}/turn")
def current_turn(conversation_id: str, after: int = 0, user: UserAccount = Depends(get_current_user)) -> dict:
    """The conversation's latest turn: whether it is still running and its events from `after` on, for a
    browser that left during the turn and came back."""
    turn = TURNS.get(conversation_id)
    if turn is None or turn["owner"] != str(user.id):
        return {"running": False, "known": False, "events": [], "count": 0}
    events = turn["events"]
    return {"running": not turn["done"], "known": True, "events": events[max(0, after):], "count": len(events)}


@router.post("/conversations/{conversation_id}/handover")
def handover(conversation_id: str, db: Session = Depends(get_db),
             user: UserAccount = Depends(get_current_user)) -> dict:
    """An Ask conversation's problem carried to Describe a problem: a new conversation in model mode with the same
    attached files (the server keeps their rows) and the person's first message, to send there."""
    import uuid

    kept = agent_store.load(db, conversation_id, str(user.id))
    if kept is None:
        raise HTTPException(status_code=404, detail="no such conversation")
    first = next((m.get("content") for m in kept.get("messages") or []
                  if m.get("role") == "user" and not str(m.get("content") or "").startswith(core.PLATFORM)), None)
    if first is None:
        # A long conversation was summarized: its first message is kept word for word in the summary.
        summary = next((str(m.get("content")) for m in kept.get("messages") or [] if m.get("role") == "user"), "")
        marker = "The person's first message, word for word:\n"
        if marker in summary:
            first = summary.split(marker, 1)[1].split("\n(end of the first message)", 1)[0]
    new_id = uuid.uuid4().hex
    files = list(kept.get("files") or [])
    agent_store.save(db, new_id, str(user.id), str(user.organization_id), "model", [], files, turned=False)
    first = ATTACHED_NOTE.sub("", first or "")  # the files travel on their own
    return {"conversation_id": new_id, "text": first, "files": [_light(f) for f in files]}


@router.post("/conversations/{conversation_id}/stop", status_code=204, response_class=Response)
def stop_turn(conversation_id: str, user: UserAccount = Depends(get_current_user)) -> Response:
    """Stop: no further action is started in this conversation's running turn."""
    turn = TURNS.get(conversation_id)
    if turn is not None and turn["owner"] == str(user.id):
        turn["agent"].cancelled.set()
    return Response(status_code=204)


@router.delete("/conversations/{conversation_id}", status_code=204, response_class=Response)
def forget(conversation_id: str, db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> Response:
    """A new chat: the old conversation is no longer needed."""
    turn = TURNS.get(conversation_id)
    if turn is not None and turn["owner"] == str(user.id):
        turn["agent"].cancelled.set()
    agent_store.delete(db, conversation_id, str(user.id))
    return Response(status_code=204)


#: The note a message gets naming the files attached with it (see the turn above).
ATTACHED_NOTE = __import__("re").compile(r"\n\n\[Attached with this message: [^\n]*\]$")


@router.post("/files")
def read_file(
    file: UploadFile = File(...),
    domain_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict:
    """An attached file as tables (app/agent/files.py). A map file is read by the platform's own CAD/GIS
    readers and kept as a Map Import upload is (`gis_upload`, a day), so it can be placed again or imported
    as map data; anything else is not kept: the answer is the file."""
    import hashlib

    from app.api.gis import MAX_UPLOAD_BYTES

    name = (file.filename or "file")[:255]
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    try:
        if not agent_files.is_spatial(name, data):
            return agent_files.parse(name, data)
        if len(data) > MAX_UPLOAD_BYTES:
            raise agent_files.FileRefused("a map file can be at most 50 MB")
        parsed = agent_files.parse_spatial(name, data)
    except agent_files.FileRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    summary = {"sha256": hashlib.sha256(data).hexdigest(), "domain_id": domain_id, "from": "assistant",
               "format": parsed["spatial"]["format"]}
    upload_id = db.execute(text(
        "INSERT INTO gis_upload (organization_id, created_by, filename, size_bytes, data, summary)"
        " VALUES (:o, :u, :f, :s, :d, CAST(:sm AS jsonb)) RETURNING id"),
        {"o": user.organization_id, "u": str(user.id), "f": name, "s": len(data), "d": data,
         "sm": json.dumps(summary)}).scalar_one()
    db.commit()
    parsed["spatial"]["upload_id"] = str(upload_id)
    # Its fingerprint: an import uses the upload up, so a later workspace finds the same drawing's map by it.
    parsed["spatial"]["sha256"] = summary["sha256"]
    return parsed


class PlaceFile(BaseModel):
    upload_id: str
    placement: dict[str, Any]


@router.post("/files/place")
def place_file(body: PlaceFile, db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict:
    """A map file read again, in the coordinate system the person named (`{"kind": "epsg", "code": 22992}`)."""
    from app.api.gis import _upload

    row = _upload(db, body.upload_id, user)
    try:
        return agent_files.parse_spatial(row["filename"], bytes(row["data"]), body.placement, upload_id=body.upload_id)
    except agent_files.FileRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/workspace")
def workspace(domain_id: int, db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict:
    """What a domain already holds, in its own words: kinds of record (fields, counts), relationship types,
    data values (parameters), map data, problems (versions, scenarios). The assistant reads it before
    asking the person anything (`describe_workspace`), so it reuses what is there instead of asking for it."""
    domain = db.execute(text("SELECT id, name FROM domain WHERE id = :d"), {"d": domain_id}).mappings().first()
    if domain is None:
        raise HTTPException(status_code=404, detail="domain not found")
    types = db.execute(text(
        "SELECT t.id, t.name, t.role, (SELECT count(*) FROM entity e WHERE e.entity_type_id = t.id) AS records"
        " FROM entity_type t WHERE t.domain_id = :d ORDER BY t.name"), {"d": domain_id}).mappings().all()
    names = {t["id"]: t["name"] for t in types}
    attrs: dict[int, dict[str, str]] = {}
    for a in db.execute(text(
            "SELECT a.entity_type_id, a.name, a.data_type, a.unit, a.required FROM attribute_def a"
            " JOIN entity_type t ON t.id = a.entity_type_id WHERE t.domain_id = :d ORDER BY a.sort_order NULLS LAST, a.name"),
            {"d": domain_id}).mappings():
        attrs.setdefault(a["entity_type_id"], {})[a["name"]] = (
            f"{a['data_type']}" + (f" ({a['unit']})" if a["unit"] else "") + (" required" if a["required"] else ""))
    samples: dict[int, list[str]] = {}
    for row in db.execute(text(
            "SELECT entity_type_id, key FROM (SELECT e.entity_type_id, e.key, row_number() OVER"
            " (PARTITION BY e.entity_type_id ORDER BY e.sort_order, e.key) AS n FROM entity e"
            " JOIN entity_type t ON t.id = e.entity_type_id WHERE t.domain_id = :d) x WHERE n <= 5"),
            {"d": domain_id}).mappings():
        samples.setdefault(row["entity_type_id"], []).append(row["key"])
    rels = db.execute(text(
        "SELECT r.name, r.from_type_id, r.to_type_id, r.cardinality, r.is_hierarchy,"
        " (SELECT count(*) FROM relationship x WHERE x.relationship_type_id = r.id) AS links"
        " FROM relationship_type r WHERE r.domain_id = :d ORDER BY r.name"), {"d": domain_id}).mappings().all()
    params = db.execute(text(
        "SELECT p.name, p.index_type_ids, p.default_value, p.unit,"
        " (SELECT count(*) FROM parameter_value v WHERE v.parameter_def_id = p.id) AS cells"
        " FROM parameter_def p WHERE p.domain_id = :d ORDER BY p.name"), {"d": domain_id}).mappings().all()
    maps = db.execute(text(
        "SELECT d.id, d.name, d.placement, d.source->>'filename' AS file, (SELECT json_agg(json_build_object('layer', l.name, 'features', l.feature_count))"
        " FROM gis_layer l WHERE l.dataset_id = d.id) AS layers FROM gis_dataset d WHERE d.domain_id = :d"
        " ORDER BY d.updated_at DESC"), {"d": domain_id}).mappings().all()
    problems = db.execute(text(
        "SELECT p.id, p.name, (SELECT count(*) FROM model_version v WHERE v.problem_id = p.id) AS versions,"
        " (SELECT max(v.id) FROM model_version v WHERE v.problem_id = p.id) AS latest_version,"
        " (SELECT json_agg(json_build_object('id', s.id, 'name', s.name)) FROM scenario s WHERE s.problem_id = p.id)"
        " AS scenarios FROM problem p WHERE p.domain_id = :d ORDER BY p.id"), {"d": domain_id}).mappings().all()
    return {
        "domain": {"id": domain["id"], "name": domain["name"]},
        "kinds_of_record": [{"name": t["name"], "role": t["role"], "records": t["records"],
                             "fields": attrs.get(t["id"], {}), "some_keys": samples.get(t["id"], [])} for t in types],
        "relationship_types": [{"name": r["name"], "from": names.get(r["from_type_id"]), "to": names.get(r["to_type_id"]),
                                "cardinality": r["cardinality"], "hierarchy": r["is_hierarchy"], "links": r["links"]}
                               for r in rels],
        "data_values": [{"name": p["name"], "index": [names.get(i, i) for i in (p["index_type_ids"] or [])],
                         "default": float(p["default_value"]) if p["default_value"] is not None else None,
                         "unit": p["unit"], "cells": p["cells"]} for p in params],
        "map_data": [{"id": m["id"], "name": m["name"], "file": m["file"], "placement": m["placement"],
                      "layers": m["layers"] or []}
                     for m in maps],
        "problems": [dict(p) for p in problems],
        "data_sources": _data_sources(db, user, domain_id),
        # Files kept in the workspace (migration 0115): what a build loaded from an attached file, by version.
        "files": [{"name": f["name"], "latest_version": f["latest"], "versions": f["versions"], "rows": f["rows"],
                   "updated_at": f["updated_at"]} for f in _kept_files(db, domain_id)],
        "refresh_schedule": _refresh_schedule(db, domain_id),
    }


def _refresh_schedule(db: Session, domain_id: int) -> dict | None:
    """The workspace's scheduled refresh (migration 0116): how often, what it does, and how its last run went."""
    row = db.execute(text("SELECT every_hours, mode, solve, enabled, next_at, last_at, last_error,"
                          " last_report->'changes' AS changes, last_report->'applied' AS applied,"
                          " jsonb_array_length(coalesce(last_report->'runs', '[]'::jsonb)) AS runs"
                          " FROM source_schedule WHERE domain_id = :d"), {"d": domain_id}).mappings().one_or_none()
    return dict(row) if row else None


def _kept_files(db: Session, domain_id: int) -> list[dict]:
    from app.integrations.refresh import files

    return files(db, domain_id)


def _data_sources(db: Session, user: UserAccount, domain_id: int) -> list[dict]:
    """The domain's database connections, for someone allowed to read them: each one's table and columns, its
    last extraction (when, how many rows, or why it failed) and what its rows were loaded into. The Assistant
    pulls one in with `use_source`; credentials and hosts are never shown."""
    if "integration.run" not in capabilities_of(db, user):
        return []
    rows = db.execute(text(
        "SELECT c.id, c.name, c.enabled, c.config->>'schema' AS schema_name, c.config->>'table' AS table_name,"
        " c.config->>'kind' AS kind, c.config->>'url' AS url, coalesce(c.config->>'engine', 'postgres') AS engine,"
        " c.config->'columns' AS columns,"
        " (SELECT json_build_object('job_id', j.id, 'state', j.state, 'finished_at', j.finished_at,"
        "    'error_code', j.error_code) FROM ingestion_job j WHERE j.connection_id = c.id ORDER BY j.id DESC LIMIT 1)"
        "   AS last_extraction,"
        " (SELECT json_agg(DISTINCT x.name) FROM ("
        "    SELECT coalesce(e.name, rt.name, p.name) AS name FROM import_load l JOIN ingestion_job j"
        "    ON j.id = l.job_id LEFT JOIN entity_type e ON e.id = l.entity_type_id"
        "    LEFT JOIN relationship_type rt ON rt.id = l.relationship_type_id"
        "    LEFT JOIN parameter_def p ON p.id = l.parameter_id WHERE j.connection_id = c.id"
        "    UNION SELECT b.target FROM source_binding b WHERE b.connection_id = c.id) x) AS loaded_into"
        " FROM integration_connection c WHERE c.domain_id = :d AND c.organization_id = :o ORDER BY c.id"),
        {"d": domain_id, "o": user.organization_id}).mappings().all()
    return [{"id": r["id"], "name": r["name"], "enabled": r["enabled"],
             **({"web_address": r["url"]} if r["kind"] == "http" else {"table": f"{r['schema_name']}.{r['table_name']}",
                                                                          "engine": r["engine"]}),
             "columns": r["columns"] or [],
             "last_extraction": r["last_extraction"], "loaded_into": r["loaded_into"] or []} for r in rows]


@router.get("/sources/{job_id}/file")
def source_file(job_id: int, db: Session = Depends(get_db), user=Depends(requires("integration.run"))) -> dict:
    """An extracted source as an attached file (`use_source`): the same tables `read_file`, `query_file` and a
    plan's *_from_file read, its rows checked against the extraction's SHA-256, and where they came from."""
    from app.integrations import artifacts, refresh

    job = refresh.job_row(db, job_id, user.organization_id)
    if job is None:
        raise HTTPException(404, "Ingestion job not found")
    try:
        return refresh.job_sheet(job, user.organization_id)
    except (artifacts.ArtifactUnavailable, artifacts.ArtifactChanged) as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/result/{run_id}")
def result(run_id: int, db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict:
    """A run's answer as the assistant reports it (`read_result`): goal and its parts, each decision joined
    with its records' names and numbers, per-record totals, rules held / tight / broken -- from the run's
    own frozen data (app/agent/result.py)."""
    from app.agent import result as agent_result
    from app.api.run_export import _record

    rec = _record(db, run_id)
    if rec.get("domain_id") is not None:
        rec["map_placed"] = any(
            (p or {}).get("kind") == "local" and (p or {}).get("anchor") is not None
            for (p,) in db.execute(text("SELECT placement FROM gis_dataset WHERE domain_id = :d"),
                                   {"d": rec["domain_id"]}).all())
    points = db.execute(text("SELECT seq, first_value, second_value, status, point_run_id, goal_values"
                             " FROM pareto_point WHERE run_id = :r ORDER BY seq"), {"r": run_id}).all()
    if points:
        # A trade-off front: each point's two goal values and what it chooses, from its own run.
        rec["front"] = []
        for seq, first, second, status, point_run, goal_values in points:
            chosen: dict[str, list[str]] = {}
            if point_run is not None:
                point = db.execute(text("SELECT assignments FROM solution WHERE run_id = :r"),
                                   {"r": point_run}).scalar()
                for var, cells in (point or {}).items():
                    keys = [" · ".join(map(str, c)) for c in cells or [] if isinstance(c, list)
                            and not (c and isinstance(c[-1], (int, float)) and not isinstance(c[-1], bool))]
                    if keys:
                        chosen[var] = keys
            rec["front"].append({"seq": seq, "first": first, "second": second, "status": status,
                                 "values": goal_values if isinstance(goal_values, list) else [first, second],
                                 "run_id": point_run, "chosen": chosen})
    return {"text": agent_result.summary(rec), "facts": agent_result.facts(rec)}


#: The same read-back, under the runs it belongs to: a person reads it on the run's page without the Assistant
#: (owner, 9 October 2026).
explanation_router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


@explanation_router.get("/{run_id}/explanation")
def explanation(run_id: int, db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict:
    """A run's answer in words: the goal and its parts, what each decision chose with its records' names and
    numbers, per-record totals, room left and busy time, rules held / tight / broken, what a change of a number
    would do while the plan stays the same, routes and layouts -- what the Assistant reads (`read_result`)."""
    return result(run_id, db, user)
