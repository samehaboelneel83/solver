"""A domain's data refreshed from its database sources (app/integrations/refresh.py, migration 0114).

    GET  /api/v1/domains/{domain_id}/source-bindings          what came from which source, through which mapping
    POST /api/v1/domains/{domain_id}/sources/refresh          {"jobs": {connection_id: job_id}?, "apply": false,
                                                                "remove_missing": true, "connections": [ids]?}

Without `apply` it only reports, per binding, what the newer extraction would change: records added, fields
changed, records gone (set inactive, not deleted), links and values added, changed, gone. With `apply` it writes
all of it in one transaction (nothing on any refusal) and marks the bindings with the extraction applied. Without
`jobs`, each connection's latest successful extraction is used; run a fresh extraction first for today's data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import capabilities_of, requires
from app.core.db import get_db
from app.integrations import artifacts, refresh

router = APIRouter(prefix="/api/v1", tags=["imports"])


class FileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: dict[str, Any] = Field(description="a file as /api/v1/agent/files read it: {name, sheets: [...]}")


class RefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jobs: dict[int, int] | None = Field(default=None, description="connection id -> extraction (job) id to use")
    files: dict[str, int] | None = Field(default=None, description="workspace file name -> version to use")
    connections: list[int] | None = Field(default=None, description="only these connections' bindings")
    apply: bool = False
    remove_missing: bool = True
    solve: bool = Field(default=False, description="after applying: solve again every scenario that reads the data")


def _domain(db: Session, domain_id: int, organization_id) -> None:
    if db.execute(text("SELECT 1 FROM domain WHERE id = :d AND organization_id = :o"),
                  {"d": domain_id, "o": organization_id}).first() is None:
        raise HTTPException(404, "Domain not found")


@router.get("/domains/{domain_id}/files")
def list_files(domain_id: int, db: Session = Depends(get_db), user=Depends(requires("integration.run"))) -> dict:
    """The files kept in this workspace, each with its latest version."""
    _domain(db, domain_id, user.organization_id)
    return {"items": refresh.files(db, domain_id)}


@router.post("/domains/{domain_id}/files", status_code=201)
def add_file(domain_id: int, body: FileBody, request: Request, db: Session = Depends(get_db),
             user=Depends(requires("domain.edit"))) -> dict:
    """Keep a file (as /api/v1/agent/files read it) in the workspace: a new version of its name, unless the latest
    version has the same content. Nothing in the domain changes until a refresh applies it."""
    _domain(db, domain_id, user.organization_id)
    if not refresh.keepable({**body.file, "source": None}) or not body.file.get("sheets"):
        raise HTTPException(422, f"a workspace keeps table files (CSV, Excel, JSON) of at most {refresh.FILE_ROWS:,} rows")
    kept = refresh.save_file(db, domain_id, body.file, user.id)
    if kept["new"]:
        audit.write(db, user, request, action="domain.file.add", object_type="domain", object_id=domain_id,
                    after={"file": kept["name"], "version": kept["version"], "sha256": kept["sha256"]})
    db.commit()
    return kept


@router.get("/domains/{domain_id}/files/{name}")
def get_file(domain_id: int, name: str, version: int | None = Query(None, ge=1), db: Session = Depends(get_db),
             user=Depends(requires("integration.run"))) -> dict:
    _domain(db, domain_id, user.organization_id)
    found = refresh.file_sheet(db, domain_id, name, version)
    if found is None:
        raise HTTPException(404, "No such file (or version) in this workspace")
    return found


@router.get("/domains/{domain_id}/source-bindings")
def list_bindings(domain_id: int, db: Session = Depends(get_db), user=Depends(requires("integration.run"))) -> dict:
    _domain(db, domain_id, user.organization_id)
    return {"items": refresh.bindings(db, domain_id)}


class BindingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_name: str = Field(min_length=1, max_length=255, description="a file kept in this workspace")
    kind: Literal["entities", "relationships", "parameter_values"]
    target: str = Field(min_length=1, max_length=200, description="the kind of record, relationship type or parameter")
    mapping: dict[str, Any] = Field(description="as an *_from_file entry: sheet, key, label, attrs; from, to; "
                                                "entities, value")


def _target_exists(db: Session, domain_id: int, kind: str, target: str) -> bool:
    table = {"entities": "entity_type", "relationships": "relationship_type", "parameter_values": "parameter_def"}[kind]
    return db.execute(text(f"SELECT 1 FROM {table} WHERE domain_id = :d AND name = :n"),
                      {"d": domain_id, "n": target}).first() is not None


@router.post("/domains/{domain_id}/source-bindings", status_code=201)
def bind_file(domain_id: int, body: BindingBody, request: Request, db: Session = Depends(get_db),
              user=Depends(requires("domain.edit"))) -> dict:
    """Load a kept file's table into records, links or values and keep them refreshed from it -- what a plan
    built from a file does, without the Assistant (owner, 9 October 2026). The mapping is checked against the
    file's latest version now; nothing is written until a refresh applies it (its first one loads every row)."""
    _domain(db, domain_id, user.organization_id)
    sheet = refresh.file_sheet(db, domain_id, body.file_name)
    if sheet is None:
        raise HTTPException(404, "No such file in this workspace; keep it first")
    if not _target_exists(db, domain_id, body.kind, body.target):
        raise HTTPException(422, detail=[{"loc": ["target"], "msg": f"{body.target!r} is not one of this domain's "
                                          + {"entities": "kinds of record", "relationships": "relationship types",
                                             "parameter_values": "parameters"}[body.kind]}])
    mapping = {k: v for k, v in body.mapping.items() if k not in ("file", "type", "parameter")}
    try:
        made = refresh._wanted({"kind": body.kind, "target": body.target, "mapping": mapping,
                                "connection": body.file_name}, sheet)
    except refresh.RefreshRefused as exc:
        raise HTTPException(422, detail=[{"loc": ["mapping"], "msg": str(exc)}]) from None
    refresh.record_bindings(db, domain_id, [{"file_name": body.file_name, "file_version": None, "sha256": None,
                                             "kind": body.kind, "target": body.target, "mapping": mapping}])
    audit.write(db, user, request, action="domain.source.bind", object_type="domain", object_id=domain_id,
                after={"file": body.file_name, "kind": body.kind, "target": body.target})
    db.commit()
    return {"bound": True, "rows": len(made)}


