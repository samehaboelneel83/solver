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
    op: Literal["date_parts", "categories", "from_link", "formula", "linked_total"]
    #: The field read -- for `formula`, the name of the field made.
    field: str = Field(pattern=_NAME, max_length=63)
    #: For `from_link`: the number field of the linked kind to copy.
    of: str | None = Field(default=None, pattern=_NAME, max_length=63)
    #: For `formula`: the arithmetic over the record's number fields.
    formula: str | None = Field(default=None, max_length=500)
    #: For `linked_total`: the kind whose records link here, by which link field, and how to total.
    from_kind: str | None = Field(default=None, pattern=_NAME, max_length=63)
    link: str | None = Field(default=None, pattern=_NAME, max_length=63)
    how: Literal["count", "sum", "mean", "max", "min"] = "count"


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
    if body.op == "linked_total":
        return _linked_total(db, user, kind, fields, body)
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


def _linked_total(db: Session, user: UserAccount, kind: Any, fields: dict[str, dict[str, Any]], body: DeriveBody) -> dict[str, Any]:
    """Each record's count -- or the sum, mean, max or min of a number -- over the records of another kind
    that link to it: calls per district, demand per warehouse (benchmark, October 2026)."""
    if not body.from_kind or not body.link:
        raise HTTPException(422, "name the kind whose records link here (from_kind) and its link field (link)")
    source = db.execute(text("SELECT id FROM entity_type WHERE domain_id = (SELECT domain_id FROM entity_type WHERE id = :t)"
                             " AND name = :n"), {"t": kind["id"], "n": body.from_kind}).scalar_one_or_none()
    if source is None:
        raise HTTPException(422, f"there is no kind {body.from_kind!r}")
    theirs = _fields(db, source)
    link = theirs.get(body.link)
    target = db.execute(text("SELECT to_type_id FROM relationship_type WHERE id = :r"),
                        {"r": link["references_id"]}).scalar_one() if link and link["references_id"] else None
    if target is None or kind["id"] not in db.execute(text("SELECT unnest(entity_type_lineage(:t))"), {"t": target}).scalars().all() \
            and target != kind["id"]:
        raise HTTPException(422, f"{body.link} is not a link from {body.from_kind} to {kind['name']}")
    if body.how != "count" and (body.of is None or (theirs.get(body.of) or {}).get("data_type") not in ("number", "integer")):
        raise HTTPException(422, f"a {body.how} needs a number field of {body.from_kind} (of)")
    existing = fields.get(body.field)
    if existing is not None and existing["data_type"] not in ("number", "integer"):
        raise HTTPException(409, f"{body.field} already exists as a {existing['data_type']} field; choose another name")
    groups: dict[str, list[float]] = {}
    for (attrs,) in db.execute(text("SELECT attrs FROM entity WHERE active AND entity_type_id = ANY (entity_type_family(:t))"),
                               {"t": source}):
        attrs = attrs or {}
        to = attrs.get(body.link)
        if to in (None, ""):
            continue
        if body.how == "count":
            groups.setdefault(str(to), []).append(1.0)
        else:
            v = attrs.get(body.of)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                groups.setdefault(str(to), []).append(float(v))
    reduce = {"count": len, "sum": sum, "mean": lambda xs: sum(xs) / len(xs), "max": max, "min": min}[body.how]
    if existing is None:
        db.execute(text("INSERT INTO attribute_def (entity_type_id, name, data_type) VALUES (:t, :n, 'number')"),
                   {"t": kind["id"], "n": body.field})
    written = 0
    for entity_id, key in db.execute(text("SELECT id, key FROM entity WHERE entity_type_id = ANY (entity_type_family(:t))"),
                                     {"t": kind["id"]}):
        xs = groups.get(key, [])
        value = reduce(xs) if xs else (0.0 if body.how in ("count", "sum") else None)
        if value is None:
            continue
        db.execute(text("UPDATE entity SET attrs = attrs || jsonb_build_object(:f, CAST(:v AS numeric)) WHERE id = :id"),
                   {"f": body.field, "v": round(float(value), 9), "id": entity_id})
        written += 1
    audit.record(db, organization_id=user.organization_id, actor_id=user.id,
                 api_key_id=getattr(user, "api_key_id", None), action="entity_type.derive",
                 object_type="entity_type", object_id=kind["id"])
    db.commit()
    return {"made": [body.field], "records": written, "left_empty": 0}


