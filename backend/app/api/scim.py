"""SCIM 2.0 HTTP routes (queue R36)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import audit, scim
from app.api.deps import requires
from app.core.db import enter_tenant, get_db
from app.models.iam import UserAccount

router = APIRouter(tags=["scim"])


def _org_from_bearer(db: Session, authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="SCIM bearer token required")
    org_id = scim.resolve_token(db, authorization.split(" ", 1)[1].strip())
    if org_id is None:
        raise HTTPException(status_code=401, detail="invalid SCIM token")
    enter_tenant(db, org_id)
    return org_id


@router.post("/api/v1/scim/token")
def mint_scim_token(
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("iam.manage")),
) -> dict[str, str]:
    token = scim.mint_token(db, user.organization_id)
    audit.record(
        db,
        organization_id=user.organization_id,
        actor_id=user.id,
        action="scim.token.mint",
        object_type="scim_token",
        object_id=str(user.organization_id),
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return {"token": token, "token_type": "Bearer"}


@router.get("/scim/v2/Users")
def scim_list_users(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    startIndex: int = 1,
    count: int = 100,
) -> dict[str, Any]:
    org = _org_from_bearer(db, authorization)
    return scim.list_users(db, org, start=startIndex, count=count)


@router.get("/scim/v2/Users/{user_id}")
def scim_get_user(
    user_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    org = _org_from_bearer(db, authorization)
    row = scim.get_user(db, org, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.post("/scim/v2/Users", status_code=201)
def scim_create_user(
    body: dict[str, Any],
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    org = _org_from_bearer(db, authorization)
    try:
        row = scim.create_user(db, org, body)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return row


@router.put("/scim/v2/Users/{user_id}")
def scim_replace_user(
    user_id: str,
    body: dict[str, Any],
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    org = _org_from_bearer(db, authorization)
    row = scim.replace_user(db, org, user_id, body)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    db.commit()
    return row


@router.delete("/scim/v2/Users/{user_id}", status_code=204)
def scim_delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Response:
    org = _org_from_bearer(db, authorization)
    if not scim.delete_user(db, org, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    db.commit()
    return Response(status_code=204)


@router.get("/scim/v2/Groups")
def scim_list_groups(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    org = _org_from_bearer(db, authorization)
    return scim.list_groups(db, org)
