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
from decimal import Decimal
from typing import Literal, Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.api import search
from app.api.deps import capabilities_of, get_current_user, requires
from app.api.quantity import QuantityOut
from app.api.routers import hash_user_password
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_problem import ConstraintResult, Problem, Run, Scenario, Solution
from app.solve.backends import available_names
from app.solve.compare import NotComparable, compare
from app.solve.service import CannotCancel, QuotaExceeded, SettingUnusable, cancel_run, enqueue_run
from app.solve import whynot

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
    #: Leave it true and a question already answered -- the same model,
    #: data, patch and deciding settings, proven optimal -- is answered from
    #: that run without a solve (migration 0042). False solves it again.
    reuse: bool = True
    #: Ask for the trade-off front between the goal's two terms instead of
    #: one answer: the ends and this many steps between (`app.solve.pareto`).
    pareto_steps: Annotated[int, Field(ge=2, le=50)] | None = None
    #: Solve the robust counterpart: every rule that reads a parameter
    #: declared uncertain within a range must hold for any `gamma` of its
    #: values moving (`app.solve.robust`), and report the price.
    robust: bool = False
    #: After the answer, list up to this many next-best distinct plans
    #: (`app.solve.alternatives`): each differs from every other in at least
    #: `alternatives_min_changes` decisions (yes-or-no, or bounded whole
    #: numbers) and is within `alternatives_within` of the best value.
    alternatives: Annotated[int, Field(ge=1, le=20)] | None = None
    #: The gap, as a share of the best value (0.02 is 2%). Only with `alternatives`.
    alternatives_within: Annotated[float, Field(ge=0, le=1)] | None = None
    #: How many decisions each plan changes from every other (1 by default). Only with `alternatives`.
    alternatives_min_changes: Annotated[int, Field(ge=1, le=50)] | None = None


