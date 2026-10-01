"""Camps: a camp kept as records of its domain, drawn on the map, solved and shown on the map.

    GET    /api/v1/camps?domain_id=                 the domain's camps (records of type camp), each with its latest solve
    POST   /api/v1/camps                            {domain_id, name, start: blank|small|complex, problem?}
    POST   /api/v1/camps/check                      {problem} -> faults and the door zones it implies
    POST   /api/v1/camps/import                     a .dxf or .xlsx file -> {problem, notes} (stores nothing)
    POST   /api/v1/camps/from-map                   {domain_id, name, dataset_id, boundary, doors, obstacles, prohibited,
                                                    zones} (layer ids of imported map data) -> a new camp
    GET    /api/v1/camps/{id}                       the camp as a problem, its check, its solves and its records
    PUT    /api/v1/camps/{id}                       {name?, problem?, options?, updated_at?} -> written to its records
    DELETE /api/v1/camps/{id}                       the camp and its records
    GET    /api/v1/camps/{id}/export?format=xlsx|dxf|json
    POST   /api/v1/camps/{id}/solves                {solver?, beds_seconds?, seconds?} -> queued solve
    GET    /api/v1/camp-solves/{id}                 status, progress and, when done, the result
    POST   /api/v1/camp-solves/{id}/cancel
    GET    /api/v1/camp-solves/{id}/files/{name}    output_wgs84.geojson, output_local.geojson,
                                                    input_wgs84.geojson, input_local.geojson,
                                                    report.json, layout.json, viewer.html

**A camp is domain data** (`app.camp.domain`): a `camp` record, its doors,
areas, zones and bed types as records, linked by relationships and tuned by
parameters -- the same records the Records, Relationships and Parameters
pages show, and edits there are what the next solve reads. The editor works
on the camp as a `camp-problem/1` problem in the camp's own frame; saving
writes it back to the records. A camp's id is its record's id.

A solve freezes the problem as it was asked, so editing the camp never
changes an answer already given. Solves run in the worker (`app.camp.jobs`).

Writes need `domain.edit`; asking for a solve needs `run.submit`, as a run does.
"""
from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import get_current_user, requires
from app.camp import domain as records
from app.camp import jobs, service
from app.camp.engine import serial
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["camps"])

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_PROBLEM_BYTES = 2 * 1024 * 1024
FILES = {
    "output_wgs84.geojson", "output_local.geojson", "input_wgs84.geojson", "input_local.geojson",
    "report.json", "layout.json", "viewer.html",
}


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    start: Literal["blank", "small", "complex"] = "blank"
    problem: dict[str, Any] | None = None
    origin_lonlat: tuple[float, float] | None = None


class FromMapBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    dataset_id: int = Field(gt=0)
    boundary: int = Field(gt=0)
    doors: list[int] = []
    obstacles: list[int] = []
    prohibited: list[int] = []
    zones: list[int] = []


class SaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    problem: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    #: The version the editor started from; a newer save by someone else is refused, not overwritten.
    updated_at: datetime | None = None


class CheckBody(BaseModel):
    problem: dict[str, Any]


class SolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    solver: Literal["cpsat", "scip", "highs", "cbc", "heuristic"] | None = None
    beds_seconds: int | None = Field(default=None, ge=5, le=1800)
    seconds: int | None = Field(default=None, ge=5, le=1800)


def _domain(db: Session, domain_id: int, user: UserAccount) -> None:
    found = db.execute(text("SELECT id FROM domain WHERE id = :d AND organization_id = :o"),
                       {"d": domain_id, "o": user.organization_id}).scalar_one_or_none()
    if found is None:
        raise HTTPException(404, "Domain not found")


def _camp(db: Session, camp_id: int, user: UserAccount) -> Any:
    row = records.camp_row(db, camp_id, user.organization_id)
    if row is None:
        raise HTTPException(404, "Camp not found")
    return row


