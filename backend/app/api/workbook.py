"""A whole domain's records as one Excel workbook: one sheet per kind of record.

    GET  /api/v1/domains/{id}/workbook          ?rows=true      the template (or the data)
    POST /api/v1/domains/{id}/workbook          ?dry_run=       (multipart `file`)

The one-kind upload (`bulk.py`) needs the kinds a file refers to already filled: regions before
depots, depots before trucks. A workbook brings them together, so this module puts them in order:

1. **Kinds first, then what refers to them.** A sheet is written after every sheet whose kind its
   reference fields name.
2. **References that cannot wait are deferred.** A reference to the same kind (a manager, a
   parent region) or one closing a circle between kinds can name a record that is further down
   the workbook. Those columns are left out of the first pass and written in a second pass,
   once every record exists.
3. **All or nothing.** Every sheet goes through the same checks as a one-kind upload -- each cell
   against its type, each row against the database's triggers in a savepoint -- inside one
   transaction, kept only if the whole workbook is clean; `dry_run` checks and keeps nothing.

Sheets named after no kind are reported as ignored; `about` (the template's notes) is skipped.
"""
from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import audit
from app.api.bulk import MAX_BYTES, MAX_ROWS, _entity_columns, entity_writer, write_rows
from app.api.deps import get_current_user, requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_domain import Entity, EntityType

router = APIRouter(prefix="/api/v1", tags=["bulk"])

#: Excel's limit on a sheet's name.
SHEET_NAME = 31
NOTES = "about"


def _kinds(db: Session, domain_id: int) -> list[EntityType]:
    return list(db.execute(select(EntityType).where(EntityType.domain_id == domain_id, EntityType.is_abstract.is_(False))
                           .order_by(EntityType.name)).scalars())


def _refers(db: Session, kinds: list[EntityType]) -> dict[int, dict[str, set[int]]]:
    """Per kind: each reference field (own or inherited) and the concrete kinds it may name."""
    ids = [k.id for k in kinds]
    out: dict[int, dict[str, set[int]]] = {k.id: {} for k in kinds}
    rows = db.execute(text(
        "SELECT k.id AS kind, ad.name, ARRAY(SELECT unnest(entity_type_family(rt.to_type_id))) AS targets"
        "  FROM entity_type k"
        "  JOIN attribute_def ad ON ad.entity_type_id = ANY(entity_type_lineage(k.id)) AND ad.data_type::text = 'reference'"
        "  JOIN relationship_type rt ON rt.id = ad.references_id"
        " WHERE k.id = ANY(:ids)"), {"ids": ids}).mappings()
    for r in rows:
        out[r["kind"]][r["name"]] = set(r["targets"]) & set(ids)
    return out


def plan(kind_ids: list[int], refers: dict[int, dict[str, set[int]]]) -> tuple[list[int], dict[int, set[str]]]:
    """An order to write the kinds in, and per kind the reference fields to write in a second pass.

    Depth-first over "refers to": a kind is placed after the kinds its fields name. A field naming
    its own kind, or a kind still being placed (a circle), is deferred instead of followed."""
    order: list[int] = []
    deferred: dict[int, set[str]] = {k: set() for k in kind_ids}
    state: dict[int, str] = {}

    def visit(k: int) -> None:
        state[k] = "placing"
        for field, targets in sorted(refers.get(k, {}).items()):
            for t in sorted(targets):
                if t == k or state.get(t) == "placing":
                    deferred[k].add(field)
                elif t not in state:
                    visit(t)
        state[k] = "placed"
        order.append(k)

    for k in kind_ids:
        if k not in state:
            visit(k)
    # A field is written in the first pass only if every kind it names is already written by then.
    position = {k: i for i, k in enumerate(order)}
    for k in kind_ids:
        for field, targets in refers.get(k, {}).items():
            if any(position[t] >= position[k] for t in targets):
                deferred[k].add(field)
    return order, deferred


def _sheet_for(kind: EntityType, names: list[str]) -> str | None:
    for n in names:
        if n == kind.name or (len(kind.name) > SHEET_NAME and n == kind.name[:SHEET_NAME]):
            return n
    return None


def _read_book(upload: UploadFile) -> dict[str, tuple[list[str], list[list[Any]]]]:
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"the file is over {MAX_BYTES // (1024 * 1024)} MB; split it")
    from openpyxl import load_workbook

    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 -- any unreadable workbook is the same answer
        raise HTTPException(422, "the file is not a readable .xlsx workbook") from exc
    sheets: dict[str, tuple[list[str], list[list[Any]]]] = {}
    total = 0
    for sheet in book.worksheets:
        table = [list(r) for r in sheet.iter_rows(values_only=True)]
        while table and all(v is None or str(v).strip() == "" for v in table[-1]):
            table.pop()
        if not table:
            continue
        total += len(table) - 1
        sheets[sheet.title] = ([str(h).strip() if h is not None else "" for h in table[0]], table[1:])
    if total > MAX_ROWS:
        raise HTTPException(413, f"at most {MAX_ROWS:,} rows per workbook; split it")
    return sheets


