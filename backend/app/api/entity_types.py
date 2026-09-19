"""Entity types and their attribute definitions.

The first of schema v1's purpose-built routers. An `entity_type` and its
`attribute_def` rows are a single thing to a user -- "what an employee is"
-- so the read model embeds the attributes, and the attributes get their
own nested write routes rather than a separate top-level resource.

    GET    /api/v1/entity-types                    ?domain_id=&limit=&offset=
    POST   /api/v1/entity-types
    GET    /api/v1/entity-types/{id}
    PATCH  /api/v1/entity-types/{id}
    DELETE /api/v1/entity-types/{id}
    GET    /api/v1/entity-types/{id}/attributes
    POST   /api/v1/entity-types/{id}/attributes
    PATCH  /api/v1/attributes/{id}
    DELETE /api/v1/attributes/{id}

Schemas are hand-written rather than produced by `make_crud_schemas`: the
generator mirrors columns, and these two tables carry rules that are not
columns (the name patterns, `name <> 'id'`, the data_type/enum_values
pairing, the read model's embedded `attributes`).

Which layer answers which failure
---------------------------------
Two different 422 bodies are available on this platform, and mixing them
for one status code would make the contract unreadable, so this module
picks one and applies it to **every** field with a database-level CHECK:

1. **FastAPI's validation-error shape** -- `{"detail": [{"loc", "msg",
   "type"}, ...]}` -- for everything the request layer can decide on its
   own: the `^[a-z][a-z0-9_]*$` names, `attribute_def.name <> 'id'`, the
   `(data_type = 'enum') = (enum_values IS NOT NULL)` pairing, and the two
   enum-typed columns (`role`, `data_type`).

2. **`translate_db_error`** -- for everything only the database knows: the
   two UNIQUE constraints and the `domain_id` foreign key, which come back
   as 409s with a string `detail`.

Why not leave (1) to the database and let `translate_db_error` shape it?
Because it cannot produce a 422 for these at all. Task 3's 422 contract
(`{"message", "field", "kind"}`) is driven by a JSON `DETAIL` payload that
only the three DOMAIN validation *triggers* emit (`entity_validate`,
`relationship_validate`, `parameter_value_validate` -- migration 0006).
Neither `entity_type` nor `attribute_def` has a trigger: their rules are
plain table CHECKs, which arrive as SQLSTATE 23514 with **no** DETAIL, and
`translate_db_error` maps those to a generic **409**. Letting the database
answer would therefore mean `name="Employee"` returns 409 with a message
about a constraint name, not a 422 naming the field.

The cost is that this router no longer reaches those CHECKs. They remain
the backstop for every other writer -- the seed, a migration, psql, a
future worker -- and `test_api_entity_types.py` asserts one of them still
fires on a direct insert, so a shadowed constraint cannot be quietly
dropped later. The request-layer rules are deliberately at least as strict
as the CHECKs they shadow (see `_validate_name`).
"""

import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.crud.db_errors import translate_db_error
from app.models.iam import UserAccount
from app.models.v1_domain import AttributeDef, EntityType

router = APIRouter(prefix="/api/v1", tags=["entity types"])

# The two enum types the DDL declares. Spelled out as Literals rather than
# left as `str`, because an unknown label is not a CHECK violation: it
# reaches the driver as SQLSTATE 22P02 (invalid_text_representation), which
# `translate_db_error` re-raises untouched -- i.e. a 500. A Literal turns it
# into a 422 naming the field, like every other bad value here.
EntityRole = Literal["agent", "resource", "time", "location", "task", "org", "other"]
AttrType = Literal["integer", "number", "text", "boolean", "enum", "time", "date"]

# `entity_type.name` and `attribute_def.name` both carry
# CHECK (name ~ '^[a-z][a-z0-9_]*$') -- the names are used verbatim in IR
# expressions. Quoted here for the error message; the match itself uses
# `re.fullmatch` on the unanchored body rather than `re.match` on the
# anchored form, because Python's `$` also matches just before a trailing
# newline while Postgres's does not -- `"employee\n"` would otherwise pass
# validation and then be rejected by the database as a confusing 409.
NAME_PATTERN = "^[a-z][a-z0-9_]*$"
_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")

_NAME_MESSAGE = (
    f"must match {NAME_PATTERN}: a lowercase letter, then lowercase letters, "
    "digits or underscores (it is used verbatim in model expressions)"
)


def _validate_name(value: str | None) -> str | None:
    if value is None:  # PATCH: field simply not being changed
        return value
    if _NAME_RE.fullmatch(value) is None:
        raise ValueError(_NAME_MESSAGE)
    return value


