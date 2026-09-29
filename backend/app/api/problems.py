"""Model versions and scenarios -- the PROBLEM half's purpose-built routes.

    GET    /api/v1/problems/{id}/versions   ?limit=&offset=   newest first, no `ir`
    POST   /api/v1/problems/{id}/versions   {ir, note}        -> the created version
    POST   /api/v1/problems/{id}/versions/validate  {ir}      -> {ok: true}, or the 422 publish would give; writes nothing
    GET    /api/v1/versions/{id}                              -> one version, with `ir`
    POST   /api/v1/templates/{id}/apply     {domain_id, name?} or {problem_id} or {domain_name}
    GET    /api/v1/scenarios                ?problem_id=&model_version_id=&limit=&offset=
    POST   /api/v1/scenarios
    GET    /api/v1/scenarios/{id}
    PATCH  /api/v1/scenarios/{id}
    DELETE /api/v1/scenarios/{id}

`problem` itself is **not** served here: it is a flat table with no
cross-row rule, and Task 4 registered it in the generic factory
(`/api/problem/`). This module adds only what the generic factory cannot
express.

Model versions are immutable
----------------------------
Editing a model means inserting its next version. There is deliberately no
PUT, PATCH or DELETE on a version: the `forbid_update()` trigger would
refuse an UPDATE anyway (as a 409, via `translate_db_error`'s P0001
branch), but offering a route the database always rejects is worse than
offering none, so those methods answer 405. DELETE is *not* blocked by the
database; this API simply has no way to issue it. A version goes away only
with its problem (`ON DELETE CASCADE`).

`version` and `ir_hash` are filled by BEFORE INSERT triggers
(`next_model_version()` and `set_hash()`, migration 0007), and the ORM model
does not know that: it declares neither with a server default, so a
``db.add(ModelVersion(...))`` sends explicit NULLs for both and, after the
flush, still believes they are NULL. The insert is therefore a Core
``INSERT ... RETURNING`` naming only `problem_id`, `ir` and `note`, and the
response is built from what RETURNING reports -- the values *after* the
triggers ran -- never from the request. Leaving `version` out of the INSERT
also matters for correctness, not only for reading back: the trigger fills
only a NULL `version`, so a caller-supplied number would be stored verbatim.

`ir_hash` is ``sha256(ir::text)`` over jsonb's canonical text, so two IRs
with the same content hash identically whatever key order or whitespace
they were sent in. It identifies content; it does not deduplicate. Posting
the same IR twice creates two versions with one hash.

What `ir` is validated as
-------------------------
Against the **problem IR contract** -- `docs/contracts/problem-ir.md`, and
`backend/app/ir/contract.json` as the machine-readable half of it. Until
Phase 0 there was no IR schema in this repository, so the IR was free-form
but for the two keys `snapshot_dataset()` reads; the contract now says what
a model is, and `app.ir.validate` judges every document against it.

Two things changed here, and both were holes:

1. **Resolution against the domain happens at submit time.** An IR naming
   a set or a parameter this problem's domain does not have used to be
   accepted, and then failed inside `snapshot_dataset()` as a bare
   ``RAISE EXCEPTION`` -- SQLSTATE P0001, which `translate_db_error` does
   not attribute to a field -- i.e. as a 500 on whatever route eventually
   took a snapshot. It is now a 422 naming the element (Rulings 19, 30).
   The check is deliberately not race-free and does not need to be: a
   domain can lose an entity type after a version is frozen, and
   `snapshot_dataset()` stays the backstop for exactly that. What this
   closes is the case where the IR was never resolvable at all.
2. **A constraint must be expressed, not merely named.** The contract
   admits no "declared but unexpressed" constraint, because a
   `model_version` is immutable, content-hashed and exists to be run. That
   decision is argued in the contract document; the seeded demo was
   rewritten to meet it.

The IR still must be a JSON object, and ``sets`` and ``parameters`` still
must have the shape `snapshot_dataset()` reads them in -- those two rules
are now `sets_not_array` and `parameters_not_object` in the contract, which
is where they were always going to end up once one existed.

Scenarios
---------
A scenario is a patch over one model version. Two rules the database does
not state are enforced here, as 422s:

1. **The version must belong to the scenario's problem.** `scenario`'s
   `problem_id` and `model_version_id` started as two independent foreign
   keys, so the database accepted a scenario pointing at another problem's
   version; migration 0009 (rule 7) closed that with `UNIQUE (id,
   problem_id)` on `model_version` plus the composite FK
   `scenario_version_same_problem_fkey`, which is what the seed and any
   other non-HTTP writer meet. This check is kept because it is the one
   that produces a 422 naming the field rather than a 409. The
   check is race-free in practice: a version's `problem_id` can never
   change (the row is immutable) and this API cannot delete a version.
   `problem_id` is not patchable, for the same reason `domain_id` is not
   patchable elsewhere; re-pointing `model_version_id` is, and is held to
   the same rule.

2. **`patch` has the shape `ProblemIR.patched()` takes**, as documented on
   the column: ``{"disable": [id], "harden": [id], "soften": {id: weight}}``,
   every key optional and no others allowed. Ids are non-empty strings;
   weights are strict positive integers within int64 (CP-SAT's coefficient
   type -- a float, a numeric string or a boolean is refused rather than
   coerced, and a weight of 0 or less would make "softening" a constraint
   either a disable or an incentive to break it). One constraint may carry
   one instruction: an id repeated within a list, or named in two of the
   three, is refused, since which instruction wins would otherwise be left
   to the solver's patch order. The patch is stored exactly as sent: keys
   the client omitted stay omitted rather than being filled with empties.

3. **Every id in the patch names a constraint of the version it patches.**
   This is Task 9's recorded gap, and the contract is what closes it: a
   version's constraint ids are now `ir.constraints[].id`, so there is
   somewhere authoritative to look. A misspelt id used to be stored and
   silently have no effect on the run.

   A version whose IR predates the contract has no `constraints` array to
   check against, and those rows are immutable, so the check applies only
   when the version carries one. That is not a loophole left open: every
   version created from here on is refused unless it carries one.

`scenario.patch` is replaced wholesale on PATCH, not merged, for the reason
`entities.py` records for `attrs`: a merge makes removing a key impossible.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)
from sqlalchemy import and_, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import audit
from app.api import search
from app.api.deps import get_current_user, requires
from app.api.validation import field_error, reject_null
from app.core.db import get_db
from app.crud.db_errors import translate_db_error
from app.ir.validate import validate_ir
from app.models.iam import UserAccount
from app.models.v1_domain import Domain
from app.models.v1_problem import ModelVersion, Problem, Scenario, Template
from app.seed import plant_domain_seed

router = APIRouter(prefix="/api/v1", tags=["model versions and scenarios"])

INT64_MAX = 2**63 - 1
# Ids are `bigint`. Lax, like every other id on the platform; only the
# range is bounded, since an out-of-range id reaches the driver as SQLSTATE
# 22003, which `translate_db_error` re-raises as a 500.
BigintId = Annotated[int, Field(ge=-(2**63), le=INT64_MAX)]
ConstraintId = Annotated[StrictStr, Field(min_length=1)]
Weight = Annotated[StrictInt, Field(ge=1, le=INT64_MAX)]

_version_columns = ModelVersion.__table__.c


# --- schemas ---------------------------------------------------------------


class ModelVersionSummary(BaseModel):
    """A list row. The IR can be large, so it is fetched per version."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    problem_id: int
    version: int
    ir_hash: str
    note: str | None
    created_at: datetime


