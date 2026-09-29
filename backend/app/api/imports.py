"""From an extraction to domain data (Epic UX, U-4).

    GET  /api/v1/connections/{id}/jobs              a connection's jobs, newest first, each with its loads
    GET  /api/v1/ingestion-jobs/{id}/preview        the artifact's columns and first rows
    POST /api/v1/ingestion-jobs/{id}/validate       check it against a mapping; nothing is written
    POST /api/v1/ingestion-jobs/{id}/load           write a validated mapping; its lineage recorded

A mapping names what the rows become and, for each source column used, the
target column -- the columns of that target's upload template:

- an entity type (`entity_type_id`): `key`, `label`, `sort_order`, `active`
  or an attribute;
- a relationship type (`relationship_type_id`): `from` and `to` (the two
  entities' keys), `valid_from`, `valid_to` or an attribute of the link;
- a parameter (`parameter_id`): one key column per index, named as in its
  template, and `value`. Validation runs every row
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
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit
from app.api import bulk
from app.api.deps import capabilities_of, requires
from app.core.db import get_db
from app.integrations import artifacts
from app.models.v1_domain import EntityType, ParameterDef, RelationshipType

router = APIRouter(prefix="/api/v1", tags=["imports"])

PREVIEW_MAX = 200


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: What the rows become: exactly one of these.
    entity_type_id: int | None = Field(default=None, gt=0)
    relationship_type_id: int | None = Field(default=None, gt=0)
    parameter_id: int | None = Field(default=None, gt=0)
    #: source column -> target column, in the order the report lists them.
    columns: dict[str, str] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _one_target(self) -> "Mapping":
        named = [v for v in (self.entity_type_id, self.relationship_type_id, self.parameter_id) if v is not None]
        if len(named) != 1:
            raise ValueError("name exactly one of entity_type_id, relationship_type_id or parameter_id")
        return self

    @property
    def target(self) -> tuple[str, int]:
        if self.entity_type_id is not None:
            return "entity_type", self.entity_type_id
        if self.relationship_type_id is not None:
            return "relationship_type", self.relationship_type_id
        return "parameter", self.parameter_id  # type: ignore[return-value]


@dataclass(frozen=True)
class Target:
    """What a mapping writes into, in the words the report and the lineage use."""

    kind: str  # entity_type | relationship_type | parameter
    id: int
    name: str
    #: What one written row is, for "12 records written".
    noun: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "id": self.id, "name": self.name}


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
    # An entity mapping hashes as it always has, so earlier loads still match it.
    kind, identity = mapping.target
    canonical = json.dumps({f"{kind}_id": identity,
                            "columns": sorted(mapping.columns.items())},
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
                "SELECT l.id, l.job_id, l.entity_type_id, l.relationship_type_id, l.parameter_id,"
                " e.name AS entity_type, rt.name AS relationship_type, p.name AS parameter,"
                " l.rows_written, l.artifact_sha256, l.mapping_hash, l.created_at FROM import_load l"
                " LEFT JOIN entity_type e ON e.id = l.entity_type_id"
                " LEFT JOIN relationship_type rt ON rt.id = l.relationship_type_id"
                " LEFT JOIN parameter_def p ON p.id = l.parameter_id"
                " WHERE l.job_id = ANY(:ids) ORDER BY l.id"), {"ids": [j["id"] for j in jobs]}).mappings():
            load = dict(r)
            kind = ("entity_type" if load["entity_type_id"] else
                    "relationship_type" if load["relationship_type_id"] else "parameter")
            load["target"] = {"kind": kind, "id": load[f"{kind}_id"], "name": load[kind]}
            loads.setdefault(r["job_id"], []).append(load)
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


def _writer(db: Session, job: dict, mapping: Mapping, header: list[str]) -> tuple[Target, list, object]:
    """The target a mapping names, its template's columns and the writer the file upload uses for it."""
    kind, identity = mapping.target
    if kind == "entity_type":
        entity_type = db.get(EntityType, identity)
        if entity_type is None or entity_type.domain_id != job["domain_id"]:
            raise HTTPException(422, "Choose an entity type of this connection's domain.")
        if entity_type.is_abstract:
            raise HTTPException(422, f"{entity_type.name!r} is abstract and holds no entities of its own.")
        columns, writer = bulk.entity_writer(db, entity_type, header)
        return Target(kind, identity, entity_type.name, "records"), columns, writer
    if kind == "relationship_type":
        rel = db.get(RelationshipType, identity)
        if rel is None or rel.domain_id != job["domain_id"]:
            raise HTTPException(422, "Choose a relationship type of this connection's domain.")
        try:
            bulk._mirror(db, rel)
        except HTTPException as exc:
            raise HTTPException(422, exc.detail) from None
        columns, writer = bulk.relationship_writer(db, rel, header)
        return Target(kind, identity, rel.name, "links"), columns, writer
    parameter = db.get(ParameterDef, identity)
    if parameter is None or parameter.domain_id != job["domain_id"]:
        raise HTTPException(422, "Choose a parameter of this connection's domain.")
    columns, writer = bulk.parameter_writer(db, parameter)
    return Target(kind, identity, parameter.name, "values"), columns, writer


