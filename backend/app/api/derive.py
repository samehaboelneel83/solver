"""Number fields made from other fields, for a predictor or a model to read (benchmark, October 2026).

A predictor learns from number fields of one kind, and a rule reads number fields too. Four of five
testers had what they needed in another shape: a weather or soil *text*, a *date*, a number on a
*linked* record (an observation's road, a yield's parcel). This makes it numbers, once, on the
records themselves -- plain fields anyone can see, change and use:

- `date_parts`: from a date field, `<field>_weekday` (Monday 0), `<field>_month`, `<field>_day_of_year`;
- `categories`: from a text or choice field, one 0/1 field per value (`<field>_<value>`), at most 12;
- `from_link`: from a link field and a number field of the linked kind, `<link>_<field>`;
- `formula`: a number field computed from the record's own number fields, with + - * / and
  brackets -- `volume_vph / capacity_vph`, `length_km / speed_kmh * 60` -- a ratio a model reads as
  data (benchmark, October 2026: formulas could not divide).

    POST /api/v1/entity-types/{id}/derive   {"op": "date_parts", "field": "date"}
"""

from __future__ import annotations

import ast
import json
import operator
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
    op: Literal["date_parts", "categories", "from_link", "formula"]
    #: The field read -- for `formula`, the name of the field made.
    field: str = Field(pattern=_NAME, max_length=63)
    #: For `from_link`: the number field of the linked kind to copy.
    of: str | None = Field(default=None, pattern=_NAME, max_length=63)
    #: For `formula`: the arithmetic over the record's number fields.
    formula: str | None = Field(default=None, max_length=500)


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
    if body.op == "formula":
        return _formula_field(db, user, kind, fields, body)
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


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _parsed(formula: str, numbers: set[str]) -> ast.AST:
    """The formula's tree, holding only numbers, the kind's number fields, + - * / and brackets."""
    try:
        tree = ast.parse(formula, mode="eval").body
    except SyntaxError as exc:
        raise HTTPException(422, f"the formula does not read as arithmetic: {exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in numbers:
            raise HTTPException(422, f"{node.id!r} is not a number field of this kind ({', '.join(sorted(numbers)) or 'none'})")
        if not isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Name, ast.Constant, ast.Load, ast.USub, ast.UAdd, *_OPS)):
            raise HTTPException(422, "a formula holds number fields, numbers, + - * / and brackets only")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise HTTPException(422, "a formula holds number fields, numbers, + - * / and brackets only")
    return tree


def _value(node: ast.AST, row: dict[str, Any]) -> float | None:
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        v = row.get(node.id)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    if isinstance(node, ast.UnaryOp):
        inner = _value(node.operand, row)
        return None if inner is None else (-inner if isinstance(node.op, ast.USub) else inner)
    assert isinstance(node, ast.BinOp)
    a, b = _value(node.left, row), _value(node.right, row)
    if a is None or b is None or (isinstance(node.op, ast.Div) and b == 0):
        return None
    return _OPS[type(node.op)](a, b)


def _formula_field(db: Session, user: UserAccount, kind: Any, fields: dict[str, dict[str, Any]], body: DeriveBody) -> dict[str, Any]:
    if not body.formula or not body.formula.strip():
        raise HTTPException(422, "write the formula, e.g. volume_vph / capacity_vph")
    existing = fields.get(body.field)
    if existing is not None and existing["data_type"] not in ("number", "integer"):
        raise HTTPException(409, f"{body.field} already exists as a {existing['data_type']} field; choose another name")
    numbers = {n for n, f in fields.items() if f["data_type"] in ("number", "integer") and n != body.field}
    tree = _parsed(body.formula, numbers)
    if existing is None:
        db.execute(text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, :n, 'number')"),
                   {"t": kind["id"], "n": body.field})
    written, empty = 0, []
    for entity_id, key, attrs in db.execute(text(
            "SELECT id, key, attrs FROM entity WHERE entity_type_id = ANY (entity_type_family(:t))"), {"t": kind["id"]}):
        value = _value(tree, dict(attrs or {}))
        if value is None:
            empty.append(key)
            continue
        db.execute(text("UPDATE entity SET attrs = attrs || jsonb_build_object(:f, CAST(:v AS numeric)) WHERE id = :id"),
                   {"f": body.field, "v": round(value, 9), "id": entity_id})
        written += 1
    audit.record(db, organization_id=user.organization_id, actor_id=user.id,
                 api_key_id=getattr(user, "api_key_id", None), action="entity_type.derive",
                 object_type="entity_type", object_id=kind["id"])
    db.commit()
    return {"made": [body.field], "records": written, "left_empty": len(empty), "empty": empty[:20]}