@router.delete("/domains/{domain_id}/source-bindings/{binding_id}", status_code=204, response_class=Response)
def unbind(domain_id: int, binding_id: int, request: Request, db: Session = Depends(get_db),
           user=Depends(requires("domain.edit"))) -> Response:
    """Stop keeping data refreshed from a source; what it loaded stays."""
    _domain(db, domain_id, user.organization_id)
    gone = db.execute(text("DELETE FROM source_binding WHERE id = :b AND domain_id = :d RETURNING kind, target"),
                      {"b": binding_id, "d": domain_id}).first()
    if gone is None:
        raise HTTPException(404, "No such binding in this domain")
    audit.write(db, user, request, action="domain.source.unbind", object_type="domain", object_id=domain_id,
                after={"binding": binding_id, "kind": gone[0], "target": gone[1]})
    db.commit()
    return Response(status_code=204)


@router.post("/domains/{domain_id}/sources/refresh")
def refresh_sources(domain_id: int, body: RefreshBody, request: Request, db: Session = Depends(get_db),
                    user=Depends(requires("integration.run"))) -> dict:
    _domain(db, domain_id, user.organization_id)
    held = capabilities_of(db, user)
    if body.apply and "domain.edit" not in held:
        raise HTTPException(403, "this account does not have the 'domain.edit' capability")
    if body.solve and "run.submit" not in held:
        raise HTTPException(403, "this account does not have the 'run.submit' capability")
    try:
        out = refresh.run_refresh(
            db, domain_id, user.organization_id, jobs=body.jobs, files=body.files, connections=body.connections,
            apply=body.apply, remove_missing=body.remove_missing,
            on_applied=lambda written: audit.write(db, user, request, action="domain.sources.refresh",
                                                   object_type="domain", object_id=domain_id,
                                                   after={"bindings": written}))
    except refresh.RefreshRefused as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from None
    if out["applied"] and body.solve and out["changes"]:
        out["runs"] = refresh.solve_again(db, domain_id, out)
    return out


class ScheduleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    every_hours: int = Field(ge=1, le=8760, description="how often: 24 for daily, 168 for weekly")
    mode: str = Field(default="report", pattern="^(report|apply)$",
                      description="report: keep what changed for a person to apply; apply: write it")
    solve: bool = Field(default=False, description="with apply: solve again every scenario that reads the data")
    enabled: bool = True
    first_at: datetime | None = Field(default=None, description="the first run (default: now)")


