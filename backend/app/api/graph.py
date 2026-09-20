"""The graph read: one domain's nodes and edges, ready for the canvas.

    GET /api/v1/graph?domain_id=&hierarchy_type_id=

Read-only by design. v0 mounted create/update/delete routes for nodes and
edges here, duplicating what `app/api/entities.py` and
`app/api/relationships.py` now do properly -- with the attribute and
relationship rules the database owns, rather than a second Python
implementation of them. Those routes are therefore gone rather than
rewritten; the graph editor writes through the two v1 routers.

The path moves with them: v0's `/api/graph/domain?organization_id=` is
replaced by `/api/v1/graph?domain_id=`, because v1 has no `organization`
and the resource is a domain. `frontend/src/api/graph.ts` still points at
the old path and is **task 14's** to move -- the frontend graph page has
been offline since task 1 unmounted this router, so nothing regresses in
the meantime.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.graph.schemas import GraphResponse
from app.graph.service import HierarchyTypeNotFound, get_domain_graph
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["graph"])


@router.get("/graph")
def read_domain_graph(
    domain_id: int = Query(..., description="the domain whose graph to draw"),
    hierarchy_type_id: int | None = Query(
        None,
        description=(
            "a relationship_type with is_hierarchy = true, whose rows become "
            "the nodes' compound parents; one of `hierarchies[]`"
        ),
    ),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> GraphResponse:
    try:
        return get_domain_graph(
            db, domain_id=domain_id, hierarchy_type_id=hierarchy_type_id
        )
    except HierarchyTypeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
