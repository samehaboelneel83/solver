"""Entities -- rows of a domain's data, with database-validated attributes.

    GET    /api/v1/entities            ?entity_type_id=&q=&limit=&offset=
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
Three shapes are reachable from this router, and the split is by who can
possibly know:

1. **422, object `detail`** (``{"message", "field", "kind"}``) -- the
   trigger, via Task 3's :func:`translate_db_error`. `kind` is one of
   ``unknown_attribute``, ``required_attribute``, ``attribute_type``; the
   three the trigger emits. This is the first router on the platform from
   which that contract is reachable at all: Task 5's tables carry no
   trigger, so their CHECK failures arrive with no `DETAIL` and come back
   as a 409 (Ruling 16).
2. **422, list `detail`** -- FastAPI's own body validation, for what this
   module can decide without the database: `attrs` being an object at all
   (the table's ``CHECK (jsonb_typeof(attrs) = 'object')`` is a plain
   CHECK with no `DETAIL`, so leaving it to the database would produce a
   409 for a plainly malformed body), and the ordinary column types.
3. **409, string `detail`** -- :func:`translate_db_error`'s other branch:
   ``UNIQUE (entity_type_id, key)`` and the ``entity_type_id`` foreign
   key. `entity_type_id` is a body field rather than a path segment, so a
   bad one is a conflict with the data, not a missing resource -- the same
   answer Task 5 gives for a bad `domain_id`.

Two of those are 422 with different bodies, which a client has to branch
on. That asymmetry is inherited from the spec, not chosen here; see the
task 6 report.

`key` deliberately carries no request-layer pattern: unlike
`entity_type.name` and `attribute_def.name`, `entity.key` has no CHECK in
the DDL, and inventing a rule the database does not have is what makes the
two layers drift (the reasoning Task 5 recorded for `enum_values`).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.crud.db_errors import translate_db_error
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
    the value the trigger validates is one no request ever stated.
    """

    key: str | None = None
    label: str | None = None
    sort_order: int | None = None
    active: bool | None = None
    attrs: dict[str, Any] | None = None


class EntityList(BaseModel):
    items: list[EntityRead]
    total: int


# --- helpers ---------------------------------------------------------------


def _get_entity(db: Session, entity_id: int) -> Entity:
    entity = db.get(Entity, entity_id)
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


@router.get("/entities")
def list_entities(
    entity_type_id: int | None = Query(None),
    q: str | None = Query(None, description="matches key or label, case-insensitively"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> EntityList:
    query = db.query(Entity)
    if entity_type_id is not None:
        query = query.filter(Entity.entity_type_id == entity_type_id)
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


@router.post("/entities", status_code=201)
def create_entity(
    payload: EntityCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> EntityRead:
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
    _: UserAccount = Depends(get_current_user),
) -> EntityRead:
    entity = _get_entity(db, entity_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
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
    _: UserAccount = Depends(get_current_user),
) -> None:
    # Relationships cascade (ON DELETE CASCADE) and `parameter_value` rows
    # indexed by this entity are removed by the `parameter_value_cleanup`
    # BEFORE DELETE trigger -- arrays cannot carry a foreign key, so the
    # trigger is what stands in for one. Nothing to do here but issue the
    # DELETE and let the database finish it.
    db.delete(_get_entity(db, entity_id))
    _commit(db)