def _schedule(db: Session, domain_id: int) -> dict | None:
    row = db.execute(text(
        "SELECT every_hours, mode, solve, enabled, next_at, state, last_at, last_report, last_error, owner_id,"
        " (SELECT username FROM iam.user_account u WHERE u.id = s.owner_id) AS owner"
        " FROM source_schedule s WHERE domain_id = :d"), {"d": domain_id}).mappings().one_or_none()
    return {k: v for k, v in dict(row).items() if k != "owner_id"} if row else None


@router.get("/domains/{domain_id}/refresh-schedule")
def get_schedule(domain_id: int, db: Session = Depends(get_db), user=Depends(requires("integration.run"))) -> dict:
    """The workspace's scheduled refresh (or null), with its last run's report."""
    _domain(db, domain_id, user.organization_id)
    return {"schedule": _schedule(db, domain_id)}


@router.put("/domains/{domain_id}/refresh-schedule")
def set_schedule(domain_id: int, body: ScheduleBody, request: Request, db: Session = Depends(get_db),
                 user=Depends(requires("integration.run"))) -> dict:
    """Refresh this workspace from its sources every `every_hours`, as you, with your permissions at each run."""
    _domain(db, domain_id, user.organization_id)
    held = capabilities_of(db, user)
    for needed, why in (("domain.edit", True), ("run.submit", body.solve)):
        if why and needed not in held:
            raise HTTPException(403, f"this account does not have the {needed!r} capability")
    if body.solve and body.mode != "apply":
        raise HTTPException(422, "solving again needs mode 'apply': a report alone changes nothing to solve")
    if not refresh.bindings(db, domain_id):
        raise HTTPException(409, "Nothing in this workspace was built from a data source or a kept file yet, so a "
                                 "schedule would have nothing to refresh.")
    db.execute(text(
        "INSERT INTO source_schedule (domain_id, owner_id, every_hours, mode, solve, enabled, next_at)"
        " VALUES (:d, :u, :h, :m, :s, :e, coalesce(:first, now()))"
        " ON CONFLICT (domain_id) DO UPDATE SET owner_id = EXCLUDED.owner_id, every_hours = EXCLUDED.every_hours,"
        " mode = EXCLUDED.mode, solve = EXCLUDED.solve, enabled = EXCLUDED.enabled,"
        " next_at = CASE WHEN :first IS NULL THEN source_schedule.next_at ELSE EXCLUDED.next_at END,"
        " updated_at = now()"),
        {"d": domain_id, "u": user.id, "h": body.every_hours, "m": body.mode, "s": body.solve, "e": body.enabled,
         "first": body.first_at})
    audit.write(db, user, request, action="domain.sources.schedule", object_type="domain", object_id=domain_id,
                after=body.model_dump(mode="json"))
    db.commit()
    return {"schedule": _schedule(db, domain_id)}


@router.delete("/domains/{domain_id}/refresh-schedule", status_code=204, response_class=Response)
def delete_schedule(domain_id: int, request: Request, db: Session = Depends(get_db),
                    user=Depends(requires("domain.edit"))):
    _domain(db, domain_id, user.organization_id)
    db.execute(text("DELETE FROM source_schedule WHERE domain_id = :d"), {"d": domain_id})
    audit.write(db, user, request, action="domain.sources.schedule.delete", object_type="domain", object_id=domain_id)
    db.commit()
    return Response(status_code=204)


@router.post("/domains/{domain_id}/refresh-schedule/run-now")
def run_schedule_now(domain_id: int, db: Session = Depends(get_db), user=Depends(requires("domain.edit"))) -> dict:
    """Bring the next scheduled run forward to now (the ingestion worker picks it up within a minute)."""
    _domain(db, domain_id, user.organization_id)
    done = db.execute(text("UPDATE source_schedule SET next_at = now(), updated_at = now() WHERE domain_id = :d"
                           " AND state = 'idle' RETURNING domain_id"), {"d": domain_id}).first()
    if done is None:
        raise HTTPException(409, "No schedule, or it is running now")
    db.commit()
    return {"schedule": _schedule(db, domain_id)}
