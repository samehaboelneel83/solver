"""Domain-owned connections. No response exposes ciphertext or plaintext secrets."""
import json
from typing import Literal, Union
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app import audit
from app.api.deps import requires
from app.core.db import get_db
from app.integrations import secrets
from app.integrations.policy import source_for

router = APIRouter(prefix="/api/v1", tags=["integrations"])


class SourceBody(BaseModel):
    """A table or view in a database (app/integrations/postgres.py, databases.py). For Oracle, `database` is the
    service name and `schema` the owner; for MySQL / MariaDB, `schema` is the database the table is in."""
    model_config = ConfigDict(extra="forbid")
    engine: Literal["postgres", "mysql", "sqlserver", "oracle"] = "postgres"
    host: str = Field(min_length=1, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535, description="default: the engine's usual port")
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    schema_name: str = Field(alias="schema", min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    columns: list[str] = Field(min_length=1, max_length=200)
    changed_column: str = Field(default="", max_length=128, description="a column that grows when a row changes "
                                "(an update time or a version), one of `columns`: lets a read take only what changed")

    @model_validator(mode="after")
    def _changed_is_read(self):
        if self.changed_column and self.changed_column not in self.columns:
            raise ValueError("changed_column must be one of the columns read")
        return self


class HttpSourceBody(BaseModel):
    """A REST endpoint's JSON list, or a CSV / Excel file, read over HTTPS (app/integrations/http_source.py)."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["http"]
    url: str = Field(min_length=9, max_length=2000, pattern=r"^https://")
    format: Literal["json", "csv", "xlsx"]
    columns: list[str] = Field(min_length=1, max_length=200)
    auth: Literal["none", "bearer", "basic"] = "none"
    username: str = Field(default="", max_length=128)
    sheet: str = Field(default="", max_length=128)
    records_at: str = Field(default="", max_length=200, description='dotted path to the list in a JSON answer, e.g. "data.items"')
    paging: Literal["none", "next_link", "link_header", "page_number"] = "none"
    next_at: str = Field(default="", max_length=200, description='where the next page\'s address is, e.g. "next", "links.next", "@odata.nextLink"')
    page_param: str = Field(default="", max_length=64, description='the address\'s page parameter, e.g. "page"')
    first_page: int = Field(default=1, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def _paging_is_whole(self):
        if self.paging != "none" and self.format != "json":
            raise ValueError("pages are read for a JSON answer only")
        if self.paging == "next_link" and not self.next_at.strip():
            raise ValueError('paging by a next link needs next_at: where the link is in the answer, e.g. "next"')
        if self.paging == "page_number" and not self.page_param.strip():
            raise ValueError('paging by page number needs page_param: the address\'s page parameter, e.g. "page"')
        return self


class ConnectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    source: Union[HttpSourceBody, SourceBody]
    #: The database password, or the web source's token or password; none for a web source without a login.
    password: SecretStr | None = None


def _needs_secret(source) -> bool:
    return not (isinstance(source, HttpSourceBody) and source.auth == "none")


class CredentialBody(BaseModel):
    password: SecretStr


def _password(value):
    password = value.get_secret_value()
    if not password or len(password) > 4096:
        raise HTTPException(422, "A credential of 1–4096 characters is required")
    return password


def _connection(db, identity, org):
    row = db.execute(text("SELECT * FROM integration_connection WHERE id=:id AND organization_id=:org"), {"id": identity, "org": org}).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Connection not found")
    return row


def _audit(db, user, action, identity):
    audit.record(db, organization_id=user.organization_id, actor_id=user.id,
                 api_key_id=getattr(user, "api_key_id", None), action=action,
                 object_type="integration", object_id=identity)


@router.get("/connections")
def list_connections(domain_id: int = Query(gt=0), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), user=Depends(requires("integration.run"))):
    params = {"d": domain_id, "o": user.organization_id, "l": limit, "p": offset}
    rows = db.execute(text("SELECT id,domain_id,name,enabled,config,created_at,updated_at FROM integration_connection WHERE domain_id=:d AND organization_id=:o ORDER BY id LIMIT :l OFFSET :p"), params).mappings().all()
    total = db.execute(text("SELECT count(*) FROM integration_connection WHERE domain_id=:d AND organization_id=:o"), params).scalar_one()
    return {"items": [dict(row) for row in rows], "total": total}


@router.post("/connections", status_code=201)
def create_connection(body: ConnectionBody, db: Session = Depends(get_db), user=Depends(requires("integration.manage"))):
    if _needs_secret(body.source) and body.password is None:
        raise HTTPException(422, "A credential of 1–4096 characters is required")
    password = _password(body.password) if _needs_secret(body.source) else None
    domain = db.execute(text("SELECT id FROM domain WHERE id=:id AND organization_id=:o"), {"id": body.domain_id, "o": user.organization_id}).scalar_one_or_none()
    if domain is None:
        raise HTTPException(404, "Domain not found")
    config = body.source.model_dump(by_alias=True)
    if "engine" in config and config.get("port") is None:
        from app.integrations.databases import DEFAULT_PORTS

        config["port"] = DEFAULT_PORTS[config["engine"]]
    try:
        source_for({"config": config, "organization_id": user.organization_id, "id": 1})
    except ValueError:
        raise HTTPException(503, "Integration policy is unavailable or the source configuration is invalid") from None
    identity = db.execute(text("INSERT INTO integration_connection(domain_id,organization_id,name,config) VALUES (:d,:o,:n,CAST(:c AS jsonb)) RETURNING id"), {"d": body.domain_id, "o": user.organization_id, "n": body.name, "c": json.dumps(config)}).scalar_one()
    if password is not None:
        try:
            envelope = secrets.encrypt(password, user.organization_id, identity)
        except secrets.SecretUnavailable:
            db.rollback()
            raise HTTPException(503, "Integration keyring is unavailable") from None
        db.execute(text("UPDATE integration_connection SET credential=CAST(:s AS jsonb) WHERE id=:id"), {"s": json.dumps(envelope), "id": identity})
    _audit(db, user, "integration.connection.create", identity)
    db.commit()
    return {"id": identity, "domain_id": body.domain_id, "name": body.name, "enabled": True}


@router.put("/connections/{identity}/credential", status_code=204)
def rotate_credential(identity: int, body: CredentialBody, db: Session = Depends(get_db), user=Depends(requires("integration.manage"))):
    _connection(db, identity, user.organization_id)
    try:
        envelope = secrets.encrypt(_password(body.password), user.organization_id, identity)
    except secrets.SecretUnavailable:
        raise HTTPException(503, "Integration keyring is unavailable") from None
    db.execute(text("UPDATE integration_connection SET credential=CAST(:s AS jsonb),updated_at=now() WHERE id=:id"), {"s": json.dumps(envelope), "id": identity})
    _audit(db, user, "integration.credential.rotate", identity)
    db.commit()


@router.post("/connections/{identity}/disable", status_code=204)
def disable_connection(identity: int, db: Session = Depends(get_db), user=Depends(requires("integration.manage"))):
    _connection(db, identity, user.organization_id)
    db.execute(text("UPDATE integration_connection SET enabled=false,updated_at=now() WHERE id=:id"), {"id": identity})
    db.execute(text("UPDATE ingestion_job SET cancel_requested=true WHERE connection_id=:id AND state IN ('queued','running')"), {"id": identity})
    _audit(db, user, "integration.connection.disable", identity)
    db.commit()


class JobBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: Only the rows changed since the source's last read (migration 0118); needs the source's changed_column.
    incremental: bool = False


@router.post("/connections/{identity}/jobs", status_code=202)
def submit(identity: int, body: JobBody | None = None, db: Session = Depends(get_db),
           user=Depends(requires("integration.run"))):
    row = _connection(db, identity, user.organization_id)
    if not row["enabled"]:
        raise HTTPException(409, "Connection is disabled")
    incremental = bool(body and body.incremental)
    if incremental and not (row["config"] or {}).get("changed_column"):
        raise HTTPException(422, "This source names no changed column (an update time or a version), so it can only be "
                                 "read whole")
    try:
        job = db.execute(text("INSERT INTO ingestion_job(connection_id,organization_id,requested_by,incremental)"
                              " VALUES (:id,:o,:u,:inc) RETURNING id"),
                         {"id": identity, "o": user.organization_id, "u": user.id, "inc": incremental}).scalar_one()
        _audit(db, user, "integration.job.submit", job)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An ingestion job is already active") from None
    return {"id": job, "state": "queued", "incremental": incremental}


@router.get("/ingestion-jobs/{identity}")
def job_status(identity: int, db: Session = Depends(get_db), user=Depends(requires("integration.run"))):
    row = db.execute(text("SELECT id,connection_id,state,cancel_requested,created_at,started_at,finished_at,artifact_id,error_code,incremental FROM ingestion_job WHERE id=:id AND organization_id=:o"), {"id": identity, "o": user.organization_id}).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Ingestion job not found")
    return dict(row)


@router.post("/ingestion-jobs/{identity}/cancel", status_code=204)
def cancel(identity: int, db: Session = Depends(get_db), user=Depends(requires("integration.run"))):
    job_status(identity, db, user)
    db.execute(text("UPDATE ingestion_job SET cancel_requested=true WHERE id=:id AND organization_id=:o AND state IN ('queued','running')"), {"id": identity, "o": user.organization_id})
    _audit(db, user, "integration.job.cancel", identity)
    db.commit()