def _solve(db: Session, solve_id: int, user: UserAccount) -> Any:
    row = db.execute(text(
        "SELECT s.*, extract(epoch FROM coalesce(s.finished_at, now()) - coalesce(s.started_at, now()))::float AS seconds"
        " FROM camp_solve s WHERE s.id = :i AND s.organization_id = :o"),
        {"i": solve_id, "o": user.organization_id}).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Solve not found")
    return row


def _audit(db: Session, user: UserAccount, action: str, identity: int) -> None:
    audit.record(db, organization_id=user.organization_id, actor_id=user.id,
                 api_key_id=getattr(user, "api_key_id", None), action=action,
                 object_type="camp", object_id=identity)


def _checked_problem(problem: dict[str, Any]) -> dict[str, Any]:
    """The problem in its stored shape, or a 422 naming what is not a camp problem.
    A drawing that is not yet solvable is stored: the check says what is missing."""
    if len(json.dumps(problem)) > MAX_PROBLEM_BYTES:
        raise HTTPException(413, "the camp is larger than 2 MB of shapes")
    try:
        return serial.to_dict(serial.from_dict(service.normalised(problem)))
    except serial.ProblemFormatError as exc:
        raise HTTPException(422, [{"type": "value_error", "loc": ["body", "problem"], "msg": str(exc),
                                   "input": None}]) from exc


def _write(db: Session, domain_id: int, problem: dict[str, Any], *, camp_id: int | None = None,
           options: dict[str, Any] | None = None) -> int:
    try:
        return records.write_problem(db, domain_id, problem, camp_id=camp_id, options=options)
    except Exception as exc:  # noqa: BLE001 -- a record the database refuses (a key, a type) is the sender's
        from sqlalchemy.exc import DBAPIError
        if isinstance(exc, DBAPIError):
            db.rollback()
            detail = str(getattr(exc, "orig", exc)).splitlines()[0][:300]
            raise HTTPException(422, f"the camp could not be written as records: {detail}") from exc
        raise


def _solve_summary(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "status": row["status"], "beds": row["beds"], "valid": row["valid"],
        "error": row["error"], "options": row["options"], "queued_at": row["queued_at"],
        "started_at": row["started_at"], "finished_at": row["finished_at"],
    }


