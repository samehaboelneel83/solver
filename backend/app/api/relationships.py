"""Relationship types and relationships -- edges, and the rules about them.

    GET    /api/v1/relationship-types        ?domain_id=&limit=&offset=
    POST   /api/v1/relationship-types
    GET    /api/v1/relationship-types/{id}
    PATCH  /api/v1/relationship-types/{id}
    DELETE /api/v1/relationship-types/{id}
    GET    /api/v1/relationships             ?relationship_type_id=&from_entity_id=
                                             &to_entity_id=&limit=&offset=
    POST   /api/v1/relationships
    GET    /api/v1/relationships/{id}
    PATCH  /api/v1/relationships/{id}
    DELETE /api/v1/relationships/{id}

Hierarchy is not a table in schema v1. A hierarchy *is* a
`relationship_type` with `is_hierarchy = true`, read as **from_entity is
the parent of to_entity**, and the DDL constrains such a type to
`from_type_id = to_type_id` with `cardinality = 'one_to_many'` (one parent
per child). Everything the v0 `hierarchy`/`hierarchy_node` pair used to do
is therefore expressed by rows in these two tables -- including the graph
read in `app/graph/service.py`, which nests nodes from one selected
hierarchy type's rows.

Which layer answers which failure
---------------------------------
The split follows Task 5's and Task 6's, and the deciding question is the
same: can the failure carry a machine-readable `kind`?

1. **`relationship`: 422 with `kind`, from the database.** This table
   carries the `relationship_validate` trigger (migration 0006), which
   emits ``type_mismatch``, ``cardinality`` and ``cycle`` as a JSON
   ``DETAIL``. :func:`translate_db_error` turns those into a 422. Note
   that, unlike ``entity_validate``, this trigger's ``field`` is the
   **relationship type's name** -- not a column name -- so the resulting
   ``loc`` is ``["body", "reports_to"]`` rather than ``["body",
   "<column>"]``. That is the trigger's contract, not a bug here.

2. **`relationship_type`: 422 from this module.** This table carries no
   trigger; its rules are plain table CHECKs, which arrive with
   ``DETAIL = None`` and which ``translate_db_error`` maps to a **409**
   (Ruling 16). The brief requires 422 for the two hierarchy rules, so
   they are shadowed here, exactly as ``entity_types.py`` shadows the
   ``enum_values`` pairing CHECK. The same reasoning covers the
   ``name`` pattern, the ``cardinality`` label set, and
   ``relationship``'s ``valid_to >= valid_from`` CHECK.

3. **409 with a string detail** for what only the database can know: the
   two UNIQUE constraints and the four foreign keys.

The shadowed CHECKs remain the backstop for every other writer (the seed,
a migration, psql, a future worker), and `test_v1_domain_triggers.py`
exercises them directly, so a shadowed constraint cannot be quietly
dropped later.

Two rules are deliberately *not* mirrored here. The cycle and cardinality
rules over `relationship` rows are the database's alone: checking them in
Python would mean a second implementation of a recursive walk that has to
agree with the trigger under concurrency, which it cannot.
"""

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
# Shared rather than re-derived: `relationship_type.name` carries the
# identical `^[a-z][a-z0-9_]*$` CHECK as the two names Task 5 validates,
# including the trailing-newline subtlety that `re.fullmatch` closes and
# `re.match` on an anchored pattern does not. (Imported privately from
# `entity_types` until Task 8 moved them to `validation`, per Ruling 22.)
from app.api.validation import NAME_PATTERN, field_error, validate_colour, validate_name
from app.core.db import get_db
from app.crud.db_errors import translate_db_error
from app.models.iam import UserAccount
from app.models.v1_domain import Relationship, RelationshipType

router = APIRouter(prefix="/api/v1", tags=["relationships"])

# A text column with a CHECK, not an enum -- so an unknown label would
# reach the database and come back a 409 naming a constraint. A Literal
# turns it into a 422 naming the field, like every other bad value here.
Cardinality = Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]

__all__ = ["router", "NAME_PATTERN"]


# --- shadowed CHECKs -------------------------------------------------------


def _check_hierarchy_rules(
    from_type_id: int, to_type_id: int, cardinality: str, is_hierarchy: bool
) -> None:
    """``CHECK (NOT is_hierarchy OR (from_type_id = to_type_id AND
    cardinality = 'one_to_many'))``.

    Takes the four values the row will *have*, not the ones the request
    names: a PATCH setting only `is_hierarchy` still has to be judged
    against the stored `cardinality`. Same shape, and the same reason, as
    `entity_types._check_enum_pairing`.
    """
    if not is_hierarchy:
        return
    if from_type_id != to_type_id:
        raise field_error(
            "to_type_id",
            "a hierarchy nests one entity type inside itself, so from_type_id "
            "and to_type_id must name the same entity type",
            to_type_id,
        )
    if cardinality != "one_to_many":
        raise field_error(
            "cardinality",
            "a hierarchy must be one_to_many, so that each child has at most "
            f"one parent (got {cardinality!r})",
            cardinality,
        )


