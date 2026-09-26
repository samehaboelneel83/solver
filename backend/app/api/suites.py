"""A problem's acceptance cases (queue R29, app.solve.suite).

    GET    /api/v1/problems/{id}/suite-cases                every case, with its last run's verdict
    POST   /api/v1/problems/{id}/suite-cases/from-run/{run} {name}: a case from an answered run
    PATCH  /api/v1/suite-cases/{id}                         {name?, expect?}: rename, loosen or tighten
    DELETE /api/v1/suite-cases/{id}
    POST   /api/v1/suite-cases/{id}/runs                    {model_version_id?}: ask it again

A case's run is a run (`purpose = 'suite'`): poll `GET /runs/{id}` for its `verdict`. Making and
changing cases needs `model.publish`, the capability that already guards versions; running one needs
`run.submit`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.solve import suite

router = APIRouter(prefix="/api/v1", tags=["suites"])


class CaseFromRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class Expect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(optimal|feasible|infeasible|unbounded)$")
    objective: float | None = None
    tolerance_abs: float = Field(default=0, ge=0)
    tolerance_rel: float = Field(default=suite.DEFAULT_TOLERANCE, ge=0)
    must_hold: list[dict[str, Any]] = Field(default_factory=list)
    max_seconds: float = Field(default=suite.MIN_SECONDS, gt=0)


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    expect: Expect | None = None


class CaseRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_version_id: int | None = None


def _refused(exc: suite.NotACase) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=[{"type": exc.code, "loc": ["body"], "msg": str(exc)}])


def _case(db: Session, case_id: int) -> dict[str, Any]:
    row = db.execute(
        text(
            "SELECT c.id, c.problem_id, c.name, c.dataset_id, c.patch, c.expect, c.created_from_run_id, c.created_by,"
            "       c.created_at,"
            "       (SELECT jsonb_build_object('run_id', r.id, 'status', r.status, 'verdict', r.verdict,"
            "                                  'model_version_id', (r.params ->> 'model_version_id')::bigint)"
            "          FROM run r WHERE r.purpose = 'suite' AND (r.params ->> 'case_id')::bigint = c.id"
            "         ORDER BY r.id DESC LIMIT 1) AS last"
            "  FROM suite_case c WHERE c.id = :c"
        ),
        {"c": case_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="case not found")
    return dict(row)


@router.get("/problems/{problem_id}/suite-cases")
def list_cases(problem_id: int, db: Session = Depends(get_db),
               _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    ids = db.execute(text("SELECT id FROM suite_case WHERE problem_id = :p ORDER BY name, id"),
                     {"p": problem_id}).scalars().all()
    return {"items": [_case(db, i) for i in ids]}


@router.post("/problems/{problem_id}/suite-cases/from-run/{run_id}", status_code=201)
def case_from_run(problem_id: int, run_id: int, payload: CaseFromRun, db: Session = Depends(get_db),
                  user: UserAccount = Depends(requires("model.publish"))) -> dict[str, Any]:
    owner = db.execute(text("SELECT s.problem_id FROM run r JOIN scenario s ON s.id = r.scenario_id WHERE r.id = :r"),
                       {"r": run_id}).scalar_one_or_none()
    if owner != problem_id:
        raise HTTPException(status_code=404, detail="no such run of this problem")
    try:
        case_id = suite.from_run(db, run_id, payload.name, user.username)
        db.commit()
    except suite.NotACase as exc:
        db.rollback()
        raise _refused(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"this problem already has a case called {payload.name!r}") from exc
    return _case(db, case_id)


@router.patch("/suite-cases/{case_id}")
def update_case(case_id: int, payload: CaseUpdate, db: Session = Depends(get_db),
                _: UserAccount = Depends(requires("model.publish"))) -> dict[str, Any]:
    _case(db, case_id)
    import json

    if payload.name is not None:
        db.execute(text("UPDATE suite_case SET name = :n WHERE id = :c"), {"n": payload.name, "c": case_id})
    if payload.expect is not None:
        db.execute(text("UPDATE suite_case SET expect = CAST(:e AS jsonb) WHERE id = :c"),
                   {"e": json.dumps(payload.expect.model_dump(exclude_none=True)), "c": case_id})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"this problem already has a case called {payload.name!r}") from exc
    return _case(db, case_id)


@router.delete("/suite-cases/{case_id}", status_code=204, response_model=None)
def delete_case(case_id: int, db: Session = Depends(get_db),
                _: UserAccount = Depends(requires("model.publish"))) -> None:
    _case(db, case_id)
    db.execute(text("DELETE FROM suite_case WHERE id = :c"), {"c": case_id})
    db.commit()


@router.get("/model-versions/{version_id}/checks")
def version_checks(version_id: int, db: Session = Depends(get_db),
                   _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    """Where a version stands against its problem's cases (queue R30)."""
    try:
        return suite.version_checks(db, version_id)
    except suite.NotACase as exc:
        raise _refused(exc) from exc


@router.post("/model-versions/{version_id}/check", status_code=201)
def check_version(version_id: int, db: Session = Depends(get_db),
                  _: UserAccount = Depends(requires("run.submit"))) -> dict[str, Any]:
    """Ask every case of the version's problem of it (queue R30); poll `GET .../checks`."""
    try:
        runs = suite.check_version(db, version_id)
    except suite.NotACase as exc:
        db.rollback()
        raise _refused(exc) from exc
    return {"run_ids": runs, **suite.version_checks(db, version_id)}


@router.post("/suite-cases/{case_id}/runs", status_code=201)
def run_case(case_id: int, payload: CaseRun | None = None, db: Session = Depends(get_db),
             _: UserAccount = Depends(requires("run.submit"))) -> dict[str, Any]:
    _case(db, case_id)
    try:
        run_id = suite.queue(db, case_id, (payload or CaseRun()).model_version_id)
    except suite.NotACase as exc:
        db.rollback()
        raise _refused(exc) from exc
    return {"run_id": run_id}
