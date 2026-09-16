from typing import Type
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.crud.registry import register_table
from app.models.iam import UserAccount


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
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        _: UserAccount = Depends(get_current_user),
    ) -> dict:
        total = db.query(model).count()
        rows = db.query(model).offset(offset).limit(limit).all()
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
        db.commit()
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
        db.commit()
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
        db.commit()

    return router
