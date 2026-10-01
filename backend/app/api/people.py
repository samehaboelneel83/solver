"""People and their roles on one page (UX audit A-1, A-2).

    GET  /api/v1/people                      every user with the roles they hold; every role with its
                                             capabilities and how many hold it
    PUT  /api/v1/people/{user_id}/roles      the roles a user holds, all at once
    PATCH /api/v1/people/{user_id}           {"is_active": bool}

The generic table editor showed a user's internal fields (external sub,
token version) and no roles at all: two accounts named "Planner" held
nothing, and nothing said so. This is the administrator's view of the same
rows. An administrator cannot lock themself out: deactivating their own
account, or taking away their own last way to manage people, is refused.
Deactivating a user also ends their sessions (the token version moves on).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import requires
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["people"])

MANAGE = "iam.manage"


def _roles(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(text(
        "SELECT r.id, r.code, r.name,"
        "       coalesce(array_agg(DISTINCT rc.capability_code) FILTER (WHERE rc.capability_code IS NOT NULL), '{}') AS capabilities,"
        "       (SELECT count(*) FROM iam.user_role ur WHERE ur.role_id = r.id) AS users"
        "  FROM iam.role r LEFT JOIN iam.role_capability rc ON rc.role_id = r.id"
        " GROUP BY r.id, r.code, r.name ORDER BY r.name")).mappings().all()
    return [{"id": str(r["id"]), "code": r["code"], "name": r["name"], "capabilities": sorted(r["capabilities"]),
             "users": int(r["users"])} for r in rows]


def _users(db: Session, user_id: UUID | None = None) -> list[dict[str, Any]]:
    rows = db.execute(text(
        "SELECT u.id, u.username, u.display_name, u.email, u.is_active,"
        "       coalesce(json_agg(json_build_object('id', r.id, 'code', r.code, 'name', r.name) ORDER BY r.name)"
        "                FILTER (WHERE r.id IS NOT NULL), '[]') AS roles"
        "  FROM iam.user_account u"
        "  LEFT JOIN iam.user_role ur ON ur.user_id = u.id LEFT JOIN iam.role r ON r.id = ur.role_id"
        + (" WHERE u.id = :u" if user_id else "") +
        " GROUP BY u.id ORDER BY u.username"), {"u": str(user_id)} if user_id else {}).mappings().all()
    return [{"id": str(r["id"]), "username": r["username"], "display_name": r["display_name"], "email": r["email"],
             "is_active": r["is_active"], "roles": [{**role, "id": str(role["id"])} for role in r["roles"]]} for r in rows]


def _one(db: Session, user_id: UUID) -> dict[str, Any]:
    found = _users(db, user_id)
    if not found:
        raise HTTPException(404, "user not found")
    return found[0]


@router.get("/people")
def people(db: Session = Depends(get_db), _: UserAccount = Depends(requires(MANAGE))) -> dict[str, Any]:
    return {"users": _users(db), "roles": _roles(db)}


class RolesIn(BaseModel):
    role_ids: list[UUID]


@router.put("/people/{user_id}/roles")
def set_roles(user_id: UUID, body: RolesIn, request: Request, db: Session = Depends(get_db),
              user: UserAccount = Depends(requires(MANAGE))) -> dict[str, Any]:
    before = _one(db, user_id)
    wanted = {str(r) for r in body.role_ids}
    known = {r["id"]: r for r in _roles(db)}
    unknown = wanted - set(known)
    if unknown:
        raise HTTPException(422, f"no such role: {', '.join(sorted(unknown))}")
    if str(user_id) == str(user.id) and not any(MANAGE in known[r]["capabilities"] for r in wanted):
        raise HTTPException(422, "These roles would take away your own way to manage people. Ask another administrator to do it.")
    held = {r["id"] for r in before["roles"]}
    for role_id in held - wanted:
        db.execute(text("DELETE FROM iam.user_role WHERE user_id = :u AND role_id = :r"), {"u": str(user_id), "r": role_id})
    for role_id in wanted - held:
        db.execute(text("INSERT INTO iam.user_role (id, user_id, role_id) VALUES (:id, :u, :r)"),
                   {"id": str(uuid4()), "u": str(user_id), "r": role_id})
    after = _one(db, user_id)
    audit.write(db, user, request, action="user.roles", object_type="user_account", object_id=str(user_id),
                before={"roles": sorted(r["code"] for r in before["roles"])}, after={"roles": sorted(r["code"] for r in after["roles"])})
    db.commit()
    return after


class PersonPatch(BaseModel):
    is_active: bool


@router.patch("/people/{user_id}")
def update_person(user_id: UUID, body: PersonPatch, request: Request, db: Session = Depends(get_db),
                  user: UserAccount = Depends(requires(MANAGE))) -> dict[str, Any]:
    before = _one(db, user_id)
    if str(user_id) == str(user.id) and not body.is_active:
        raise HTTPException(422, "You cannot deactivate your own account.")
    if before["is_active"] != body.is_active:
        # A deactivated user's tokens stop working at once, not when they expire.
        db.execute(text("UPDATE iam.user_account SET is_active = :a, token_version = token_version + (CASE WHEN :a THEN 0 ELSE 1 END)"
                        " WHERE id = :u"), {"a": body.is_active, "u": str(user_id)})
        audit.write(db, user, request, action="user.activate" if body.is_active else "user.deactivate",
                    object_type="user_account", object_id=str(user_id))
        db.commit()
    return _one(db, user_id)
