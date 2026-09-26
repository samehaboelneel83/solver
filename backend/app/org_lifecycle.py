"""Organization export and hard deletion (queue R37).

Retention of settled runs uses ``run.retention_days`` (default 365). Hard
delete removes every row of a non-operator organization and returns a signed
deletion report (HMAC-SHA256 of a canonical summary, key = JWT_SECRET).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings


class OrgLifecycleRefused(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def export_organization(db: Session, organization_id) -> dict[str, Any]:
    org = db.execute(
        text(
            "SELECT id, code, name, description, is_active, is_operator, created_at"
            "  FROM iam.organization WHERE id = :o"
        ),
        {"o": organization_id},
    ).mappings().one_or_none()
    if org is None:
        raise OrgLifecycleRefused("org_missing", "organization not found")
    users = db.execute(
        text(
            "SELECT id, username, display_name, email, is_active, external_sub, created_at"
            "  FROM iam.user_account WHERE organization_id = :o ORDER BY username"
        ),
        {"o": organization_id},
    ).mappings().all()
    problems = db.execute(
        text(
            "SELECT id, name, domain_id, created_at FROM problem"
            " WHERE organization_id = :o ORDER BY name"
        ),
        {"o": organization_id},
    ).mappings().all()
    settings_rows = db.execute(
        text("SELECT key, scope, scope_id, value FROM setting WHERE organization_id = :o"),
        {"o": organization_id},
    ).mappings().all()
    quota = db.execute(
        text("SELECT * FROM iam.quota WHERE organization_id = :o"),
        {"o": organization_id},
    ).mappings().one_or_none()
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "organization": {k: (str(v) if hasattr(v, "hex") else v) for k, v in dict(org).items()},
        "users": [
            {k: (str(v) if hasattr(v, "hex") else v) for k, v in dict(u).items()}
            for u in users
        ],
        "problems": [
            {k: (str(v) if hasattr(v, "hex") else v) for k, v in dict(p).items()}
            for p in problems
        ],
        "settings": [dict(s) for s in settings_rows],
        "quota": {k: (str(v) if hasattr(v, "hex") else v) for k, v in dict(quota).items()} if quota else None,
    }


def delete_organization(db: Session, organization_id, *, confirm_code: str, actor_username: str) -> dict[str, Any]:
    org = db.execute(
        text(
            "SELECT id, code, name, is_operator FROM iam.organization WHERE id = :o"
        ),
        {"o": organization_id},
    ).mappings().one_or_none()
    if org is None:
        raise OrgLifecycleRefused("org_missing", "organization not found")
    if org["is_operator"] or org["code"] == "default":
        raise OrgLifecycleRefused("org_operator", "the operator organization cannot be deleted")
    if confirm_code != org["code"]:
        raise OrgLifecycleRefused(
            "org_confirm",
            f"confirm_code must be the organization code {org['code']!r}",
        )

    # Hard delete crosses tenant RLS (tenant_isolation has no operator OR).
    # Act as the connecting role, which bypasses RLS (migration 0032).
    db.execute(text("RESET ROLE"))
    db.execute(text("SELECT set_config('app.org_delete', '1', true)"))
    counts: dict[str, int] = {}

    def _del(label: str, sql: str, params: dict | None = None) -> None:
        result = db.execute(text(sql), params or {"o": organization_id})
        counts[label] = result.rowcount

    # Child data first. Immutable tables allow DELETE (only UPDATE is forbidden).
    _del("run_event", "DELETE FROM run_event e USING run r WHERE e.run_id = r.id AND r.organization_id = :o")
    _del("constraint_result", "DELETE FROM constraint_result WHERE organization_id = :o")
    _del("solution", "DELETE FROM solution WHERE organization_id = :o")
    _del("run", "DELETE FROM run WHERE organization_id = :o")
    _del("scenario", "DELETE FROM scenario WHERE organization_id = :o")
    _del("dataset", "DELETE FROM dataset WHERE organization_id = :o")
    _del("model_version", "DELETE FROM model_version WHERE organization_id = :o")
    _del("problem", "DELETE FROM problem WHERE organization_id = :o")
    _del("setting", "DELETE FROM setting WHERE organization_id = :o")
    _del("parameter_value", "DELETE FROM parameter_value WHERE organization_id = :o")
    _del("parameter_def", "DELETE FROM parameter_def WHERE organization_id = :o")
    _del("relationship", "DELETE FROM relationship WHERE organization_id = :o")
    _del("relationship_type", "DELETE FROM relationship_type WHERE organization_id = :o")
    _del("entity", "DELETE FROM entity WHERE organization_id = :o")
    _del("attribute_def", "DELETE FROM attribute_def WHERE organization_id = :o")
    _del("entity_type", "DELETE FROM entity_type WHERE organization_id = :o")
    _del("domain", "DELETE FROM domain WHERE organization_id = :o")
    _del("api_key", "DELETE FROM iam.api_key WHERE organization_id = :o")
    _del("user_role", "DELETE FROM iam.user_role ur USING iam.user_account u WHERE ur.user_id = u.id AND u.organization_id = :o")
    _del("user_account", "DELETE FROM iam.user_account WHERE organization_id = :o")
    _del("quota", "DELETE FROM iam.quota WHERE organization_id = :o")
    _del("usage_month", "DELETE FROM iam.usage_month WHERE organization_id = :o")
    _del("oidc_provider", "DELETE FROM iam.oidc_provider WHERE organization_id = :o")
    _del("scim_token", "DELETE FROM iam.scim_token WHERE organization_id = :o")
    db.execute(text("SELECT set_config('app.audit_prune', '1', true)"))
    _del("audit_event", "DELETE FROM iam.audit_event WHERE organization_id = :o")
    db.execute(text("SELECT set_config('app.audit_prune', '', true)"))
    _del("organization", "DELETE FROM iam.organization WHERE id = :o")
    deleted_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "organization_id": str(organization_id),
        "code": org["code"],
        "name": org["name"],
        "deleted_at": deleted_at,
        "deleted_by": actor_username,
        "counts": counts,
        "statement": (
            f"This certifies that organization {org['code']!r} ({org['name']}) "
            f"and the counts of rows listed were permanently deleted at {deleted_at}."
        ),
    }
    canonical = json.dumps(summary, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    signature = hmac.new(
        get_settings().jwt_secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()
    report = {**summary, "summary_sha256": digest, "signature": signature, "signature_alg": "HMAC-SHA256"}
    return report


def verify_report(report: dict[str, Any]) -> bool:
    payload = {k: report[k] for k in ("organization_id", "code", "name", "deleted_at", "deleted_by", "counts", "statement")}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    if digest != report.get("summary_sha256"):
        return False
    expected = hmac.new(
        get_settings().jwt_secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, report.get("signature") or "")
