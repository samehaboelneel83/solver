"""Parameter definitions and their sparse value grid.

    GET    /api/v1/parameters              ?domain_id=&limit=&offset=
    POST   /api/v1/parameters
    GET    /api/v1/parameters/{id}
    PATCH  /api/v1/parameters/{id}
    DELETE /api/v1/parameters/{id}
    GET    /api/v1/parameters/{id}/values
    PUT    /api/v1/parameters/{id}/values

A `parameter_def` is indexed data that belongs to no single entity --
``demand[day, shift]`` -- and its `parameter_value` rows are the cells of
that grid, keyed by an array of entity ids in index order. Spec §5 calls it
"a spreadsheet, not a list", so the values are not a CRUD resource: one GET
returns the grid, one PUT sets any number of cells up to
``PARAMETER_VALUES_MAX_CELLS`` (a year of hourly cells).

Sparse storage
--------------
Only cells that differ from ``default_value`` are stored. A PUT cell whose
value equals the default **deletes** the row rather than writing it, so
"reset to default" and "never set" are the same state. Changing
``default_value`` on PATCH does not rewrite stored cells: every absent cell
takes the new default, and a stored cell that now happens to equal it is
merely redundant, not wrong.

Task 8 raised the obvious gap in that -- a dataset that carries only
stored rows cannot say what an absent cell is worth -- and Ruling 28 is the
user's answer: storage stays sparse, and `snapshot_dataset()` (migration
0009) emits a sibling ``parameter_defaults`` object, one entry per
parameter the IR references. The solver's rule is "look the cell up; if it
is absent, use the default". Pinned by
`test_snapshot_resolves_a_cell_reset_to_the_default` here and by
`test_v1_problem_run.py`'s snapshot tests.

Which layer answers which failure
---------------------------------
1. **422 with ``kind="parameter_index"``, from the database.**
   `parameter_value` carries the `parameter_value_validate` trigger
   (migration 0006), which compares the cell's entity types, in order,
   against ``index_type_ids`` -- one comparison covering wrong arity, wrong
   types, wrong order and non-existent ids. It is the only implementation
   of that rule; this module never re-derives it. Every PUT cell passes
   through it, **including** a cell being reset to the default: that cell
   is upserted and then deleted within the same transaction, so a
   malformed cell cannot slip through merely because there was nothing to
   store. The router then re-addresses the trigger's 422 to the cell that
   failed (``loc: ["body", "cells", i, "entity_ids"]`` -- the same `loc`
   Pydantic gives a bad ``cells[i].value``) and replaces the trigger's
   message, which prints a raw Postgres array, with one that names the
   expected index types. `kind` is kept.

   The new message uses what the trigger's ``expected`` payload key
   carries -- ``parameter_def.index_type_ids`` -- but read from the row
   this router already holds, not from the payload: ``translate_db_error``
   drops ``expected``, and the ids alone would not give a user the type
   *names* anyway.

2. **422 without ``kind``, from this module.** `parameter_def` has no
   trigger, so its CHECKs (the name pattern, ``cardinality(index_type_ids)
   >= 1``) would reach the client as 409s (Ruling 16). They are shadowed
   here, as are three rules the DDL cannot state at all: every index type
   must exist and belong to the parameter's own domain, the same cell may
   not appear twice in one PUT, and values must be numbers the column can
   store. A repeated index type is legal (migration ``0025``).

   Strictness matters more than usual here: Postgres **rounds** a numeric
   into an ``int`` column, so a lax validator passing ``5.5`` through would
   store ``6`` rather than fail. ``5.0`` is refused too, on the same
   footing as ``"5"`` and ``true``: a client holding a float has a type
   bug, and "happens to be integral" is not a type (spec §2: integer-only,
   deliberately, for CP-SAT).

3. **409 with a string detail** for what only the database knows:
   ``UNIQUE (domain_id, name)``, the ``domain_id`` foreign key -- and one
   rule of this module's own: ``index_type_ids`` cannot change while cells
   are stored, because the trigger judges a cell only when *it* is written
   and would never revisit cells shaped for the old index.

   The count-then-PATCH would miss a PUT that had written cells but not
   yet committed, and the PUT's trigger would already have passed against
   the old index. PUT therefore takes ``FOR SHARE`` on ``parameter_def``
   before it writes cells; PATCH and DELETE take ``FOR UPDATE``. The two
   cannot interleave, so the cell-count either sees the PUT or the PUT
   waits and is judged against the new index.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api import search
from app.api.search import search_text
from app.api.deps import get_current_user, requires
from app.api.concurrency import check_not_stale, stale_record_conflict
from app.api.validation import field_error, reject_null, validate_name
from app.core.db import get_db
from app.api.quantity import Quantity, QuantityOut
from app.crud.db_errors import translate_db_error
from app.models.iam import UserAccount
from app.models.v1_domain import Entity, EntityType, ParameterDef, ParameterValue

router = APIRouter(prefix="/api/v1", tags=["parameters"])



# Ids are `bigint`. Lax on purpose, like every other id on the platform;
# only the range is bounded, for the same 22003 reason.
BigintId = Annotated[int, Field(ge=-(2**63), le=2**63 - 1)]

# --- schemas ---------------------------------------------------------------


class ParameterDefRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain_id: int
    name: str
    # Index order, exactly as defined: demand[day, shift] != demand[shift, day].
    index_type_ids: list[int]
    default_value: QuantityOut
    unit: str | None
    # Migration 0068 (queue R20b): its values are entities of this type.
    value_type_id: int | None = None


class ParameterDefCreate(BaseModel):
    domain_id: int
    name: str
    index_type_ids: list[BigintId] = Field(min_length=1)
    # Mirrors the column's server default, so the field can be omitted.
    default_value: Quantity = Decimal(0)
    unit: str | None = None
    value_type_id: BigintId | None = None

    _check_name = field_validator("name")(validate_name)


class ParameterDefUpdate(BaseModel):
    """`domain_id` is not patchable: the index types and every stored
    cell's entities belong to the old domain."""

    name: str | None = None
    index_type_ids: list[BigintId] | None = Field(default=None, min_length=1)
    default_value: Quantity | None = None
    unit: str | None = None
    value_type_id: BigintId | None = None

    _check_name = field_validator("name")(validate_name)
    _check_not_null = field_validator("name", "index_type_ids", "default_value")(reject_null)