class ModelVersionRead(ModelVersionSummary):
    ir: dict[str, Any]


class ModelVersionList(BaseModel):
    items: list[ModelVersionSummary]
    total: int


class ModelVersionCreate(BaseModel):
    """`version` and `ir_hash` are not fields: the database assigns both.
    A client that sends them anyway has them ignored, not honoured."""

    ir: dict[str, Any]
    note: str | None = None


Key = Annotated[StrictStr | StrictInt, Field()]


class CellLock(BaseModel):
    """One decision fixed at a value (queue R24, app.solve.locks)."""

    model_config = ConfigDict(extra="forbid")
    var: StrictStr
    index: list[Key]
    value: float


class SliceLock(BaseModel):
    """Every cell of a decision whose index is in the lists, fixed at its value in an earlier run."""

    model_config = ConfigDict(extra="forbid")
    var: StrictStr
    where: dict[StrictStr, Annotated[list[Key], Field(min_length=1)]] = Field(min_length=1)
    from_run: BigintId


class HorizonLock(BaseModel):
    """Every cell indexed by a set's entity whose attribute is before a cut-off, from an earlier run."""

    model_config = ConfigDict(extra="forbid")
    before: StrictStr | float
    attr: StrictStr
    set: StrictStr
    from_run: BigintId
    vars: list[StrictStr] = None  # type: ignore[assignment]


