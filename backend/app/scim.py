"""SCIM 2.0 Users and Groups (queue R36).

Per-organization bearer token. Deprovisioning deactivates the user, bumps
``token_version`` (JWTs stop), and revokes every API key at once.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.sso import bump_token_version


def mint_token(db: Session, organization_id) -> str:
    raw = "scim_" + secrets.token_urlsafe(32)
    prefix = raw[:12]
    digest = hashlib.sha256(raw.encode()).hexdigest()
    db.execute(
        text(
            "INSERT INTO iam.scim_token (organization_id, token_hash, prefix, created_at)"
            " VALUES (:o, :h, :p, now())"
            " ON CONFLICT (organization_id) DO UPDATE SET"
            "  token_hash = EXCLUDED.token_hash, prefix = EXCLUDED.prefix, created_at = now()"
        ),
        {"o": organization_id, "h": digest, "p": prefix},
    )
    return raw


def resolve_token(db: Session, bearer: str):
    if not bearer or not bearer.startswith("scim_"):
        return None
    digest = hashlib.sha256(bearer.encode()).hexdigest()
    return db.execute(
        text("SELECT organization_id FROM iam.scim_token WHERE token_hash = :h"),
        {"h": digest},
    ).scalar_one_or_none()


def list_users(db: Session, organization_id, *, start: int = 1, count: int = 100) -> dict[str, Any]:
    total = db.execute(
        text("SELECT count(*) FROM iam.user_account WHERE organization_id = :o"),
        {"o": organization_id},
    ).scalar_one()
    rows = db.execute(
        text(
            "SELECT id, username, display_name, email, is_active, external_sub"
            "  FROM iam.user_account WHERE organization_id = :o"
            " ORDER BY username OFFSET :off LIMIT :lim"
        ),
        {"o": organization_id, "off": max(0, start - 1), "lim": count},
    ).mappings().all()
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total,
        "startIndex": start,
        "itemsPerPage": count,
        "Resources": [_user_resource(r) for r in rows],
    }


def get_user(db: Session, organization_id, user_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text(
            "SELECT id, username, display_name, email, is_active, external_sub"
            "  FROM iam.user_account WHERE organization_id = :o AND id = :u"
        ),
        {"o": organization_id, "u": user_id},
    ).mappings().one_or_none()
    return _user_resource(row) if row else None


def create_user(db: Session, organization_id, body: dict[str, Any]) -> dict[str, Any]:
    from app.models.iam import UserAccount

    user_name = body.get("userName") or (body.get("emails") or [{}])[0].get("value")
    if not user_name:
        raise ValueError("userName is required")
    email = None
    emails = body.get("emails") or []
    if emails:
        email = emails[0].get("value")
    display = (body.get("displayName") or user_name)[:255]
    active = body.get("active", True)
    external = body.get("externalId")
    user = UserAccount(
        organization_id=organization_id,
        username=str(user_name)[:150],
        display_name=display,
        email=email,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        is_active=bool(active),
        external_sub=external,
    )
    db.add(user)
    db.flush()
    return _user_resource(
        {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "is_active": user.is_active,
            "external_sub": user.external_sub,
        }
    )


def replace_user(db: Session, organization_id, user_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
    row = db.execute(
        text("SELECT id FROM iam.user_account WHERE organization_id = :o AND id = :u"),
        {"o": organization_id, "u": user_id},
    ).one_or_none()
    if row is None:
        return None
    active = body.get("active", True)
    display = body.get("displayName")
    email = None
    emails = body.get("emails") or []
    if emails:
        email = emails[0].get("value")
    db.execute(
        text(
            "UPDATE iam.user_account SET"
            "  is_active = :a,"
            "  display_name = coalesce(:d, display_name),"
            "  email = coalesce(:e, email),"
            "  updated_at = now()"
            " WHERE id = :u"
        ),
        {"a": bool(active), "d": display, "e": email, "u": user_id},
    )
    if not active:
        deprovision(db, organization_id, user_id)
    return get_user(db, organization_id, user_id)


def deprovision(db: Session, organization_id, user_id: str) -> None:
    db.execute(
        text(
            "UPDATE iam.user_account SET is_active = false, updated_at = now()"
            " WHERE id = :u AND organization_id = :o"
        ),
        {"u": user_id, "o": organization_id},
    )
    bump_token_version(db, user_id)
    db.execute(
        text(
            "UPDATE iam.api_key SET revoked_at = now()"
            " WHERE user_id = :u AND revoked_at IS NULL"
        ),
        {"u": user_id},
    )


def delete_user(db: Session, organization_id, user_id: str) -> bool:
    if get_user(db, organization_id, user_id) is None:
        return False
    deprovision(db, organization_id, user_id)
    return True


def list_groups(db: Session, organization_id) -> dict[str, Any]:
    rows = db.execute(
        text("SELECT id, code, name FROM iam.role ORDER BY code")
    ).mappings().all()
    resources = [
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "id": str(r["id"]),
            "displayName": r["name"],
            "externalId": r["code"],
        }
        for r in rows
    ]
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": len(resources),
        "Resources": resources,
    }


def _user_resource(row) -> dict[str, Any]:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": str(row["id"]),
        "userName": row["username"],
        "displayName": row["display_name"],
        "active": bool(row["is_active"]),
        "emails": [{"value": row["email"], "primary": True}] if row["email"] else [],
        "externalId": row["external_sub"],
    }