class ParameterDefList(BaseModel):
    items: list[ParameterDefRead]
    total: int


class IndexType(BaseModel):
    id: int
    # None only if the entity type was deleted after the parameter was
    # defined: an array cannot carry a foreign key, so nothing cascades.
    name: str | None


class Cell(BaseModel):
    entity_ids: list[BigintId]
    # A number parameter's cell carries `value`; an entity-valued one's
    # (migration 0068) carries `value_entity_id`, and a null there clears it.
    value: Quantity | None = None
    value_entity_id: BigintId | None = None
    # Read only: the entity's key, for showing an entity cell.
    value_key: str | None = None
    # Present on a stored cell's GET. Optional on PUT: send the value the
    # form last read to opt in to the stale check, omit it to keep the
    # pre-0022 last-save-wins behaviour (a first write into an empty cell,
    # scripts, `curl`).
    updated_at: datetime | None = None


class ParameterValues(BaseModel):
    index_types: list[IndexType]
    cells: list[Cell]
    default_value: QuantityOut


# A year of hourly cells; past that, split the PUT. Read at validation
# time so tests can lower it without reconstructing the schema.
PARAMETER_VALUES_MAX_CELLS = 10_000


class ParameterValuesPut(BaseModel):
    cells: list[Cell]

    @field_validator("cells")
    @classmethod
    def _cap_cells(cls, cells: list[Cell]) -> list[Cell]:
        if len(cells) > PARAMETER_VALUES_MAX_CELLS:
            raise ValueError(f"at most {PARAMETER_VALUES_MAX_CELLS} cells per request")
        return cells