class ConstraintOutcome(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    constraint_id: str
    label: str
    hard: bool
    satisfied: bool
    # Decimal since migration 0015: a rule in a continuous model can be
    # short by half a unit, and rounding that would report a breach that
    # did not happen.
    total_violation: QuantityOut
    penalty_paid: QuantityOut
    # Which instances broke, worst first. Empty for a satisfied constraint.
    violations: Any
    # Residual at the assignment, tightest instance. Null on runs made
    # before the column existed, and on a constraint the compiler never
    # emitted (a vacuous forall). Zero means the rule has no room left.
    slack: QuantityOut | None = None
    # Shadow price from a linear solver. Null when the backend has none
    # (CP-SAT, mixed-integer) or the run predates the column.
    dual: QuantityOut | None = None


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scenario_id: int
    dataset_id: int
    status: str
    # Migration 0028. `global`: proven the best of all answers. `local`: the
    # best among its neighbours -- a better one may exist elsewhere. `none`:
    # an answer, with no claim to be the best. `approximate` (0051): optimal to
    # a tolerance (PDLP), not proven. Null when there is no answer.
    optimality: Literal["global", "local", "approximate", "none"] | None = None
    solver: str
    solver_version: str | None
    compiler_version: str | None
    objective: QuantityOut | None
    # Migration 0029. `best_bound`: no answer can beat it. `gap`: how far the
    # answer may be from the best, as a fraction -- 0 when proven optimal.
    best_bound: float | None = None
    gap: float | None = None
    wall_time_s: float | None
    error: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested: bool = False
    # The run whose proven optimum answered this one without a solve
    # (migration 0042); null for a run that was solved.
    reused_from: int | None = None
    # Migration 0069 (queue R26): a plan, or a question about another run and its answer.
    purpose: str = "plan"
    parent_run_id: int | None = None
    verdict: dict[str, Any] | None = None


class AlternativePlan(BaseModel):
    """One next-best distinct plan, and the run that holds it (Epic engine)."""

    seq: int
    objective: float
    #: How many yes-or-no decisions differ from the best answer.
    changed: int
    status: str
    run_id: int | None


class ParetoPoint(BaseModel):
    """One point of a run's trade-off front, and the run that holds it."""

    seq: int
    first: float
    second: float
    epsilon: float | None
    status: str
    run_id: int | None


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
    # What each rule means, in the words its author gave it (`note` in the
    # model version the run solved): what a conflict is read in, rather than
    # rule ids. Only rules that carry one.
    rule_notes: dict[str, str] = {}
    # What a view is chosen from (queue R17): each decision's kind (binary, integer, continuous,
    # interval), each set's role in the domain (time, agent, location...), and each set's members
    # in the order the dataset froze them -- Monday to Sunday, not alphabetically.
    variable_kinds: dict[str, str] = {}
    set_roles: dict[str, str] = {}
    set_order: dict[str, list[str]] = {}
    # Each interval decision's start, end and presence decisions, by name (queue R17b's Gantt).
    intervals: dict[str, dict[str, str]] = {}
    # How much each whole-number or continuous decision took, where it took any (migration 0065).
    # Null for runs recorded before it, and when there is no answer.
    amounts: dict[str, list[dict[str, Any]]] | None = None
    # LP ranging (queue R27): `rows` and `costs`, each with the range it may move in; null for
    # any run that is not a proven optimum of a linear program.
    ranges: dict[str, Any] | None = None
    # The trade-off front, when one was asked for (migration 0045): its
    # points in order of the first term, each linked to its own run, and
    # the two terms' ids. Null otherwise.
    pareto: list[ParetoPoint] | None = None
    pareto_terms: list[str] | None = None
    # The next-best distinct plans, when they were asked for: best first, each
    # linked to its own run. Null otherwise.
    alternatives: list[AlternativePlan] | None = None
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
    # Reduced costs from a linear solver, grouped like the roster. Null when
    # the backend has none or the run predates the column.
    reduced_costs: dict[str, Any] | None = None
    constraints: list[ConstraintOutcome]


@router.post("/scenarios/{scenario_id}/runs", status_code=201)
def create_run(
    scenario_id: int,
    response: Response,
    payload: RunRequest | None = None,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("run.submit")),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
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

    **Idempotency-Key** (optional): the same organization-scoped key returns
    the existing run with **200** instead of queueing another (OAAS S02).
    """
    if db.get(Scenario, scenario_id) is None:
        raise HTTPException(status_code=404, detail="scenario not found")

    key = None
    if idempotency_key is not None:
        key = idempotency_key.strip()
        if not key or len(key) > 128 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise HTTPException(
                status_code=422,
                detail="Idempotency-Key must be 1–128 printable ASCII characters",
            )
        prior = db.execute(
            text(
                "SELECT r.id FROM run r JOIN scenario s ON s.id = r.scenario_id"
                " WHERE r.organization_id = :o AND r.idempotency_key = :k"
            ),
            {"o": user.organization_id, "k": key},
        ).scalar_one_or_none()
        if prior is not None:
            response.status_code = 200
            return _read(db, int(prior))

    request = payload or RunRequest()
    for given in ("alternatives_within", "alternatives_min_changes"):
        if getattr(request, given) is not None and not request.alternatives:
            raise HTTPException(
                status_code=422,
                detail=[{"type": "value_error", "loc": ["body", given],
                         "msg": f"`{given}` is given with `alternatives`: how many next-best plans to list",
                         "input": None}],
            )
    if request.alternatives and (request.pareto_steps or request.robust):
        raise HTTPException(
            status_code=422,
            detail=[{"type": "value_error", "loc": ["body", "alternatives"],
                     "msg": "alternatives are listed for one best answer, not beside a front or a robust answer",
                     "input": request.alternatives}],
        )
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
    try:
        run_id = enqueue_run(
            db,
            scenario_id,
            time_limit=request.time_limit_s,
            seed=request.seed,
            solver=request.solver,
            reuse=request.reuse,
            pareto_steps=request.pareto_steps,
            robust=request.robust,
            alternatives=request.alternatives,
            alternatives_within=request.alternatives_within,
            alternatives_min_changes=request.alternatives_min_changes,
            idempotency_key=key,
        )
    except IntegrityError:
        # Concurrent retry won the unique index: return that run.
        db.rollback()
        prior = db.execute(
            text(
                "SELECT id FROM run WHERE organization_id = :o AND idempotency_key = :k"
            ),
            {"o": user.organization_id, "k": key},
        ).scalar_one_or_none()
        if prior is None:
            raise
        response.status_code = 200
        return _read(db, int(prior))
    except SettingUnusable as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=[{"type": "setting", "loc": ["settings", exc.key], "msg": str(exc)}],
        ) from exc
    except QuotaExceeded as exc:
        # 422, not 429: the request is well-formed and the caller is not
        # sending too fast; what it asks for is over a limit, and the body
        # names which one.
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=[{"type": "quota", "loc": ["quota", exc.quota], "msg": str(exc)}],
        ) from exc
    return _read(db, run_id)


@router.post("/runs/{run_id}/cancel")
def cancel(
    run_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("run.submit")),
) -> RunRead:
    """Stop a run that has not finished.

    A queued run is cancelled immediately: no worker has started it. A
    running one is asked to stop; the worker records `cancelled` instead of
    an answer. A settled run is a 422 -- the result is already written.
    """
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    try:
        cancel_run(db, run_id)
    except CannotCancel as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    return _me(db, user)


class MeUpdate(BaseModel):
    """What an account may change about itself.

    Username, organisation and whether the account is active stay off
    this form: those are who the person is, and granting that is
    `iam.manage`. An omitted password leaves the stored hash.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    email: str | None = None
    password: str | None = None


def _me(db: Session, user: UserAccount) -> dict[str, Any]:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "capabilities": sorted(capabilities_of(db, user)),
    }


