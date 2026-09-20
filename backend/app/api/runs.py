"""Runs: ask for an answer, and read the one you got.

``POST /api/v1/scenarios/{id}/runs`` freezes the data, solves, and records
everything; the other two routes read it back.

**Solving happens in the request, deliberately and temporarily.** The
roadmap's Phase 3 wants a queue and a worker, and this is not that: the
seeded demo solves in 9ms, and a route is what makes solving reachable from
the product at all. The bounded time limit is what keeps the decision
honest -- a request cannot run away -- and the shape here (a `run` row that
exists before the answer does, carrying `queued_at`/`started_at`/
`finished_at`) is the shape a worker will fill in later, so moving to one
does not change this contract.

**A run is immutable once written**, like the dataset and the version it
points at, so there is no PATCH or DELETE. Re-running is a new run, which is
what makes two results comparable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_problem import ConstraintResult, Run, Scenario, Solution
from app.solve.service import run_scenario

router = APIRouter(prefix="/api/v1", tags=["runs"])

# Bounded because solving happens in the request. Ten seconds answers the
# demo a thousand times over; the ceiling is what stops a request running
# away before there is a worker to run away in.
TimeLimit = Annotated[float, Field(gt=0, le=60)]
Seed = Annotated[int, Field(ge=0, le=2**31 - 1)]


class RunRequest(BaseModel):
    """Both fields are recorded on the run: a result nobody can attribute to
    a time limit and a seed is not reproducible."""

    time_limit_s: TimeLimit = 10.0
    seed: Seed = 1


class ConstraintOutcome(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    constraint_id: str
    label: str
    hard: bool
    satisfied: bool
    total_violation: int
    penalty_paid: int
    # Which instances broke, worst first. Empty for a satisfied constraint.
    violations: Any


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scenario_id: int
    dataset_id: int
    status: str
    solver: str
    solver_version: str | None
    compiler_version: str | None
    objective: int | None
    wall_time_s: float | None
    error: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunRead(RunSummary):
    """The answer, in the domain's own words."""

    params: dict[str, Any]
    # variable name -> the index tuples it took, e.g.
    # {"assign": [["ahmed", "mon", "morning"], ...]}. Absent when the run
    # found nothing, which is not the same as an empty roster.
    assignments: dict[str, Any] | None
    constraints: list[ConstraintOutcome]


@router.post("/scenarios/{scenario_id}/runs", status_code=201)
def create_run(
    scenario_id: int,
    payload: RunRequest | None = None,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> RunRead:
    """Solve a scenario and return the run.

    **201 even when the model cannot be solved.** An infeasible model, or one
    this compiler cannot express, is an answer about the model -- recorded on
    the run with its reason -- not a malformed request. A 4xx would say the
    caller did something wrong, and reading the status is how you learn what
    happened.
    """
    if db.get(Scenario, scenario_id) is None:
        raise HTTPException(status_code=404, detail="scenario not found")

    outcome = run_scenario(
        db,
        scenario_id,
        time_limit=(payload or RunRequest()).time_limit_s,
        seed=(payload or RunRequest()).seed,
    )
    return _read(db, outcome.run_id)


@router.get("/runs")
def list_runs(
    scenario_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    """Newest first: the last run of a scenario is the one being looked for."""
    stmt = select(Run)
    count_stmt = select(func.count()).select_from(Run)
    if scenario_id is not None:
        stmt = stmt.where(Run.scenario_id == scenario_id)
        count_stmt = count_stmt.where(Run.scenario_id == scenario_id)
    rows = db.scalars(stmt.order_by(Run.id.desc()).limit(limit).offset(offset)).all()
    return {
        "items": [RunSummary.model_validate(r) for r in rows],
        "total": db.scalar(count_stmt) or 0,
    }


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> RunRead:
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _read(db, run_id)


def _read(db: Session, run_id: int) -> RunRead:
    run = db.get(Run, run_id)
    solution = db.scalars(select(Solution).where(Solution.run_id == run_id)).first()
    constraints = db.scalars(
        select(ConstraintResult)
        .where(ConstraintResult.run_id == run_id)
        # Broken first: the reason a run is being read is usually what gave.
        .order_by(ConstraintResult.satisfied, ConstraintResult.constraint_id)
    ).all()
    return RunRead(
        **RunSummary.model_validate(run).model_dump(),
        params=run.params or {},
        assignments=solution.assignments if solution else None,
        constraints=[ConstraintOutcome.model_validate(c) for c in constraints],
    )
