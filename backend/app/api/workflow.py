"""A problem from one place (simplification plan, phase 1).

    GET  /api/v1/problems/{id}/readiness   each step of Data > Model > Check > Solve > Results
    POST /api/v1/problems/{id}/solve       solve the latest version, keeping a "Base" scenario

Getting an answer used to take a published version, a scenario made from it,
a check on that scenario and a run, each on its own page. The readiness says
in one read where a problem stands and what is next -- including every value
the model reads that a record lacks, with what a form needs to fill it in --
and the solve does the bookkeeping: it keeps one scenario, "Base", on the
latest published version (making it, or moving it forward) and queues the run.
Scenarios the planner made are never touched; they stay for what-if work.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import capabilities_of, get_current_user, requires
from app.api.preflight import model_findings, worker_status
from app.api.runs import TimeLimit
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["workflow"])

BASE = "Base"


def _problem(db: Session, problem_id: int) -> dict[str, Any]:
    row = db.execute(text("SELECT id, domain_id, name FROM problem WHERE id = :p"), {"p": problem_id}).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "problem not found")
    return dict(row)


def _latest(db: Session, problem_id: int) -> dict[str, Any] | None:
    row = db.execute(text(
        "SELECT id, version, ir, created_at FROM model_version WHERE problem_id = :p ORDER BY version DESC LIMIT 1"),
        {"p": problem_id}).mappings().one_or_none()
    return dict(row) if row else None


def _base(db: Session, problem_id: int) -> dict[str, Any] | None:
    row = db.execute(text(
        "SELECT s.id, s.name, s.model_version_id, mv.version FROM scenario s"
        " JOIN model_version mv ON mv.id = s.model_version_id"
        " WHERE s.problem_id = :p AND s.name = :n ORDER BY s.id LIMIT 1"),
        {"p": problem_id, "n": BASE}).mappings().one_or_none()
    return dict(row) if row else None


@router.get("/problems/{problem_id}/readiness")
def readiness(problem_id: int, db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    problem = _problem(db, problem_id)
    latest = _latest(db, problem_id)
    draft = db.execute(text(
        "SELECT d.revision, d.updated_at, d.base_version_id, (d.ir IS DISTINCT FROM mv.ir) AS unpublished"
        "  FROM model_draft d LEFT JOIN model_version mv ON mv.id = (SELECT id FROM model_version"
        "       WHERE problem_id = :p ORDER BY version DESC LIMIT 1)"
        " WHERE d.problem_id = :p AND d.owner_id = :o"),
        {"p": problem_id, "o": user.id}).mappings().one_or_none()
    check = None
    if latest is not None:
        checked = model_findings(db, problem["domain_id"], problem_id, latest["ir"])
        check = {
            "ready": not any(f["kind"] == "blocker" for f in checked["findings"]),
            "findings": checked["findings"],
            "model_class": checked["model_class"],
            "sets": checked["sets"],
        }
    last_run = db.execute(text(
        "SELECT r.id, r.status, r.optimality, r.objective, r.queued_at, r.finished_at, r.scenario_id, s.name AS scenario"
        "  FROM run r JOIN scenario s ON s.id = r.scenario_id"
        # A plan, not a question asked of one (why-not probes) nor a point or alternative of
        # another run: those are opened from their run (UX audit C-2).
        " WHERE s.problem_id = :p AND r.purpose = 'plan'"
        "   AND r.params->'pareto_of' IS NULL AND r.params->'alternative_of' IS NULL"
        " ORDER BY r.id DESC LIMIT 1"),
        {"p": problem_id}).mappings().one_or_none()
    base = _base(db, problem_id)
    return {
        "problem": {"id": problem["id"], "domain_id": problem["domain_id"], "name": problem["name"]},
        "latest_version": {"id": latest["id"], "version": latest["version"], "created_at": latest["created_at"]} if latest else None,
        "draft": {
            "revision": draft["revision"],
            "updated_at": draft["updated_at"],
            "unpublished": bool(draft["unpublished"]),
        } if draft else None,
        "check": check,
        "base_scenario": {"id": base["id"], "version": base["version"]} if base else None,
        "last_run": {**dict(last_run), "objective": float(last_run["objective"]) if last_run["objective"] is not None else None}
        if last_run else None,
        "workers": worker_status(db),
    }


class SolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: How long the solver may look; the workspace's setting when left out.
    time_limit_s: TimeLimit | None = None


@router.post("/problems/{problem_id}/solve", status_code=201)
def solve(
    problem_id: int,
    request: Request,
    response: Response,
    body: SolveBody | None = None,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("run.submit")),
):
    """Solve the latest published version: on the "Base" scenario, made or
    moved forward to that version first. Returns the queued run, as
    `POST /scenarios/{id}/runs` does."""
    from app.api.problems import ScenarioCreate, ScenarioUpdate, create_scenario, update_scenario
    from app.api.runs import RunRequest, create_run

    _problem(db, problem_id)
    latest = _latest(db, problem_id)
    if latest is None:
        raise HTTPException(422, "Publish the model first: there is no version to solve.")
    base = _base(db, problem_id)
    if base is None or base["model_version_id"] != latest["id"]:
        # Making or moving a scenario is a modeller's step; a planner who may only solve
        # asks one to, rather than being refused by the scenario route with no context.
        if "model.publish" not in capabilities_of(db, user):
            raise HTTPException(
                403,
                f"The {BASE} scenario is not on version {latest['version']} yet, and this account may solve but "
                "not change scenarios. Ask a modeller to solve once, or to move it.",
            )
        if base is None:
            made = create_scenario(
                ScenarioCreate(problem_id=problem_id, model_version_id=latest["id"], name=BASE), request, db, user)
            scenario_id = made.id
        else:
            update_scenario(base["id"], ScenarioUpdate(model_version_id=latest["id"]), request, db, user)
            scenario_id = base["id"]
    else:
        scenario_id = base["id"]
    return create_run(scenario_id, response, RunRequest(time_limit_s=body.time_limit_s if body else None), db, user, None)
