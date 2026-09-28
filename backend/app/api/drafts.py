"""Server-saved model drafts and their publication (OAAS M2).

    GET    /api/v1/problems/{id}/draft                     -> the caller's draft, or 404
    PUT    /api/v1/problems/{id}/draft          {ir, base_version_id, expected_revision}
    DELETE /api/v1/problems/{id}/draft?expected_revision=N
    POST   /api/v1/problems/{id}/draft/publish  {expected_revision, note}  [Idempotency-Key]

One draft per person per problem, owned by the stable account id -- not
the username the browser's local store namespaces by. Nobody else reads or
writes it, an administrator included: a draft is work in progress, not a
shared record. Row-level security keeps it inside its organization as well.

Revisions, not timestamps
-------------------------
Every save names the revision it was built on (`expected_revision`; ``null``
to create the first one). A save built on anything else is refused with the
platform's stale-record 409 (`app.api.concurrency`), so a second tab or a
second browser cannot silently overwrite newer work. The row is read ``FOR
UPDATE`` so the comparison and the write cannot be split by a concurrent
save. The design proposal suggested ETag/If-Match and a 412; this module
keeps the platform's existing single body shape for "conflicts with the
row's current state" instead (Ruling 19), which the browser already
recognises.

A draft is not validated as a model
-----------------------------------
Drafts may be incomplete. Only its shape is checked (a JSON object within
the size limit); the IR contract is applied at publication, to the exact
revision being published, inside the same transaction that locks it.

Publication is idempotent
-------------------------
Publishing validates the locked revision, inserts the next immutable
`model_version`, deletes the draft and records the request -- one commit.
With an ``Idempotency-Key``, a retry of the same request (same revision,
same note) returns the version the first attempt created, with 200 rather
than 201, instead of publishing twice; the same key with a different
request is refused. Without a key, the revision check alone still stops a
double submit: the first publish deletes the draft, so the second finds
nothing to publish.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.api.concurrency import stale_record_conflict
from app.api.deps import requires
from app.api.problems import (
    ModelVersionRead,
    _check_ir,
    _get_problem,
    _version_columns,
)
from app.api.validation import field_error
from app.core.db import get_db
from app.crud.db_errors import translate_db_error
from app.models.iam import UserAccount
from app.models.v1_problem import ModelVersion

router = APIRouter(prefix="/api/v1", tags=["drafts"])

#: The same ceiling the browser's backup restore uses.
MAX_DRAFT_BYTES = 5 * 1024 * 1024
#: Printable ASCII, as for run submission's Idempotency-Key.
MAX_KEY_LENGTH = 128

_DRAFT_COLUMNS = (
    "id, problem_id, base_version_id, ir, revision, created_at, updated_at,"
    " (SELECT v.version FROM model_version v WHERE v.id = model_draft.base_version_id) AS base_version"
)


class DraftRead(BaseModel):
    id: int
    problem_id: int
    base_version_id: int | None
    #: The number of the version it started from, for "started from version N".
    base_version: int | None
    ir: dict[str, Any]
    revision: int
    created_at: datetime
    updated_at: datetime


class DraftSave(BaseModel):
    ir: dict[str, Any]
    base_version_id: int | None = None
    #: The revision this save was built on; null creates the first one.
    expected_revision: int | None = Field(default=None, ge=1)


class DraftPublish(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str | None = None


def _locked_draft(db: Session, problem_id: int, owner_id) -> dict[str, Any] | None:
    row = db.execute(
        text(
            f"SELECT {_DRAFT_COLUMNS} FROM model_draft"
            " WHERE problem_id = :p AND owner_id = :o FOR UPDATE"
        ),
        {"p": problem_id, "o": owner_id},
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def _check_size(ir: dict[str, Any]) -> None:
    size = len(json.dumps(ir, separators=(",", ":")).encode())
    if size > MAX_DRAFT_BYTES:
        raise field_error(
            "ir", f"a draft may be at most {MAX_DRAFT_BYTES // (1024 * 1024)} MB; this one is {size} bytes", None
        )


def _idempotency_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = raw.strip()
    if not key or len(key) > MAX_KEY_LENGTH or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise HTTPException(
            status_code=422,
            detail=f"Idempotency-Key must be 1–{MAX_KEY_LENGTH} printable ASCII characters",
        )
    return key


def _digest(payload: DraftPublish) -> str:
    body = json.dumps({"expected_revision": payload.expected_revision, "note": payload.note}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def _prior_publication(db: Session, problem_id: int, actor_id, key: str, digest: str) -> ModelVersionRead | None:
    prior = db.execute(
        text(
            "SELECT model_version_id, request_digest FROM model_publication"
            " WHERE problem_id = :p AND actor_id = :a AND idempotency_key = :k"
        ),
        {"p": problem_id, "a": actor_id, "k": key},
    ).mappings().one_or_none()
    if prior is None:
        return None
    if prior["request_digest"] != digest:
        raise HTTPException(
            status_code=409,
            detail="This Idempotency-Key was already used for a different publish request."
            " Use a new key for a new request.",
        )
    row = db.execute(
        ModelVersion.__table__.select().where(_version_columns.id == prior["model_version_id"])
    ).mappings().one()
    return ModelVersionRead.model_validate(dict(row))


@router.get("/problems/{problem_id}/draft")
def get_draft(
    problem_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("model.publish")),
) -> DraftRead:
    _get_problem(db, problem_id)
    row = db.execute(
        text(f"SELECT {_DRAFT_COLUMNS} FROM model_draft WHERE problem_id = :p AND owner_id = :o"),
        {"p": problem_id, "o": user.id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="no draft")
    return DraftRead.model_validate(dict(row))


@router.put("/problems/{problem_id}/draft")
def save_draft(
    problem_id: int,
    payload: DraftSave,
    response: Response,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("model.publish")),
) -> DraftRead:
    _get_problem(db, problem_id)
    _check_size(payload.ir)
    if payload.base_version_id is not None:
        owner = db.execute(
            select(_version_columns.problem_id).where(_version_columns.id == payload.base_version_id)
        ).scalar_one_or_none()
        if owner != problem_id:
            raise field_error(
                "base_version_id",
                f"model version {payload.base_version_id} is not a version of problem {problem_id}",
                payload.base_version_id,
            )
    current = _locked_draft(db, problem_id, user.id)
    params = {
        "p": problem_id,
        "o": user.id,
        "b": payload.base_version_id,
        "ir": json.dumps(payload.ir),
    }
    try:
        if current is None:
            if payload.expected_revision is not None:
                # It was published or discarded elsewhere after this client read it.
                raise stale_record_conflict("draft")
            row = db.execute(
                text(
                    "INSERT INTO model_draft (problem_id, owner_id, base_version_id, ir)"
                    f" VALUES (:p, :o, :b, CAST(:ir AS jsonb)) RETURNING {_DRAFT_COLUMNS}"
                ),
                params,
            ).mappings().one()
            response.status_code = 201
        else:
            if payload.expected_revision != current["revision"]:
                raise stale_record_conflict("draft")
            row = db.execute(
                text(
                    "UPDATE model_draft SET ir = CAST(:ir AS jsonb), base_version_id = :b,"
                    " revision = revision + 1"
                    f" WHERE id = :id RETURNING {_DRAFT_COLUMNS}"
                ),
                {**params, "id": current["id"]},
            ).mappings().one()
        db.commit()
    except IntegrityError as exc:
        # Two first saves raced; the other one won the (problem, owner) key.
        db.rollback()
        if "model_draft_problem_id_owner_id_key" in str(exc.orig):
            raise stale_record_conflict("draft") from exc
        raise translate_db_error(exc, "model_draft") from exc
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, "model_draft") from exc
    except HTTPException:
        db.rollback()
        raise
    return DraftRead.model_validate(dict(row))


@router.delete("/problems/{problem_id}/draft", status_code=204)
def discard_draft(
    problem_id: int,
    expected_revision: int = Query(ge=1),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("model.publish")),
) -> Response:
    _get_problem(db, problem_id)
    current = _locked_draft(db, problem_id, user.id)
    if current is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="no draft")
    if current["revision"] != expected_revision:
        db.rollback()
        raise stale_record_conflict("draft")
    db.execute(text("DELETE FROM model_draft WHERE id = :id"), {"id": current["id"]})
    db.commit()
    return Response(status_code=204)


@router.post("/problems/{problem_id}/draft/publish", status_code=201)
def publish_draft(
    problem_id: int,
    payload: DraftPublish,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("model.publish")),
) -> ModelVersionRead:
    problem = _get_problem(db, problem_id)
    key = _idempotency_key(idempotency_key)
    digest = _digest(payload)
    # Lock first: a concurrent retry waits here, and once the first attempt
    # commits it finds the draft gone and its publication recorded.
    current = _locked_draft(db, problem_id, user.id)
    if key is not None:
        prior = _prior_publication(db, problem_id, user.id, key, digest)
        if prior is not None:
            db.rollback()
            response.status_code = 200
            return prior
    if current is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="no draft")
    if current["revision"] != payload.expected_revision:
        db.rollback()
        raise stale_record_conflict("draft")
    # Validated under the lock: exactly the revision being published.
    _check_ir(db, problem, current["ir"])
    try:
        row = db.execute(
            insert(ModelVersion.__table__)
            .values(problem_id=problem_id, ir=current["ir"], note=payload.note)
            .returning(*_version_columns)
        ).mappings().one()
        if key is not None:
            db.execute(
                text(
                    "INSERT INTO model_publication"
                    " (problem_id, actor_id, idempotency_key, request_digest, model_version_id)"
                    " VALUES (:p, :a, :k, :d, :v)"
                ),
                {"p": problem_id, "a": user.id, "k": key, "d": digest, "v": row["id"]},
            )
        db.execute(text("DELETE FROM model_draft WHERE id = :id"), {"id": current["id"]})
        audit.write(
            db, user, request,
            action="model.publish",
            object_type="model_version",
            object_id=row["id"],
            after={
                "problem_id": problem_id,
                "version": row["version"],
                "note": payload.note,
                "draft_revision": current["revision"],
            },
        )
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, "model_version") from exc
    return ModelVersionRead.model_validate(dict(row))


__all__ = ["router", "MAX_DRAFT_BYTES"]
