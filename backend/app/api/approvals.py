"""Approved plans (OAAS Phase 5): business acceptance of an immutable run.

Distinct from solver proof (`optimal`) and from publishing a model version.
A new solve never silently replaces an approved plan; supersede explicitly.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_problem import Run
from app import audit

router = APIRouter(prefix="/api/v1", tags=["approvals"])


class ApproveBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    effective_from: date | None = None
    effective_to: date | None = None


class ApprovedPlanRead(BaseModel):
    id: int
    run_id: int
    problem_id: int
    reason: str
    approved_by: UUID | None
    approved_at: datetime
    effective_from: date | None
    effective_to: date | None
    superseded_by: int | None


@router.post("/runs/{run_id}/approve", status_code=201)
def approve_run(
    run_id: int,
    body: ApproveBody,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("model.publish")),
) -> ApprovedPlanRead:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status not in ("optimal", "feasible"):
        raise HTTPException(status_code=422, detail="only a usable plan can be approved")
    existing = db.execute(
        text("SELECT id FROM approved_plan WHERE run_id = :r"), {"r": run_id}
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="this run is already approved")

    problem_id = db.execute(
        text(
            "SELECT s.problem_id FROM run r JOIN scenario s ON s.id = r.scenario_id WHERE r.id = :r"
        ),
        {"r": run_id},
    ).scalar_one()

    # Supersede any current approval on the same problem.
    prior = db.execute(
        text(
            "SELECT id FROM approved_plan"
            " WHERE problem_id = :p AND superseded_by IS NULL"
        ),
        {"p": problem_id},
    ).scalar_one_or_none()

    row = db.execute(
        text(
            "INSERT INTO approved_plan"
            " (organization_id, run_id, problem_id, reason, approved_by,"
            "  effective_from, effective_to)"
            " VALUES (:o, :r, :p, :reason, :by, :ef, :et)"
            " RETURNING id, run_id, problem_id, reason, approved_by, approved_at,"
            "           effective_from, effective_to, superseded_by"
        ),
        {
            "o": user.organization_id,
            "r": run_id,
            "p": problem_id,
            "reason": body.reason,
            "by": user.id,
            "ef": body.effective_from,
            "et": body.effective_to,
        },
    ).mappings().one()

    if prior is not None:
        db.execute(
            text("UPDATE approved_plan SET superseded_by = :n WHERE id = :old"),
            {"n": row["id"], "old": prior},
        )

    audit.record(
        db,
        action="plan.approve",
        actor_id=user.id,
        organization_id=user.organization_id,
        object_type="run",
        object_id=run_id,
        after={"problem_id": problem_id, "reason": body.reason},
    )
    db.commit()
    return ApprovedPlanRead(**row)


@router.get("/problems/{problem_id}/approvals")
def list_approvals(
    problem_id: int,
    current_only: bool = True,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> list[ApprovedPlanRead]:
    sql = (
        "SELECT id, run_id, problem_id, reason, approved_by, approved_at,"
        "       effective_from, effective_to, superseded_by"
        "  FROM approved_plan WHERE problem_id = :p"
    )
    if current_only:
        sql += " AND superseded_by IS NULL"
    sql += " ORDER BY approved_at DESC"
    rows = db.execute(text(sql), {"p": problem_id}).mappings().all()
    return [ApprovedPlanRead(**row) for row in rows]
