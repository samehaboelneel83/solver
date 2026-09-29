"""Operator / admin audit log (queue R34)."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(tags=["audit"])


def _require_admin(db: Session) -> None:
    # Organization admins and operators: anyone who can read the audit of their org.
    # Operators see every org; others see only app_org().
    if not db.execute(text("SELECT app_org() IS NOT NULL OR app_is_operator()")).scalar_one():
        raise HTTPException(status_code=403, detail="audit requires a signed-in organization")


@router.get("/api/v1/audit")
def list_audit(
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
    action: str | None = None,
    object_type: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    format: str | None = None,
) -> Any:
    _require_admin(db)
    clauses = ["TRUE"]
    params: dict[str, Any] = {"lim": limit, "off": offset}
    if action:
        clauses.append("a.action = :action")
        params["action"] = action
    if object_type:
        clauses.append("a.object_type = :ot")
        params["ot"] = object_type
    where = " AND ".join(clauses)
    total = db.execute(
        text(f"SELECT count(*) FROM iam.audit_event a WHERE {where}"), params
    ).scalar_one()
    rows = db.execute(
        text(
            # Who, by name (operator trial F30): the account's username, or the API key's name.
            f"SELECT a.id, a.at, a.organization_id, a.actor_id, a.api_key_id, a.action,"
            f" a.object_type, a.object_id, a.before_hash, a.after_hash, host(a.ip) AS ip,"
            f" u.username AS actor, k.name AS api_key_name"
            f"  FROM iam.audit_event a"
            f"  LEFT JOIN iam.user_account u ON u.id = a.actor_id"
            f"  LEFT JOIN iam.api_key k ON k.id = a.api_key_id"
            f" WHERE {where}"
            f" ORDER BY a.at DESC, a.id DESC LIMIT :lim OFFSET :off"
        ),
        params,
    ).mappings().all()
    items = [
        {
            "id": r["id"],
            "at": r["at"].isoformat() if r["at"] else None,
            "organization_id": str(r["organization_id"]),
            "actor_id": str(r["actor_id"]) if r["actor_id"] else None,
            "actor": r["actor"],
            "api_key_name": r["api_key_name"],
            "api_key_id": str(r["api_key_id"]) if r["api_key_id"] else None,
            "action": r["action"],
            "object_type": r["object_type"],
            "object_id": r["object_id"],
            "before_hash": r["before_hash"],
            "after_hash": r["after_hash"],
            "ip": r["ip"],
        }
        for r in rows
    ]
    if format == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=[
                "id", "at", "organization_id", "actor_id", "actor", "api_key_id", "api_key_name", "action",
                "object_type", "object_id", "before_hash", "after_hash", "ip",
            ],
        )
        writer.writeheader()
        writer.writerows(items)
        return Response(content=buf.getvalue(), media_type="text/csv")
    return {"total": total, "items": items}