def _check_validity_window(valid_from: date | None, valid_to: date | None) -> None:
    """``CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >=
    valid_from)``. Judged on the merged row, for the same reason."""
    if valid_from is not None and valid_to is not None and valid_to < valid_from:
        raise field_error(
            "valid_to",
            f"valid_to ({valid_to.isoformat()}) is before valid_from "
            f"({valid_from.isoformat()})",
            valid_to,
        )


# --- schemas ---------------------------------------------------------------


class RelationshipTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain_id: int
    name: str
    from_type_id: int
    to_type_id: int
    cardinality: Cardinality
    is_hierarchy: bool
    # Migration 0009. NULL means "not chosen"; the graph assigns a
    # deterministic fallback rather than the wire inventing one.
    colour: str | None


class RelationshipTypeCreate(BaseModel):
    domain_id: int
    name: str
    from_type_id: int
    to_type_id: int
    # Both mirror the column server defaults, so the payload may omit them.
    cardinality: Cardinality = "many_to_many"
    is_hierarchy: bool = False
    colour: str | None = None

    _check_name = field_validator("name")(validate_name)
    _check_colour = field_validator("colour")(validate_colour)


class RelationshipTypeUpdate(BaseModel):
    """Every field optional; `model_dump(exclude_unset=True)` distinguishes
    "not supplied" from a value. `domain_id` is not patchable: moving a
    relationship type between domains would orphan every row that uses it,
    since the entities it joins belong to the old domain."""

    name: str | None = None
    from_type_id: int | None = None
    to_type_id: int | None = None
    cardinality: Cardinality | None = None
    is_hierarchy: bool | None = None
    colour: str | None = None

    _check_name = field_validator("name")(validate_name)
    _check_colour = field_validator("colour")(validate_colour)


class RelationshipTypeList(BaseModel):
    items: list[RelationshipTypeRead]
    total: int


class RelationshipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    relationship_type_id: int
    from_entity_id: int
    to_entity_id: int
    attrs: dict[str, Any]
    valid_from: date | None
    valid_to: date | None


class RelationshipCreate(BaseModel):
    relationship_type_id: int
    from_entity_id: int
    to_entity_id: int
    attrs: dict[str, Any] = Field(default_factory=dict)
    valid_from: date | None = None
    valid_to: date | None = None


class RelationshipUpdate(BaseModel):
    """`relationship_type_id` is deliberately absent: an edge's type is
    what decides which rules apply to it, and re-typing an existing edge
    is a delete plus a create, not an amendment.

    Re-pointing `from_entity_id`/`to_entity_id` *is* supported, and is the
    whole point of amendment (c) -- moving a subtree to a new parent is an
    ordinary edit, and the cycle walk excludes the row under update so its
    own pre-update version cannot be mistaken for an existing edge.

    `attrs` is replaced wholesale, not merged, for the reason
    `entities.py` records: a merge makes removing a key impossible.
    """

    from_entity_id: int | None = None
    to_entity_id: int | None = None
    attrs: dict[str, Any] | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class RelationshipList(BaseModel):
    items: list[RelationshipRead]
    total: int


# --- helpers ---------------------------------------------------------------


def _get_relationship_type(db: Session, relationship_type_id: int) -> RelationshipType:
    row = db.get(RelationshipType, relationship_type_id)
    if row is None:
        raise HTTPException(status_code=404, detail="relationship type not found")
    return row


def _get_relationship(db: Session, relationship_id: int) -> Relationship:
    row = db.get(Relationship, relationship_id)
    if row is None:
        raise HTTPException(status_code=404, detail="relationship not found")
    return row


def _commit(db: Session, table: str) -> None:
    try:
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, table) from exc


# --- relationship types ----------------------------------------------------


