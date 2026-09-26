"""Per-organization solve tiers (queue R40).

Commercial defaults: free / standard / enterprise. Setting a tier fills the
quota row; later PUT fields still override individual limits.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

TIERS: dict[str, dict[str, Any]] = {
    "free": {
        "max_concurrent_runs": 1,
        "max_queued_runs": 5,
        "max_time_limit_s": 60.0,
        "max_memory_mb": 1024,
        "priority_weight": 1,
    },
    "standard": {
        "max_concurrent_runs": 5,
        "max_queued_runs": 25,
        "max_time_limit_s": 600.0,
        "max_memory_mb": 4096,
        "priority_weight": 5,
    },
    "enterprise": {
        "max_concurrent_runs": 20,
        "max_queued_runs": 100,
        "max_time_limit_s": 3600.0,
        "max_memory_mb": 16384,
        "priority_weight": 10,
    },
}


def apply_tier(db: Session, organization_id, tier: str, *, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Upsert quota from a named tier; optional overrides win."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; choose free, standard or enterprise")
    values = {**TIERS[tier], "tier": tier}
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                values[key] = value
    db.execute(
        text(
            "INSERT INTO iam.quota (organization_id, tier, priority_weight, max_memory_mb,"
            "  max_concurrent_runs, max_queued_runs, max_time_limit_s)"
            " VALUES (:o, :tier, :priority_weight, :max_memory_mb,"
            "  :max_concurrent_runs, :max_queued_runs, :max_time_limit_s)"
            " ON CONFLICT (organization_id) DO UPDATE SET"
            "  tier = EXCLUDED.tier,"
            "  priority_weight = EXCLUDED.priority_weight,"
            "  max_memory_mb = EXCLUDED.max_memory_mb,"
            "  max_concurrent_runs = EXCLUDED.max_concurrent_runs,"
            "  max_queued_runs = EXCLUDED.max_queued_runs,"
            "  max_time_limit_s = EXCLUDED.max_time_limit_s,"
            "  updated_at = now()"
        ),
        {"o": organization_id, **values},
    )
    return values
