"""Notices (migration 0119): what the platform did for a person while they were away -- a scheduled refresh that
found changes, applied them, or could not finish. Each person reads their own.

    GET  /api/v1/notices              newest first, the unread count beside them
    POST /api/v1/notices/{id}/read    marked read
    POST /api/v1/notices/read-all     all of the person's marked read
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["notices"])


@router.get("/notices")
def notices(unread: bool = Query(False), limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
            user: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    rows = db.execute(text(
        "SELECT id, kind, title, body, link, created_at, read_at FROM notice WHERE user_id = :u"
        + (" AND read_at IS NULL" if unread else "") + " ORDER BY created_at DESC, id DESC LIMIT :l"),
        {"u": user.id, "l": limit}).mappings().all()
    count = db.execute(text("SELECT count(*) FROM notice WHERE user_id = :u AND read_at IS NULL"),
                       {"u": user.id}).scalar_one()
    return {"items": [dict(r) for r in rows], "unread": int(count)}


@router.post("/notices/{notice_id}/read")
def read(notice_id: int, db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict:
    done = db.execute(text("UPDATE notice SET read_at = coalesce(read_at, now()) WHERE id = :i AND user_id = :u"
                           " RETURNING id"), {"i": notice_id, "u": user.id}).scalar()
    if done is None:
        raise HTTPException(404, "notice not found")
    db.commit()
    return {"id": notice_id, "read": True}


@router.post("/notices/read-all")
def read_all(db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)) -> dict:
    n = db.execute(text("UPDATE notice SET read_at = now() WHERE user_id = :u AND read_at IS NULL"),
                   {"u": user.id}).rowcount
    db.commit()
    return {"read": n}
