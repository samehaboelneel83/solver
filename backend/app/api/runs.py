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

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import capabilities_of, get_current_user, requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_problem import ConstraintResult, Run, Scenario, Solution
from app.solve.backends import available_names
from app.solve.compare import NotComparable, compare
from app.solve.service import enqueue_run

router = APIRouter(prefix="/api/v1", tags=["runs"])

# Bounded because a solve holds a worker for its duration. Ten seconds
# answers the demo a thousand times over; the ceiling is what stops one run
# starving every other.
TimeLimit = Annotated[float, Field(gt=0, le=60)]
Seed = Annotated[int, Field(ge=0, le=2**31 - 1)]


class RunRequest(BaseModel):
    """All three are recorded on the run: a result nobody can attribute to a
    solver, a time limit and a seed is not reproducible.

    All three are also **optional**. What the caller does not name is resolved
    from settings -- problem, then domain, then platform, then the built-in
    default -- so a domain whose models need ninety seconds can say so once
    rather than at every call (migration 0014).
    """

    time_limit_s: TimeLimit | None = None
    seed: Seed | None = None
    #: Leave it out and the platform chooses, recording why. Naming one that
    #: cannot take the model fails the run with that reason rather than
    #: quietly using another -- "I used something else" would make the
    #: record a lie.
    solver: str | None = None


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


class ConflictItem(BaseModel):
    """One instance of a rule that is part of why there is no answer."""

    constraint_id: str
    # The index tuple, e.g. ["mon", "morning"] -- the instance, not the rule.
    instance: list[str]


class RunRead(RunSummary):
    """The answer, in the domain's own words."""

    params: dict[str, Any]
    # Display names as they were when the run was made, `{set: {key: label}}`,
    # read from the frozen dataset rather than from today's entities: a run
    # answers the question as it was asked, and that includes what things were
    # called. Absent for runs made before migration 0012, whose answers read
    # back in keys -- which is what they were shown as at the time.
    labels: dict[str, dict[str, str]]
    # Which set each position of an index tuple comes from, so a reader can
    # turn ["ahmed", "mon"] into names without guessing which type a key
    # belongs to. Keys are unique within a type, not across them.
    index_sets: dict[str, dict[str, list[str]]]
    # Why there is no answer: rules that cannot hold together. Null unless
    # the run was infeasible.
    conflict: list[ConflictItem] | None
    # Whether that set was proven irreducible. False means it conflicts but
    # may contain rules that are not needed -- the search was cut short, and
    # saying so is the difference between "change one of these" and "the
    # reason is somewhere in here".
    conflict_minimal: bool | None
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
    user: UserAccount = Depends(requires("run.submit")),
) -> RunRead:
    """Queue a run and return it, `queued`.

    **The answer is not in this response.** Solving happens in a worker, so
    this returns as soon as the data is frozen and the work is recorded; the
    caller polls `GET /runs/{id}` until the status settles. That is what lets
    a model take longer than a request may, and what stops one solve holding
    a web worker.

    **201 even when the model cannot be solved.** An infeasible model, or one
    this compiler cannot express, is an answer about the model -- recorded on
    the run with its reason -- not a malformed request. A 4xx would say the
    caller did something wrong, and reading the status is how you learn what
    happened.
    """
    if db.get(Scenario, scenario_id) is None:
        raise HTTPException(status_code=404, detail="scenario not found")

    request = payload or RunRequest()
    # Naming a solver is a separate capability from solving. A planner should
    # be able to ask the question; choosing the technique it is answered with
    # is a decision about the platform, and a run's solver is part of what
    # makes its answer defensible.
    if request.solver is not None and "solver.configure" not in capabilities_of(db, user):
        raise HTTPException(
            status_code=403,
            detail="this account may solve, but not choose the solver; omit `solver` to let the"
            " platform choose and record why",
        )
    if request.solver is not None and request.solver not in available_names():
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "type": "value_error",
                    "loc": ["body", "solver"],
                    "msg": f"no solver called {request.solver!r}; this build has "
                    f"{', '.join(available_names())}",
                }
            ],
        )
    run_id = enqueue_run(
        db,
        scenario_id,
        time_limit=request.time_limit_s,
        seed=request.seed,
        solver=request.solver,
    )
    return _read(db, run_id)


