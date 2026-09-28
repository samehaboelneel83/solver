"""A run's expected duration (Epic ML, `app.ml.eta`).

    GET /api/v1/runs/{run_id}/eta

A settled run answers with the time it took. A run that has compiled (its
fingerprint is recorded) is estimated from the organization's own settled
runs by a random forest; one that has not compiled yet, or an organization
with too few settled runs, gets no number and a reason instead of a guess.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.ml import eta
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["runs"])

_USABLE = (
    " FROM run WHERE organization_id = :o AND finished_at IS NOT NULL AND wall_time_s IS NOT NULL"
    " AND reused_from IS NULL AND params ? 'fingerprint' AND id <> :r"
)


def _limit(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@router.get("/runs/{run_id}/eta")
def run_eta(
    run_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    run = db.execute(
        text(
            "SELECT id, status, solver, wall_time_s, finished_at, started_at,"
            " params -> 'fingerprint' AS fingerprint, params ->> 'time_limit_s' AS time_limit,"
            " extract(epoch FROM (now() - started_at)) AS elapsed"
            " FROM run WHERE id = :r AND organization_id = :o"
        ),
        {"r": run_id, "o": user.organization_id},
    ).mappings().one_or_none()
    if run is None:
        raise HTTPException(404, "Run not found")
    if run["finished_at"] is not None:
        return {"run_id": run_id, "settled": True, "seconds": run["wall_time_s"], "estimate_seconds": None}
    base = {"run_id": run_id, "settled": False, "elapsed_seconds": run["elapsed"], "estimate_seconds": None}
    if not run["fingerprint"]:
        return {**base, "reason": "the run has not compiled yet; its size is known once it has"}
    params = {"o": user.organization_id, "r": run_id}
    count = db.execute(text("SELECT count(*)" + _USABLE), params).scalar_one()

    def load() -> list[tuple[dict[str, Any], str, float | None, float]]:
        rows = db.execute(
            text(
                "SELECT params -> 'fingerprint', solver, params ->> 'time_limit_s', wall_time_s"
                + _USABLE + " ORDER BY id DESC LIMIT :n"
            ),
            {**params, "n": eta.MAX_RUNS},
        ).all()
        return [(fp or {}, solver, _limit(limit), float(seconds)) for fp, solver, limit, seconds in rows]

    model = eta.model_for(str(user.organization_id), int(count), load)
    if model is None:
        return {
            **base,
            "reason": f"estimates start once {eta.MIN_RUNS} runs have settled here; {count} have",
        }
    found = model.estimate(run["fingerprint"], run["solver"], _limit(run["time_limit"]))
    return {
        **base,
        "estimate_seconds": round(found.seconds, 3),
        "low_seconds": round(found.low, 3),
        "high_seconds": round(found.high, 3),
        "based_on_runs": found.based_on,
        "range_is": "the spread of the forest's trees (10th to 90th percentile), not a calibrated interval",
    }
