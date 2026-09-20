import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Type

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import String, Text, inspect, or_
from sqlalchemy.exc import DataError, DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.crud.db_errors import translate_db_error
from app.crud.registry import register_table
from app.models.iam import UserAccount


def searchable_columns(model: Type) -> list:
    """Return the mapped String/Text columns of `model`.

    Used to build the OR-ed `ilike` search for the `q` list param. Also
    reused by Task 2's search UI to know which columns are searchable.

    Note: this does not know about a router's `read_schema`, so callers
    that expose data over HTTP (list_items below) must additionally
    intersect the result with the read schema's fields to avoid leaking
    `hidden` columns through search.
    """
    mapper = inspect(model)
    return [
        prop.columns[0]
        for prop in mapper.column_attrs
        if isinstance(prop.columns[0].type, (String, Text))
    ]


def _column_attr_keys(model: Type) -> dict:
    """Map Column object -> attribute name, to correlate searchable_columns()
    output (raw Columns) back to read-schema field names (attribute names)."""
    mapper = inspect(model)
    return {prop.columns[0]: prop.key for prop in mapper.column_attrs}


def _filterable_attrs(model: Type, read_schema: Type[BaseModel]) -> dict:
    """Map attribute name -> InstrumentedAttribute, for filter/order validation.

    Restricted to columns that are actually exposed on `read_schema`, so a
    column dropped via `hidden=` (e.g. hashed_password) can't be reached
    through `f_<column>` or `order_by` even though it's still a real
    mapped column on the model.
    """
    mapper = inspect(model)
    allowed = set(read_schema.model_fields.keys())
    return {prop.key: getattr(model, prop.key) for prop in mapper.column_attrs if prop.key in allowed}


def _python_type(attr) -> type:
    try:
        return attr.type.python_type
    except NotImplementedError:
        return str


def _cast_filter_value(attr, raw: str):
    py_type = _python_type(attr)
    if py_type is bool:
        lowered = raw.strip().lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0"):
            return False
        raise ValueError(f"not a boolean: {raw!r}")
    if py_type is uuid.UUID:
        return uuid.UUID(raw)
    if py_type is int:
        return int(raw)
    if py_type is float:
        return float(raw)
    if py_type is Decimal:
        return Decimal(raw)
    if py_type is datetime:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if py_type is date:
        return date.fromisoformat(raw)
    return raw