Lock = CellLock | SliceLock | HorizonLock


class StayClose(BaseModel):
    """Change as little as possible from an earlier run (queue R25, app.solve.locks.stay_close):
    `weighted` adds `weight` per changed cell (or unit an amount moved) to the goal; `lex` keeps
    the goal first and, among the plans that reach it, takes the closest."""

    model_config = ConfigDict(extra="forbid")
    from_run: BigintId
    mode: Literal["weighted", "lex"] = None  # type: ignore[assignment]
    weight: Annotated[float, Field(gt=0)] = None  # type: ignore[assignment]
    vars: list[StrictStr] = None  # type: ignore[assignment]


class ScenarioPatch(BaseModel):
    """``ProblemIR.patched()``'s argument. Each key is optional; a key the
    client omits is omitted from what is stored (`model_dump(exclude_unset
    =True)`). The fields are typed non-optional with a ``None`` default, so
    an *explicit* ``null`` is refused while an absent key is fine."""

    model_config = ConfigDict(extra="forbid")

    disable: list[ConstraintId] = None  # type: ignore[assignment]
    harden: list[ConstraintId] = None  # type: ignore[assignment]
    soften: dict[ConstraintId, Weight] = None  # type: ignore[assignment]
    # Parts of a plan held fixed while the rest is solved again (queue R24).
    lock: list[Lock] = None  # type: ignore[assignment]
    stay_close: StayClose = None  # type: ignore[assignment]

    @model_validator(mode="after")
    def _one_instruction_per_constraint(self) -> "ScenarioPatch":
        seen: dict[str, str] = {}
        for key in ("disable", "harden", "soften"):
            ids = getattr(self, key)
            if ids is None:
                continue
            for constraint_id in ids:  # a dict iterates its keys
                if constraint_id in seen:
                    where = (
                        f"twice in {key}"
                        if seen[constraint_id] == key
                        else f"in both {seen[constraint_id]} and {key}"
                    )
                    raise ValueError(
                        f"constraint {constraint_id!r} appears {where}; a patch "
                        "may give each constraint one instruction"
                    )
                seen[constraint_id] = key
        return self

    def stored(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True, exclude_none=True)


class ScenarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    problem_id: int
    model_version_id: int
    name: str
    patch: dict[str, Any]
    created_at: datetime


class ScenarioCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    problem_id: BigintId
    model_version_id: BigintId
    name: str
    patch: ScenarioPatch = Field(default_factory=ScenarioPatch)


class ScenarioUpdate(BaseModel):
    """`problem_id` is deliberately absent (and so ignored if sent): moving
    a scenario to another problem would detach it from its own version and
    from every run already made under it."""

    model_config = ConfigDict(protected_namespaces=())

    name: str | None = None
    model_version_id: BigintId | None = None
    patch: ScenarioPatch | None = None

    _check_not_null = field_validator("name", "model_version_id", "patch")(reject_null)


class ScenarioList(BaseModel):
    items: list[ScenarioRead]
    total: int


class ApplyTemplateRequest(BaseModel):
    """Fill an empty problem, create one in a domain, or make a domain.

    `domain_seed` is walked first: missing types, records and parameter
    cells are created; names that already exist are left alone. An empty
    seed is a no-op, and `validate_ir` still 422s if the IR names a set
    the domain does not have.
    """

    domain_id: BigintId | None = None
    domain_name: str | None = None
    problem_id: BigintId | None = None
    name: str | None = None

    @model_validator(mode="after")
    def _need_a_place(self) -> "ApplyTemplateRequest":
        named = (self.domain_name or "").strip()
        if self.problem_id is None and self.domain_id is None and not named:
            raise ValueError("name a domain to create a problem in, or a problem to fill")
        return self


class ApplyTemplateResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    template_id: int
    domain_id: int
    problem_id: int
    model_version_id: int
    scenario_id: int


# --- helpers ---------------------------------------------------------------


def _get_problem(db: Session, problem_id: int) -> Problem:
    row = db.get(Problem, problem_id)
    if row is None:
        raise HTTPException(status_code=404, detail="problem not found")
    return row


