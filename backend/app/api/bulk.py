"""Download templates and bulk uploads (queue R21), for any entity type, relationship
type and parameter.

    GET  /api/v1/entity-types/{id}/template        ?format=csv|xlsx&rows=
    POST /api/v1/entity-types/{id}/upload          ?clean_only=&dry_run=   (multipart `file`)
    GET  /api/v1/relationship-types/{id}/template
    POST /api/v1/relationship-types/{id}/upload
    GET  /api/v1/parameters/{id}/template
    POST /api/v1/parameters/{id}/upload

A template carries the right columns -- an entity's key, label, sort order,
active and each attribute (its own and inherited); an edge's from and to keys,
its dates and its attributes; a parameter's one column per index plus value --
and, as XLSX, an `about` sheet saying each column's type, whether it is
required and its allowed values. `rows=true` fills it with what is stored
(a parameter's template always lists every cell of its index), so a file
can go out, be edited and come back.

An upload checks every row -- each value against its column's type here,
then each row against the database's own triggers inside a savepoint -- and
reports each fault by row and column. Nothing is written unless the whole
file is clean, or (`clean_only`) the clean rows are; `dry_run` checks and
writes nothing. The triggers stay the one place the rules live: this module
parses cells so that "must be a number" can name its row, and leaves every
other rule to them.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from itertools import product
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import audit
from app.api.deps import get_current_user, requires
from app.core.db import get_db
from app.crud.db_errors import translate_db_error
from app.models.iam import UserAccount
from app.models.v1_domain import (
    ATTRIBUTE_ORDER,
    AttributeDef,
    Entity,
    EntityType,
    ParameterDef,
    ParameterValue,
    Relationship,
    RelationshipType,
)

router = APIRouter(prefix="/api/v1", tags=["bulk"])

#: The most rows one file may carry, and the largest file read.
MAX_ROWS = 100_000
MAX_BYTES = 20 * 1024 * 1024
#: The most cells a parameter's full template lists.
MAX_TEMPLATE_CELLS = 100_000
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Fault(BaseModel):
    row: int
    column: str | None
    message: str


class UploadReport(BaseModel):
    ok: bool
    rows: int
    written: int
    skipped: int
    dry_run: bool
    faults: list[Fault]


# --- columns -----------------------------------------------------------------


class Column:
    def __init__(self, name: str, kind: str, *, required: bool = False, values: list[str] | None = None,
                 note: str = "", structural: bool = False) -> None:
        self.name, self.kind, self.required, self.values, self.note = name, kind, required, values, note
        # A structural column (a key, an end, an index) is in every file; an attribute's is
        # optional -- an update may carry only the columns it changes, and the trigger
        # still refuses a new row that lacks a required value.
        self.structural = structural


def _attributes(db: Session, *, entity_type_id: int | None = None, relationship_type_id: int | None = None) -> list[AttributeDef]:
    if relationship_type_id is not None:
        where = AttributeDef.relationship_type_id == relationship_type_id
    else:
        where = AttributeDef.entity_type_id == func.any(func.entity_type_lineage(entity_type_id))
    return list(db.execute(select(AttributeDef).where(where).order_by(*ATTRIBUTE_ORDER)).scalars())


def _attribute_columns(attributes: list[AttributeDef]) -> list[Column]:
    return [
        Column(a.name, a.data_type, required=a.required, values=list(a.enum_values or []) or None,
               note=(f"unit {a.unit}" if a.unit else "") + ("; key of an entity it refers to" if a.data_type == "reference" else ""))
        for a in attributes
    ]


def _parse(kind: str, raw: Any, values: list[str] | None) -> tuple[Any, str | None]:
    """A cell as the value its column's type stores, or why it is not one. `None` is empty."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None, None
    if isinstance(raw, str) and "\x00" in raw:
        return None, "holds a NUL character, which no value may"
    if kind in ("integer", "number"):
        if isinstance(raw, bool):
            return None, "must be a number"
        try:
            number = Decimal(str(raw).strip())
        except InvalidOperation:
            return None, f"must be {'a whole number' if kind == 'integer' else 'a number'}, not {raw!r}"
        if not number.is_finite():
            return None, "must be a finite number"
        if kind == "integer":
            if number % 1 != 0:
                return None, f"must be a whole number, not {raw!r}"
            return int(number), None
        return (int(number) if number % 1 == 0 else float(number)), None
    if kind == "boolean":
        if isinstance(raw, bool):
            return raw, None
        word = str(raw).strip().lower()
        if word in ("true", "yes", "y", "1"):
            return True, None
        if word in ("false", "no", "n", "0"):
            return False, None
        return None, f"must be true or false (yes or no), not {raw!r}"
    if kind == "date":
        if isinstance(raw, datetime):
            return raw.date().isoformat(), None
        if isinstance(raw, date):
            return raw.isoformat(), None
        word = str(raw).strip()
        try:
            if not _DATE_RE.match(word):
                raise ValueError(word)
            date.fromisoformat(word)
        except ValueError:
            return None, f"must be a date, YYYY-MM-DD, not {raw!r}"
        return word, None
    if kind == "time":
        if isinstance(raw, time):
            return raw.strftime("%H:%M"), None
        if isinstance(raw, datetime):
            return raw.strftime("%H:%M"), None
        word = str(raw).strip()
        if not _TIME_RE.match(word):
            return None, f"must be a time of day, HH:MM, not {raw!r}"
        return word, None
    if kind == "geometry":
        from app.spatial.geometry import validate_geometry

        try:
            shape = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return None, "must be GeoJSON, such as {\"type\": \"Point\", \"coordinates\": [31.2, 30.0]}"
        fault = validate_geometry(shape)
        return (None, fault) if fault else (shape, None)
    # A spreadsheet stores 101 as a number; as a key or a text it is "101", not "101.0".
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    word = raw.isoformat() if isinstance(raw, (date, datetime)) else str(raw)
    word = word.strip() if kind != "text" else word
    if kind == "enum" and word not in (values or []):
        return None, f"must be one of {', '.join(values or [])}, not {word!r}"
    return word, None