# --- helpers ---------------------------------------------------------------


def _get_parameter(
    db: Session, parameter_id: int, *, lock: Literal["share", "update"] | None = None
) -> ParameterDef:
    # PUT holds FOR SHARE so a concurrent PATCH cannot change index_type_ids
    # until the cells are committed; PATCH and DELETE take FOR UPDATE so they
    # wait for that PUT, then see the new cell count. See the module doc.
    kwargs: dict = {}
    if lock == "share":
        kwargs["with_for_update"] = {"read": True}
    elif lock == "update":
        kwargs["with_for_update"] = True
    row = db.get(ParameterDef, parameter_id, **kwargs)
    if row is None:
        raise HTTPException(status_code=404, detail="parameter not found")
    return row


def _check_cells_not_stale(db: Session, parameter_id: int, cells: list[Cell]) -> None:
    """Refuse the whole PUT if any named cell was loaded from a superseded
    read. Checked before any write so a 409 is as atomic as a 422."""
    for cell in cells:
        if cell.updated_at is None:
            continue
        stored = db.execute(
            select(ParameterValue.updated_at)
            .where(ParameterValue.parameter_def_id == parameter_id)
            .where(ParameterValue.entity_ids == cell.entity_ids)
            .with_for_update()
        ).scalar_one_or_none()
        if stored is None:
            raise stale_record_conflict("parameter cell")
        check_not_stale("parameter cell", stored, cell.updated_at)


def _commit(db: Session, table: str) -> None:
    try:
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise translate_db_error(exc, table) from exc


def _type_names(db: Session, type_ids: list[int]) -> dict[int, tuple[str, int]]:
    """`{id: (name, domain_id)}` for whichever of `type_ids` exist."""
    rows = db.execute(
        select(EntityType.id, EntityType.name, EntityType.domain_id).where(
            EntityType.id.in_(type_ids)
        )
    ).all()
    return {row.id: (row.name, row.domain_id) for row in rows}


def _check_index_types(db: Session, domain_id: int, index_type_ids: list[int]) -> None:
    known = _type_names(db, index_type_ids)
    for type_id in index_type_ids:
        if type_id not in known or known[type_id][1] != domain_id:
            raise field_error(
                "index_type_ids",
                f"entity type {type_id} does not exist in this parameter's domain",
                index_type_ids,
            )


def _coordinate_key(entity: Entity | None, entity_id: int) -> tuple:
    # (sort_order, key) is how an entity is ordered everywhere else on the
    # platform (entities.py, snapshot_dataset); `id` makes it total. A cell's
    # entities always exist -- `parameter_value_cleanup` deletes the cell
    # with the entity -- but an absent one sorts last rather than raising.
    if entity is None:
        return (1, 0, "", entity_id)
    return (0, entity.sort_order, entity.key, entity_id)


def _grid(db: Session, parameter: ParameterDef) -> ParameterValues:
    """The grid as stored. Cells are ordered by their coordinates left to
    right, each coordinate by its entity's `(sort_order, key, id)` -- the
    order a user reads the grid in, and one that does not depend on
    insertion order or on the ids the database happened to assign."""
    names = _type_names(db, parameter.index_type_ids)
    # Core, not `db.query(ParameterValue)`: the ORM's identity map hashes
    # primary keys, and this table's key contains an array (a list).
    rows = db.execute(
        select(
            ParameterValue.entity_ids, ParameterValue.value, ParameterValue.value_entity_id,
            ParameterValue.updated_at,
        ).where(ParameterValue.parameter_def_id == parameter.id)
    ).all()
    entity_ids = {eid for row in rows for eid in row.entity_ids} | {
        row.value_entity_id for row in rows if row.value_entity_id is not None
    }
    entities = (
        {e.id: e for e in db.query(Entity).filter(Entity.id.in_(entity_ids)).all()}
        if entity_ids
        else {}
    )
    rows.sort(
        key=lambda row: tuple(_coordinate_key(entities.get(eid), eid) for eid in row.entity_ids)
    )
    return ParameterValues(
        index_types=[
            IndexType(id=type_id, name=names[type_id][0] if type_id in names else None)
            for type_id in parameter.index_type_ids
        ],
        cells=[
            Cell(
                entity_ids=list(row.entity_ids),
                value=row.value,
                value_entity_id=row.value_entity_id,
                value_key=entities[row.value_entity_id].key if row.value_entity_id in entities else None,
                updated_at=row.updated_at,
            )
            for row in rows
        ],
        default_value=parameter.default_value,
    )


