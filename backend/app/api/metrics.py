"""Operator-only Prometheus exposition (queue R33).

The API and worker still serve internal scrape ports (9101 / 9100) on the
compose network only. This route is the authenticated view of the same
text, so an operator can read queue depth without joining the network.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core import metrics
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(tags=["metrics"])


@router.get("/api/v1/metrics")
def prometheus_metrics(
    db: Session = Depends(get_db),
    _user: UserAccount = Depends(get_current_user),
) -> Response:
    if not db.execute(text("SELECT app_is_operator()")).scalar_one():
        raise HTTPException(status_code=403, detail="metrics are for operators")
    # Ensure the queue gauges are registered even if lifespan has not run
    # (TestClient) or a worker process imported this module alone.
    metrics.register_queue_depth()
    return Response(content=metrics.exposition(), media_type="text/plain; version=0.0.4; charset=utf-8")