@router.get("/me")
def whoami(
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    """Who the caller is and what they may do.

    A UI that guessed at this would guess wrong: it would either offer
    actions that fail with a 403 -- a button whose only outcome is an error --
    or hide actions the user actually has. The capabilities are computed in
    the one place that enforces them, so the two cannot disagree.
    """
    return {
        "username": user.username,
        "display_name": user.display_name,
        "capabilities": sorted(capabilities_of(db, user)),
    }


@router.get("/solvers")
def list_solvers(_: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    """What this build can solve with. A UI that hardcoded the list would
    offer a solver a different build does not have."""
    from app.solve.backends import REGISTRY

    return {
        "items": [
            {
                "name": b.name,
                "available": b.is_available(),
                "classes": sorted(b.classes),
                "note": b.note,
            }
            for b in sorted(REGISTRY, key=lambda b: b.rank)
        ]
    }


@router.get("/runs/{left_id}/compare/{right_id}")
def compare_runs(
    left_id: int,
    right_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    """Two runs side by side: what moved, what it cost, and what differed.

    **422, not 404, when they cannot be compared.** Both runs exist; the
    request to line them up is what is wrong, and the reason says which.

    The response says what differs between the two runs and whether the patch
    is the only difference. A caller that skipped that could read a change in
    the roster as the effect of relaxing a rule when it came from the data
    changing underneath -- a wrong answer dressed as an insight.
    """
    try:
        result = compare(db, left_id, right_id)
    except NotComparable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return asdict(result)


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


def _vocabulary(db: Session, run_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """The frozen display names, and which set each index position names.

    Both come from what the run points at -- the dataset it froze and the
    model version it solved -- never from today's rows.
    """
    row = db.execute(
        text(
            "SELECT d.data -> 'labels' AS labels, mv.ir AS ir"
            "  FROM run r"
            "  JOIN dataset d ON d.id = r.dataset_id"
            "  JOIN scenario s ON s.id = r.scenario_id"
            "  JOIN model_version mv ON mv.id = s.model_version_id"
            " WHERE r.id = :r"
        ),
        {"r": run_id},
    ).mappings().one()

    ir = row["ir"] or {}
    variables = {
        name: list(spec.get("index", []))
        for name, spec in (ir.get("variables") or {}).items()
        if isinstance(spec, dict)
    }
    constraints = {
        spec["id"]: [binding["set"] for binding in spec.get("forall", []) if "set" in binding]
        for spec in (ir.get("constraints") or [])
        if isinstance(spec, dict) and "id" in spec
    }
    return row["labels"] or {}, {"variables": variables, "constraints": constraints}


def _read(db: Session, run_id: int) -> RunRead:
    run = db.get(Run, run_id)
    solution = db.scalars(select(Solution).where(Solution.run_id == run_id)).first()
    labels, index_sets = _vocabulary(db, run_id)
    constraints = db.scalars(
        select(ConstraintResult)
        .where(ConstraintResult.run_id == run_id)
        # Broken first: the reason a run is being read is usually what gave.
        .order_by(ConstraintResult.satisfied, ConstraintResult.constraint_id)
    ).all()
    return RunRead(
        **RunSummary.model_validate(run).model_dump(),
        params=run.params or {},
        labels=labels,
        index_sets=index_sets,
        conflict=run.conflict,
        conflict_minimal=run.conflict_minimal,
        assignments=solution.assignments if solution else None,
        constraints=[ConstraintOutcome.model_validate(c) for c in constraints],
    )
