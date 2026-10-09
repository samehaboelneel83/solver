"""The organizations a platform serves, managed by its operator in the platform itself (owner, 9 October 2026:
everything doable without scripts or the Assistant).

    GET  /api/v1/organizations          every organization: users, problems, quota (operator only)
    POST /api/v1/organizations          a new organization and its first administrator (operator only)

Export, hard delete (`org_lifecycle.py`) and quotas (`quota.py`) already have their routes; this adds the list
to act on and the way to start a tenant, which only the seed and load scripts had.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import requires
from app.core.db import enter_tenant, get_db
from app.core.security import hash_password
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])

CODE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class NewOrganization(BaseModel):
    code: str = Field(description="short, lower-case, unique: its sign-in and export name")
    name: str = Field(min_length=1, max_length=255)
    admin_username: str = Field(min_length=3, max_length=100)
    admin_password: str = Field(min_length=12, max_length=256, description="the first administrator's; they change it")
    admin_email: str | None = Field(default=None, max_length=255)
    tier: str | None = Field(default=None, description="a quota tier to start from (app.tiers)")

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        if not CODE.match(value):
            raise ValueError("2 to 63 lower-case letters, digits or dashes, starting with a letter or digit")
        return value


def _operator_only(db: Session) -> None:
    if not bool(db.execute(text("SELECT app_is_operator()")).scalar_one()):
        raise HTTPException(status_code=403, detail="only the platform's operator organization manages organizations")


def _all(db: Session) -> list[dict[str, Any]]:
    """Every organization, read across tenants as the connecting role (as `org_lifecycle` does)."""
    db.execute(text("RESET ROLE"))
    rows = db.execute(text(
        "SELECT o.id, o.code, o.name, o.is_active, o.is_operator, o.created_at,"
        " (SELECT count(*) FROM iam.user_account u WHERE u.organization_id = o.id) AS users,"
        " (SELECT count(*) FROM problem p WHERE p.organization_id = o.id) AS problems,"
        " (SELECT to_jsonb(q) - 'organization_id' FROM iam.quota q WHERE q.organization_id = o.id) AS quota"
        " FROM iam.organization o ORDER BY o.is_operator DESC, o.code")).mappings().all()
    return [{**dict(r), "id": str(r["id"])} for r in rows]


@router.get("")
def list_organizations(db: Session = Depends(get_db), user: UserAccount = Depends(requires("iam.manage"))) -> dict:
    _operator_only(db)
    try:
        return {"items": _all(db)}
    finally:
        db.rollback()
        enter_tenant(db, user.organization_id)


@router.post("", status_code=201)
def create_organization(body: NewOrganization, request: Request, db: Session = Depends(get_db),
                        user: UserAccount = Depends(requires("iam.manage"))) -> dict:
    """A new tenant: the organization, a default quota (or a tier's), and its first administrator, who can then
    add people, roles, sign-in and everything else from inside it."""
    _operator_only(db)
    try:
        db.execute(text("RESET ROLE"))
        taken = db.execute(text("SELECT (SELECT 1 FROM iam.organization WHERE code = :c) AS org,"
                                " (SELECT 1 FROM iam.user_account WHERE username = :u) AS username"),
                           {"c": body.code, "u": body.admin_username}).mappings().one()
        if taken["org"]:
            raise HTTPException(status_code=409, detail=f"an organization with code {body.code!r} exists")
        if taken["username"]:
            raise HTTPException(status_code=409, detail=f"the user name {body.admin_username!r} is taken")
        org = db.execute(text("INSERT INTO iam.organization (id, code, name) VALUES (gen_random_uuid(), :c, :n)"
                              " RETURNING id"), {"c": body.code, "n": body.name}).scalar_one()
        db.execute(text("INSERT INTO iam.quota (organization_id) VALUES (:o) ON CONFLICT DO NOTHING"), {"o": org})
        if body.tier:
            from app.tiers import apply_tier

            try:
                apply_tier(db, org, body.tier)
            except Exception as exc:  # noqa: BLE001 -- an unknown tier is the operator's to fix
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        admin = db.execute(text(
            "INSERT INTO iam.user_account (id, organization_id, username, display_name, email, hashed_password,"
            " is_active, token_version) VALUES (gen_random_uuid(), :o, :u, 'Administrator', :e, :h, true, 0)"
            " RETURNING id"),
            {"o": org, "u": body.admin_username, "e": body.admin_email, "h": hash_password(body.admin_password)}
        ).scalar_one()
        db.execute(text("INSERT INTO iam.user_role (id, user_id, role_id) SELECT gen_random_uuid(), :u, r.id"
                        " FROM iam.role r WHERE r.code = 'admin'"), {"u": admin})
        db.commit()
    except Exception:
        db.rollback()
        enter_tenant(db, user.organization_id)
        raise
    enter_tenant(db, user.organization_id)
    audit.record(db, organization_id=user.organization_id, actor_id=user.id, action="org.create",
                 object_type="organization", object_id=body.code, after={"name": body.name,
                                                                         "admin": body.admin_username},
                 ip=request.client.host if request.client else None)
    db.commit()
    return {"id": str(org), "code": body.code, "name": body.name, "admin_username": body.admin_username}