def _get_scenario(db: Session, scenario_id: int) -> Scenario:
    row = db.get(Scenario, scenario_id)
    if row is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    return row


def _commit(db: Session, table: str) -> None:
    try:
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, table) from exc


def _check_ir(db: Session, problem: Problem, ir: dict[str, Any]) -> None:
    """The problem IR contract, both halves. Raises the platform's
    list-form 422 with `loc` naming the element the contract refused."""
    refusal = validate_ir(db, problem.domain_id, ir)
    if refusal is None:
        return
    raise field_error(["ir", *refusal.loc], refusal.message, _at(ir, refusal.loc))


def _at(ir: Any, loc: list) -> Any:
    """What the refusal's `loc` points at, for the 422's `input` field. A
    `loc` naming something absent reports the container instead, which is
    what FastAPI's own missing-field errors do."""
    node = ir
    for step in loc:
        try:
            node = node[step]
        except (KeyError, IndexError, TypeError):
            return node
    return node


def _constraint_ids(db: Session, model_version_id: int) -> set[str] | None:
    """The ids a patch may name: `ir.constraints[].id` of one version.
    ``None`` when the version's IR predates the contract and so carries no
    constraints array -- there is nothing authoritative to check against
    there, and the row is immutable, so it can never gain one."""
    ir = db.execute(
        select(_version_columns.ir).where(_version_columns.id == model_version_id)
    ).scalar_one_or_none()
    if not isinstance(ir, dict) or not isinstance(ir.get("constraints"), list):
        return None
    return {
        constraint["id"]
        for constraint in ir["constraints"]
        if isinstance(constraint, dict) and isinstance(constraint.get("id"), str)
    }


def _check_patch_ids(db: Session, model_version_id: int, patch: "ScenarioPatch") -> None:
    """Task 9's gap: a patch names constraints of the version it patches."""
    known = _constraint_ids(db, model_version_id)
    if known is None:
        return
    for key in ("disable", "harden", "soften"):
        ids = getattr(patch, key)
        if ids is None:
            continue
        for position, constraint_id in enumerate(ids):
            if constraint_id in known:
                continue
            # A list is addressed by position and a mapping by its key --
            # the same `loc` shape Pydantic gives for each, which is what
            # `test_patch_shape_is_validated` already pins.
            where = position if key != "soften" else constraint_id
            raise field_error(
                ["patch", key, where],
                f"model version {model_version_id} declares no constraint "
                f"{constraint_id!r}; it has "
                + (", ".join(sorted(known)) if known else "no constraints at all"),
                constraint_id,
            )


def _check_locks(db: Session, problem_id: int, model_version_id: int, patch: "ScenarioPatch") -> None:
    """What can be known of a lock before the data is (queue R24): the decision and the sets it
    names are this version's, a cell has as many keys as its decision has sets, and an earlier run
    is an answered run of this problem. The rest -- a value within today's bounds, an amount that
    run kept, the attribute a horizon compares -- is refused when the run is compiled."""
    if not patch.lock and not patch.stay_close:
        return
    ir = db.execute(select(_version_columns.ir).where(_version_columns.id == model_version_id)).scalar_one()
    decisions = {name: spec.get("index", []) for name, spec in (ir.get("variables") or {}).items()
                 if isinstance(spec, dict) and spec.get("domain") != "interval"}

    def refuse(position: int, key: str, code: str, message: str, value: Any) -> None:
        raise field_error(["patch", "lock", position, key], f"{code}: {message}", value)

    if patch.stay_close:
        stay = patch.stay_close
        for name in stay.vars or []:
            if name not in decisions:
                raise field_error(["patch", "stay_close", "vars"],
                                  f"stay_close_unknown: model version {model_version_id} has no decision {name!r}", name)
        if not _answered(db, problem_id, stay.from_run):
            raise field_error(["patch", "stay_close", "from_run"],
                              f"stay_close_run_invalid: run {stay.from_run} is not an answered run of this problem",
                              stay.from_run)

    for position, lock in enumerate(patch.lock or []):
        names = [lock.var] if not isinstance(lock, HorizonLock) else (lock.vars or [])
        for name in names:
            if name not in decisions:
                refuse(position, "vars" if isinstance(lock, HorizonLock) else "var", "lock_unknown",
                       f"model version {model_version_id} has no decision {name!r}"
                       + (f"; it has {', '.join(sorted(decisions))}" if decisions else ""), name)
        if isinstance(lock, CellLock) and len(lock.index) != len(decisions[lock.var]):
            refuse(position, "index", "lock_index_arity",
                   f"{lock.var!r} is indexed by {decisions[lock.var]}, so a cell names {len(decisions[lock.var])} keys",
                   lock.index)
        if isinstance(lock, SliceLock):
            for s in lock.where:
                if s not in decisions[lock.var]:
                    refuse(position, "where", "lock_unknown", f"{lock.var!r} is not indexed by {s!r}", s)
        if isinstance(lock, HorizonLock):
            if lock.set not in (ir.get("sets") or []):
                refuse(position, "set", "lock_unknown", f"model version {model_version_id} has no set {lock.set!r}", lock.set)
            for name in names:
                if lock.set not in decisions[name]:
                    refuse(position, "vars", "lock_unknown", f"{name!r} is not indexed by {lock.set!r}", name)
        if not isinstance(lock, CellLock):
            if not _answered(db, problem_id, lock.from_run):
                refuse(position, "from_run", "lock_run_invalid",
                       f"run {lock.from_run} is not an answered run of this problem", lock.from_run)