# --- files ---------------------------------------------------------------------


def _read(upload: UploadFile) -> tuple[list[str], list[list[Any]]]:
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"the file is over {MAX_BYTES // (1024 * 1024)} MB; split it")
    name = (upload.filename or "").lower()
    if name.endswith(".xlsx") or data[:2] == b"PK":
        from openpyxl import load_workbook

        try:
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 -- any unreadable workbook is the same answer
            raise HTTPException(422, "the file is not a readable .xlsx workbook") from exc
        sheet = book["data"] if "data" in book.sheetnames else book.worksheets[0]
        table = [list(row) for row in sheet.iter_rows(values_only=True)]
    else:
        try:
            decoded = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(422, "the file is neither UTF-8 CSV nor .xlsx") from exc
        table = [list(row) for row in csv.reader(io.StringIO(decoded))]
    while table and all(v is None or str(v).strip() == "" for v in table[-1]):
        table.pop()
    if not table:
        raise HTTPException(422, "the file is empty: the first row names the columns")
    if len(table) - 1 > MAX_ROWS:
        raise HTTPException(413, f"at most {MAX_ROWS:,} rows per file; split it")
    header = [str(h).strip() if h is not None else "" for h in table[0]]
    return header, table[1:]


def _check_header(header: list[str], columns: list[Column]) -> list[Fault]:
    known = {c.name for c in columns}
    faults = [Fault(row=1, column=h or f"column {i + 1}", message="is not a column of this template")
              for i, h in enumerate(header) if h not in known]
    faults += [Fault(row=1, column=h, message="appears more than once") for h in {h for h in header if header.count(h) > 1}]
    faults += [Fault(row=1, column=c.name, message="is required and missing")
               for c in columns if c.structural and c.name not in header]
    return faults


