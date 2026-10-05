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
from app.api.deps import capabilities_of, get_current_user, oauth2_scheme
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
    else:
        messages = [m.model_dump(exclude_none=True) for m in body.messages]
        files = list(body.files or [])
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
        messages.append({"role": "user", "content": body.text.strip()})

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

    def stream() -> Iterator[bytes]:
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
                    steps += kind == "tool"
                    if kind in ("answer", "error", "confirm", "plan", "built"):
                        last = event
                    if body.server_history and kind == "state":
                        # Kept here, not sent back whole: the browser shows the turn, the server holds it.
                        _keep(body.conversation_id, owner, organization, body.mode, event["messages"],
                              agent.ctx.files)
                        event = {"type": "state", "messages": [], "wrote": event.get("wrote"),
                                 "stored": {"messages": len(event["messages"]),
                                            "tokens": len(json.dumps(event["messages"], ensure_ascii=False,
                                                                     default=str)) // 2}}
                    elif body.server_history and kind == "file":
                        event = {"type": "file", "file": _light(event["file"])}
                    events.put(event)
            except BaseException as exc:  # noqa: BLE001 -- logged, then the stream ends as before
                ending = f"crashed: {type(exc).__name__}: {exc}"
                raise
            finally:
                events.put(done)
                text_ = str((last or {}).get("text") or "")
                logger.info("assistant.turn", user=user.username, conversation=body.conversation_id,
                            mode=body.mode, seconds=round(time.monotonic() - started, 1), tool_calls=steps,
                            ended_with=(last or {}).get("type") or "nothing", ending=ending,
                            text=text_[:400], history_messages=len(messages))

        threading.Thread(target=work, daemon=True, name="assistant").start()
        while True:
            try:
                event = events.get(timeout=10)
            except queue.Empty:
                yield b'{"type": "ping"}\n'
                continue
            if event is done:
                return
            yield (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode()

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _light(file: dict[str, Any]) -> dict[str, Any]:
    """An attached file as the browser shows it: names and counts, not rows (the server keeps those)."""
    return {**file, "sheets": [{**s, "rows": []} for s in file.get("sheets") or []]}


def _keep(conversation_id: str, owner: str, organization: str, mode: str, messages: list, files: list) -> None:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        agent_store.save(db, conversation_id, owner, organization, mode, messages, files)


@router.delete("/conversations/{conversation_id}", status_code=204, response_class=Response)
def forget(conversation_id: str, db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> Response:
    """A new chat: the old conversation is no longer needed."""
    agent_store.delete(db, conversation_id, str(user.id))
    return Response(status_code=204)


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
    }


@router.get("/result/{run_id}")
def result(run_id: int, db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict:
    """A run's answer as the assistant reports it (`read_result`): goal and its parts, each decision joined
    with its records' names and numbers, per-record totals, rules held / tight / broken -- from the run's
    own frozen data (app/agent/result.py)."""
    from app.agent import result as agent_result
    from app.api.run_export import _record

    return {"text": agent_result.summary(_record(db, run_id))}
