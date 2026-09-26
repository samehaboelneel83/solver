"""Organization export and hard delete (queue R37)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit, org_lifecycle
from app.api.deps import requires
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1/organizations", tags=["org-lifecycle"])


class DeleteBody(BaseModel):
    confirm_code: str


@router.get("/{organization_id}/export")
def export_org(
    organization_id: UUID,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("iam.manage")),
) -> dict[str, Any]:
    if not _operator(db):
        raise HTTPException(status_code=403, detail="only an operator may export an organization")
    try:
        return org_lifecycle.export_organization(db, organization_id)
    except org_lifecycle.OrgLifecycleRefused as exc:
        raise HTTPException(status_code=404 if exc.code == "org_missing" else 422, detail=str(exc)) from exc


@router.post("/{organization_id}/delete")
def delete_org(
    organization_id: UUID,
    body: DeleteBody,
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("iam.manage")),
) -> dict[str, Any]:
    if not _operator(db):
        raise HTTPException(status_code=403, detail="only an operator may delete an organization")
    try:
        report = org_lifecycle.delete_organization(
            db,
            organization_id,
            confirm_code=body.confirm_code,
            actor_username=user.username,
        )
    except org_lifecycle.OrgLifecycleRefused as exc:
        code = 404 if exc.code == "org_missing" else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    # Org is gone; audit on the operator org.
    audit.record(
        db,
        organization_id=user.organization_id,
        actor_id=user.id,
        action="org.delete",
        object_type="organization",
        object_id=report["code"],
        after={"summary_sha256": report["summary_sha256"]},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return report


def _operator(db: Session) -> bool:
    from sqlalchemy import text

    return bool(db.execute(text("SELECT app_is_operator()")).scalar_one())
