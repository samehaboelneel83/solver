"""A record's history (migration 0100).

    GET /api/v1/entities/{id}/history   ?limit=&offset=

Newest first: when, who, what was done, and for an update each field that changed with its value
before and after -- `key`, `label`, `active`, `sort_order`, or a field of the record by its name.
A deleted record's history is still answered: it outlives the record.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["entities"])

COLUMNS = ("key", "label", "active", "sort_order")


def changes(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Field by field, what differs between two snapshots (either may be absent)."""
    b, a = before or {}, after or {}
    out = [{"field": c, "before": b.get(c), "after": a.get(c)} for c in COLUMNS if b.get(c) != a.get(c)]
    battrs, aattrs = b.get("attrs") or {}, a.get("attrs") or {}
    for name in sorted(set(battrs) | set(aattrs)):
        if battrs.get(name) != aattrs.get(name):
            out.append({"field": name, "before": battrs.get(name), "after": aattrs.get(name)})
    return out


@router.get("/entities/{entity_id}/history")
def history(entity_id: int, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
            db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    total = db.execute(text("SELECT count(*) FROM entity_change WHERE entity_id = :e"), {"e": entity_id}).scalar_one()
    if total == 0 and db.execute(text("SELECT 1 FROM entity WHERE id = :e"), {"e": entity_id}).first() is None:
        raise HTTPException(404, "entity not found")
    rows = db.execute(text(
        "SELECT id, at, actor, op, before, after FROM entity_change WHERE entity_id = :e"
        " ORDER BY at DESC, id DESC LIMIT :lim OFFSET :off"), {"e": entity_id, "lim": limit, "off": offset}).mappings()
    items = [{"id": r["id"], "at": r["at"], "actor": r["actor"], "op": r["op"], "changes": changes(r["before"], r["after"])}
             for r in rows]
    return {"entity_id": entity_id, "total": total, "items": items}
