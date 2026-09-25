"""Entities -- rows of a domain's data, with database-validated attributes.

    GET    /api/v1/entities            ?entity_type_id=&q=&expr=&limit=&offset=
    POST   /api/v1/entities
    GET    /api/v1/entities/{id}
    PATCH  /api/v1/entities/{id}
    DELETE /api/v1/entities/{id}

`attrs` is a free-form JSON object. That is deliberate and it is the whole
design of this router: which attributes an entity may carry, whether each
is required, and what type its value must be are all declared in
`attribute_def` rows, which this module never reads. The `entity_validate`
trigger (migration ``0006_schema_v1_domain``) is the validator, and it is
also what **materialises** ``attribute_def.default_value`` into ``attrs``
on write -- so the stored row is not always the submitted row, and every
write path here re-reads the row before answering.

Why not mirror the rules in Pydantic
------------------------------------
Because they are data, not schema. A Pydantic model would have to be built
per entity type, per request, from `attribute_def` -- and would then be a
second implementation of the trigger's `CASE d.data_type` arms, free to
drift from it. Every other writer (the seed, a migration, psql, a future
worker) goes through the trigger regardless, so the trigger is the only
place the rules can live exactly once.

Which layer answers which failure
---------------------------------
Two shapes are reachable from this router, and the split is by who can
possibly know:

1. **422, list `detail`, from the trigger** -- via Task 3's
   :func:`translate_db_error`, which (since Task 7, Ruling 19) emits
   FastAPI's own list shape with ``loc: ["body", <field>]`` and ``kind``
   carried as a sibling key on the item. `kind` is one of
   ``unknown_attribute``, ``required_attribute``, ``attribute_type``; the
   three the trigger emits. This is the first router on the platform from
   which that contract is reachable at all: Task 5's tables carry no
   trigger, so their CHECK failures arrive with no `DETAIL` and come back
   as a 409 (Ruling 16).
2. **422, list `detail`, from the request layer** -- FastAPI's own body
   validation (no ``kind`` key), for what this
   module can decide without the database: `attrs` being an object at all
   (the table's ``CHECK (jsonb_typeof(attrs) = 'object')`` is a plain
   CHECK with no `DETAIL`, so leaving it to the database would produce a
   409 for a plainly malformed body), and the ordinary column types.
3. **409, string `detail`** -- :func:`translate_db_error`'s other branch:
   ``UNIQUE (entity_type_id, key)`` and the ``entity_type_id`` foreign
   key. `entity_type_id` is a body field rather than a path segment, so a
   bad one is a conflict with the data, not a missing resource -- the same
   answer Task 5 gives for a bad `domain_id`.

Both 422 sources share one body shape, so a client never branches on it;
``kind`` is present exactly when the database's trigger answered. Until
Task 7 the trigger's 422 was an object instead -- see Ruling 19.

Filtering by an expression (Task 14d)
-------------------------------------
`expr` carries the same JSON document the browser's condition builder
writes (`frontend/src/expressions/document.ts`), and
`app/expressions/` compiles it to a parameterised predicate. Three
properties are worth stating here rather than only there:

- it **narrows**. The predicate is one more `filter()` on the query this
  route had already built, so an expression can never return a row the
  route would not have returned without it, and the route's
  authentication and `entity_type_id` scoping are untouched.
- a refusal is a **422 in the same list shape as every other** (Ruling
  19), with `loc = ["query", "expr", ...<a path into the document>]` so
  the builder can point at the rule that is wrong (Ruling 30).
- nothing in the document becomes SQL text. Literals and attribute names
  are bound parameters; column, function and direction names are dict
  lookups that yield objects. See `app/expressions/compiler.py`.

`key` deliberately carries no request-layer *pattern*: unlike
`entity_type.name` and `attribute_def.name`, `entity.key` has no shape
rule in the DDL, and inventing one the database does not have is what
makes the two layers drift (the reasoning Task 5 recorded for
`enum_values`). Migration 0009 (rule 2) does add one CHECK --
`entity_key_not_blank`, `key ~ '[^[:space:]]'` -- and
`translate_db_error` names that constraint as a 422 on `key` rather than
collapsing it into the generic CHECK 409.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.concurrency import check_not_stale
from app.api.deps import get_current_user, requires
from app.api.validation import field_error
from app.core.db import get_db
from app.crud.db_errors import translate_db_error
from app.expressions import ExpressionRefusal, compile_expression, parse_expression
from app.models.iam import UserAccount
from app.models.v1_domain import Entity

router = APIRouter(prefix="/api/v1", tags=["entities"])


# --- schemas ---------------------------------------------------------------


class EntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_type_id: int
    key: str
    label: str | None
    sort_order: int
    active: bool
    # Always the **stored** object, which may carry defaults the request
    # never mentioned -- see the module docstring.
    attrs: dict[str, Any]
    # Migration 0010, Ruling 42. Send it back on PATCH and a save built on
    # a superseded read is refused with a 409 instead of silently reverting
    # whatever another client changed in the meantime.
    updated_at: datetime


class EntityCreate(BaseModel):
    entity_type_id: int
    key: str
    label: str | None = None
    # These three mirror the column defaults, so a payload may omit them.
    sort_order: int = 0
    active: bool = True
    attrs: dict[str, Any] = Field(default_factory=dict)


class EntityUpdate(BaseModel):
    """Every field optional; `model_dump(exclude_unset=True)` is what
    distinguishes "not supplied" from an explicit value.

    `attrs` is one JSONB column and is replaced wholesale, not merged: a
    merge would make it impossible to remove an attribute, and would mean
    the value the trigger validates is one no request ever stated. That
    is exactly why `updated_at` exists: wholesale replacement is what
    makes a concurrent edit recoverable only by detecting it.
    """

    key: str | None = None
    label: str | None = None
    sort_order: int | None = None
    active: bool | None = None
    attrs: dict[str, Any] | None = None
    # Ruling 42: the `updated_at` the client last read. It is NOT a
    # column update -- `update_entity` pops it before assigning the rest,
    # and the database's trigger is the only writer of that column.
    # Omitted means "no check", which is what keeps every pre-0010 caller
    # working; see `app/api/concurrency.py`.
    updated_at: datetime | None = None


class EntityList(BaseModel):
    items: list[EntityRead]
    total: int


# --- helpers ---------------------------------------------------------------


def _get_entity(db: Session, entity_id: int, *, for_update: bool = False) -> Entity:
    # `for_update` is passed only when the caller supplied an `updated_at`
    # to check against: reading, comparing and writing are three steps, and
    # without the lock a second client can commit between the second and
    # the third. See `app/api/concurrency.py`.
    entity = db.get(Entity, entity_id, with_for_update=True) if for_update else db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="entity not found")
    return entity


def _commit(db: Session) -> None:
    """Commit, turning a trigger or constraint failure into Task 3's
    HTTPException. Same three-line shape as `entity_types.py` and
    `factory.py`, not a reimplementation of the translation itself."""
    try:
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, "entity") from exc


# --- routes ----------------------------------------------------------------


def _expression_filter(db: Session, expr: str):
    """`expr` as a predicate, or a 422 naming the rule that is wrong.

    Two steps, and the order is the security property (see
    `app/expressions/__init__.py`): `parse_expression` has no database in
    scope, so everything it can refuse is refused before one is reachable;
    `compile_expression` reads `attribute_def` and `relationship_type` and
    nothing else, so even its refusals happen without `entity` being read.

    The refusal's `path` points into the document, and becomes `loc`
    beneath `["query", "expr"]` -- FastAPI's own list shape (Ruling 19's
    single 422 body), keyed by `loc` rather than by a code (Ruling 30), so
    the builder can highlight the offending rule.
    """
    try:
        parsed = parse_expression(expr)
        return compile_expression(db, parsed)
    except ExpressionRefusal as refusal:
        raise field_error(
            ["expr", *refusal.path], refusal.message, None, where="query"
        ) from refusal


@router.get("/entities")
def list_entities(
    entity_type_id: int | None = Query(None),
    family: bool = Query(False, description="with entity_type_id: its descendants' entities too (queue R18)"),
    q: str | None = Query(None, description="matches key or label, case-insensitively"),
    expr: str | None = Query(
        None,
        description=(
            "a JSON expression document (frontend/src/expressions/document.ts), "
            "which narrows this list further -- it can never widen it"
        ),
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> EntityList:
    query = db.query(Entity)
    if entity_type_id is not None and family:
        # What a reference to this type may name (migration 0067).
        query = query.filter(
            Entity.entity_type_id == func.any(func.entity_type_family(entity_type_id))
        )
    elif entity_type_id is not None:
        query = query.filter(Entity.entity_type_id == entity_type_id)
    # The expression is one more `filter()` on the query the route had
    # already built, which is what makes "it cannot widen what a caller
    # sees" structural rather than a promise: every predicate this adds is
    # ANDed with the ones above and below it.
    if expr is not None:
        query = query.filter(_expression_filter(db, expr))
    if q:
        # `%` and `_` in the needle are escaped so a user typing them gets a
        # literal search rather than a silently wider one.
        needle = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(
            or_(
                Entity.key.ilike(needle, escape="\\"),
                Entity.label.ilike(needle, escape="\\"),
            )
        )
    total = query.count()
    # `sort_order` first: it is what makes mon..sun come back in week order
    # rather than alphabetically. `key` then `id` complete the total order,
    # without which offset pagination can skip or repeat rows across pages.
    rows = (
        query.order_by(Entity.sort_order.asc(), Entity.key.asc(), Entity.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return EntityList(items=[EntityRead.model_validate(row) for row in rows], total=total)


def _check_geometries(db: Session, entity_type_id: int, attrs: dict[str, Any] | None) -> None:
    """A geometry is judged here in full (the trigger only coarsely), so a
    refusal names the ring or position at fault (migration 0049)."""
    if not attrs:
        return
    from app.spatial.geometry import validate_geometry

    names = db.execute(
        text("SELECT name FROM attribute_def WHERE entity_type_id = :t AND data_type::text = 'geometry'"),
        {"t": entity_type_id},
    ).scalars()
    for name in names:
        value = attrs.get(name)
        if value is not None:
            fault = validate_geometry(value)
            if fault:
                raise field_error(["attrs", name], fault, value)


@router.post("/entities", status_code=201)
def create_entity(
    payload: EntityCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("domain.edit")),
) -> EntityRead:
    _check_geometries(db, payload.entity_type_id, payload.attrs)
    entity = Entity(**payload.model_dump())
    db.add(entity)
    _commit(db)
    # Re-read rather than echo the payload: the trigger may have added
    # materialised defaults to `attrs`, and the response has to agree with
    # what a subsequent GET will return.
    db.refresh(entity)
    return EntityRead.model_validate(entity)


@router.get("/entities/{entity_id}")
def get_entity(
    entity_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> EntityRead:
    return EntityRead.model_validate(_get_entity(db, entity_id))


@router.patch("/entities/{entity_id}")
def update_entity(
    entity_id: int,
    payload: EntityUpdate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("domain.edit")),
) -> EntityRead:
    changes = payload.model_dump(exclude_unset=True)
    expected = changes.pop("updated_at", None)
    entity = _get_entity(db, entity_id, for_update=expected is not None)
    check_not_stale("entity", entity.updated_at, expected)
    if "attrs" in changes:
        _check_geometries(db, entity.entity_type_id, changes["attrs"])
    for field, value in changes.items():
        setattr(entity, field, value)
    # `entity_validate` is BEFORE INSERT **OR UPDATE**, so this path gets
    # the identical contract -- including defaults being materialised into
    # a row that predates the attribute_def carrying them.
    _commit(db)
    db.refresh(entity)
    return EntityRead.model_validate(entity)


@router.delete("/entities/{entity_id}", status_code=204)
def delete_entity(
    entity_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("domain.edit")),
) -> None:
    # Relationships cascade (ON DELETE CASCADE) and `parameter_value` rows
    # indexed by this entity are removed by the `parameter_value_cleanup`
    # BEFORE DELETE trigger -- arrays cannot carry a foreign key, so the
    # trigger is what stands in for one. Nothing to do here but issue the
    # DELETE and let the database finish it.
    db.delete(_get_entity(db, entity_id))
    _commit(db)