# --- data values computed from records and other data values -------------------------------------


class DeriveValueBody(BaseModel):
    """A data value computed once from the records (benchmark, October 2026: suitability by soil and
    crop, and "not the crop grown last year", were worked out outside the app and uploaded):

    - `lookup`: `name[kind, ...]` = `source[kind's link, ...]` -- a parcel's suitability for each crop,
      read through the parcel's soil from `suitability[soil, crop]`;
    - `compare`: `name[kind, other]` = 1 where the kind's `field` is (`=`) or is not (`!=`) the other
      record -- its key, or its `against` field -- else 0: `rotation_ok[parcel, crop]`.
    """

    model_config = ConfigDict(extra="forbid")
    op: Literal["lookup", "compare"]
    name: str = Field(pattern=_NAME, max_length=63)
    kind: str = Field(pattern=_NAME, max_length=63)
    #: lookup: the kind's link field; compare: the kind's field compared.
    field: str = Field(pattern=_NAME, max_length=63)
    #: lookup: the data value read through the link.
    source: str | None = Field(default=None, pattern=_NAME, max_length=63)
    #: compare: the other kind, what of it is compared, and how.
    other: str | None = Field(default=None, pattern=_NAME, max_length=63)
    against: str = Field(default="key", max_length=63)
    compare: Literal["=", "!="] = "="

MAX_CELLS = 200_000