def _check(db: Session, job: dict, manifest: dict, mapping: Mapping, path, *, write: bool, before_commit=None,
           user=None, request=None) -> tuple[bulk.UploadReport, Target]:
    header = list(mapping.columns.values())
    target, columns, writer = _writer(db, job, mapping, header)
    unknown = [c for c in mapping.columns if c not in manifest.get("columns", [])]
    if unknown:
        raise HTTPException(422, f"Not columns of this extraction: {', '.join(unknown)}.")
    sources = list(mapping.columns.keys())
    try:
        records = artifacts.verified_rows(path, manifest.get("sha256", ""), bulk.MAX_ROWS)
    except artifacts.ArtifactChanged as exc:
        raise HTTPException(409, str(exc)) from None
    except artifacts.ArtifactUnavailable as exc:
        raise HTTPException(409, str(exc)) from None
    rows = [[record.get(source) for source in sources] for record in records]
    report = bulk.run_rows(db, header, rows, columns, writer, clean_only=False, dry_run=not write,
                           user=user, request=request, audit_object=(target.kind, target.id) if write else None,
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
        message = f"mapping: {fault.message}" if header_fault else fault.message
        # A required attribute no column feeds fails every row; say the fix, not only the fact (operator trial F24).
        unfed = _REQUIRED.search(message)
        if unfed and unfed.group(1) not in target_to_source:
            message += f": map a column onto {unfed.group(1)} (each column feeds one target)"
        faults.append(bulk.Fault(row=0 if header_fault else fault.row - 1, column=column, message=message))
    return report.model_copy(update={"faults": faults}), target


_REQUIRED = re.compile(r'attribute "([^"]+)" is required')


def _empty(value) -> bool:
    return value is None or str(value).strip() == ""


def _defaults_taken(db: Session, target: Target, mapping: Mapping, records: list[dict]) -> list[dict]:
    """Where an empty or unmapped value will take a default: no fault, but not what the source said (F25)."""
    if target.kind == "parameter":
        parameter = db.get(ParameterDef, target.id)
        defaults = {"value": parameter.default_value} if parameter is not None else {}
    else:
        attributes = (bulk._attributes(db, entity_type_id=target.id) if target.kind == "entity_type"
                      else bulk._attributes(db, relationship_type_id=target.id))
        defaults = {a.name: a.default_value for a in attributes if a.default_value is not None}
    target_to_source = {t: s for s, t in mapping.columns.items()}
    notices = []
    for name, default in defaults.items():
        source = target_to_source.get(name)
        if source is None:
            if target.kind != "parameter":
                notices.append({"column": name, "rows": len(records), "default": default,
                                "message": f"no column feeds {name}; new records take the default {default}"})
            continue
        rows = [i + 1 for i, record in enumerate(records) if _empty(record.get(source))]
        if rows:
            shown = ", ".join(str(r) for r in rows[:10]) + ("…" if len(rows) > 10 else "")
            notices.append({"column": f"{source} → {name}", "rows": len(rows), "default": default,
                            "message": f"{len(rows)} {'row is' if len(rows) == 1 else 'rows are'} empty (row {shown})"
                                       f" and will take the default {default}"})
    return notices


def _target_columns(target: Target) -> dict:
    return {f"{kind}_id": (target.id if kind == target.kind else None)
            for kind in ("entity_type", "relationship_type", "parameter")}


@router.post("/ingestion-jobs/{job_id}/validate")
def validate(job_id: int, mapping: Mapping, db: Session = Depends(get_db),
             user=Depends(requires("integration.run"))) -> dict:
    job = _job(db, job_id, user.organization_id)
    path, manifest = _artifact(job, user.organization_id)
    report, target = _check(db, job, manifest, mapping, path, write=False)
    notices = _defaults_taken(db, target, mapping, artifacts.verified_rows(path, manifest.get("sha256", ""), bulk.MAX_ROWS))
    identity = db.execute(text(
        "INSERT INTO import_validation (job_id, entity_type_id, relationship_type_id, parameter_id, mapping, mapping_hash,"
        " artifact_sha256, rows, ok, faults, validated_by) VALUES (:j, :entity_type_id, :relationship_type_id,"
        " :parameter_id, CAST(:m AS jsonb), :mh, :sha, :rows, :ok, CAST(:f AS jsonb), :u) RETURNING id"),
        {"j": job_id, **_target_columns(target), "m": mapping.model_dump_json(exclude_none=True), "mh": mapping_hash(mapping),
         "sha": manifest["sha256"], "rows": report.rows, "ok": report.ok,
         "f": json.dumps([f.model_dump() for f in report.faults]), "u": user.id}).scalar_one()
    db.commit()
    # A check writes nothing, so what it would write is every row without a fault (none, if the mapping is at fault).
    mapping_at_fault = any(f.row == 0 for f in report.faults)
    would_write = 0 if mapping_at_fault else report.rows - len({f.row for f in report.faults})
    return {"validation_id": identity, "ok": report.ok, "rows": report.rows, "would_write": would_write,
            "faults": [f.model_dump() for f in report.faults], "defaults": notices,
            "target": target.as_dict(), "noun": target.noun,
            **({"entity_type": target.name} if target.kind == "entity_type" else {}),
            "artifact_sha256": manifest["sha256"], "mapping_hash": mapping_hash(mapping)}


@router.post("/ingestion-jobs/{job_id}/load")
def load(job_id: int, body: LoadBody, request: Request, db: Session = Depends(get_db),
         user=Depends(requires("integration.run"))) -> dict:
    if "domain.edit" not in capabilities_of(db, user):
        raise HTTPException(403, "this account does not have the 'domain.edit' capability")
    job = _job(db, job_id, user.organization_id)
    validation = db.execute(text(
        "SELECT id, mapping, mapping_hash, artifact_sha256, ok FROM import_validation"
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
    kind, identity = mapping.target
    targets = {f"{k}_id": (identity if k == kind else None) for k in ("entity_type", "relationship_type", "parameter")}
    loaded: dict = {}

    def lineage(written: int) -> None:
        loaded["id"] = db.execute(text(
            "INSERT INTO import_load (job_id, validation_id, entity_type_id, relationship_type_id, parameter_id,"
            " mapping_hash, artifact_sha256, rows_written, loaded_by) VALUES (:j, :v, :entity_type_id,"
            " :relationship_type_id, :parameter_id, :mh, :sha, :n, :u) RETURNING id"),
            {"j": job_id, "v": validation["id"], **targets, "mh": validation["mapping_hash"],
             "sha": validation["artifact_sha256"], "n": written, "u": user.id}).scalar_one()
        audit.write(db, user, request, action="import.load", object_type="ingestion_job", object_id=job_id,
                    after={f"{kind}_id": identity, "rows": written,
                           "artifact_sha256": validation["artifact_sha256"], "mapping_hash": validation["mapping_hash"]})

    report, target = _check(db, job, manifest, mapping, path, write=True, before_commit=lineage,
                            user=user, request=request)
    if not report.ok:
        # The domain changed since validation (a key taken, a rule added): nothing was written.
        raise HTTPException(409, detail={"message": "The rows no longer load cleanly; nothing was written.",
                                         "faults": [f.model_dump() for f in report.faults]})
    return {"load_id": loaded["id"], "rows_written": report.written, "target": target.as_dict(), "noun": target.noun,
            **({"entity_type": target.name} if target.kind == "entity_type" else {}),
            "artifact_sha256": validation["artifact_sha256"], "mapping_hash": validation["mapping_hash"]}