def _file(name: str, columns: list[Column], rows: list[list[Any]], fmt: str) -> Response:
    if fmt == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font

        book = Workbook()
        sheet = book.active
        sheet.title = "data"
        sheet.append([c.name for c in columns])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append([json.dumps(v) if isinstance(v, (dict, list)) else v for v in row])
        about = book.create_sheet("about")
        about.append(["column", "type", "required", "allowed values", "note"])
        for cell in about[1]:
            cell.font = Font(bold=True)
        for c in columns:
            about.append([c.name, c.kind, "yes" if c.required else "", ", ".join(c.values or []), c.note])
        out = io.BytesIO()
        book.save(out)
        return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    out_text = io.StringIO()
    writer = csv.writer(out_text)
    writer.writerow([c.name for c in columns])
    for row in rows:
        writer.writerow(["" if v is None else json.dumps(v) if isinstance(v, (dict, list)) else
                         ("true" if v is True else "false" if v is False else v) for v in row])
    return Response("﻿" + out_text.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


def write_rows(db: Session, header: list[str], rows: list[list[Any]], columns: list[Column], write_row,
               *, first_row: int = 2) -> tuple[int, list[Fault], set[int]]:
    """Parse each row and write it inside a savepoint; nothing is committed here. Returns the rows
    written, the faults and the numbers of the rows that had any. Several files (a workbook's
    sheets) can share one transaction this way."""
    faults = _check_header(header, columns)
    if faults:
        return 0, faults, set(range(first_row, first_row + len(rows)))
    kinds = {c.name: c for c in columns}
    written = 0
    bad_rows: set[int] = set()
    for offset, raw in enumerate(rows):
        number = offset + first_row  # the header is row 1
        if all(v is None or str(v).strip() == "" for v in raw):
            continue
        values: dict[str, Any] = {}
        row_faults = []
        for i, name in enumerate(header):
            column = kinds[name]
            value, fault = _parse(column.kind, raw[i] if i < len(raw) else None, column.values)
            if fault:
                row_faults.append(Fault(row=number, column=name, message=fault))
            elif value is None and column.required:
                row_faults.append(Fault(row=number, column=name, message="is required"))
            else:
                values[name] = value
        if not row_faults:
            savepoint = db.begin_nested()
            try:
                problem = write_row(values)
                if problem:
                    row_faults.append(Fault(row=number, column=problem[0], message=problem[1]))
                    savepoint.rollback()
                else:
                    db.flush()
                    savepoint.commit()
            except DBAPIError as exc:
                savepoint.rollback()
                http = translate_db_error(exc, "bulk upload")
                detail = http.detail
                if isinstance(detail, list) and detail:
                    loc = detail[0].get("loc") or []
                    row_faults.append(Fault(row=number, column=str(loc[-1]) if len(loc) > 1 else None,
                                            message=str(detail[0].get("msg"))))
                else:
                    row_faults.append(Fault(row=number, column=None, message=str(detail)))
        if row_faults:
            faults += row_faults
            bad_rows.add(number)
        else:
            written += 1
    return written, faults, bad_rows


def run_rows(db: Session, header: list[str], rows: list[list[Any]], columns: list[Column], write_row,
         clean_only: bool, dry_run: bool, *, user=None, request=None, audit_object: tuple[str, Any] | None = None,
         before_commit=None) -> UploadReport:
    """Parse each row, write it inside a savepoint, and keep or undo the lot."""
    header_faults = _check_header(header, columns)
    if header_faults:
        return UploadReport(ok=False, rows=len(rows), written=0, skipped=len(rows), dry_run=dry_run, faults=header_faults)
    written, faults, bad_rows = write_rows(db, header, rows, columns, write_row)
    keep = not dry_run and (not faults or clean_only)
    if keep:
        if user is not None and audit_object is not None and written:
            ot, oid = audit_object
            audit.write(
                db, user, request,
                action="bulk.upload",
                object_type=ot,
                object_id=oid,
                after={"rows": written, "faults": len(faults), "clean_only": clean_only},
            )
        if before_commit is not None:
            # In the same transaction as the rows: an import's lineage row (Epic UX, U-4).
            before_commit(written)
        db.commit()
    else:
        db.rollback()
    return UploadReport(ok=not faults, rows=len(rows), written=written if keep else 0,
                        skipped=len(bad_rows) if keep else len(rows), dry_run=dry_run, faults=faults[:1000])


# --- entity types ----------------------------------------------------------------


def _entity_columns(db: Session, entity_type: EntityType) -> tuple[list[Column], list[AttributeDef]]:
    attributes = _attributes(db, entity_type_id=entity_type.id)
    return [
        Column("key", "text", required=True, structural=True, note="unique within the type; how a model names the entity"),
        Column("label", "text", note="shown instead of the key"),
        Column("sort_order", "integer", note="lower first"),
        Column("active", "boolean", note="false leaves it out of every run"),
        *_attribute_columns(attributes),
    ], attributes


def _get(db: Session, model, id_: int, what: str):
    row = db.get(model, id_)
    if row is None:
        raise HTTPException(404, f"{what} not found")
    return row


def entity_writer(db: Session, entity_type: EntityType, header: list[str]):
    """The columns of an entity type and the function that writes one parsed row of it:
    shared by a file upload and a database import (Epic UX, U-4), so both meet the same checks."""
    columns, attributes = _entity_columns(db, entity_type)
    names = {a.name for a in attributes}
    seen: set[str] = set()

    def write(values: dict[str, Any]):
        key = values["key"]
        if key in seen:
            return "key", f"{key!r} appears earlier in this file"
        seen.add(key)
        found = db.execute(select(Entity).where(Entity.entity_type_id == entity_type.id, Entity.key == key)).scalar_one_or_none()
        attrs = dict(found.attrs or {}) if found else {}
        for name in names & set(header):
            if values.get(name) is None:
                attrs.pop(name, None)
            else:
                attrs[name] = values[name]
        if found is None:
            found = Entity(entity_type_id=entity_type.id, key=key, attrs=attrs)
            db.add(found)
        else:
            found.attrs = attrs
        if "label" in header:
            found.label = values.get("label")
        if values.get("sort_order") is not None:
            found.sort_order = values["sort_order"]
        if values.get("active") is not None:
            found.active = values["active"]
        return None

    return columns, write


@router.get("/entity-types/{entity_type_id}/template")
def entity_template(entity_type_id: int, format: str = Query("csv", pattern="^(csv|xlsx)$"), rows: bool = False,
                    db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> Response:
    entity_type = _get(db, EntityType, entity_type_id, "entity type")
    columns, attributes = _entity_columns(db, entity_type)
    body: list[list[Any]] = []
    if rows:
        for e in db.execute(select(Entity).where(Entity.entity_type_id == entity_type.id)
                            .order_by(Entity.sort_order, Entity.key)).scalars():
            body.append([e.key, e.label, e.sort_order, e.active, *[(e.attrs or {}).get(a.name) for a in attributes]])
    return _file(entity_type.name, columns, body, format)


_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def add_new_fields(db: Session, entity_type: EntityType, header: list[str], rows: list[list[Any]]) -> list[str]:
    """Columns the type has no field for become fields, typed from their own values (the same
    reading a spreadsheet start uses). Only names a field may have; anything else stays a fault.
    Inside the upload's transaction, so a dry run or a refused file leaves the type as it was."""
    from app.api.start import infer

    known = {c.name for c in _entity_columns(db, entity_type)[0]}
    added = []
    for i, name in enumerate(header):
        if name in known or not _FIELD_NAME.match(name or "") or header.count(name) > 1:
            continue
        values = [r[i] for r in rows if i < len(r) and r[i] is not None and str(r[i]).strip() != ""]
        data_type, choices = infer(values)
        db.add(AttributeDef(entity_type_id=entity_type.id, name=name, data_type=data_type, enum_values=choices))
        added.append(name)
    if added:
        db.flush()
    return added


@router.post("/entity-types/{entity_type_id}/upload")
def entity_upload(entity_type_id: int, request: Request, file: UploadFile = File(...), clean_only: bool = False,
                  dry_run: bool = False, add_fields: bool = False, db: Session = Depends(get_db),
                  user: UserAccount = Depends(requires("domain.edit"))) -> UploadReport:
    """`add_fields`: a column the type has no field for becomes a new field instead of a fault."""
    entity_type = _get(db, EntityType, entity_type_id, "entity type")
    if entity_type.is_abstract:
        raise HTTPException(422, f"{entity_type.name!r} is abstract and holds no entities of its own")
    header, rows = _read(file)
    if add_fields:
        add_new_fields(db, entity_type, header, rows)
    columns, write = entity_writer(db, entity_type, header)
    return run_rows(db, header, rows, columns, write, clean_only, dry_run,
                user=user, request=request, audit_object=("entity_type", entity_type_id))


# --- relationship types ------------------------------------------------------------


def _relationship_columns(db: Session, rel: RelationshipType) -> tuple[list[Column], list[AttributeDef]]:
    attributes = _attributes(db, relationship_type_id=rel.id)
    names = {t.id: t.name for t in db.execute(select(EntityType).where(EntityType.id.in_([rel.from_type_id, rel.to_type_id]))).scalars()}
    return [
        Column("from", "text", required=True, structural=True, note=f"key of a {names.get(rel.from_type_id)}"),
        Column("to", "text", required=True, structural=True, note=f"key of a {names.get(rel.to_type_id)}"),
        Column("valid_from", "date"),
        Column("valid_to", "date"),
        *_attribute_columns(attributes),
    ], attributes


def _mirror(db: Session, rel: RelationshipType) -> None:
    owner = db.execute(select(AttributeDef.name).where(AttributeDef.references_id == rel.id)).scalar_one_or_none()
    if owner is not None:
        raise HTTPException(409, f"{rel.name!r} is the reference attribute {owner!r}; upload it with the entities")


def _keyed(db: Session, type_id: int) -> dict[str, list[int]]:
    """Key -> the ids of the entities of that type's family bearing it."""
    found: dict[str, list[int]] = {}
    for eid, key in db.execute(text("SELECT id, key FROM entity WHERE entity_type_id = ANY (entity_type_family(:t))"),
                               {"t": type_id}).all():
        found.setdefault(key, []).append(eid)
    return found


def _resolve(index: dict[str, list[int]], key: str, what: str) -> tuple[int | None, str | None]:
    ids = index.get(key, [])
    if not ids:
        return None, f"no {what} has the key {key!r}"
    if len(ids) > 1:
        return None, f"{len(ids)} entities of the {what} family have the key {key!r}; it is ambiguous"
    return ids[0], None


@router.get("/relationship-types/{relationship_type_id}/template")
def relationship_template(relationship_type_id: int, format: str = Query("csv", pattern="^(csv|xlsx)$"), rows: bool = False,
                          db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> Response:
    rel = _get(db, RelationshipType, relationship_type_id, "relationship type")
    columns, attributes = _relationship_columns(db, rel)
    body: list[list[Any]] = []
    if rows:
        for a, b, valid_from, valid_to, attrs in db.execute(text(
                "SELECT ef.key, et.key, r.valid_from, r.valid_to, r.attrs FROM relationship r "
                "JOIN entity ef ON ef.id = r.from_entity_id JOIN entity et ON et.id = r.to_entity_id "
                "WHERE r.relationship_type_id = :t ORDER BY ef.key, et.key"), {"t": rel.id}).all():
            body.append([a, b, valid_from.isoformat() if valid_from else None,
                         valid_to.isoformat() if valid_to else None,
                         *[(attrs or {}).get(x.name) for x in attributes]])
    return _file(rel.name, columns, body, format)


def relationship_writer(db: Session, rel: RelationshipType, header: list[str]):
    """The columns of a relationship type and the function that writes one parsed row of it:
    shared by a file upload and a database import, as `entity_writer`."""
    columns, attributes = _relationship_columns(db, rel)
    names = {a.name for a in attributes}
    froms, tos = _keyed(db, rel.from_type_id), _keyed(db, rel.to_type_id)
    seen: set[tuple[int, int]] = set()

    def write(values: dict[str, Any]):
        a, fault = _resolve(froms, values["from"], "from end")
        if fault:
            return "from", fault
        b, fault = _resolve(tos, values["to"], "to end")
        if fault:
            return "to", fault
        if (a, b) in seen:
            return "to", f"{values['from']} -> {values['to']} appears earlier in this file"
        seen.add((a, b))
        found = db.execute(select(Relationship).where(Relationship.relationship_type_id == rel.id,
                                                      Relationship.from_entity_id == a,
                                                      Relationship.to_entity_id == b)).scalar_one_or_none()
        attrs = dict(found.attrs or {}) if found else {}
        for name in names & set(header):
            if values.get(name) is None:
                attrs.pop(name, None)
            else:
                attrs[name] = values[name]
        if found is None:
            found = Relationship(relationship_type_id=rel.id, from_entity_id=a, to_entity_id=b, attrs=attrs)
            db.add(found)
        else:
            found.attrs = attrs
        for when in ("valid_from", "valid_to"):
            if when in header:
                setattr(found, when, date.fromisoformat(values[when]) if values.get(when) else None)
        return None

    return columns, write


@router.post("/relationship-types/{relationship_type_id}/upload")
def relationship_upload(relationship_type_id: int, request: Request, file: UploadFile = File(...),
                        clean_only: bool = False, dry_run: bool = False, db: Session = Depends(get_db),
                        user: UserAccount = Depends(requires("domain.edit"))) -> UploadReport:
    rel = _get(db, RelationshipType, relationship_type_id, "relationship type")
    _mirror(db, rel)
    header, rows = _read(file)
    columns, write = relationship_writer(db, rel, header)
    return run_rows(db, header, rows, columns, write, clean_only, dry_run,
                user=user, request=request, audit_object=("relationship_type", relationship_type_id))


# --- parameters ----------------------------------------------------------------------


def _parameter_columns(db: Session, parameter: ParameterDef) -> tuple[list[Column], list[str]]:
    names = {t.id: t.name for t in db.execute(select(EntityType).where(
        EntityType.id.in_([*parameter.index_type_ids, *([parameter.value_type_id] if parameter.value_type_id else [])]))).scalars()}
    index_names = [names.get(t, f"type_{t}") for t in parameter.index_type_ids]
    # A type that indexes twice (distance[site, site]) gets its position.
    heads = [f"{n}_{i + 1}" if index_names.count(n) > 1 else n for i, n in enumerate(index_names)]
    value = (Column("value", "text", note=f"key of a {names.get(parameter.value_type_id)}; empty for none")
             if parameter.value_type_id else
             Column("value", "number", note=f"empty for the default, {parameter.default_value}"
                    + (f"; unit {parameter.unit}" if parameter.unit else "")))
    return [*[Column(h, "text", required=True, structural=True, note=f"key of a {n}") for h, n in zip(heads, index_names)],
            value], heads


@router.get("/parameters/{parameter_id}/template")
def parameter_template(parameter_id: int, format: str = Query("csv", pattern="^(csv|xlsx)$"),
                       db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> Response:
    """Every cell of the index, each with its stored value or empty."""
    parameter = _get(db, ParameterDef, parameter_id, "parameter")
    columns, _heads = _parameter_columns(db, parameter)
    axes = [list(db.execute(select(Entity.id, Entity.key).where(Entity.entity_type_id == t)
                            .order_by(Entity.sort_order, Entity.key)).all()) for t in parameter.index_type_ids]
    total = 1
    for axis in axes:
        total *= len(axis)
    if total > MAX_TEMPLATE_CELLS:
        raise HTTPException(413, f"{total:,} cells is more than one template lists ({MAX_TEMPLATE_CELLS:,})")
    stored = {tuple(r.entity_ids): r for r in db.execute(
        select(ParameterValue.entity_ids, ParameterValue.value, ParameterValue.value_entity_id)
        .where(ParameterValue.parameter_def_id == parameter.id)).all()}
    keys = dict(db.execute(select(Entity.id, Entity.key).where(
        Entity.id.in_([r.value_entity_id for r in stored.values() if r.value_entity_id]))).all()) if stored else {}
    body = []
    for combo in product(*axes):
        cell = stored.get(tuple(e.id for e in combo))
        value = None
        if cell is not None:
            value = keys.get(cell.value_entity_id) if cell.value_entity_id else (
                int(cell.value) if cell.value % 1 == 0 else float(cell.value))
        body.append([*[e.key for e in combo], value])
    return _file(parameter.name, columns, body, format)


def parameter_writer(db: Session, parameter: ParameterDef):
    """The columns of a parameter (one per index, then `value`) and the function that
    writes one parsed cell: shared by a file upload and a database import."""
    columns, heads = _parameter_columns(db, parameter)
    axes = [_keyed(db, t) for t in parameter.index_type_ids]
    of = _keyed(db, parameter.value_type_id) if parameter.value_type_id else None
    seen: set[tuple[int, ...]] = set()

    def write(values: dict[str, Any]):
        ids = []
        for head, axis in zip(heads, axes):
            eid, fault = _resolve(axis, values[head], head)
            if fault:
                return head, fault
            ids.append(eid)
        if tuple(ids) in seen:
            return heads[-1], "this cell appears earlier in this file"
        seen.add(tuple(ids))
        where = (ParameterValue.parameter_def_id == parameter.id) & (ParameterValue.entity_ids == ids)
        raw = values.get("value")
        if raw is None:
            db.execute(delete(ParameterValue).where(where))  # the default, or no entity
            return None
        if of is not None:
            eid, fault = _resolve(of, str(raw), "value")
            if fault:
                return "value", fault
            cell = {"value": None, "value_entity_id": eid}
        else:
            cell = {"value": Decimal(str(raw)), "value_entity_id": None}
        upsert = insert(ParameterValue).values(parameter_def_id=parameter.id, entity_ids=ids, **cell)
        db.execute(upsert.on_conflict_do_update(
            index_elements=[ParameterValue.parameter_def_id, ParameterValue.entity_ids],
            set_={"value": upsert.excluded.value, "value_entity_id": upsert.excluded.value_entity_id}))
        if of is None and cell["value"] == parameter.default_value:
            db.execute(delete(ParameterValue).where(where))  # sparse: the default is not stored
        return None

    return columns, write


@router.post("/parameters/{parameter_id}/upload")
def parameter_upload(parameter_id: int, request: Request, file: UploadFile = File(...), clean_only: bool = False,
                     dry_run: bool = False, db: Session = Depends(get_db),
                     user: UserAccount = Depends(requires("domain.edit"))) -> UploadReport:
    parameter = _get(db, ParameterDef, parameter_id, "parameter")
    header, rows = _read(file)
    columns, write = parameter_writer(db, parameter)
    return run_rows(db, header, rows, columns, write, clean_only, dry_run,
                user=user, request=request, audit_object=("parameter", parameter_id))