@router.patch("/me")
def update_whoami(
    payload: MeUpdate,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    """Change the caller's own name, email or password.

    Creating users and assigning roles is `iam.manage`. This is not that:
    the row is already theirs. Any authenticated account may call it.
    """
    changes = hash_user_password(payload.model_dump(exclude_unset=True))
    if "hashed_password" in changes:
        user.hashed_password = changes["hashed_password"]
    if "display_name" in changes:
        user.display_name = changes["display_name"]
    if "email" in changes:
        user.email = changes["email"]
    db.add(user)
    db.commit()
    db.refresh(user)
    return _me(db, user)


class ClassifyRequest(BaseModel):
    """A draft IR, and optionally the problem whose live domain to read.

    Classification of the *shape* does not need the domain. Empty ranges
    and `fractional-data` do: they are properties of the numbers and the
    people, not of the document. `problem_id` is how the editor names
    those without freezing a dataset — `snapshot_dataset()` writes, and a
    keystroke must not.
    """

    ir: dict[str, Any]
    problem_id: int | None = Field(default=None, ge=1)


@router.post("/classify")
def classify_model(
    payload: ClassifyRequest,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    """What kind of model this is, in the classifier's words and a planner's.

    **Posted, not stored.** The same function a run records as
    `classified_as` / `why`, so the editor cannot disagree with the run
    about what the model is. With a `problem_id`, the live domain is
    read (not snapshotted) so a vacuous `forall` and a fractional
    parameter can be named here the same way a run names them.
    `would_solve` is `choose()`'s pick in planner language -- the editor
    never offers a solver, but it does say which kind a run would use.
    """
    from app.solve.backends import planner_choice_for
    from app.solve.classify import classify
    from app.solve.compile import Unsupported, compile_model
    from app.solve.convexity import refine
    from app.solve.preview import live_data

    data = None
    empty_ranges: list[dict[str, Any]] = []
    compiled = None
    if payload.problem_id is not None:
        problem = db.get(Problem, payload.problem_id)
        if problem is None:
            raise HTTPException(status_code=404, detail="problem not found")
        data = live_data(db, problem.domain_id, payload.ir)
        try:
            compiled = compile_model(payload.ir, data)
            empty_ranges = compiled.empty_ranges
        except Unsupported:
            empty_ranges = []

    found = classify(payload.ir, data)
    structure, planner = None, list(found.planner)
    if compiled is not None:
        # The same convexity step a run takes, so the editor does not name
        # a solver for a quadratic model the run would then refuse.
        found = refine(found, compiled)
        planner = list(found.planner)
        # How it splits (queue R4): the input to a decomposition, said plainly.
        from app.solve.blocks import said, structure as structure_of

        structure = structure_of(compiled)
        if (line := said(structure)) is not None:
            planner.append(line)
    return {
        "model_class": found.model_class,
        "needs": sorted(found.needs),
        "reasons": found.reasons,
        "planner": planner,
        "structure": structure,
        "empty_ranges": empty_ranges,
        "would_solve": planner_choice_for(found),
    }


@router.get("/solvers")
def list_solvers(db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    """What this build can solve with. A UI that hardcoded the list would
    offer a solver a different build does not have."""
    from app.api.solver_licences import licence_state
    from app.solve import adapters, conformance
    from app.solve.backends import REGISTRY, is_automatic

    adapters.refresh_verified(db)
    reports = conformance.latest(db)

    return {
        "items": [
            {
                "name": b.name,
                "available": b.is_available(),
                "classes": sorted(b.classes),
                "note": b.note,
                # Queue R41: where it came from, and whether the rules may choose it unasked.
                "origin": b.origin,
                # Whether the rules may choose it unasked: a built-in, or an added solver whose
                # current version passed the conformance kit (queue R43).
                "automatic": is_automatic(b),
                # Whether the rules would actually choose it for a model it fits (operator trial F17): a
                # local solver (IPOPT, the searches) never is -- it runs only when named or as a fallback.
                "chosen_unasked": is_automatic(b) and b.proves != "local",
                "proves": b.proves,
                # Queue R42: whether this organization has the licence the solver needs.
                "licence": licence_state(db, user.organization_id, b),
                **({"kind": b.manifest.kind, "version": b.manifest.version,
                    "conformance": _conformance_of(reports.get(b.name), b.manifest.version)}
                   if b.manifest is not None else {}),
            }
            for b in sorted(REGISTRY, key=lambda b: b.rank)
        ],
        # Manifests that were not loaded, and why.
        "skipped": list(adapters.SKIPPED),
    }


def _conformance_of(report: dict | None, version: str) -> dict[str, Any] | None:
    """The kit's last word on an added solver: none yet, or passed/failed, when, on which version."""
    if report is None:
        return None
    return {"passed": report["passed"], "version": report["version"], "current": report["version"] == version,
            "ran_at": report["ran_at"], "ran_by": report["ran_by"],
            "failed": [c["check"] for c in report["checks"] if c["result"] == "fail"],
            "notes": [c["detail"] for c in report["checks"] if c["result"] == "note"]}


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
    purpose: Literal["plan", "why_not", "shadow", "suite"] = Query(default="plan"),
    parent_run_id: int | None = Query(default=None),
    q: str | None = Query(default=None, description="status or solver contains this; a number also matches the id"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    """Newest first: the last run of a scenario is the one being looked for."""
    # A trade-off front's points are runs of their own, opened from their
    # front's chart; the list shows the run that was asked for.
    # Why-not probes (queue R26) are asked for by `purpose`, not mixed into the plans.
    # Alternative plans (Epic engine) are runs of their own too, listed under their run.
    not_a_point = and_(Run.params["pareto_of"].is_(None), Run.params["alternative_of"].is_(None),
                       Run.purpose == purpose)
    if parent_run_id is not None:
        not_a_point = and_(not_a_point, Run.parent_run_id == parent_run_id)
    searched = search.condition(q, Run.status, Run.params["chosen_solver"].astext, id_column=Run.id)
    if searched is not None:
        not_a_point = and_(not_a_point, searched)
    stmt = select(Run).where(not_a_point)
    count_stmt = select(func.count()).select_from(Run).where(not_a_point)
    if scenario_id is not None:
        stmt = stmt.where(Run.scenario_id == scenario_id)
        count_stmt = count_stmt.where(Run.scenario_id == scenario_id)
    rows = db.scalars(stmt.order_by(Run.id.desc()).limit(limit).offset(offset)).all()
    return {
        "items": [RunSummary.model_validate(r) for r in rows],
        "total": db.scalar(count_stmt) or 0,
    }


class WhyNotCell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    var: str
    index: list[str | int]
    value: float


class WhatIfValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    param: str
    index: list[str | int]
    value: float


class WhyNotRequest(BaseModel):
    """The cells a planner asks about and the value each should have (queue R26), and the
    parameter values to change for the question (a what-if, queue R27)."""

    model_config = ConfigDict(extra="forbid")
    force: list[WhyNotCell] = Field(default_factory=list)
    override: list[WhatIfValue] = Field(default_factory=list)


class WhyNotAnswer(BaseModel):
    """Either the probe queued to answer the question (poll `GET /runs/{run_id}` for its
    `verdict`), or -- when the plan already has every asked cell -- the verdict at once."""

    run_id: int | None
    verdict: dict[str, Any] | None


@router.post("/runs/{run_id}/why-not", status_code=201)
def ask_why_not(
    run_id: int,
    payload: WhyNotRequest,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("run.submit")),
) -> WhyNotAnswer:
    """"Why isn't this so?" about an answered run: a probe on the run's own frozen data with the
    asked cells locked and the rest kept as close to the plan as the rules allow
    (`app.solve.whynot`)."""
    try:
        probe, verdict = whynot.ask(db, run_id, [c.model_dump() for c in payload.force],
                                    [v.model_dump() for v in payload.override])
    except whynot.NotAskable as exc:
        db.rollback()
        raise HTTPException(
            status_code=exc.status,
            detail=[{"type": exc.code, "loc": ["body", "force"], "msg": str(exc)}],
        ) from exc
    except QuotaExceeded as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=[{"type": "quota", "loc": ["quota", exc.quota], "msg": str(exc)}],
        ) from exc
    return WhyNotAnswer(run_id=probe, verdict=verdict)


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> RunRead:
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _read(db, run_id)


class AmountsPage(BaseModel):
    run_id: int
    variable: str | None
    offset: int
    limit: int
    total: int
    chunked: bool
    items: list[dict[str, Any]]


@router.get("/runs/{run_id}/amounts")
def get_run_amounts(
    run_id: int,
    variable: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> AmountsPage:
    """Paginated continuous/integer amounts (OAAS Phase 5).

    Inline `solution.amounts` when the run was small enough; otherwise rows from
    `solution_amount_chunk`. Binary decisions are never listed here.
    """
    if db.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    solution = db.scalars(select(Solution).where(Solution.run_id == run_id)).first()
    if solution is None:
        raise HTTPException(status_code=404, detail="solution not found")

    if solution.amounts is not None:
        rows: list[dict[str, Any]] = []
        for name, entries in sorted(solution.amounts.items()):
            if variable is not None and name != variable:
                continue
            for entry in entries:
                rows.append({"variable": name, **entry})
        page = rows[offset : offset + limit]
        return AmountsPage(
            run_id=run_id,
            variable=variable,
            offset=offset,
            limit=limit,
            total=len(rows),
            chunked=False,
            items=page,
        )

    # Chunked path: flatten requested variable (or all) in chunk order.
    sql = (
        "SELECT variable, chunk_index, rows FROM solution_amount_chunk"
        " WHERE run_id = :r"
        + (" AND variable = :v" if variable else "")
        + " ORDER BY variable, chunk_index"
    )
    params: dict[str, Any] = {"r": run_id}
    if variable:
        params["v"] = variable
    flat: list[dict[str, Any]] = []
    for name, _idx, chunk_rows in db.execute(text(sql), params):
        for entry in chunk_rows or []:
            flat.append({"variable": name, **entry})
    page = flat[offset : offset + limit]
    return AmountsPage(
        run_id=run_id,
        variable=variable,
        offset=offset,
        limit=limit,
        total=len(flat),
        chunked=True,
        items=page,
    )


def _vocabulary(db: Session, run_id: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
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
    notes = {
        spec["id"]: spec["note"].strip()
        for spec in (ir.get("constraints") or [])
        if isinstance(spec, dict) and "id" in spec and isinstance(spec.get("note"), str) and spec["note"].strip()
    }
    return row["labels"] or {}, {"variables": variables, "constraints": constraints}, notes


def _shapes(db: Session, run_id: int) -> tuple[dict[str, str], dict[str, str], dict[str, list[str]], dict[str, dict[str, str]]]:
    """Each decision's kind, each set's role, each set's members in order (queue R17), and each
    interval's start, end and presence decisions -- what a Gantt draws (queue R17b)."""
    row = db.execute(
        text(
            "SELECT mv.ir AS ir, d.data -> 'sets' AS sets, p.domain_id AS domain"
            "  FROM run r JOIN dataset d ON d.id = r.dataset_id JOIN scenario s ON s.id = r.scenario_id"
            "  JOIN problem p ON p.id = s.problem_id JOIN model_version mv ON mv.id = s.model_version_id"
            " WHERE r.id = :r"
        ),
        {"r": run_id},
    ).mappings().one()
    ir = row["ir"] or {}
    kinds = {name: str(spec.get("domain", "binary")) for name, spec in (ir.get("variables") or {}).items()
             if isinstance(spec, dict)}
    names = [s for s in ir.get("sets") or [] if isinstance(s, str)]
    roles = dict(db.execute(
        text("SELECT name, role::text FROM entity_type WHERE domain_id = :d AND name = ANY(:n)"),
        {"d": row["domain"], "n": names},
    ).all()) if names else {}
    sets = row["sets"] or {}
    order = {name: [str(r["id"]) for r in sets.get(name, []) if isinstance(r, dict) and "id" in r] for name in names}
    intervals = {
        name: {part: spec[part] for part in ("start", "end", "presence") if isinstance(spec.get(part), str)}
        for name, spec in (ir.get("variables") or {}).items()
        if isinstance(spec, dict) and spec.get("domain") == "interval"
    }
    return kinds, roles, order, intervals


def _front(db: Session, run: Run) -> dict[str, Any]:
    rows = db.execute(
        text(
            "SELECT seq, first_value, second_value, epsilon, status, point_run_id"
            "  FROM pareto_point WHERE run_id = :r ORDER BY seq"
        ),
        {"r": run.id},
    ).all()
    if not rows:
        return {}
    return {
        "pareto": [
            ParetoPoint(seq=r[0], first=r[1], second=r[2], epsilon=r[3], status=r[4], run_id=r[5]) for r in rows
        ],
        "pareto_terms": (run.params or {}).get("pareto", {}).get("terms"),
    }


def _alternatives(db: Session, run: Run) -> dict[str, Any]:
    rows = db.execute(
        text("SELECT seq, objective, changed, status, point_run_id FROM run_alternative WHERE run_id = :r ORDER BY seq"),
        {"r": run.id},
    ).all()
    if not rows:
        return {}
    return {"alternatives": [AlternativePlan(seq=r[0], objective=r[1], changed=r[2], status=r[3], run_id=r[4])
                             for r in rows]}


def _read(db: Session, run_id: int) -> RunRead:
    run = db.get(Run, run_id)
    solution = db.scalars(select(Solution).where(Solution.run_id == run_id)).first()
    labels, index_sets, rule_notes = _vocabulary(db, run_id)
    kinds, roles, order, intervals = _shapes(db, run_id)
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
        rule_notes=rule_notes,
        variable_kinds=kinds,
        set_roles=roles,
        set_order=order,
        intervals=intervals,
        amounts=solution.amounts if solution else None,
        ranges=solution.ranges if solution else None,
        **_front(db, run),
        **_alternatives(db, run),
        conflict=run.conflict,
        conflict_minimal=run.conflict_minimal,
        assignments=solution.assignments if solution else None,
        reduced_costs=solution.reduced_costs if solution else None,
        constraints=[ConstraintOutcome.model_validate(c) for c in constraints],
    )
