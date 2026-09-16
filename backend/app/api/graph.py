import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.graph.schemas import GraphResponse
from app.graph.service import get_domain_graph
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
