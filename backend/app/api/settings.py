"""Settings: read what applies, and change it without a deployment.

Two routes, because settings are two questions that look like one:

- **What applies here?** Resolved, with the level each value came from. A
  number nobody can attribute is a number nobody can change with confidence.
- **Set this, at this level.** Or unset it, by sending `null`, which is not
  the same as setting it to zero: unsetting restores whatever the level above
  says, and a platform that could only ever add overrides would accumulate
  them.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import get_current_user, requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.settings_resolve import resolve

router = APIRouter(prefix="/api/v1", tags=["settings"])

Scope = Literal["platform", "domain", "problem"]


class SettingWrite(BaseModel):
    scope: Scope
    #: A domain id or a problem id; omitted for the platform level.
    scope_id: int | None = None
    key: str
    #: `null` unsets this level, restoring whatever the level above says.
    value: Any = None


@router.get("/settings")
def read_settings(
    problem_id: int | None = Query(default=None),
    domain_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    """Every setting, with the value that applies and where it came from.

    With neither id this is the platform level alone, which is what a
    platform-wide settings screen shows.
    """
    resolved = resolve(db, problem_id=problem_id, domain_id=domain_id)
    return {
        "items": [
            {
                "key": r.key,
                "value": r.value,
                "source": r.source,
                "value_type": r.value_type,
                "description": r.description,
            }
            for r in resolved.values()
        ]
    }


@router.put("/settings")
def write_setting(
    payload: SettingWrite,
    request: Request,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(requires("settings.edit")),
) -> dict[str, Any]:
    """Set or unset one setting at one level.

    **422 for an unknown key**, rather than storing it: a setting nobody reads
    is indistinguishable from one that is not working, and the caller would
    have no way to tell which they had.
    """
    known = db.execute(
        text("SELECT value_type FROM setting_key WHERE key = :k"), {"k": payload.key}
    ).scalar_one_or_none()
    if known is None:
        raise HTTPException(status_code=422, detail=f"no setting called {payload.key!r}")
    if payload.key.startswith("gpu.") and payload.scope != "platform":
        raise HTTPException(status_code=422, detail="GPU connection settings are platform-only")
    if payload.key == "gpu.endpoint" and payload.value:
        from urllib.parse import urlsplit
        url = urlsplit(str(payload.value))
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
            raise HTTPException(status_code=422, detail="Use an http(s) service origin without credentials, path, query or fragment")

    if (payload.scope == "platform") != (payload.scope_id is None):
        raise HTTPException(
            status_code=422,
            detail="the platform level takes no scope_id; a domain or problem level needs one",
        )

    # The platform level governs every organization's runs, so only an
    # operator organization may change it (migration 0032); the database
    # refuses it too, but this says why.
    if payload.scope == "platform" and not db.execute(text("SELECT app_is_operator()")).scalar_one():
        raise HTTPException(
            status_code=403,
            detail="platform settings apply to every organization; only an operator organization may change them",
        )

    before = db.execute(
        text(
            "SELECT value FROM setting WHERE scope = CAST(:s AS setting_scope)"
            "   AND scope_id IS NOT DISTINCT FROM :i AND key = :k"
        ),
        {"s": payload.scope, "i": payload.scope_id, "k": payload.key},
    ).scalar_one_or_none()

    if payload.value is None:
        db.execute(
            text(
                "DELETE FROM setting WHERE scope = CAST(:s AS setting_scope)"
                "   AND scope_id IS NOT DISTINCT FROM :i AND key = :k"
            ),
            {"s": payload.scope, "i": payload.scope_id, "k": payload.key},
        )
        audit.record(
            db,
            organization_id=user.organization_id,
            actor_id=user.id,
            action="settings.unset",
            object_type="setting",
            object_id=payload.key,
            before={"scope": payload.scope, "scope_id": payload.scope_id, "value": before},
            ip=request.client.host if request.client else None,
        )
        db.commit()
        return {"unset": payload.key, "scope": payload.scope, "scope_id": payload.scope_id}

    _refuse_wrong_type(known, payload.value, payload.key)
    _refuse_out_of_range(payload.key, payload.value)
    _refuse_unknown_choice(payload.key, payload.value)

    try:
        db.execute(
            text(
                "INSERT INTO setting (scope, scope_id, key, value)"
                " VALUES (CAST(:s AS setting_scope), :i, :k, CAST(:v AS jsonb))"
                " ON CONFLICT (scope, scope_id, key)"
                " DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
            ),
            {"s": payload.scope, "i": payload.scope_id, "k": payload.key, "v": _json(payload.value)},
        )
        audit.record(
            db,
            organization_id=user.organization_id,
            actor_id=user.id,
            action="settings.set",
            object_type="setting",
            object_id=payload.key,
            before={"scope": payload.scope, "scope_id": payload.scope_id, "value": before},
            after={"scope": payload.scope, "scope_id": payload.scope_id, "value": payload.value},
            ip=request.client.host if request.client else None,
        )
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        # The trigger's 23503: the domain or problem named does not exist.
        raise HTTPException(
            status_code=422,
            detail=f"no {payload.scope} with id {payload.scope_id}",
        ) from exc

    return {"key": payload.key, "scope": payload.scope, "scope_id": payload.scope_id,
            "value": payload.value}


def _refuse_wrong_type(value_type: str, value: Any, key: str) -> None:
    """A string where a number belongs would resolve, then fail at solve time
    -- far from the screen that set it."""
    ok = {
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
    }[value_type]
    if not ok:
        raise HTTPException(
            status_code=422,
            detail=f"{key} is a {value_type}, and {value!r} is not",
        )


# The numbers a solve setting may take. A negative gap, zero threads or a
# zero time limit would be stored happily and fail at solve time, far from the
# screen that set them. Inclusive bounds; None means no limit that side.
_RANGES: dict[str, tuple[float | None, float | None]] = {
    "gpu.memory_mb": (64, 1048576),
    "solve.time_limit_s": (0.1, None),
    "solve.workers": (1, 64),
    "solve.gap_rel": (0, 0.5),
    "solve.seed": (0, 2_147_483_647),
    "run.retention_days": (1, None),
    # 0 keeps a run's events for ever (app.retention).
    "run.event_retention_days": (0, None),
}


# The words a string setting may take, where only some mean anything.
_CHOICES: dict[str, tuple[str, ...]] = {
    "solve.network_engine": ("networkx", "ortools"),
}


def _refuse_unknown_choice(key: str, value: Any) -> None:
    if key in _CHOICES and value is not None and value not in _CHOICES[key]:
        raise HTTPException(status_code=422, detail=f"{key} is one of {', '.join(_CHOICES[key])}; {value!r} is not")


def _refuse_out_of_range(key: str, value: Any) -> None:
    low, high = _RANGES.get(key, (None, None))
    if (low is not None and value < low) or (high is not None and value > high):
        span = f"from {low}" + (f" to {high}" if high is not None else " up")
        raise HTTPException(status_code=422, detail=f"{key} takes values {span}, and {value!r} is not one")
    if key in ("solve.workers", "solve.seed", "run.retention_days", "run.event_retention_days") and value != int(value):
        raise HTTPException(status_code=422, detail=f"{key} is a whole number, and {value!r} is not")


def _json(value: Any) -> str:
    import json

    return json.dumps(value)
