"""OIDC SSO HTTP routes (queue R35)."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit, sso
from app.api.deps import get_current_user, requires
from app.core.db import enter_tenant, get_db
from app.core.security import create_access_token
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1/sso", tags=["sso"])

# In-memory PKCE state for the authorize round-trip (single-process OK for compose).
_pending: dict[str, dict[str, Any]] = {}


class ProviderWrite(BaseModel):
    issuer: str
    client_id: str
    client_secret: str
    scopes: str = "openid profile email"
    group_claim: str = "groups"
    role_map: dict[str, str] = Field(default_factory=dict)
    sso_required: bool = False


@router.get("/provider")
def read_provider(
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("iam.manage")),
) -> dict[str, Any]:
    row = sso.get_provider(db, user.organization_id)
    if row is None:
        return {"configured": False}
    return {
        "configured": True,
        "issuer": row["issuer"],
        "client_id": row["client_id"],
        "scopes": row["scopes"],
        "group_claim": row["group_claim"],
        "role_map": row["role_map"],
        "sso_required": row["sso_required"],
    }


@router.put("/provider")
def write_provider(
    payload: ProviderWrite,
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("iam.manage")),
) -> dict[str, Any]:
    try:
        sso.put_provider(
            db,
            user.organization_id,
            issuer=payload.issuer,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            scopes=payload.scopes,
            group_claim=payload.group_claim,
            role_map=payload.role_map,
            sso_required=payload.sso_required,
        )
    except sso.SsoRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.record(
        db,
        organization_id=user.organization_id,
        actor_id=user.id,
        action="sso.provider.set",
        object_type="oidc_provider",
        object_id=str(user.organization_id),
        after={"issuer": payload.issuer, "sso_required": payload.sso_required},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return read_provider(db=db, user=user)


@router.get("/login/{organization_id}")
def begin_login(
    organization_id: str,
    redirect_uri: str,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    provider = sso.get_provider(db, organization_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="SSO is not configured for this organization")
    verifier, challenge = sso.pkce_pair()
    state = secrets.token_urlsafe(24)
    _pending[state] = {
        "organization_id": organization_id,
        "redirect_uri": redirect_uri,
        "verifier": verifier,
    }
    return {
        "authorization_url": sso.authorization_url(
            provider, redirect_uri=redirect_uri, state=state, code_challenge=challenge
        ),
        "state": state,
    }


@router.get("/callback")
def callback(
    code: str,
    state: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    pending = _pending.pop(state, None)
    if pending is None:
        raise HTTPException(status_code=400, detail="unknown or expired SSO state")
    provider = sso.get_provider(db, pending["organization_id"])
    if provider is None:
        raise HTTPException(status_code=404, detail="SSO is not configured for this organization")
    try:
        result = sso.exchange_code(
            provider,
            code=code,
            redirect_uri=pending["redirect_uri"],
            code_verifier=pending["verifier"],
        )
        user = sso.upsert_user_from_claims(db, pending["organization_id"], result["claims"], provider)
        db.commit()
    except sso.SsoRefused as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    token = create_access_token(subject=user.username, token_version=user.token_version)
    try:
        audit.record(
            db,
            organization_id=user.organization_id,
            actor_id=user.id,
            action="auth.login.sso",
            object_type="user",
            object_id=user.username,
            after={"username": user.username, "via": "oidc"},
            ip=request.client.host if request.client else None,
        )
        db.commit()
    except Exception:
        db.rollback()
    return {"access_token": token, "token_type": "bearer"}