def _answered(db: Session, problem_id: int, run_id: int) -> bool:
    """Whether a run is an answered run of this problem: what a lock or stay_close may read from."""
    return db.execute(
        text(
            "SELECT 1 FROM run r JOIN scenario s ON s.id = r.scenario_id JOIN solution so ON so.run_id = r.id"
            " WHERE r.id = :r AND s.problem_id = :p AND r.status IN ('optimal', 'feasible')"
        ),
        {"r": run_id, "p": problem_id},
    ).first() is not None


def _check_gate(db: Session, problem_id: int, model_version_id: int) -> None:
    """Queue R30: a version is put into use only once it has passed the problem's cases."""
    from app.solve import suite

    held = suite.gate(db, problem_id, model_version_id)
    if held:
        raise HTTPException(status_code=409, detail=[{"type": "version_not_checked", "loc": ["body", "model_version_id"],
                                                     "msg": held}])


def _check_version_belongs(db: Session, problem_id: int, model_version_id: int) -> None:
    """The rule the schema does not state: a scenario's version must be a
    version of the scenario's own problem."""
    owner = db.execute(
        select(_version_columns.problem_id).where(_version_columns.id == model_version_id)
    ).scalar_one_or_none()
    if owner is None:
        raise field_error(
            "model_version_id", f"model version {model_version_id} does not exist", model_version_id
        )
    if owner != problem_id:
        raise field_error(
            "model_version_id",
            f"model version {model_version_id} belongs to problem {owner}, not to this "
            f"scenario's problem {problem_id}; a scenario patches a version of its own problem",
            model_version_id,
        )


# --- model versions ----------------------------------------------------------


@router.get("/problems/{problem_id}/versions")
def list_versions(
    problem_id: int,
    q: str | None = Query(None, description="the note contains this; a number also matches the version number or id"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> ModelVersionList:
    _get_problem(db, problem_id)
    where = _version_columns.problem_id == problem_id
    searched = search.condition(q, _version_columns.note, id_column=_version_columns.id,
                                number_columns=(_version_columns.version,))
    if searched is not None:
        where = and_(where, searched)
    total = db.execute(
        select(func.count()).select_from(ModelVersion.__table__).where(where)
    ).scalar_one()
    rows = db.execute(
        select(*(c for c in _version_columns if c.name != "ir"))
        .where(where)
        # Newest first. `version` is unique per problem, so it is a total
        # order on its own; it is *not* the same as id order, since an
        # importer may insert explicit numbers.
        .order_by(_version_columns.version.desc())
        .offset(offset)
        .limit(limit)
    ).mappings()
    return ModelVersionList(
        items=[ModelVersionSummary.model_validate(dict(row)) for row in rows], total=total
    )


@router.post("/problems/{problem_id}/versions/validate")
def validate_version(
    problem_id: int,
    payload: ModelVersionCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("model.publish")),
) -> dict[str, bool]:
    """What publishing this IR would say, without publishing it: the block
    editor asks on every pause, so a refusal only the domain can make (a
    set that is not one of its entity types) shows before Publish. Writes
    nothing; answers exactly as `create_version` would refuse."""
    _check_ir(db, _get_problem(db, problem_id), payload.ir)
    return {"ok": True}


@router.post("/problems/{problem_id}/versions", status_code=201)
def create_version(
    problem_id: int,
    payload: ModelVersionCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("model.publish")),
) -> ModelVersionRead:
    problem = _get_problem(db, problem_id)
    _check_ir(db, problem, payload.ir)
    # Core, not ORM: see the module docstring. RETURNING reports the row as
    # the BEFORE INSERT triggers left it, so `version` and `ir_hash` are the
    # database's own values.
    statement = (
        insert(ModelVersion.__table__)
        .values(problem_id=problem_id, ir=payload.ir, note=payload.note)
        .returning(*_version_columns)
    )
    try:
        row = db.execute(statement).mappings().one()
        audit.write(
            db, user, request,
            action="model.publish",
            object_type="model_version",
            object_id=row["id"],
            after={"problem_id": problem_id, "version": row["version"], "note": payload.note},
        )
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, "model_version") from exc
    return ModelVersionRead.model_validate(dict(row))


