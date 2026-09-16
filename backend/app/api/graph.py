import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.graph.schemas import GraphResponse
from app.graph.service import (
    GraphConflictError,
    GraphNotFoundError,
    create_node,
    delete_node,
    get_domain_graph,
    update_node,
)
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/graph/domain", tags=["graph"])


@router.get("")
def read_domain_graph(
    organization_id: uuid.UUID = Query(...),
    hierarchy_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> GraphResponse:
    return get_domain_graph(db, organization_id=organization_id, hierarchy_id=hierarchy_id)


class CreateNodeRequest(BaseModel):
    organization_id: uuid.UUID
    entity_type_id: uuid.UUID
    name: str
    code: str | None = None
    status: str | None = None
    description: str | None = None
    attributes: dict = {}
    hierarchy_id: uuid.UUID | None = None
    parent_entity_id: uuid.UUID | None = None


@router.post("/nodes", status_code=201)
def create_node_route(
    payload: CreateNodeRequest,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
):
    try:
        return create_node(
            db,
            organization_id=payload.organization_id,
            entity_type_id=payload.entity_type_id,
            name=payload.name,
            code=payload.code,
            status=payload.status,
            description=payload.description,
            attributes=payload.attributes,
            hierarchy_id=payload.hierarchy_id,
            parent_entity_id=payload.parent_entity_id,
        )
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class UpdateNodeRequest(BaseModel):
    name: str | None = None
    code: str | None = None
    status: str | None = None
    description: str | None = None
    attributes: dict | None = None
    hierarchy_id: uuid.UUID | None = None
    parent_entity_id: uuid.UUID | None = None


@router.patch("/nodes/{entity_id}")
def update_node_route(
    entity_id: uuid.UUID,
    payload: UpdateNodeRequest,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
):
    try:
        return update_node(
            db,
            entity_id,
            name=payload.name,
            code=payload.code,
            status=payload.status,
            description=payload.description,
            attributes=payload.attributes,
            hierarchy_id=payload.hierarchy_id,
            parent_entity_id=payload.parent_entity_id,
        )
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/nodes/{entity_id}", status_code=204)
def delete_node_route(
    entity_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> None:
    try:
        delete_node(db, entity_id)
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GraphConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
