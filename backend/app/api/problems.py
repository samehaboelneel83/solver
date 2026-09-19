"""Model versions and scenarios -- the PROBLEM half's purpose-built routes.

    GET    /api/v1/problems/{id}/versions   ?limit=&offset=   newest first, no `ir`
    POST   /api/v1/problems/{id}/versions   {ir, note}        -> the created version
    GET    /api/v1/versions/{id}                              -> one version, with `ir`
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
There is no IR schema in this repository (the compiler that defines it is
absent), so the IR is free-form, with two exceptions. It must be a JSON
object, and the two keys the platform *itself* reads must have the shape it
reads them in: `snapshot_dataset()` iterates ``ir.sets`` with
``jsonb_array_elements_text`` and ``ir.parameters`` with
``jsonb_object_keys``. Any other shape -- including an explicit ``null`` --
makes that function fail with SQLSTATE 22023, which ``translate_db_error``
does not recognise, so a bad IR accepted here would surface much later as
a 500 from the snapshot. So ``sets``, when present, must be an array of
strings and ``parameters``, when present, an object. Whether those names
resolve against the domain is **not** checked: the domain changes over
time, and `snapshot_dataset()` already refuses an unresolvable name with a
readable message at the moment it matters.

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

   Patch ids are **not** checked against the version's IR. The IR has no
   schema here, so there is nowhere authoritative to find its constraint
   ids; guessing a layout would reject valid patches as readily as it
   caught typos. `ProblemIR.patched()` is the authority, and it does not
   exist in this repository yet. Until it does, a misspelt id is stored
   and silently has no effect.

`scenario.patch` is replaced wholesale on PATCH, not merged, for the reason
`entities.py` records for `attrs`: a merge makes removing a key impossible.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)
from sqlalchemy import func, insert, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.validation import field_error, reject_null
from app.core.db import get_db
from app.crud.db_errors import translate_db_error
from app.models.iam import UserAccount
from app.models.v1_problem import ModelVersion, Problem, Scenario

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


class ScenarioPatch(BaseModel):
    """``ProblemIR.patched()``'s argument. Each key is optional; a key the
    client omits is omitted from what is stored (`model_dump(exclude_unset
    =True)`). The fields are typed non-optional with a ``None`` default, so
    an *explicit* ``null`` is refused while an absent key is fine."""

    model_config = ConfigDict(extra="forbid")

    disable: list[ConstraintId] = None  # type: ignore[assignment]
    harden: list[ConstraintId] = None  # type: ignore[assignment]
    soften: dict[ConstraintId, Weight] = None  # type: ignore[assignment]

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
        return self.model_dump(exclude_unset=True)


class ScenarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    problem_id: int
    model_version_id: int
    name: str
    patch: dict[str, Any]
    created_at: datetime


class ScenarioCreate(BaseModel):
    problem_id: BigintId
    model_version_id: BigintId
    name: str
    patch: ScenarioPatch = Field(default_factory=ScenarioPatch)


class ScenarioUpdate(BaseModel):
    """`problem_id` is deliberately absent (and so ignored if sent): moving
    a scenario to another problem would detach it from its own version and
    from every run already made under it."""

    name: str | None = None
    model_version_id: BigintId | None = None
    patch: ScenarioPatch | None = None

    _check_not_null = field_validator("name", "model_version_id", "patch")(reject_null)


class ScenarioList(BaseModel):
    items: list[ScenarioRead]
    total: int


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


def _check_ir(ir: dict[str, Any]) -> None:
    """The two IR keys `snapshot_dataset()` reads, in the shape it reads
    them. See the module docstring for why nothing else is checked."""
    if "sets" in ir:
        sets = ir["sets"]
        if not isinstance(sets, list):
            raise field_error(["ir", "sets"], "sets must be an array of entity type names", sets)
        for i, name in enumerate(sets):
            if not isinstance(name, str):
                raise field_error(
                    ["ir", "sets", i], "each set must be an entity type name (a string)", name
                )
    if "parameters" in ir and not isinstance(ir["parameters"], dict):
        raise field_error(
            ["ir", "parameters"],
            "parameters must be an object keyed by parameter name",
            ir["parameters"],
        )


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
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> ModelVersionList:
    _get_problem(db, problem_id)
    where = _version_columns.problem_id == problem_id
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


@router.post("/problems/{problem_id}/versions", status_code=201)
def create_version(
    problem_id: int,
    payload: ModelVersionCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> ModelVersionRead:
    _get_problem(db, problem_id)
    _check_ir(payload.ir)
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
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, "model_version") from exc
    return ModelVersionRead.model_validate(dict(row))


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
    total = query.count()
    # `name` is unique per problem, not globally, so `id` completes the order.
    rows = query.order_by(Scenario.name.asc(), Scenario.id.asc()).offset(offset).limit(limit).all()
    return ScenarioList(items=[ScenarioRead.model_validate(row) for row in rows], total=total)


@router.post("/scenarios", status_code=201)
def create_scenario(
    payload: ScenarioCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> ScenarioRead:
    _check_version_belongs(db, payload.problem_id, payload.model_version_id)
    row = Scenario(
        problem_id=payload.problem_id,
        model_version_id=payload.model_version_id,
        name=payload.name,
        patch=payload.patch.stored(),
    )
    db.add(row)
    _commit(db, "scenario")
    db.refresh(row)
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
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> ScenarioRead:
    row = _get_scenario(db, scenario_id)
    changes = payload.model_fields_set
    if "model_version_id" in changes:
        _check_version_belongs(db, row.problem_id, payload.model_version_id)
        row.model_version_id = payload.model_version_id
    if "name" in changes:
        row.name = payload.name
    if "patch" in changes:
        row.patch = payload.patch.stored()
    _commit(db, "scenario")
    db.refresh(row)
    return ScenarioRead.model_validate(row)


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> None:
    # `run` rows cascade in the database (ON DELETE CASCADE).
    db.delete(_get_scenario(db, scenario_id))
    _commit(db, "scenario")