def _project(header: list[str], rows: list[list[Any]], keep: list[str]) -> tuple[list[str], list[list[Any]]]:
    at = [header.index(h) for h in keep]
    return keep, [[r[i] if i < len(r) else None for i in at] for r in rows]


@router.get("/domains/{domain_id}/workbook")
def workbook_template(domain_id: int, rows: bool = False, db: Session = Depends(get_db),
                      _: UserAccount = Depends(get_current_user)) -> Response:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    kinds = _kinds(db, domain_id)
    if not kinds:
        raise HTTPException(404, "this domain has no kinds of record to fill")
    by_id = {k.id: k for k in kinds}
    refers = _refers(db, kinds)
    order, deferred = plan([k.id for k in kinds], refers)
    book = Workbook()
    book.remove(book.active)
    notes: list[list[Any]] = []
    for kid in order:
        kind = by_id[kid]
        columns, attributes = _entity_columns(db, kind)
        sheet = book.create_sheet(kind.name[:SHEET_NAME])
        sheet.append([c.name for c in columns])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        if rows:
            for e in db.execute(select(Entity).where(Entity.entity_type_id == kid).order_by(Entity.sort_order, Entity.key)).scalars():
                sheet.append([e.key, e.label, e.sort_order, e.active, *[(e.attrs or {}).get(a.name) for a in attributes]])
        for c in columns:
            names = sorted(by_id[t].name for t in refers[kid].get(c.name, set()))
            notes.append([kind.name, c.name, c.kind, "yes" if c.required else "", ", ".join(c.values or []),
                          ", ".join(names), "second pass" if c.name in deferred[kid] else "", c.note])
    about = book.create_sheet(NOTES)
    about.append(["sheet", "column", "type", "required", "allowed values", "refers to", "written", "note"])
    for cell in about[1]:
        cell.font = Font(bold=True)
    for n in notes:
        about.append(n)
    out = io.BytesIO()
    book.save(out)
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="records.xlsx"'})


@router.post("/domains/{domain_id}/workbook")
def workbook_upload(domain_id: int, request: Request, file: UploadFile = File(...), dry_run: bool = Query(False),
                    db: Session = Depends(get_db), user: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    kinds = _kinds(db, domain_id)
    if not kinds:
        raise HTTPException(404, "this domain has no kinds of record to fill")
    by_id = {k.id: k for k in kinds}
    book = _read_book(file)
    matched = {k.id: s for k in kinds if (s := _sheet_for(k, list(book)))}
    ignored = [s for s in book if s not in matched.values() and s != NOTES]
    refers = _refers(db, kinds)
    order, deferred = plan([k for k in matched], {k: {f: t & set(matched) for f, t in v.items()} for k, v in refers.items() if k in matched})

    reports: dict[int, dict[str, Any]] = {}
    for kid in order:
        header, rows = book[matched[kid]]
        first = [h for h in header if h not in deferred[kid]]
        h1, r1 = _project(header, rows, first)
        columns, write = entity_writer(db, by_id[kid], h1)
        written, faults, bad = write_rows(db, h1, r1, columns, write)
        reports[kid] = {"sheet": matched[kid], "kind": by_id[kid].name, "rows": len(rows), "written": written,
                        "faults": faults, "bad": bad, "second_pass": sorted(deferred[kid] & set(header))}
    for kid in order:
        later = [h for h in (deferred[kid] & set(book[matched[kid]][0]))]
        if not later:
            continue
        header, rows = book[matched[kid]]
        h2, r2 = _project(header, rows, ["key", *sorted(later)])
        columns, write = entity_writer(db, by_id[kid], h2)
        _, faults, bad = write_rows(db, h2, r2, columns, write)
        report = reports[kid]
        # A row refused in the first pass is refused again here only for want of itself: say it once.
        report["faults"] += [f for f in faults if f.row not in report["bad"]]
        report["bad"] |= bad

    total_faults = sum(len(r["faults"]) for r in reports.values())
    keep = not dry_run and total_faults == 0
    if keep:
        audit.write(db, user, request, action="bulk.workbook", object_type="domain", object_id=domain_id,
                    after={"sheets": [r["sheet"] for r in reports.values()], "rows": sum(r["written"] for r in reports.values())})
        db.commit()
    else:
        db.rollback()
    sheets = [{"sheet": r["sheet"], "kind": r["kind"], "rows": r["rows"],
               "written": r["written"] if keep else 0, "second_pass": r["second_pass"],
               "faults": [f.model_dump() for f in r["faults"][:500]]}
              for r in (reports[k] for k in order)]
    return {"ok": total_faults == 0, "dry_run": dry_run, "kept": keep, "order": [by_id[k].name for k in order],
            "sheets": sheets, "ignored": ignored}