def _cell_error(
    http: HTTPException, index: int, cell: Cell, parameter: ParameterDef, db: Session
) -> HTTPException:
    """Re-address `parameter_value_validate`'s 422 to the cell that failed.
    Anything else from `translate_db_error` is returned unchanged."""
    detail = http.detail
    if not (
        http.status_code == 422
        and isinstance(detail, list)
        and detail
        and detail[0].get("kind") == "parameter_index"
    ):
        return http
    names = _type_names(db, parameter.index_type_ids)
    expected = ", ".join(
        names[t][0] if t in names else str(t) for t in parameter.index_type_ids
    )
    count = len(parameter.index_type_ids)
    message = (
        f"entity_ids must name {count} existing "
        f"{'entity' if count == 1 else 'entities'}, one of each index type in "
        f"this order: ({expected}); got {cell.entity_ids}"
    )
    return HTTPException(
        status_code=422,
        detail=[
            {
                "type": detail[0].get("type", "value_error"),
                "loc": ["body", "cells", index, "entity_ids"],
                "msg": message,
                "kind": "parameter_index",
            }
        ],
    )


# --- parameter definitions -------------------------------------------------


@router.get("/parameters")
def list_parameters(
    domain_id: int | None = Query(None),
    q: str | None = Query(None, description="name or description contains this; a number also matches the id"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> ParameterDefList:
    query = db.query(ParameterDef)
    if domain_id is not None:
        query = query.filter(ParameterDef.domain_id == domain_id)
    searched = search.condition(q, *search_text(ParameterDef, "name", "description"), id_column=ParameterDef.id)
    if searched is not None:
        query = query.filter(searched)
    total = query.count()
    # `name` is unique per domain but not globally; `id` makes the order
    # total, which offset pagination needs.
    rows = (
        query.order_by(ParameterDef.name.asc(), ParameterDef.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return ParameterDefList(
        items=[ParameterDefRead.model_validate(row) for row in rows], total=total
    )


@router.post("/parameters", status_code=201)
def create_parameter(
    payload: ParameterDefCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("domain.edit")),
) -> ParameterDefRead:
    _check_index_types(db, payload.domain_id, payload.index_type_ids)
    if payload.value_type_id is not None:
        _check_index_types(db, payload.domain_id, [payload.value_type_id])
    row = ParameterDef(**payload.model_dump())
    db.add(row)
    _commit(db, "parameter_def")
    db.refresh(row)
    return ParameterDefRead.model_validate(row)


@router.get("/parameters/{parameter_id}")
def get_parameter(
    parameter_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> ParameterDefRead:
    return ParameterDefRead.model_validate(_get_parameter(db, parameter_id))


@router.patch("/parameters/{parameter_id}")
def update_parameter(
    parameter_id: int,
    payload: ParameterDefUpdate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("domain.edit")),
) -> ParameterDefRead:
    row = _get_parameter(db, parameter_id, lock="update")
    changes = payload.model_dump(exclude_unset=True)
    new_index = changes.get("index_type_ids")
    if "value_type_id" in changes and changes["value_type_id"] != row.value_type_id:
        # A cell holds a number or an entity; changing which would orphan them all.
        if changes["value_type_id"] is not None:
            _check_index_types(db, row.domain_id, [changes["value_type_id"]])
        if db.scalar(select(func.count()).select_from(ParameterValue).where(ParameterValue.parameter_def_id == row.id)):
            raise HTTPException(
                status_code=409,
                detail="cannot change what a parameter's values are while it has stored values; clear them first",
            )
    if new_index is not None and list(new_index) != list(row.index_type_ids):
        _check_index_types(db, row.domain_id, new_index)
        stored = db.scalar(
            select(func.count())
            .select_from(ParameterValue)
            .where(ParameterValue.parameter_def_id == row.id)
        )
        if stored:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"cannot change the index types of a parameter with {stored} stored "
                    "value(s): they were entered for the old index. Reset them to the "
                    "default (or delete the parameter) first."
                ),
            )
    for field, value in changes.items():
        setattr(row, field, value)
    _commit(db, "parameter_def")
    db.refresh(row)
    return ParameterDefRead.model_validate(row)


@router.delete("/parameters/{parameter_id}", status_code=204)
def delete_parameter(
    parameter_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("domain.edit")),
) -> None:
    # `parameter_value` rows cascade (ON DELETE CASCADE).
    db.delete(_get_parameter(db, parameter_id, lock="update"))
    _commit(db, "parameter_def")


