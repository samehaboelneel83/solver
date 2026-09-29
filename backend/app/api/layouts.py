"""Graph layouts saved on the server (OAAS plan §7.3, follow-up).

    GET    /api/v1/problems/{id}/graph-layout   -> {"positions": {...}, "updated_at"} (empty when none)
    PUT    /api/v1/problems/{id}/graph-layout   {"positions": {card id: {"x", "y"}}}
    DELETE /api/v1/problems/{id}/graph-layout

Where a person put the cards of a problem's Visual Graph, so the arrangement
follows them to another browser. Presentation only: it never touches the IR,
a version or a draft, so no revision check guards it -- the last arrangement
saved is the arrangement. One per person and problem, like a draft: a
colleague arranges their own, and nobody else reads it.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.problems import _get_problem
from app.api.validation import field_error
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["layouts"])

#: The browser keeps at most this many cards too (`graphLayout.ts`).
MAX_CARDS = 2000
MAX_ID = 300
#: Far beyond any canvas; a guard against nonsense, not a layout rule.
MAX_COORDINATE = 1e7


class LayoutSave(BaseModel):
    positions: dict[str, dict[str, Any]]


class LayoutRead(BaseModel):
    positions: dict[str, dict[str, float]]
    updated_at: datetime | None


def _checked(positions: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    if len(positions) > MAX_CARDS:
        raise field_error("positions", f"a layout places at most {MAX_CARDS} cards; this one has {len(positions)}", None)
    out: dict[str, dict[str, float]] = {}
    for card, point in positions.items():
        if not card or len(card) > MAX_ID:
            raise field_error("positions", f"a card id is 1 to {MAX_ID} characters", card[:40])
        x, y = point.get("x"), point.get("y")
        if set(point) != {"x", "y"} or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= MAX_COORDINATE
            for v in (x, y)
        ):
            raise field_error("positions", f"card {card!r} is placed at finite numbers {{x, y}}", card[:40])
        out[card] = {"x": float(x), "y": float(y)}  # type: ignore[arg-type]
    return out


@router.get("/problems/{problem_id}/graph-layout")
def get_layout(
    problem_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> LayoutRead:
    _get_problem(db, problem_id)
    row = db.execute(
        text("SELECT positions, updated_at FROM graph_layout WHERE problem_id = :p AND owner_id = :o"),
        {"p": problem_id, "o": user.id},
    ).mappings().one_or_none()
    if row is None:
        return LayoutRead(positions={}, updated_at=None)
    return LayoutRead.model_validate(dict(row))


@router.put("/problems/{problem_id}/graph-layout")
def save_layout(
    problem_id: int,
    payload: LayoutSave,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> LayoutRead:
    _get_problem(db, problem_id)
    positions = _checked(payload.positions)
    if not positions:
        db.execute(text("DELETE FROM graph_layout WHERE problem_id = :p AND owner_id = :o"),
                   {"p": problem_id, "o": user.id})
        db.commit()
        return LayoutRead(positions={}, updated_at=None)
    row = db.execute(
        text(
            "INSERT INTO graph_layout (problem_id, owner_id, positions) VALUES (:p, :o, CAST(:pos AS jsonb))"
            " ON CONFLICT (problem_id, owner_id) DO UPDATE SET positions = EXCLUDED.positions"
            " RETURNING positions, updated_at"
        ),
        {"p": problem_id, "o": user.id, "pos": json.dumps(positions)},
    ).mappings().one()
    db.commit()
    return LayoutRead.model_validate(dict(row))


@router.delete("/problems/{problem_id}/graph-layout", status_code=204)
def delete_layout(
    problem_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
) -> Response:
    _get_problem(db, problem_id)
    db.execute(text("DELETE FROM graph_layout WHERE problem_id = :p AND owner_id = :o"),
               {"p": problem_id, "o": user.id})
    db.commit()
    return Response(status_code=204)