def build_crud_router(
    *,
    model: Type,
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    read_schema: Type[BaseModel],
    schema_name: str,
    table_name: str,
    creatable: bool = True,
    updatable: bool = True,
    deletable: bool = True,
) -> APIRouter:
    """Build a generic list/get/create/update/delete router for one table.

    Registers the table in TABLE_REGISTRY as a side effect, so Task 18's
    /api/meta/schema endpoint picks it up automatically without a second
    bookkeeping step.

    `creatable`/`updatable`/`deletable` (all default True) suppress the
    corresponding write route entirely when False -- used for tables a
    trigger makes read-only at the DB level (see IMMUTABLE_TABLES), so the
    API doesn't advertise a route the database will reject anyway.

    The path param type for the single-item routes is derived from the
    model's own primary key column rather than hardcoded: schema v1's flat
    tables (domain, template, problem, ...) use `bigint` surrogate keys,
    while the untouched `iam` tables still use `UUID`. Deriving it keeps
    both working through the same generic factory.

    `schema_name == "public"` (schema v1's flat tables all live there) is
    special-cased to drop the schema segment from the URL, so these read as
    flat resources (`/api/domain/1`) rather than `/api/public/domain/1`;
    every other schema (e.g. `iam`) keeps its qualified prefix.
    """
    if schema_name == "public":
        prefix = f"/api/{table_name}"
        tags = [table_name]
    else:
        prefix = f"/api/{schema_name}/{table_name}"
        tags = [f"{schema_name}.{table_name}"]
    router = APIRouter(prefix=prefix, tags=tags)
    register_table(
        schema_name,
        table_name,
        model,
        create_schema,
        read_schema,
        creatable=creatable,
        updatable=updatable,
        deletable=deletable,
    )

    item_id_type = _python_type(inspect(model).primary_key[0])

    @router.get("/")
    def list_items(
        request: Request,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        q: str | None = Query(None),
        order_by: str | None = Query(None),
        order: str = Query("asc"),
        db: Session = Depends(get_db),
        _: UserAccount = Depends(get_current_user),
    ) -> dict:
        filterable = _filterable_attrs(model, read_schema)
        query = db.query(model)

        if q:
            allowed_field_names = set(read_schema.model_fields.keys())
            column_keys = _column_attr_keys(model)
            columns = [c for c in searchable_columns(model) if column_keys.get(c) in allowed_field_names]
            if columns:
                query = query.filter(or_(*[col.ilike(f"%{q}%") for col in columns]))

        for key, raw_value in request.query_params.items():
            if not key.startswith("f_"):
                continue
            column_name = key[2:]
            attr = filterable.get(column_name)
            if attr is None:
                raise HTTPException(status_code=422, detail=f"unknown column {column_name}")
            try:
                value = _cast_filter_value(attr, raw_value)
            except (ValueError, TypeError, ArithmeticError, InvalidOperation):
                raise HTTPException(status_code=422, detail=f"invalid value for column {column_name}")
            query = query.filter(attr == value)

        order_normalized = order.strip().lower()
        if order_normalized not in ("asc", "desc"):
            raise HTTPException(status_code=422, detail=f"invalid order {order!r}, expected asc or desc")

        # A stable order is required for offset pagination to be meaningful at
        # all -- without one, Postgres is free to return rows in a different
        # order across two otherwise-identical queries (e.g. after a
        # concurrent write, or just because it felt like it), which can skip
        # or repeat rows across pages. `id` (every model's primary key,
        # UUID for `iam` tables and bigint elsewhere) is unique and never
        # null, so it's always a valid sort key: the sole
        # order when none was requested, and a tiebreaker appended after any
        # requested order_by (whose own column may not be unique).
        if order_by is not None:
            attr = filterable.get(order_by)
            if attr is None:
                raise HTTPException(status_code=422, detail=f"unknown column {order_by}")
            primary = attr.desc() if order_normalized == "desc" else attr.asc()
            query = query.order_by(primary, model.id.asc())
        else:
            query = query.order_by(model.id.asc())

        try:
            total = query.count()
            rows = query.offset(offset).limit(limit).all()
        except DataError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail="invalid filter value") from exc
        return {
            "items": [read_schema.model_validate(row).model_dump(mode="json") for row in rows],
            "total": total,
        }

    @router.get("/{item_id}")
    def get_item(
        item_id: item_id_type, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)
    ) -> read_schema:
        item = db.get(model, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        return item

    if creatable:

        @router.post("/", status_code=201)
        def create_item(
            payload: create_schema,
            db: Session = Depends(get_db),
            _: UserAccount = Depends(get_current_user),
        ) -> read_schema:
            item = model(**payload.model_dump())
            db.add(item)
            try:
                db.commit()
            except DBAPIError as exc:
                db.rollback()
                raise translate_db_error(exc, table_name) from exc
            db.refresh(item)
            return item

    if updatable:

        @router.put("/{item_id}")
        def update_item(
            item_id: item_id_type,
            payload: update_schema,
            db: Session = Depends(get_db),
            _: UserAccount = Depends(get_current_user),
        ) -> read_schema:
            item = db.get(model, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="not found")
            for field, value in payload.model_dump(exclude_unset=True).items():
                setattr(item, field, value)
            try:
                db.commit()
            except DBAPIError as exc:
                db.rollback()
                raise translate_db_error(exc, table_name) from exc
            db.refresh(item)
            return item

    if deletable:

        @router.delete("/{item_id}", status_code=204)
        def delete_item(
            item_id: item_id_type, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)
        ) -> None:
            item = db.get(model, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="not found")
            db.delete(item)
            try:
                db.commit()
            except DBAPIError as exc:
                db.rollback()
                raise translate_db_error(exc, table_name) from exc

    return router
