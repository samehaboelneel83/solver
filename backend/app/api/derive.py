"""Number fields made from other fields, for a predictor or a model to read (benchmark, October 2026).

A predictor learns from number fields of one kind, and a rule reads number fields too. Four of five
testers had what they needed in another shape: a weather or soil *text*, a *date*, a number on a
*linked* record (an observation's road, a yield's parcel). This makes it numbers, once, on the
records themselves -- plain fields anyone can see, change and use:

- `date_parts`: from a date field, `<field>_weekday` (Monday 0), `<field>_month`, `<field>_day_of_year`;
- `categories`: from a text or choice field, one 0/1 field per value (`<field>_<value>`), at most 12;
- `from_link`: from a link field and a number field of the linked kind, `<link>_<field>`.

    POST /api/v1/entity-types/{id}/derive   {"op": "date_parts", "field": "date"}
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import requires
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["entity-types"])

MAX_CATEGORIES = 12
_NAME = r"^[a-z][a-z0-9_]*$"


class DeriveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["date_parts", "categories", "from_link"]
    field: str = Field(pattern=_NAME, max_length=63)
    #: For `from_link`: the number field of the linked kind to copy.
    of: str | None = Field(default=None, pattern=_NAME, max_length=63)


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_") or "blank"


def _fields(db: Session, type_id: int) -> dict[str, dict[str, Any]]:
    return {r.name: dict(r._mapping) for r in db.execute(text(
        "SELECT name, data_type::text AS data_type, references_id FROM attribute_def"
        " WHERE entity_type_id = ANY (entity_type_lineage(:t))"), {"t": type_id})}


@router.post("/entity-types/{entity_type_id}/derive")
def derive(entity_type_id: int, body: DeriveBody, db: Session = Depends(get_db),
           user: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    kind = db.execute(text("SELECT id, name FROM entity_type WHERE id = :t"), {"t": entity_type_id}).mappings().one_or_none()
    if kind is None:
        raise HTTPException(404, "entity type not found")
    fields = _fields(db, entity_type_id)
    source = fields.get(body.field)
    if source is None:
        raise HTTPException(422, f"{kind['name']} has no field {body.field!r}")
    records = db.execute(text("SELECT id, key, attrs FROM entity WHERE entity_type_id = ANY (entity_type_family(:t))"),
                         {"t": entity_type_id}).all()
    values: dict[int, dict[str, float]] = {}
    made: list[str] = []

    if body.op == "date_parts":
        if source["data_type"] not in ("date", "datetime", "text"):
            raise HTTPException(422, f"{body.field} is a {source['data_type']} field, not a date")
        made = [f"{body.field}_weekday", f"{body.field}_month", f"{body.field}_day_of_year"]
        for entity_id, _key, attrs in records:
            raw = (attrs or {}).get(body.field)
            try:
                day = date.fromisoformat(str(raw)[:10])
            except (TypeError, ValueError):
                continue
            values[entity_id] = dict(zip(made, (day.weekday(), day.month, day.timetuple().tm_yday)))
    elif body.op == "categories":
        if source["data_type"] not in ("text", "enum", "boolean"):
            raise HTTPException(422, f"{body.field} is a {source['data_type']} field; categories come from text or a choice")
        seen = sorted({str((attrs or {}).get(body.field)) for _, _, attrs in records
                       if (attrs or {}).get(body.field) not in (None, "")}, key=_slug)
        if len(seen) > MAX_CATEGORIES:
            raise HTTPException(422, f"{body.field} has {len(seen)} different values; at most {MAX_CATEGORIES} become fields")
        names = {v: f"{body.field}_{_slug(v)}" for v in seen}
        made = list(dict.fromkeys(names.values()))
        for entity_id, _key, attrs in records:
            raw = (attrs or {}).get(body.field)
            if raw in (None, ""):
                continue
            values[entity_id] = {n: 1.0 if names[str(raw)] == n else 0.0 for n in made}
    else:
        if source["data_type"] != "reference" or source["references_id"] is None:
            raise HTTPException(422, f"{body.field} is not a link to another record")
        if not body.of:
            raise HTTPException(422, "name the linked record's number field to copy (of)")
        target = db.execute(text("SELECT to_type_id FROM relationship_type WHERE id = :r"),
                            {"r": source["references_id"]}).scalar_one()
        linked = _fields(db, target).get(body.of)
        if linked is None or linked["data_type"] not in ("number", "integer", "boolean"):
            raise HTTPException(422, f"the linked kind has no number field {body.of!r}")
        lookup = {key: (attrs or {}).get(body.of) for key, attrs in db.execute(text(
            "SELECT key, attrs FROM entity WHERE entity_type_id = ANY (entity_type_family(:t))"), {"t": target})}
        made = [f"{body.field}_{body.of}"]
        for entity_id, _key, attrs in records:
            v = lookup.get(str((attrs or {}).get(body.field)))
            if isinstance(v, bool):
                v = 1.0 if v else 0.0
            if isinstance(v, (int, float)):
                values[entity_id] = {made[0]: float(v)}

    clash = [n for n in made if n in fields and fields[n]["data_type"] not in ("number", "integer")]
    if clash:
        raise HTTPException(409, f"{', '.join(clash)} already exist as fields of another type; rename them first")
    for name in made:
        if name not in fields:
            db.execute(text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, :n, 'number')"),
                       {"t": entity_type_id, "n": name})
    for entity_id, extra in values.items():
        db.execute(text("UPDATE entity SET attrs = attrs || CAST(:a AS jsonb) WHERE id = :id"),
                   {"a": json.dumps(extra), "id": entity_id})
    audit.record(db, organization_id=user.organization_id, actor_id=user.id,
                 api_key_id=getattr(user, "api_key_id", None), action="entity_type.derive",
                 object_type="entity_type", object_id=entity_type_id)
    db.commit()
    return {"made": made, "records": len(values), "left_empty": len(records) - len(values)}