@router.post("/templates/{template_id}/apply", status_code=201)
def apply_template(
    template_id: int,
    payload: ApplyTemplateRequest,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("model.publish")),
) -> ApplyTemplateResult:
    """Start a problem from a template's IR.

    `plant_domain_seed` runs first: missing types named by `domain_seed`
    are created, existing names are skipped. `validate_ir` still refuses
    a miss, so a template whose seed is empty cannot half-build a domain.

    Creating a problem uses `name`, defaulting to the template's. Filling
    an existing one refuses if it already has a version -- a template
    starts a model, it does not overwrite one. `domain_name` makes a
    domain when neither `domain_id` nor `problem_id` is given.
    """
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")

    problem: Problem | None = None
    if payload.problem_id is not None:
        problem = _get_problem(db, payload.problem_id)
        if payload.domain_id is not None and problem.domain_id != payload.domain_id:
            raise HTTPException(
                status_code=422,
                detail="that problem does not belong to the named domain",
            )
        already = db.scalar(
            select(func.count())
            .select_from(ModelVersion.__table__)
            .where(_version_columns.problem_id == problem.id)
        )
        if already:
            raise HTTPException(
                status_code=422,
                detail="this problem already has a model; a template starts one, it does not replace it",
            )
        problem.template_id = template.id
        domain_id = problem.domain_id
    elif payload.domain_id is not None:
        if db.get(Domain, payload.domain_id) is None:
            raise HTTPException(status_code=404, detail="domain not found")
        domain_id = payload.domain_id
    else:
        domain = Domain(name=(payload.domain_name or "").strip())
        db.add(domain)
        try:
            db.flush()
        except DBAPIError as exc:
            db.rollback()
            raise translate_db_error(exc, "domain") from exc
        domain_id = domain.id

    plant_domain_seed(db, domain_id, template.domain_seed)

    if problem is None:
        problem = Problem(
            domain_id=domain_id,
            name=payload.name or template.name,
            owner=user.username,
            template_id=template.id,
        )
        db.add(problem)
        try:
            db.flush()
        except DBAPIError as exc:
            db.rollback()
            raise translate_db_error(exc, "problem") from exc

    try:
        _check_ir(db, problem, template.default_ir)
    except HTTPException:
        db.rollback()
        raise
    statement = (
        insert(ModelVersion.__table__)
        .values(
            problem_id=problem.id,
            ir=template.default_ir,
            note=f"from template {template.name}",
        )
        .returning(_version_columns.id)
    )
    try:
        version_id = db.execute(statement).scalar_one()
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, "model_version") from exc

    scenario = Scenario(
        problem_id=problem.id,
        model_version_id=version_id,
        name="as modelled",
        patch={},
    )
    db.add(scenario)
    _commit(db, "scenario")
    db.refresh(scenario)
    return ApplyTemplateResult(
        template_id=template.id,
        domain_id=problem.domain_id,
        problem_id=problem.id,
        model_version_id=version_id,
        scenario_id=scenario.id,
    )