@router.get("/relationship-types")
def list_relationship_types(
    domain_id: int | None = Query(None),
    is_hierarchy: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> RelationshipTypeList:
    query = db.query(RelationshipType)
    if domain_id is not None:
        query = query.filter(RelationshipType.domain_id == domain_id)
    if is_hierarchy is not None:
        query = query.filter(RelationshipType.is_hierarchy.is_(is_hierarchy))
    total = query.count()
    # `name` is unique per domain but not globally, so `id` completes the
    # total order -- without one, offset pagination can skip or repeat rows.
    rows = (
        query.order_by(RelationshipType.name.asc(), RelationshipType.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return RelationshipTypeList(
        items=[RelationshipTypeRead.model_validate(row) for row in rows], total=total
    )


@router.post("/relationship-types", status_code=201)
def create_relationship_type(
    payload: RelationshipTypeCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> RelationshipTypeRead:
    _check_hierarchy_rules(
        payload.from_type_id, payload.to_type_id, payload.cardinality, payload.is_hierarchy
    )
    row = RelationshipType(**payload.model_dump())
    db.add(row)
    _commit(db, "relationship_type")
    db.refresh(row)
    return RelationshipTypeRead.model_validate(row)


@router.get("/relationship-types/{relationship_type_id}")
def get_relationship_type(
    relationship_type_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> RelationshipTypeRead:
    return RelationshipTypeRead.model_validate(_get_relationship_type(db, relationship_type_id))


@router.patch("/relationship-types/{relationship_type_id}")
def update_relationship_type(
    relationship_type_id: int,
    payload: RelationshipTypeUpdate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> RelationshipTypeRead:
    row = _get_relationship_type(db, relationship_type_id)
    changes = payload.model_dump(exclude_unset=True)
    _check_hierarchy_rules(
        changes.get("from_type_id", row.from_type_id),
        changes.get("to_type_id", row.to_type_id),
        changes.get("cardinality", row.cardinality),
        changes.get("is_hierarchy", row.is_hierarchy),
    )
    for field, value in changes.items():
        setattr(row, field, value)
    _commit(db, "relationship_type")
    db.refresh(row)
    return RelationshipTypeRead.model_validate(row)


@router.delete("/relationship-types/{relationship_type_id}", status_code=204)
def delete_relationship_type(
    relationship_type_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> None:
    # `relationship` rows cascade in the database (ON DELETE CASCADE).
    db.delete(_get_relationship_type(db, relationship_type_id))
    _commit(db, "relationship_type")


# --- relationships ---------------------------------------------------------


@router.get("/relationships")
def list_relationships(
    relationship_type_id: int | None = Query(None),
    from_entity_id: int | None = Query(None),
    to_entity_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> RelationshipList:
    query = db.query(Relationship)
    if relationship_type_id is not None:
        query = query.filter(Relationship.relationship_type_id == relationship_type_id)
    if from_entity_id is not None:
        query = query.filter(Relationship.from_entity_id == from_entity_id)
    if to_entity_id is not None:
        query = query.filter(Relationship.to_entity_id == to_entity_id)
    total = query.count()
    # An edge has no name to sort by; `id` is insertion order and is a
    # total order on its own.
    rows = query.order_by(Relationship.id.asc()).offset(offset).limit(limit).all()
    return RelationshipList(
        items=[RelationshipRead.model_validate(row) for row in rows], total=total
    )


@router.post("/relationships", status_code=201)
def create_relationship(
    payload: RelationshipCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> RelationshipRead:
    _check_validity_window(payload.valid_from, payload.valid_to)
    row = Relationship(**payload.model_dump())
    db.add(row)
    _commit(db, "relationship")
    db.refresh(row)
    return RelationshipRead.model_validate(row)


@router.get("/relationships/{relationship_id}")
def get_relationship(
    relationship_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> RelationshipRead:
    return RelationshipRead.model_validate(_get_relationship(db, relationship_id))


@router.patch("/relationships/{relationship_id}")
def update_relationship(
    relationship_id: int,
    payload: RelationshipUpdate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> RelationshipRead:
    row = _get_relationship(db, relationship_id)
    changes = payload.model_dump(exclude_unset=True)
    _check_validity_window(
        changes["valid_from"] if "valid_from" in changes else row.valid_from,
        changes["valid_to"] if "valid_to" in changes else row.valid_to,
    )
    for field, value in changes.items():
        setattr(row, field, value)
    # `relationship_validate` is BEFORE INSERT **OR UPDATE**, so a re-point
    # gets the identical rules -- including amendment (c), which excludes
    # this row from both terms of the cycle walk so its own pre-update
    # version is not mistaken for a competing edge.
    _commit(db, "relationship")
    db.refresh(row)
    return RelationshipRead.model_validate(row)


@router.delete("/relationships/{relationship_id}", status_code=204)
def delete_relationship(
    relationship_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> None:
    db.delete(_get_relationship(db, relationship_id))
    _commit(db, "relationship")
