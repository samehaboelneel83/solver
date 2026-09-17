import uuid
from typing import Type
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import String, Text, inspect, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.crud.errors import conflict_detail
from app.crud.registry import register_table
from app.models.iam import UserAccount


def searchable_columns(model: Type) -> list:
    """Return the mapped String/Text columns of `model`.

    Used to build the OR-ed `ilike` search for the `q` list param. Also
    reused by Task 2's search UI to know which columns are searchable.
    """
    mapper = inspect(model)
    return [
        prop.columns[0]
        for prop in mapper.column_attrs
        if isinstance(prop.columns[0].type, (String, Text))
    ]


def _filterable_attrs(model: Type) -> dict:
    """Map attribute name -> InstrumentedAttribute, for filter/order validation."""
    mapper = inspect(model)
    return {prop.key: getattr(model, prop.key) for prop in mapper.column_attrs}


def _python_type(attr) -> type:
    try:
        return attr.type.python_type
    except NotImplementedError:
        return str


def _cast_filter_value(attr, raw: str):
    py_type = _python_type(attr)
    if py_type is bool:
        lowered = raw.lower()
        if lowered not in ("true", "false"):
            raise ValueError(f"not a boolean: {raw!r}")
        return lowered == "true"
    if py_type is uuid.UUID:
        return uuid.UUID(raw)
    if py_type is int:
        return int(raw)
    return raw


def build_crud_router(
    *,
    model: Type,
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    read_schema: Type[BaseModel],
    schema_name: str,
    table_name: str,
) -> APIRouter:
    """Build a generic list/get/create/update/delete router for one table.

    Registers the table in TABLE_REGISTRY as a side effect, so Task 18's
    /api/meta/schema endpoint picks it up automatically without a second
    bookkeeping step.
    """
    router = APIRouter(prefix=f"/api/{schema_name}/{table_name}", tags=[f"{schema_name}.{table_name}"])
    register_table(schema_name, table_name, model, create_schema, read_schema)

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
        filterable = _filterable_attrs(model)
        query = db.query(model)

        if q:
            columns = searchable_columns(model)
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
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail=f"invalid value for column {column_name}")
            query = query.filter(attr == value)

        if order_by is not None:
            attr = filterable.get(order_by)
            if attr is None:
                raise HTTPException(status_code=422, detail=f"unknown column {order_by}")
            query = query.order_by(attr.desc() if order.lower() == "desc" else attr.asc())

        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        return {
            "items": [read_schema.model_validate(row).model_dump(mode="json") for row in rows],
            "total": total,
        }

    @router.get("/{item_id}")
    def get_item(
        item_id: UUID, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)
    ) -> read_schema:
        item = db.get(model, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        return item

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
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=conflict_detail(exc, table_name)) from exc
        db.refresh(item)
        return item

    @router.put("/{item_id}")
    def update_item(
        item_id: UUID,
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
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=conflict_detail(exc, table_name)) from exc
        db.refresh(item)
        return item

    @router.delete("/{item_id}", status_code=204)
    def delete_item(
        item_id: UUID, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)
    ) -> None:
        item = db.get(model, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        db.delete(item)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=conflict_detail(exc, table_name)) from exc

    return router
