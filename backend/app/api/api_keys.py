"""API keys: credentials for programs (migration 0035).

    POST   /api/v1/api-keys       create one; the token is in this response only
    GET    /api/v1/api-keys       yours -- or, with `iam.manage`, your organization's
    DELETE /api/v1/api-keys/{id}  revoke: yours, or any in your organization with `iam.manage`

A key is made by a person signed in, never by another key: a leaked key must
not be able to mint the next one. It carries a subset of its maker's
capabilities, chosen at creation (all of them if none are named), and on
every request it is further limited to what the maker holds then.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import capabilities_of, get_current_user
from app.core import api_keys
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["api keys"])


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # None: every capability the maker holds. An empty list is a key that can
    # only read what needs no capability -- allowed, and sometimes wanted.
    capabilities: list[str] | None = None
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


def _row(row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "prefix": row["prefix"],
        "user_id": str(row["user_id"]),
        "username": row["username"],
        "capabilities": sorted(row["capabilities"]),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
    }


_SELECT = (
    "SELECT k.id, k.name, k.prefix, k.user_id, u.username, k.capabilities, k.created_at,"
    "       k.expires_at, k.last_used_at, k.revoked_at"
    "  FROM iam.api_key k JOIN iam.user_account u ON u.id = k.user_id"
)


def _refuse_a_key_acting(user: UserAccount) -> None:
    if getattr(user, "api_key_id", None):
        raise HTTPException(
            status_code=403,
            detail="API keys are managed by a person signed in, not by another key",
        )


@router.post("/api-keys", status_code=201)
def create_key(
    payload: ApiKeyCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    _refuse_a_key_acting(user)
    held = capabilities_of(db, user)
    wanted = held if payload.capabilities is None else set(payload.capabilities)
    beyond = sorted(wanted - held)
    if beyond:
        raise HTTPException(
            status_code=403,
            detail=f"a key can have only capabilities its maker holds; this account lacks {', '.join(beyond)}",
        )
    prefix, secret_hash, token = api_keys.mint()
    expires = (
        datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)
        if payload.expires_in_days
        else None
    )
    key_id = db.execute(
        text(
            "INSERT INTO iam.api_key (user_id, name, prefix, secret_hash, capabilities, expires_at)"
            " VALUES (:u, :n, :p, :h, :c, :e) RETURNING id"
        ),
        {"u": user.id, "n": payload.name.strip(), "p": prefix, "h": secret_hash, "c": sorted(wanted), "e": expires},
    ).scalar_one()
    audit.write(
        db, user, request,
        action="api_key.create",
        object_type="api_key",
        object_id=key_id,
        after={"name": payload.name.strip(), "prefix": prefix, "capabilities": sorted(wanted)},
    )
    db.commit()
    row = db.execute(text(f"{_SELECT} WHERE k.id = :k"), {"k": key_id}).mappings().one()
    # The only time the token exists outside the caller's hands.
    return {**_row(row), "token": token}


@router.get("/api-keys")
def list_keys(db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    everyone = "iam.manage" in capabilities_of(db, user)
    rows = db.execute(
        text(f"{_SELECT} WHERE (:all OR k.user_id = :u) ORDER BY k.created_at DESC"),
        {"all": everyone, "u": user.id},
    ).mappings().all()
    return {"items": [_row(row) for row in rows]}


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(
    key_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> Response:
    _refuse_a_key_acting(user)
    everyone = "iam.manage" in capabilities_of(db, user)
    done = db.execute(
        text(
            "UPDATE iam.api_key SET revoked_at = coalesce(revoked_at, now())"
            " WHERE id = :k AND (:all OR user_id = :u) RETURNING id"
        ),
        {"k": key_id, "all": everyone, "u": user.id},
    ).scalar_one_or_none()
    if done is None:
        raise HTTPException(status_code=404, detail="API key not found")
    audit.write(db, user, request, action="api_key.revoke", object_type="api_key", object_id=key_id)
    db.commit()
    return Response(status_code=204)
