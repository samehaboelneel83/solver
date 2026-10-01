"""Time as ordinary data, for rosters and schedules (improvement plan 5.2).

    POST /api/v1/domains/{id}/time/too-close   {name, type_id, start_field, end_field?, duration_field?,
                                                day_field?, min_gap_hours}

Labour rules -- "at least 10 hours of rest between shifts", "no two overlapping tasks" -- are rules
about *pairs* of time slots. This reads each record's start and end from its own fields and links
every pair that overlaps or leaves less than `min_gap_hours` between them, as a relationship from a
kind to itself (each pair once, earlier to later, with the gap in hours on the link). A rule then
says "no one takes both ends of a too_close link" (the `rest_between` rule shape), for any problem:
nurses, drivers, operators, machines, rooms.

Where a time comes from, per record, without knowing what the records are:

- **start**: a `time` field ("06:00"), or a number of hours (6, 30.5);
- **day** (optional): a `date` field (YYYY-MM-DD) or a whole-number day (1, 2, 3) -- added as 24 h a day;
- **end**: a `time` field (an end at or before the start runs past midnight), a number of hours,
  or a **duration** in hours added to the start.

A record whose start or end cannot be read is listed, never guessed. Writing again replaces the links.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.api.deps import requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_domain import AttributeDef, EntityType, Relationship, RelationshipType

router = APIRouter(prefix="/api/v1", tags=["time"])

FIELD = r"^[A-Za-z_][A-Za-z0-9_]*$"
MAX_RECORDS = 20_000


class TooCloseBody(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=63)
    type_id: int
    start_field: str = Field(pattern=FIELD)
    end_field: str | None = Field(default=None, pattern=FIELD)
    duration_field: str | None = Field(default=None, pattern=FIELD)
    day_field: str | None = Field(default=None, pattern=FIELD)
    min_gap_hours: float = Field(ge=0, le=24 * 31)

    @model_validator(mode="after")
    def _one_end(self) -> "TooCloseBody":
        if (self.end_field is None) == (self.duration_field is None):
            raise ValueError("say where a slot ends: an end_field or a duration_field, one of them")
        return self


def hours_of(value: Any) -> float | None:
    """A time of day ("06:30" -> 6.5) or a number of hours; None when it is neither."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text_value = str(value).strip()
    try:
        return float(text_value)
    except ValueError:
        pass
    parts = text_value.split(":")
    if 2 <= len(parts) <= 3 and all(p.isdigit() for p in parts):
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) == 3 else 0
        return h + m / 60 + s / 3600
    return None


def day_hours(value: Any, origin: date | None) -> float | None:
    """A day as hours from the first day: a date (YYYY-MM-DD) or a whole-number day."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) * 24
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        number = hours_of(value)
        return None if number is None else number * 24
    return float((d - (origin or d)).days * 24)


def slots(rows: list[dict[str, Any]], body: TooCloseBody) -> tuple[list[tuple[int, str, float, float]], list[str]]:
    """(entity id, key, start h, end h) for every record whose times read; the keys of those that do not."""
    origin = None
    if body.day_field:
        dates = []
        for r in rows:
            try:
                dates.append(date.fromisoformat(str(r["attrs"].get(body.day_field))[:10]))
            except ValueError:
                pass
        origin = min(dates) if dates else None
    out, unread = [], []
    for r in rows:
        attrs = r["attrs"] or {}
        start = hours_of(attrs.get(body.start_field))
        base = 0.0
        if body.day_field:
            base_or_none = day_hours(attrs.get(body.day_field), origin)
            if base_or_none is None:
                unread.append(r["key"])
                continue
            base = base_or_none
        if start is None:
            unread.append(r["key"])
            continue
        if body.duration_field:
            length = hours_of(attrs.get(body.duration_field))
            if length is None or length < 0:
                unread.append(r["key"])
                continue
            end = start + length
        else:
            end = hours_of(attrs.get(body.end_field))
            if end is None:
                unread.append(r["key"])
                continue
            if end <= start and isinstance(attrs.get(body.end_field), str) and ":" in str(attrs.get(body.end_field)):
                end += 24  # a night shift: 22:00 to 06:00
        out.append((r["id"], r["key"], base + start, base + end))
    return out, unread


def too_close(items: list[tuple[int, str, float, float]], min_gap: float) -> list[tuple[int, int, float]]:
    """Each pair (earlier, later, gap h) that overlaps (gap < 0) or leaves less than `min_gap` hours."""
    ordered = sorted(items, key=lambda s: (s[2], s[3], s[0]))
    pairs = []
    for i, (a_id, _, _a_start, a_end) in enumerate(ordered):
        for b_id, _, b_start, _b_end in ordered[i + 1:]:
            gap = b_start - a_end
            if gap >= min_gap:
                break  # sorted by start, so every later slot leaves a wider gap still
            pairs.append((a_id, b_id, round(gap, 2)))
    return pairs


@router.post("/domains/{domain_id}/time/too-close", status_code=201)
def make_too_close(domain_id: int, body: TooCloseBody, db: Session = Depends(get_db),
                   _: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    kind = db.execute(select(EntityType).where(EntityType.domain_id == domain_id,
                                               EntityType.id == body.type_id)).scalar_one_or_none()
    if kind is None:
        raise HTTPException(422, f"type_id {body.type_id} is not a kind of record in this workspace")
    fields = {a.name for a in db.execute(select(AttributeDef).where(AttributeDef.entity_type_id == kind.id)).scalars()}
    asked = [f for f in (body.start_field, body.end_field, body.duration_field, body.day_field) if f]
    unknown = [f for f in asked if f not in fields]
    if unknown:
        raise HTTPException(422, f"{kind.name} has no field {', '.join(unknown)}; it has {', '.join(sorted(fields)) or 'none'}")
    rows = [dict(r) for r in db.execute(text("SELECT id, key, attrs FROM entity WHERE entity_type_id = :t"),
                                        {"t": kind.id}).mappings()]
    if len(rows) > MAX_RECORDS:
        raise HTTPException(422, f"{len(rows)} {kind.name} records is more than {MAX_RECORDS} to compare at once")
    items, unread = slots(rows, body)
    pairs = too_close(items, body.min_gap_hours)
    source = {"kind": "too_close", "of": kind.name, "min_gap_hours": body.min_gap_hours, "links": len(pairs),
              "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              **({"unread": unread[:200]} if unread else {})}
    rel = db.execute(select(RelationshipType).where(RelationshipType.domain_id == domain_id,
                                                    RelationshipType.name == body.name)).scalar_one_or_none()
    if rel is not None and (rel.from_type_id, rel.to_type_id) != (kind.id, kind.id):
        raise HTTPException(409, f"{body.name!r} is already a relationship between other kinds; choose another name")
    if rel is None:
        rel = RelationshipType(domain_id=domain_id, name=body.name, from_type_id=kind.id, to_type_id=kind.id,
                               cardinality="many_to_many", source=source)
        db.add(rel)
        db.flush()
        db.add(AttributeDef(relationship_type_id=rel.id, name="gap_h", data_type="number", unit="h"))
    else:
        rel.source = source
        db.execute(delete(Relationship).where(Relationship.relationship_type_id == rel.id))
    if pairs:
        db.execute(pg_insert(Relationship).values([
            {"relationship_type_id": rel.id, "from_entity_id": a, "to_entity_id": b, "attrs": {"gap_h": gap}}
            for a, b, gap in pairs]))
    db.commit()
    return {"relationship_type_id": rel.id, "links": len(pairs), "records": len(items), "unread": unread[:200],
            "source": source}
