"""Append-only audit log (queue R34).

Every mutating action that the plan names writes one ``iam.audit_event`` row.
Rows cannot be updated; deletes happen only when the nightly prune sets
``app.audit_prune=1``. Retention is ``audit.retention_days`` (default 400).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

KEY = "audit.retention_days"
DEFAULT_DAYS = 400


def _hash(payload: Any | None) -> str | None:
    if payload is None:
        return None
    body = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _inet_or_none(ip: str | None) -> str | None:
    if not ip:
        return None
    # Starlette TestClient uses the host name "testclient".
    if any(c.isalpha() for c in ip):
        return None
    return ip


def record(
    db: Session,
    *,
    organization_id: UUID | str,
    action: str,
    actor_id: UUID | str | None = None,
    api_key_id: UUID | str | None = None,
    object_type: str | None = None,
    object_id: str | int | None = None,
    before: Any | None = None,
    after: Any | None = None,
    ip: str | None = None,
) -> int:
    """Insert one audit row; returns its id."""
    return int(
        db.execute(
            text(
                "INSERT INTO iam.audit_event"
                " (organization_id, actor_id, api_key_id, action, object_type, object_id,"
                "  before_hash, after_hash, ip)"
                " VALUES (:o, :a, :k, :act, :ot, :oid, :bh, :ah, CAST(:ip AS inet))"
                " RETURNING id"
            ),
            {
                "o": str(organization_id),
                "a": str(actor_id) if actor_id else None,
                "k": str(api_key_id) if api_key_id else None,
                "act": action,
                "ot": object_type,
                "oid": None if object_id is None else str(object_id),
                "bh": _hash(before),
                "ah": _hash(after),
                "ip": _inet_or_none(ip),
            },
        ).scalar_one()
    )


def retention_days(db: Session, organization_id: UUID | str) -> int:
    """Days to keep this organization's audit rows (platform override, else default)."""
    del organization_id  # reserved for a per-org override once settings allow it
    row = db.execute(
        text(
            "SELECT coalesce("
            "  (SELECT (s.value #>> '{}')::numeric FROM setting s"
            "    WHERE s.scope = 'platform' AND s.key = :k),"
            "  (SELECT (k.default_value #>> '{}')::numeric FROM setting_key k WHERE k.key = :k),"
            "  :default"
            ")"
        ),
        {"k": KEY, "default": DEFAULT_DAYS},
    ).scalar_one()
    try:
        return max(0, int(row))
    except (TypeError, ValueError):
        return DEFAULT_DAYS


def prune(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Delete events older than each org's retention; record the prune itself.

    Returns ``{organization_id: deleted_count}``.
    """
    now = now or datetime.now(timezone.utc)
    orgs = db.execute(text("SELECT id FROM iam.organization")).scalars().all()
    deleted: dict[str, int] = {}
    for org in orgs:
        days = retention_days(db, org)
        if days <= 0:
            continue
        db.execute(text("SELECT set_config('app.audit_prune', '1', true)"))
        count = db.execute(
            text(
                "WITH doomed AS ("
                "  DELETE FROM iam.audit_event"
                "   WHERE organization_id = :o"
                "     AND at < (CAST(:now AS timestamptz) - make_interval(days => :d))"
                "   RETURNING 1"
                ") SELECT count(*) FROM doomed"
            ),
            {"o": str(org), "now": now, "d": int(days)},
        ).scalar_one()
        db.execute(text("SELECT set_config('app.audit_prune', '', true)"))
        if count:
            deleted[str(org)] = int(count)
            record(
                db,
                organization_id=org,
                action="audit.prune",
                after={"deleted": int(count), "retention_days": days, "at": now.isoformat()},
            )
    db.commit()
    return deleted


def main(argv: list[str] | None = None) -> int:
    del argv
    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        deleted = prune(db)
        print(f"audit prune: {sum(deleted.values())} rows across {len(deleted)} orgs")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    import sys

    sys.exit(main())
