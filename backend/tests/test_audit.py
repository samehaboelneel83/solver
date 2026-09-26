"""Append-only audit log (queue R34)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app import audit
from app.seed import seed_admin
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_record_writes_hashes_and_refuses_update(db):
    seed_admin(db)
    org = db.execute(text("SELECT id FROM iam.organization WHERE code = 'default'")).scalar_one()
    event_id = audit.record(
        db,
        organization_id=org,
        action="auth.login",
        object_type="user",
        object_id="admin",
        after={"username": "admin"},
        ip="127.0.0.1",
    )
    db.commit()
    row = db.execute(
        text("SELECT action, after_hash, before_hash FROM iam.audit_event WHERE id = :i"),
        {"i": event_id},
    ).mappings().one()
    assert row["action"] == "auth.login"
    assert row["before_hash"] is None
    assert row["after_hash"] and len(row["after_hash"]) == 64
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("UPDATE iam.audit_event SET action = 'nope' WHERE id = :i"), {"i": event_id})
        db.commit()
    db.rollback()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("DELETE FROM iam.audit_event WHERE id = :i"), {"i": event_id})
        db.commit()
    db.rollback()


def test_prune_removes_old_rows_and_records_itself(db):
    seed_admin(db)
    org = db.execute(text("SELECT id FROM iam.organization WHERE code = 'default'")).scalar_one()
    db.execute(text("SELECT set_config('app.audit_prune', '1', true)"))
    db.execute(text("DELETE FROM iam.audit_event"))
    db.execute(text("SELECT set_config('app.audit_prune', '', true)"))
    db.execute(
        text(
            "INSERT INTO iam.audit_event (organization_id, action, at)"
            " VALUES (:o, 'settings.set', :t)"
        ),
        {"o": org, "t": datetime.now(timezone.utc) - timedelta(days=500)},
    )
    db.commit()
    deleted = audit.prune(db, now=datetime.now(timezone.utc))
    assert deleted.get(str(org), 0) >= 1
    remaining = db.execute(
        text("SELECT action FROM iam.audit_event WHERE organization_id = :o ORDER BY id"),
        {"o": org},
    ).scalars().all()
    assert remaining == ["audit.prune"]


def test_login_writes_an_audit_event(db, client):
    seed_admin(db)
    from app.core.config import get_settings

    settings = get_settings()
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    assert response.status_code == 200, response.text
    actions = db.execute(
        text("SELECT action FROM iam.audit_event WHERE action = 'auth.login'")
    ).scalars().all()
    assert len(actions) >= 1


def test_audit_list_and_csv_for_operator(db, client, auth_headers):
    seed_admin(db)
    org = db.execute(text("SELECT id FROM iam.organization WHERE code = 'default'")).scalar_one()
    audit.record(db, organization_id=org, action="settings.set", object_type="setting", object_id="x")
    db.commit()
    response = client.get("/api/v1/audit", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 1
    assert any(e["action"] == "settings.set" for e in body["items"])
    csv = client.get("/api/v1/audit?format=csv", headers=auth_headers)
    assert csv.status_code == 200
    assert "action" in csv.text.splitlines()[0]
    assert "settings.set" in csv.text
