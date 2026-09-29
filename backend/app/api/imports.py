"""From an extraction to domain data (Epic UX, U-4).

    GET  /api/v1/connections/{id}/jobs              a connection's jobs, newest first, each with its loads
    GET  /api/v1/ingestion-jobs/{id}/preview        the artifact's columns and first rows
    POST /api/v1/ingestion-jobs/{id}/validate       check it against a mapping; nothing is written
    POST /api/v1/ingestion-jobs/{id}/load           write a validated mapping; its lineage recorded

A mapping names the entity type the rows become and, for each source column
used, the target column: `key`, `label`, `sort_order`, `active` or an attribute
-- the columns of that type's upload template. Validation runs every row
through exactly the code a file upload runs (`bulk.entity_writer`,
`bulk.run_rows`): each value parsed as its column's type, then written inside a
savepoint so the database's own rules speak, then all of it rolled back. The
report says which row (the n-th extracted row) and column, and why. A load
repeats that for real, only for a mapping validated clean on the same artifact
(same SHA-256), and only once per job and mapping; the data it wrote carries
the artifact's hash and the mapping's hash in `import_load`. The run that
next snapshots the domain (`snapshot_dataset`) freezes it, hash and all.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit
from app.api import bulk
from app.api.deps import capabilities_of, requires
from app.core.db import get_db
from app.integrations import artifacts
from app.models.v1_domain import EntityType

router = APIRouter(prefix="/api/v1", tags=["imports"])

PREVIEW_MAX = 200


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type_id: int = Field(gt=0)
    #: source column -> target column, in the order the report lists them.
    columns: dict[str, str] = Field(min_length=1, max_length=200)


class LoadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validation_id: int = Field(gt=0)


def _job(db: Session, job_id: int, organization_id) -> dict:
    row = db.execute(text(
        "SELECT j.id, j.state, j.artifact_id, j.connection_id, c.domain_id, c.name AS connection_name"
        " FROM ingestion_job j JOIN integration_connection c ON c.id = j.connection_id"
        " WHERE j.id = :id AND j.organization_id = :o"), {"id": job_id, "o": organization_id}).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Ingestion job not found")
    return dict(row)


def _artifact(job: dict, organization_id):
    if job["state"] != "extracted" or job["artifact_id"] is None:
        raise HTTPException(409, f"This job has no extracted rows to read (it is {job['state']}).")
    try:
        path = artifacts.folder(organization_id, job["connection_id"], job["artifact_id"])
        return path, artifacts.manifest(path)
    except artifacts.ArtifactUnavailable as exc:
        raise HTTPException(409, str(exc)) from None


def mapping_hash(mapping: Mapping) -> str:
    canonical = json.dumps({"entity_type_id": mapping.entity_type_id, "columns": sorted(mapping.columns.items())},
                           sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@router.get("/connections/{connection_id}/jobs")
def list_jobs(connection_id: int, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db), user=Depends(requires("integration.run"))) -> dict:
    params = {"c": connection_id, "o": user.organization_id, "l": limit, "p": offset}
    exists = db.execute(text("SELECT 1 FROM integration_connection WHERE id = :c AND organization_id = :o"), params).first()
    if exists is None:
        raise HTTPException(404, "Connection not found")
    jobs = [dict(r) for r in db.execute(text(
        "SELECT id, state, cancel_requested, created_at, started_at, finished_at, artifact_id, error_code"
        " FROM ingestion_job WHERE connection_id = :c AND organization_id = :o ORDER BY id DESC LIMIT :l OFFSET :p"),
        params).mappings()]
    total = db.execute(text("SELECT count(*) FROM ingestion_job WHERE connection_id = :c AND organization_id = :o"), params).scalar_one()
    loads = {}
    if jobs:
        for r in db.execute(text(
                "SELECT l.id, l.job_id, l.entity_type_id, e.name AS entity_type, l.rows_written, l.artifact_sha256,"
                " l.mapping_hash, l.created_at FROM import_load l JOIN entity_type e ON e.id = l.entity_type_id"
                " WHERE l.job_id = ANY(:ids) ORDER BY l.id"), {"ids": [j["id"] for j in jobs]}).mappings():
            loads.setdefault(r["job_id"], []).append(dict(r))
    for job in jobs:
        job["loads"] = loads.get(job["id"], [])
    return {"items": jobs, "total": total}


@router.get("/ingestion-jobs/{job_id}/preview")
def preview(job_id: int, limit: int = Query(20, ge=1, le=PREVIEW_MAX), db: Session = Depends(get_db),
            user=Depends(requires("integration.run"))) -> dict:
    job = _job(db, job_id, user.organization_id)
    path, manifest = _artifact(job, user.organization_id)
    return {
        "job_id": job_id,
        "columns": manifest.get("columns", []),
        "source_schema": manifest.get("source_schema", []),
        "source_object": manifest.get("source_object"),
        "rows_total": manifest.get("rows", 0),
        "sha256": manifest.get("sha256"),
        "completed_at": manifest.get("completed_at"),
        "rows": artifacts.head(path, limit),
    }


def _check(db: Session, job: dict, manifest: dict, mapping: Mapping, path, *, write: bool, before_commit=None,
           user=None, request=None) -> tuple[bulk.UploadReport, EntityType]:
    entity_type = db.get(EntityType, mapping.entity_type_id)
    if entity_type is None or entity_type.domain_id != job["domain_id"]:
        raise HTTPException(422, "Choose an entity type of this connection's domain.")
    if entity_type.is_abstract:
        raise HTTPException(422, f"{entity_type.name!r} is abstract and holds no entities of its own.")
    unknown = [c for c in mapping.columns if c not in manifest.get("columns", [])]
    if unknown:
        raise HTTPException(422, f"Not columns of this extraction: {', '.join(unknown)}.")
    header = list(mapping.columns.values())
    sources = list(mapping.columns.keys())
    try:
        records = artifacts.verified_rows(path, manifest.get("sha256", ""), bulk.MAX_ROWS)
    except artifacts.ArtifactChanged as exc:
        raise HTTPException(409, str(exc)) from None
    except artifacts.ArtifactUnavailable as exc:
        raise HTTPException(409, str(exc)) from None
    rows = [[record.get(source) for source in sources] for record in records]
    columns, writer = bulk.entity_writer(db, entity_type, header)
    report = bulk.run_rows(db, header, rows, columns, writer, clean_only=False, dry_run=not write,
                           user=user, request=request, audit_object=("entity_type", entity_type.id) if write else None,
                           before_commit=before_commit)
    # In the planner's terms: the n-th extracted row (a file's header is its row 1), and a mapping fault as row 0.
    target_to_source = {target: source for source, target in mapping.columns.items()}
    faults = []
    for fault in report.faults:
        header_fault = fault.row == 1 and fault.message in ("is not a column of this template", "appears more than once",
                                                            "is required and missing")
        column = fault.column
        if column in target_to_source:
            column = f"{target_to_source[column]} → {column}"
        faults.append(bulk.Fault(row=0 if header_fault else fault.row - 1, column=column,
                                 message=f"mapping: {fault.message}" if header_fault else fault.message))
    return report.model_copy(update={"faults": faults}), entity_type


@router.post("/ingestion-jobs/{job_id}/validate")
def validate(job_id: int, mapping: Mapping, db: Session = Depends(get_db),
             user=Depends(requires("integration.run"))) -> dict:
    job = _job(db, job_id, user.organization_id)
    path, manifest = _artifact(job, user.organization_id)
    report, entity_type = _check(db, job, manifest, mapping, path, write=False)
    identity = db.execute(text(
        "INSERT INTO import_validation (job_id, entity_type_id, mapping, mapping_hash, artifact_sha256, rows, ok, faults,"
        " validated_by) VALUES (:j, :e, CAST(:m AS jsonb), :mh, :sha, :rows, :ok, CAST(:f AS jsonb), :u) RETURNING id"),
        {"j": job_id, "e": entity_type.id, "m": mapping.model_dump_json(), "mh": mapping_hash(mapping),
         "sha": manifest["sha256"], "rows": report.rows, "ok": report.ok,
         "f": json.dumps([f.model_dump() for f in report.faults]), "u": user.id}).scalar_one()
    db.commit()
    # A check writes nothing, so what it would write is every row without a fault (none, if the mapping is at fault).
    mapping_at_fault = any(f.row == 0 for f in report.faults)
    would_write = 0 if mapping_at_fault else report.rows - len({f.row for f in report.faults})
    return {"validation_id": identity, "ok": report.ok, "rows": report.rows, "would_write": would_write,
            "faults": [f.model_dump() for f in report.faults], "entity_type": entity_type.name,
            "artifact_sha256": manifest["sha256"], "mapping_hash": mapping_hash(mapping)}


@router.post("/ingestion-jobs/{job_id}/load")
def load(job_id: int, body: LoadBody, request: Request, db: Session = Depends(get_db),
         user=Depends(requires("integration.run"))) -> dict:
    if "domain.edit" not in capabilities_of(db, user):
        raise HTTPException(403, "this account does not have the 'domain.edit' capability")
    job = _job(db, job_id, user.organization_id)
    validation = db.execute(text(
        "SELECT id, entity_type_id, mapping, mapping_hash, artifact_sha256, ok FROM import_validation"
        " WHERE id = :v AND job_id = :j AND organization_id = :o"),
        {"v": body.validation_id, "j": job_id, "o": user.organization_id}).mappings().one_or_none()
    if validation is None:
        raise HTTPException(404, "Validation not found for this job")
    if not validation["ok"]:
        raise HTTPException(409, "This mapping did not validate clean; fix the faults and validate again before loading.")
    earlier = db.execute(text("SELECT id FROM import_load WHERE job_id = :j AND mapping_hash = :h"),
                         {"j": job_id, "h": validation["mapping_hash"]}).scalar_one_or_none()
    if earlier is not None:
        raise HTTPException(409, f"This extraction was already loaded with this mapping (load {earlier}).")
    path, manifest = _artifact(job, user.organization_id)
    if manifest.get("sha256") != validation["artifact_sha256"]:
        raise HTTPException(409, "The extracted rows are not the ones validated; validate again.")
    mapping = Mapping.model_validate(validation["mapping"])
    loaded: dict = {}

    def lineage(written: int) -> None:
        loaded["id"] = db.execute(text(
            "INSERT INTO import_load (job_id, validation_id, entity_type_id, mapping_hash, artifact_sha256, rows_written,"
            " loaded_by) VALUES (:j, :v, :e, :mh, :sha, :n, :u) RETURNING id"),
            {"j": job_id, "v": validation["id"], "e": validation["entity_type_id"], "mh": validation["mapping_hash"],
             "sha": validation["artifact_sha256"], "n": written, "u": user.id}).scalar_one()
        audit.write(db, user, request, action="import.load", object_type="ingestion_job", object_id=job_id,
                    after={"entity_type_id": validation["entity_type_id"], "rows": written,
                           "artifact_sha256": validation["artifact_sha256"], "mapping_hash": validation["mapping_hash"]})

    report, entity_type = _check(db, job, manifest, mapping, path, write=True, before_commit=lineage,
                                 user=user, request=request)
    if not report.ok:
        # The domain changed since validation (a key taken, a rule added): nothing was written.
        raise HTTPException(409, detail={"message": "The rows no longer load cleanly; nothing was written.",
                                         "faults": [f.model_dump() for f in report.faults]})
    return {"load_id": loaded["id"], "rows_written": report.written, "entity_type": entity_type.name,
            "artifact_sha256": validation["artifact_sha256"], "mapping_hash": validation["mapping_hash"]}