def _validate_attribute_name(value: str | None) -> str | None:
    value = _validate_name(value)
    # attribute_def's CHECK is `name ~ '...' AND name <> 'id'`. 'id' matches
    # the pattern, so this half needs its own rejection.
    if value == "id":
        raise ValueError(
            "the name 'id' is reserved: every entity already has an id, and an "
            "attribute called 'id' would shadow it in model expressions"
        )
    return value


def _field_error(field: str, message: str, value: Any) -> RequestValidationError:
    """Build a refusal in exactly the shape FastAPI's own body validation
    produces, so a caller (and `formatApiError` in the frontend) does not
    have to special-case rules that happen to be checked by hand."""
    return RequestValidationError(
        [{"type": "value_error", "loc": ("body", field), "msg": message, "input": value}]
    )


def _check_enum_pairing(data_type: str, enum_values: list[str] | None) -> None:
    """`CHECK ((data_type = 'enum') = (enum_values IS NOT NULL))`.

    Deliberately a function called from the route rather than a Pydantic
    model validator: PATCH has to check the **merged** row (a PATCH naming
    only `data_type` still has to be judged against the stored
    `enum_values`), and a model validator only ever sees the payload. One
    implementation for both verbs means the two cannot drift, and blaming
    `enum_values` keeps the error attached to a real field -- a model-level
    validator's `loc` is just `["body"]`.
    """
    if data_type == "enum" and enum_values is None:
        raise _field_error(
            "enum_values",
            "an attribute of type 'enum' must list its allowed values",
            enum_values,
        )
    if data_type != "enum" and enum_values is not None:
        raise _field_error(
            "enum_values",
            f"enum_values is only meaningful for data_type 'enum', not {data_type!r}",
            enum_values,
        )


# --- schemas ---------------------------------------------------------------


class AttributeDefRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_type_id: int
    name: str
    data_type: AttrType
    required: bool
    unit: str | None
    enum_values: list[str] | None
    default_value: Any | None


class AttributeDefCreate(BaseModel):
    name: str
    data_type: AttrType
    required: bool = False
    unit: str | None = None
    enum_values: list[str] | None = None
    default_value: Any | None = None

    _check_name = field_validator("name")(_validate_attribute_name)


class AttributeDefUpdate(BaseModel):
    """Every field optional; `model_dump(exclude_unset=True)` is what
    distinguishes "not supplied" from an explicit `null` (which is how an
    enum attribute's `enum_values` would be cleared)."""

    name: str | None = None
    data_type: AttrType | None = None
    required: bool | None = None
    unit: str | None = None
    enum_values: list[str] | None = None
    default_value: Any | None = None

    _check_name = field_validator("name")(_validate_attribute_name)


class EntityTypeRead(BaseModel):
    id: int
    domain_id: int
    name: str
    role: EntityRole
    # A type and its attributes are edited as one thing, so the read model
    # carries both -- on the list route too, which is what lets the UI show
    # "employee (3 attributes)" without an N+1 of follow-up requests.
    attributes: list[AttributeDefRead]


class EntityTypeCreate(BaseModel):
    domain_id: int
    name: str
    # Mirrors the column's server default, so the field can be omitted.
    role: EntityRole = "other"

    _check_name = field_validator("name")(_validate_name)


class EntityTypeUpdate(BaseModel):
    name: str | None = None
    role: EntityRole | None = None

    _check_name = field_validator("name")(_validate_name)


class EntityTypeList(BaseModel):
    items: list[EntityTypeRead]
    total: int


# --- helpers ---------------------------------------------------------------


def _attributes_for(db: Session, entity_type_ids: list[int]) -> dict[int, list[AttributeDef]]:
    """All attribute defs for the given types, in one query, grouped by type
    and ordered by name -- so the list route stays two queries regardless of
    how many types it returns."""
    if not entity_type_ids:
        return {}
    rows = (
        db.query(AttributeDef)
        .filter(AttributeDef.entity_type_id.in_(entity_type_ids))
        .order_by(AttributeDef.name.asc())
        .all()
    )
    grouped: dict[int, list[AttributeDef]] = {type_id: [] for type_id in entity_type_ids}
    for row in rows:
        grouped[row.entity_type_id].append(row)
    return grouped


def _read(entity_type: EntityType, attributes: list[AttributeDef]) -> EntityTypeRead:
    return EntityTypeRead(
        id=entity_type.id,
        domain_id=entity_type.domain_id,
        name=entity_type.name,
        role=entity_type.role,
        attributes=[AttributeDefRead.model_validate(a) for a in attributes],
    )