@router.get("/versions/{version_id}")
def get_version(
    version_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> ModelVersionRead:
    row = db.execute(
        select(*_version_columns).where(_version_columns.id == version_id)
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="model version not found")
    return ModelVersionRead.model_validate(dict(row))


# --- scenarios ---------------------------------------------------------------


@router.get("/scenarios")
def list_scenarios(
    problem_id: int | None = Query(None),
    model_version_id: int | None = Query(None),
    include_checks: bool = Query(False),
    q: str | None = Query(None, description="the name contains this; a number also matches the id"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> ScenarioList:
    query = db.query(Scenario)
    if problem_id is not None:
        query = query.filter(Scenario.problem_id == problem_id)
    if model_version_id is not None:
        query = query.filter(Scenario.model_version_id == model_version_id)
    # Acceptance-check scenarios (queue R29/R30) stay off the planner's list unless asked for.
    if not include_checks:
        query = query.filter(~Scenario.name.like("checks: version %"))
    searched = search.condition(q, Scenario.name, id_column=Scenario.id)
    if searched is not None:
        query = query.filter(searched)
    total = query.count()
    # `name` is unique per problem, not globally, so `id` completes the order.
    rows = query.order_by(Scenario.name.asc(), Scenario.id.asc()).offset(offset).limit(limit).all()
    return ScenarioList(items=[ScenarioRead.model_validate(row) for row in rows], total=total)


@router.post("/scenarios", status_code=201)
def create_scenario(
    payload: ScenarioCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("model.publish")),
) -> ScenarioRead:
    _check_version_belongs(db, payload.problem_id, payload.model_version_id)
    _check_gate(db, payload.problem_id, payload.model_version_id)
    _check_patch_ids(db, payload.model_version_id, payload.patch)
    _check_locks(db, payload.problem_id, payload.model_version_id, payload.patch)
    row = Scenario(
        problem_id=payload.problem_id,
        model_version_id=payload.model_version_id,
        name=payload.name,
        patch=payload.patch.stored(),
    )
    db.add(row)
    _commit(db, "scenario")
    db.refresh(row)
    audit.write(
        db, user, request,
        action="scenario.create",
        object_type="scenario",
        object_id=row.id,
        after={"name": row.name, "model_version_id": row.model_version_id, "patch": row.patch},
    )
    db.commit()
    return ScenarioRead.model_validate(row)


@router.get("/scenarios/{scenario_id}")
def get_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> ScenarioRead:
    return ScenarioRead.model_validate(_get_scenario(db, scenario_id))


@router.patch("/scenarios/{scenario_id}")
def update_scenario(
    scenario_id: int,
    payload: ScenarioUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("model.publish")),
) -> ScenarioRead:
    row = _get_scenario(db, scenario_id)
    before = {"name": row.name, "model_version_id": row.model_version_id, "patch": row.patch}
    changes = payload.model_fields_set
    if "model_version_id" in changes:
        _check_version_belongs(db, row.problem_id, payload.model_version_id)
        if payload.model_version_id != row.model_version_id:
            _check_gate(db, row.problem_id, payload.model_version_id)
        row.model_version_id = payload.model_version_id
    if "name" in changes:
        row.name = payload.name
    if "patch" in changes:
        row.patch = payload.patch.stored()
    # Judged after both changes are applied, and against whichever version
    # the scenario ends up on: re-pointing a scenario at another version
    # orphans a patch id just as surely as editing the patch does, so a
    # PATCH that changes only `model_version_id` is checked too.
    if "patch" in changes or "model_version_id" in changes:
        _check_patch_ids(db, row.model_version_id, ScenarioPatch(**row.patch))
        _check_locks(db, row.problem_id, row.model_version_id, ScenarioPatch(**row.patch))
    action = "scenario.lock" if "patch" in changes and (row.patch or {}).get("lock") else "scenario.update"
    _commit(db, "scenario")
    db.refresh(row)
    audit.write(
        db, user, request,
        action=action,
        object_type="scenario",
        object_id=row.id,
        before=before,
        after={"name": row.name, "model_version_id": row.model_version_id, "patch": row.patch},
    )
    db.commit()
    return ScenarioRead.model_validate(row)


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(
    scenario_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("model.publish")),
) -> None:
    # `run` rows cascade in the database (ON DELETE CASCADE).
    row = _get_scenario(db, scenario_id)
    audit.write(
        db, user, request,
        action="scenario.delete",
        object_type="scenario",
        object_id=row.id,
        before={"name": row.name, "model_version_id": row.model_version_id},
    )
    db.delete(row)
    _commit(db, "scenario")