# --- the value grid --------------------------------------------------------


@router.get("/parameters/{parameter_id}/values")
def get_parameter_values(
    parameter_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> ParameterValues:
    return _grid(db, _get_parameter(db, parameter_id))


@router.put("/parameters/{parameter_id}/values")
def put_parameter_values(
    parameter_id: int,
    payload: ParameterValuesPut,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(requires("domain.edit")),
) -> ParameterValues:
    """Set the named cells; cells not named are left as they are. Atomic:
    one bad cell and nothing in the request is written."""
    parameter = _get_parameter(db, parameter_id, lock="share")

    seen: set[tuple[int, ...]] = set()
    for index, cell in enumerate(payload.cells):
        coordinates = tuple(cell.entity_ids)
        if coordinates in seen:
            raise field_error(
                ["cells", index, "entity_ids"],
                f"cell {cell.entity_ids} appears more than once in this request",
                cell.entity_ids,
            )
        seen.add(coordinates)

    _check_cells_not_stale(db, parameter.id, payload.cells)

    entity_valued = parameter.value_type_id is not None
    for index, cell in enumerate(payload.cells):
        if not entity_valued and cell.value is None:
            raise field_error(["cells", index, "value"], "a number parameter's cell needs a value", None)
        if entity_valued and cell.value is not None:
            raise field_error(
                ["cells", index, "value"],
                "this parameter's values are entities: send value_entity_id (null to clear the cell)",
                cell.value,
            )

    for index, cell in enumerate(payload.cells):
        key = (
            (ParameterValue.parameter_def_id == parameter.id)
            & (ParameterValue.entity_ids == cell.entity_ids)
        )
        if entity_valued and cell.value_entity_id is None:
            # No default for an entity: an empty cell is no value.
            db.execute(delete(ParameterValue).where(key))
            continue
        upsert = insert(ParameterValue).values(
            parameter_def_id=parameter.id, entity_ids=cell.entity_ids, value=cell.value,
            value_entity_id=cell.value_entity_id if entity_valued else None,
        )
        upsert = upsert.on_conflict_do_update(
            index_elements=[ParameterValue.parameter_def_id, ParameterValue.entity_ids],
            set_={"value": upsert.excluded.value, "value_entity_id": upsert.excluded.value_entity_id},
        )
        try:
            # Written even when it equals the default, so the trigger judges
            # it; then removed, so the grid stays sparse.
            db.execute(upsert)
            if not entity_valued and cell.value == parameter.default_value:
                db.execute(delete(ParameterValue).where(key))
        except DBAPIError as exc:
            db.rollback()
            raise _cell_error(
                translate_db_error(exc, "parameter_value"), index, cell, parameter, db
            ) from exc

    _commit(db, "parameter_value")
    return _grid(db, parameter)