def _read_one(db: Session, entity_type: EntityType) -> EntityTypeRead:
    return _read(entity_type, _attributes_for(db, [entity_type.id]).get(entity_type.id, []))


def _get_entity_type(db: Session, entity_type_id: int) -> EntityType:
    entity_type = db.get(EntityType, entity_type_id)
    if entity_type is None:
        raise HTTPException(status_code=404, detail="entity type not found")
    return entity_type


def _get_attribute(db: Session, attribute_id: int) -> AttributeDef:
    attribute = db.get(AttributeDef, attribute_id)
    if attribute is None:
        raise HTTPException(status_code=404, detail="attribute definition not found")
    return attribute


def _commit(db: Session, table: str) -> None:
    try:
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, table) from exc


# --- entity types ----------------------------------------------------------


@router.get("/entity-types")
def list_entity_types(
    domain_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> EntityTypeList:
    query = db.query(EntityType)
    if domain_id is not None:
        query = query.filter(EntityType.domain_id == domain_id)
    total = query.count()
    # `name` is unique per domain but not globally, so `id` is appended as a
    # tiebreaker -- without a total order, offset pagination can skip or
    # repeat rows across pages.
    rows = (
        query.order_by(EntityType.name.asc(), EntityType.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    grouped = _attributes_for(db, [row.id for row in rows])
    return EntityTypeList(
        items=[_read(row, grouped.get(row.id, [])) for row in rows], total=total
    )


@router.post("/entity-types", status_code=201)
def create_entity_type(
    payload: EntityTypeCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> EntityTypeRead:
    entity_type = EntityType(**payload.model_dump())
    db.add(entity_type)
    _commit(db, "entity_type")
    db.refresh(entity_type)
    return _read(entity_type, [])


@router.get("/entity-types/{entity_type_id}")
def get_entity_type(
    entity_type_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> EntityTypeRead:
    return _read_one(db, _get_entity_type(db, entity_type_id))


@router.patch("/entity-types/{entity_type_id}")
def update_entity_type(
    entity_type_id: int,
    payload: EntityTypeUpdate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> EntityTypeRead:
    entity_type = _get_entity_type(db, entity_type_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity_type, field, value)
    _commit(db, "entity_type")
    db.refresh(entity_type)
    return _read_one(db, entity_type)


@router.delete("/entity-types/{entity_type_id}", status_code=204)
def delete_entity_type(
    entity_type_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> None:
    # attribute_def, entity and everything below cascade in the database
    # (ON DELETE CASCADE); no ORM relationship is declared, so SQLAlchemy
    # issues the single DELETE and Postgres does the rest.
    db.delete(_get_entity_type(db, entity_type_id))
    _commit(db, "entity_type")


# --- attribute definitions -------------------------------------------------


@router.get("/entity-types/{entity_type_id}/attributes")
def list_attributes(
    entity_type_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> list[AttributeDefRead]:
    _get_entity_type(db, entity_type_id)
    return [
        AttributeDefRead.model_validate(row)
        for row in _attributes_for(db, [entity_type_id]).get(entity_type_id, [])
    ]


@router.post("/entity-types/{entity_type_id}/attributes", status_code=201)
def create_attribute(
    entity_type_id: int,
    payload: AttributeDefCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> AttributeDefRead:
    _get_entity_type(db, entity_type_id)
    _check_enum_pairing(payload.data_type, payload.enum_values)
    attribute = AttributeDef(entity_type_id=entity_type_id, **payload.model_dump())
    db.add(attribute)
    _commit(db, "attribute_def")
    db.refresh(attribute)
    return AttributeDefRead.model_validate(attribute)


@router.patch("/attributes/{attribute_id}")
def update_attribute(
    attribute_id: int,
    payload: AttributeDefUpdate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> AttributeDefRead:
    attribute = _get_attribute(db, attribute_id)
    changes = payload.model_dump(exclude_unset=True)
    # The pairing CHECK is on the row, not the payload: judge the values the
    # row will have once this patch is applied, not the ones it names.
    _check_enum_pairing(
        changes.get("data_type", attribute.data_type),
        changes["enum_values"] if "enum_values" in changes else attribute.enum_values,
    )
    for field, value in changes.items():
        setattr(attribute, field, value)
    _commit(db, "attribute_def")
    db.refresh(attribute)
    return AttributeDefRead.model_validate(attribute)


@router.delete("/attributes/{attribute_id}", status_code=204)
def delete_attribute(
    attribute_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> None:
    db.delete(_get_attribute(db, attribute_id))
    _commit(db, "attribute_def")