@router.post("/domains/{domain_id}/derive-value", status_code=201)
def derive_value(domain_id: int, body: DeriveValueBody, db: Session = Depends(get_db),
                 user: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    def kind_id(name: str) -> int:
        found = db.execute(text("SELECT id FROM entity_type WHERE domain_id = :d AND name = :n"), {"d": domain_id, "n": name}).scalar_one_or_none()
        if found is None:
            raise HTTPException(422, f"there is no kind {name!r}")
        return found

    if db.execute(text("SELECT 1 FROM parameter_def WHERE domain_id = :d AND name = :n"), {"d": domain_id, "n": body.name}).first():
        raise HTTPException(409, f"there is already a data value called {body.name!r}; choose another name")
    a = kind_id(body.kind)
    mine = _fields(db, a)
    records = db.execute(text("SELECT id, key, attrs FROM entity WHERE active AND entity_type_id = ANY (entity_type_family(:t))"
                              " ORDER BY sort_order, key"), {"t": a}).all()
    cells: list[tuple[list[int], float]] = []
    default = 0.0
    if body.op == "lookup":
        # Through a link field of the kind, or a relationship between the kinds (made from the map, or
        # imported) read from either end (benchmark re-test, October 2026: only link fields were offered).
        link = mine.get(body.field)
        targets: dict[int, list[int]] = {}
        if link and link["data_type"] == "reference" and link["references_id"]:
            b = db.execute(text("SELECT to_type_id FROM relationship_type WHERE id = :r"), {"r": link["references_id"]}).scalar_one()
            by_key = {k: i for i, k in db.execute(text("SELECT id, key FROM entity WHERE entity_type_id = ANY (entity_type_family(:t))"), {"t": b})}
            for entity_id, _key, attrs in records:
                through = by_key.get(str((attrs or {}).get(body.field)))
                if through is not None:
                    targets[entity_id] = [through]
        else:
            rel = db.execute(text(
                "SELECT id, from_type_id, to_type_id FROM relationship_type WHERE domain_id = :d AND name = :n"
                " AND (:a = ANY (entity_type_family(from_type_id)) OR from_type_id = ANY (entity_type_lineage(:a))"
                "      OR :a = ANY (entity_type_family(to_type_id)) OR to_type_id = ANY (entity_type_lineage(:a)))"),
                {"d": domain_id, "n": body.field, "a": a}).mappings().first()
            if rel is None:
                raise HTTPException(422, f"{body.field} is not a link field of {body.kind}, nor a link between {body.kind} and another kind")
            forward = a in db.execute(text("SELECT unnest(entity_type_family(:t))"), {"t": rel["from_type_id"]}).scalars().all() \
                or rel["from_type_id"] in db.execute(text("SELECT unnest(entity_type_lineage(:a))"), {"a": a}).scalars().all()
            b = rel["to_type_id"] if forward else rel["from_type_id"]
            mine_end, other_end = ("from_entity_id", "to_entity_id") if forward else ("to_entity_id", "from_entity_id")
            for x, y in db.execute(text(f"SELECT {mine_end}, {other_end} FROM relationship WHERE relationship_type_id = :r"), {"r": rel["id"]}):
                targets.setdefault(x, []).append(y)
        src = db.execute(text("SELECT id, index_type_ids, default_value FROM parameter_def WHERE domain_id = :d AND name = :n"),
                         {"d": domain_id, "n": body.source}).mappings().one_or_none()
        if src is None or not src["index_type_ids"] or src["index_type_ids"][0] != b:
            raise HTTPException(422, f"{body.source!r} is not a data value whose first index is the kind {body.field} links to")
        index = [a, *src["index_type_ids"][1:]]
        default = float(src["default_value"])
        rows: dict[int, list[tuple[list[int], float]]] = {}
        for ids, value in db.execute(text("SELECT entity_ids, value FROM parameter_value WHERE parameter_def_id = :p AND value IS NOT NULL"),
                                     {"p": src["id"]}):
            rows.setdefault(ids[0], []).append((list(ids[1:]), float(value)))
        for entity_id, _key, _attrs in records:
            # Several linked records (a cell in two districts): the mean of theirs.
            gathered: dict[tuple[int, ...], list[float]] = {}
            for through in targets.get(entity_id, []):
                for rest, value in rows.get(through, []):
                    gathered.setdefault(tuple(rest), []).append(value)
            for rest, values in gathered.items():
                cells.append(([entity_id, *rest], sum(values) / len(values)))
        how = {"op": "lookup", "through": body.field, "source": body.source}
    else:
        if body.field not in mine:
            raise HTTPException(422, f"{body.kind} has no field {body.field!r}")
        if not body.other:
            raise HTTPException(422, "name the other kind (other)")
        b = kind_id(body.other)
        others = db.execute(text("SELECT id, key, attrs FROM entity WHERE active AND entity_type_id = ANY (entity_type_family(:t))"
                                 " ORDER BY sort_order, key"), {"t": b}).all()
        if body.against != "key" and body.against not in _fields(db, b):
            raise HTTPException(422, f"{body.other} has no field {body.against!r}")
        if len(records) * len(others) > MAX_CELLS:
            raise HTTPException(422, f"{len(records) * len(others):,} cells is more than {MAX_CELLS:,}; narrow the kinds first")
        index = [a, b]
        for entity_id, _key, attrs in records:
            mine_value = (attrs or {}).get(body.field)
            for other_id, other_key, other_attrs in others:
                theirs = other_key if body.against == "key" else (other_attrs or {}).get(body.against)
                same = mine_value is not None and str(mine_value).strip().casefold() == str(theirs).strip().casefold()
                cells.append(([entity_id, other_id], 1.0 if same == (body.compare == "=") else 0.0))
        how = {"op": "compare", "field": body.field, "other": body.other, "against": body.against, "compare": body.compare}
    if len(cells) > MAX_CELLS:
        raise HTTPException(422, f"{len(cells):,} cells is more than {MAX_CELLS:,}")
    parameter_id = db.execute(text(
        "INSERT INTO parameter_def (domain_id, name, index_type_ids, default_value, source)"
        " VALUES (:d, :n, :i, :dv, CAST(:s AS jsonb)) RETURNING id"),
        {"d": domain_id, "n": body.name, "i": index, "dv": default, "s": json.dumps({"kind": "derived", **how})}).scalar_one()
    for ids, value in cells:
        db.execute(text("INSERT INTO parameter_value (parameter_def_id, entity_ids, value) VALUES (:p, :e, :v)"),
                   {"p": parameter_id, "e": ids, "v": value})
    audit.record(db, organization_id=user.organization_id, actor_id=user.id,
                 api_key_id=getattr(user, "api_key_id", None), action="parameter.derive",
                 object_type="parameter", object_id=parameter_id)
    db.commit()
    return {"parameter_id": parameter_id, "name": body.name, "cells": len(cells), "index": index}