@router.get("/camps")
def list_camps(
    domain_id: int = Query(gt=0),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    _domain(db, domain_id, user)
    rows = db.execute(text(
        "SELECT e.id, coalesce(e.label, e.key) AS name, e.key, e.updated_at, e.attrs -> 'origin' -> 'coordinates' AS origin_lonlat,"
        " (SELECT count(*) FROM relationship r JOIN relationship_type rt ON rt.id = r.relationship_type_id"
        "   WHERE rt.name = 'door_of' AND r.to_entity_id = e.id) AS doors,"
        " l.id AS solve_id, l.status, l.beds, l.valid, l.finished_at"
        " FROM entity e JOIN entity_type t ON t.id = e.entity_type_id AND t.name = 'camp'"
        " LEFT JOIN LATERAL (SELECT id, status, beds, valid, finished_at FROM camp_solve"
        "   WHERE camp_entity_id = e.id ORDER BY id DESC LIMIT 1) l ON true"
        " WHERE t.domain_id = :d AND t.organization_id = :o ORDER BY e.updated_at DESC"),
        {"d": domain_id, "o": user.organization_id}).mappings().all()
    return {"items": [dict(r) for r in rows], "structure": bool(records.types(db, domain_id))}


@router.post("/camps", status_code=201)
def create_camp(
    body: CreateBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    _domain(db, body.domain_id, user)
    if body.problem is not None:
        problem = _checked_problem({**body.problem, "name": body.name})
    elif body.start == "blank":
        problem = service.blank(body.name, body.origin_lonlat or (31.60, 30.10))
    else:
        problem = service.example(body.start, body.name)
        if body.origin_lonlat:
            problem["origin_lonlat"] = list(body.origin_lonlat)
    camp_id = _write(db, body.domain_id, problem, options=jobs.DEFAULT_OPTIONS)
    if body.problem is None and body.start == "complex":
        # The example arrives laid out: its layout ships with the engine, so it shows at once.
        done = jobs.example_result(problem)
        if done is not None:
            db.execute(text(
                "INSERT INTO camp_solve (organization_id, domain_id, camp_entity_id, camp_name, problem, options,"
                " created_by, status, progress, result, beds, valid, started_at, finished_at)"
                " VALUES (:o, :d, :c, :n, CAST(:pr AS jsonb), CAST(:opt AS jsonb), :u, 'done', CAST(:pg AS jsonb),"
                " CAST(:r AS jsonb), :b, true, now(), now())"),
                {"o": user.organization_id, "d": body.domain_id, "c": camp_id, "n": problem["name"],
                 "pr": json.dumps(problem), "opt": json.dumps(jobs.DEFAULT_OPTIONS), "u": str(user.id),
                 "pg": json.dumps([{"at": round(time.time(), 1),
                                    "line": "the example's layout, as shipped with the engine (a long CP-SAT run)"}]),
                 "r": json.dumps(done, default=str), "b": done["beds"]})
    _audit(db, user, "camp.create", camp_id)
    db.commit()
    return get_camp(camp_id, db, user)


@router.post("/camps/from-map", status_code=201)
def create_from_map(
    body: FromMapBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    """A camp from layers of imported map data, each layer given a role."""
    from app.camp.from_gis import FromMapError, build

    _domain(db, body.domain_id, user)
    found = db.execute(text("SELECT id FROM gis_dataset WHERE id = :d AND organization_id = :o AND domain_id = :dom"),
                       {"d": body.dataset_id, "o": user.organization_id, "dom": body.domain_id}).scalar_one_or_none()
    if found is None:
        raise HTTPException(404, "Map data not found in this domain")
    roles = {"boundary": [body.boundary], "doors": body.doors, "obstacles": body.obstacles,
             "prohibited": body.prohibited, "zones": body.zones}
    layers = set(db.execute(text("SELECT id FROM gis_layer WHERE dataset_id = :d"), {"d": body.dataset_id}).scalars())
    stray = {i for ids in roles.values() for i in ids} - layers
    if stray:
        raise HTTPException(422, f"layer {sorted(stray)[0]} is not in this map data")
    try:
        problem, notes = build(db, body.dataset_id, roles, body.name)
    except FromMapError as exc:
        raise HTTPException(422, str(exc)) from exc
    camp_id = _write(db, body.domain_id, problem, options=jobs.DEFAULT_OPTIONS)
    _audit(db, user, "camp.create", camp_id)
    db.commit()
    return {**get_camp(camp_id, db, user), "notes": notes}


@router.post("/camps/check")
def check_camp(body: CheckBody, user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    if len(json.dumps(body.problem)) > MAX_PROBLEM_BYTES:
        raise HTTPException(413, "the camp is larger than 2 MB of shapes")
    return service.check(body.problem)


@router.post("/camps/import")
def import_drawing(
    file: UploadFile = File(...),
    units: Literal["", "mm", "cm", "m", "in", "ft"] = Form(""),
    crs: str = Form("", max_length=60),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    """A CAD drawing or a camp workbook as a problem for the editor. Nothing is stored."""
    from camp_layout.dxf import DrawingError
    from camp_layout.workbook import dxf_to_problem, read_workbook

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".dxf", ".xlsx"):
        raise HTTPException(415, "send a .dxf drawing or a camp .xlsx workbook")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "the file is larger than 30 MB")
    name = Path(file.filename or "camp").stem.replace("_", " ")[:200] or "camp"
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"upload{suffix}"
        path.write_bytes(data)
        try:
            if suffix == ".dxf":
                problem, offset, notes = dxf_to_problem(str(path), name=name, units=units or None, crs=crs or None)
            else:
                problem, offset, notes = read_workbook(path), (0.0, 0.0), ["read the workbook"]
        except DrawingError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 -- a file we cannot read is the sender's to fix
            raise HTTPException(422, f"could not read the file: {str(exc)[:300] or type(exc).__name__}") from exc
    data_out = serial.to_dict(problem)
    return {"problem": data_out, "notes": notes, "offset": list(offset), "check": service.check(data_out)}


@router.get("/camps/{camp_id}")
def get_camp(
    camp_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    camp = _camp(db, camp_id, user)
    problem, _ = records.to_problem(db, camp_id, user.organization_id)
    solves = db.execute(text(
        "SELECT id, status, beds, valid, error, options, queued_at, started_at, finished_at FROM camp_solve"
        " WHERE camp_entity_id = :i ORDER BY id DESC LIMIT 20"), {"i": camp_id}).mappings().all()
    kinds = records.types(db, camp["domain_id"])
    counts: dict[str, int] = {}
    for k in records.children(db, camp_id):
        counts[k["type"]] = counts.get(k["type"], 0) + 1
    return {
        "id": camp_id, "domain_id": camp["domain_id"], "key": camp["key"], "name": camp["label"] or camp["key"],
        "problem": problem, "options": jobs.options_of(records.options_of(camp)), "updated_at": camp["updated_at"],
        "created_at": camp["updated_at"], "check": service.check(problem),
        "solves": [_solve_summary(s) for s in solves],
        "records": {"types": kinds, "counts": {"camp": 1, **counts}},
    }


@router.put("/camps/{camp_id}")
def save_camp(
    camp_id: int,
    body: SaveBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> dict[str, Any]:
    camp = _camp(db, camp_id, user)
    if body.updated_at is not None and abs((camp["updated_at"] - body.updated_at).total_seconds()) > 0.001:
        raise HTTPException(409, "someone saved this camp since you opened it; reload to see their changes")
    current, _ = records.to_problem(db, camp_id, user.organization_id)
    name = body.name or camp["label"] or camp["key"]
    problem = _checked_problem({**(body.problem or current), "name": name})
    options = jobs.options_of({**records.options_of(camp), **(body.options or {})})
    _write(db, camp["domain_id"], problem, camp_id=camp_id, options=options)
    _audit(db, user, "camp.save", camp_id)
    db.commit()
    return get_camp(camp_id, db, user)


@router.delete("/camps/{camp_id}", status_code=204)
def delete_camp(
    camp_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("domain.edit")),
) -> Response:
    _camp(db, camp_id, user)
    records.delete_camp(db, camp_id)
    _audit(db, user, "camp.delete", camp_id)
    db.commit()
    return Response(status_code=204)


@router.get("/camps/{camp_id}/export")
def export_camp(
    camp_id: int,
    format: Literal["xlsx", "dxf", "json"] = "xlsx",
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> Response:
    from camp_layout.dxf import write_dxf
    from camp_layout.workbook import write_workbook

    _camp(db, camp_id, user)
    problem_data, camp = records.to_problem(db, camp_id, user.organization_id)
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in (camp["label"] or camp["key"]))[:60] or "camp"
    if format == "json":
        return Response(json.dumps(problem_data, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.json"'})
    problem = serial.from_dict(service.normalised(problem_data))
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"{stem}.{format}"
        if format == "xlsx":
            write_workbook(problem, path)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            write_dxf(problem, str(path))
            media = "application/dxf"
        content = path.read_bytes()
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{stem}.{format}"'})


@router.post("/camps/{camp_id}/solves", status_code=201)
def solve_camp(
    camp_id: int,
    body: SolveBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("run.submit")),
) -> dict[str, Any]:
    camp = _camp(db, camp_id, user)
    problem, _ = records.to_problem(db, camp_id, user.organization_id)
    check = service.check(problem)
    if not check["ok"]:
        first = next(f for f in check["faults"] if f["severity"] == "error")
        raise HTTPException(422, f"fix the camp first: {first['where']} {first['message']}")
    busy = db.execute(text("SELECT count(*) FROM camp_solve WHERE camp_entity_id = :i AND status IN ('queued', 'running')"),
                      {"i": camp_id}).scalar_one()
    if busy:
        raise HTTPException(409, "this camp is already being laid out; wait for it or stop it")
    options = jobs.options_of({**records.options_of(camp), **body.model_dump(exclude_none=True)})
    solve_id = db.execute(text(
        "INSERT INTO camp_solve (organization_id, domain_id, camp_entity_id, camp_name, problem, options, created_by)"
        " VALUES (:o, :d, :c, :n, CAST(:pr AS jsonb), CAST(:opt AS jsonb), :u) RETURNING id"),
        {"o": user.organization_id, "d": camp["domain_id"], "c": camp_id, "n": camp["label"] or camp["key"],
         "pr": json.dumps(problem), "opt": json.dumps(options), "u": str(user.id)}).scalar_one()
    _audit(db, user, "camp.solve", camp_id)
    db.commit()
    return get_solve(solve_id, False, db, user)


@router.get("/camp-solves/{solve_id}")
def get_solve(
    solve_id: int,
    include_result: bool = True,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    row = _solve(db, solve_id, user)
    out = {
        **_solve_summary(row), "camp_id": row["camp_entity_id"], "camp_name": row["camp_name"],
        "domain_id": row["domain_id"], "seconds": round(row["seconds"], 1),
        "progress": [p["line"] for p in row["progress"][-200:]],
        "deadline_seconds": jobs.deadline_of(jobs.options_of(row["options"])),
        "problem": row["problem"], "result": None,
    }
    if include_result and row["result"]:
        result = row["result"]
        out["result"] = {k: result.get(k) for k in ("input", "output", "report", "origin_lonlat", "bearing", "beds", "valid")}
    return out


@router.post("/camp-solves/{solve_id}/cancel")
def cancel_solve(
    solve_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("run.submit")),
) -> dict[str, Any]:
    row = _solve(db, solve_id, user)
    if row["status"] in ("queued", "running"):
        db.execute(text("UPDATE camp_solve SET cancel_requested = true,"
                        " status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE status END,"
                        " finished_at = CASE WHEN status = 'queued' THEN now() ELSE finished_at END"
                        " WHERE id = :i"), {"i": solve_id})
        db.commit()
    return get_solve(solve_id, False, db, user)


@router.get("/camp-solves/{solve_id}/files/{name}")
def solve_file(
    solve_id: int,
    name: str,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> Response:
    from camp_layout import export

    if name not in FILES:
        raise HTTPException(404, f"no file {name!r}; one of {', '.join(sorted(FILES))}")
    row = _solve(db, solve_id, user)
    result = row["result"]
    if not result:
        raise HTTPException(409, "this solve has no answer yet")
    origin, bearing = result["origin_lonlat"], float(result.get("bearing") or 0)
    collection = lambda feats, label: {"type": "FeatureCollection", "name": label, "features": feats}
    if name == "viewer.html":
        body = export.viewer_html(result["input"]["features"], result["output"]["features"], result["report"], origin)
        media = "text/html"
    else:
        if name.endswith(".geojson"):
            part, crs = name.removesuffix(".geojson").split("_")
            feats = result[part]["features"]
            if crs == "wgs84":
                feats = export.to_wgs84(feats, origin, bearing)
            data = collection(feats, f"camp {'input' if part == 'input' else 'layout'}, "
                                     f"{'WGS84' if crs == 'wgs84' else 'local metres'}")
            media = "application/geo+json"
        else:
            data = result["report"] if name == "report.json" else result["layout"]
            media = "application/json"
        body = json.dumps(data, default=str)
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in row["camp_name"])[:60] or "camp"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{stem}-{name}"'})
