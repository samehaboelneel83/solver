"""An organization's quota and what it has used this month (migration 0034).

    GET /api/v1/quota                      -- the caller's organization
    PUT /api/v1/organizations/{id}/quota   -- an operator sets any organization's

A limit left out or null is "no limit". Only an operator organization may
set quotas; row-level security refuses anyone else, and this says why first.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.solve.service import month_usage, quota_of

router = APIRouter(prefix="/api/v1", tags=["quota"])

LIMITS = (
    "max_concurrent_runs",
    "max_queued_runs",
    "max_time_limit_s",
    "max_vars",
    "cpu_seconds_month",
    "requests_per_minute",
)


class QuotaWrite(BaseModel):
    max_concurrent_runs: int | None = Field(default=None, ge=1)
    max_queued_runs: int | None = Field(default=None, ge=1)
    max_time_limit_s: float | None = Field(default=None, gt=0)
    max_vars: int | None = Field(default=None, ge=1)
    cpu_seconds_month: float | None = Field(default=None, gt=0)
    requests_per_minute: int | None = Field(default=None, ge=1)


def _view(db: Session, organization_id) -> dict[str, Any]:
    quota = quota_of(db, organization_id)
    return {
        "organization_id": str(organization_id),
        "limits": {name: quota.get(name) for name in LIMITS},
        "this_month": month_usage(db, organization_id),
    }


@router.get("/quota")
def read_quota(db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    return _view(db, user.organization_id)


@router.put("/organizations/{organization_id}/quota")
def write_quota(
    organization_id: uuid.UUID,
    payload: QuotaWrite,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("iam.manage")),
) -> dict[str, Any]:
    if not db.execute(text("SELECT app_is_operator()")).scalar_one():
        raise HTTPException(
            status_code=403,
            detail="quotas are set by an operator organization, not by the organization they limit",
        )
    if db.execute(text("SELECT 1 FROM iam.organization WHERE id = :o"), {"o": organization_id}).first() is None:
        raise HTTPException(status_code=404, detail="organization not found")
    values = payload.model_dump()
    db.execute(
        text(
            "INSERT INTO iam.quota (organization_id, max_concurrent_runs, max_queued_runs,"
            "  max_time_limit_s, max_vars, cpu_seconds_month, requests_per_minute)"
            " VALUES (:o, :max_concurrent_runs, :max_queued_runs, :max_time_limit_s, :max_vars,"
            "  :cpu_seconds_month, :requests_per_minute)"
            " ON CONFLICT (organization_id) DO UPDATE SET"
            "  max_concurrent_runs = EXCLUDED.max_concurrent_runs,"
            "  max_queued_runs = EXCLUDED.max_queued_runs,"
            "  max_time_limit_s = EXCLUDED.max_time_limit_s,"
            "  max_vars = EXCLUDED.max_vars,"
            "  cpu_seconds_month = EXCLUDED.cpu_seconds_month,"
            "  requests_per_minute = EXCLUDED.requests_per_minute,"
            "  updated_at = now()"
        ),
        {"o": organization_id, **values},
    )
    db.commit()
    return _view(db, organization_id)
