"""The data workbench: a domain's records as one tree, read lazily.

    GET /api/v1/domains/{id}/workbench/schema                which kind nests under which, and the roots
    GET /api/v1/domains/{id}/workbench/children ?group=&parent=&q=&limit=&offset=
    GET /api/v1/domains/{id}/workbench/groups   ?parent=     a record's child groups, with counts
    GET /api/v1/domains/{id}/workbench/search   ?q=          records of any kind, with the path above each
    GET /api/v1/domains/{id}/workbench/problems              record id -> what the quality checks say of it
    GET /api/v1/entities/{id}/values                         this record's parameter cells

**What nests under what** is read from the model, never configured:

- a reference field on kind C naming kind T puts C's records under the T record they name
  (`group = "ref:<attribute id>"`; the parent is the mirror relationship's `to` end);
- a hierarchy relationship type puts its `to` records under its `from` record
  (`group = "rel:<relationship type id>"`).

A **root kind** has no reference field naming another kind and is the `to` end of no hierarchy
over another kind. The tree's top shows each root kind, and each other kind's records that have
no parent at all ("not placed"), as `group = "root:<kind id>"`: records of the kind with no parent
through any nesting edge of that kind.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["workbench"])

MAX_PATH = 20


def _domain(db: Session, domain_id: int) -> None:
    if db.execute(text("SELECT 1 FROM domain WHERE id = :d"), {"d": domain_id}).first() is None:
        raise HTTPException(404, "domain not found")


def edges(db: Session, domain_id: int) -> list[dict[str, Any]]:
    """Every nesting edge of the domain: child kind, parent kind, how, and the relationship type
    that holds it (`child_end` is the relationship column naming the child)."""
    refs = db.execute(text(
        "SELECT 'ref:' || ad.id AS group_key, ad.entity_type_id AS child_kind, rt.to_type_id AS parent_kind,"
        "       ad.name AS field, ad.required, rt.id AS relationship_type_id, 'from_entity_id' AS child_end"
        "  FROM attribute_def ad JOIN entity_type t ON t.id = ad.entity_type_id"
        "  JOIN relationship_type rt ON rt.id = ad.references_id"
        " WHERE t.domain_id = :d AND ad.data_type::text = 'reference' ORDER BY ad.required DESC, ad.name"),
        {"d": domain_id}).mappings().all()
    rels = db.execute(text(
        "SELECT 'rel:' || rt.id AS group_key, rt.to_type_id AS child_kind, rt.from_type_id AS parent_kind,"
        "       rt.name AS field, false AS required, rt.id AS relationship_type_id, 'to_entity_id' AS child_end"
        "  FROM relationship_type rt WHERE rt.domain_id = :d AND rt.is_hierarchy ORDER BY rt.name"),
        {"d": domain_id}).mappings().all()
    return [dict(r) for r in [*refs, *rels]]


def _parent_end(edge: dict[str, Any]) -> str:
    return "to_entity_id" if edge["child_end"] == "from_entity_id" else "from_entity_id"


@router.get("/domains/{domain_id}/workbench/schema")
def schema(domain_id: int, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    _domain(db, domain_id)
    kinds = [dict(r) for r in db.execute(text(
        "SELECT t.id, t.name, t.is_abstract, t.inherited_from,"
        "       (SELECT count(*) FROM entity e WHERE e.entity_type_id = t.id) AS count"
        "  FROM entity_type t WHERE t.domain_id = :d ORDER BY t.name"), {"d": domain_id}).mappings()]
    all_edges = edges(db, domain_id)
    lineage = {k["id"]: set(db.execute(text("SELECT unnest(entity_type_lineage(:t))"), {"t": k["id"]}).scalars()) for k in kinds}

    def nests_elsewhere(kind_id: int) -> bool:
        return any(e["child_kind"] in lineage[kind_id] and e["parent_kind"] not in lineage[kind_id] for e in all_edges)

    roots = [k["id"] for k in kinds if not k["is_abstract"] and not nests_elsewhere(k["id"])]
    return {"domain_id": domain_id, "kinds": kinds, "edges": all_edges, "roots": roots}


def _unplaced_filter(kind_edges: list[dict[str, Any]]) -> str:
    """SQL: the entity `e` has no parent through any of these edges."""
    parts = [f"NOT EXISTS (SELECT 1 FROM relationship r WHERE r.relationship_type_id = {int(edge['relationship_type_id'])}"
             f" AND r.{edge['child_end']} = e.id)" for edge in kind_edges]
    return " AND ".join(parts) or "TRUE"


def _child_counts(db: Session, domain_id: int, ids: list[int]) -> dict[int, int]:
    """How many records sit directly under each of these records, across every nesting edge."""
    if not ids:
        return {}
    counts: dict[int, int] = {i: 0 for i in ids}
    for edge in edges(db, domain_id):
        rows = db.execute(text(
            f"SELECT {_parent_end(edge)} AS parent, count(*) FROM relationship"
            f" WHERE relationship_type_id = :rt AND {_parent_end(edge)} = ANY(:ids) GROUP BY 1"),
            {"rt": edge["relationship_type_id"], "ids": ids}).all()
        for parent, n in rows:
            counts[parent] += n
    return counts


def _page(db: Session, domain_id: int, where: str, params: dict[str, Any], q: str | None, limit: int, offset: int) -> dict[str, Any]:
    if q:
        where += " AND (e.key ILIKE :q OR e.label ILIKE :q)"
        params = {**params, "q": "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"}
    total = db.execute(text(f"SELECT count(*) FROM entity e WHERE {where}"), params).scalar_one()
    rows = [dict(r) for r in db.execute(text(
        f"SELECT e.id, e.entity_type_id, e.key, e.label, e.sort_order, e.active, e.attrs, e.updated_at FROM entity e"
        f" WHERE {where} ORDER BY e.sort_order, e.key, e.id LIMIT :lim OFFSET :off"),
        {**params, "lim": limit, "off": offset}).mappings()]
    counts = _child_counts(db, domain_id, [r["id"] for r in rows])
    for r in rows:
        r["children"] = counts.get(r["id"], 0)
    return {"items": rows, "total": total}


@router.get("/domains/{domain_id}/workbench/children")
def children(domain_id: int, group: str, parent: int | None = None, q: str | None = None,
             limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
             db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    _domain(db, domain_id)
    how, _sep, raw = group.partition(":")
    if not raw.isdigit() or how not in ("root", "ref", "rel"):
        raise HTTPException(422, "group is root:<kind id>, ref:<attribute id> or rel:<relationship type id>")
    all_edges = edges(db, domain_id)
    if how == "root":
        kind = int(raw)
        lineage = set(db.execute(text("SELECT unnest(entity_type_lineage(:t))"), {"t": kind}).scalars())
        own = [e for e in all_edges if e["child_kind"] in lineage]
        return _page(db, domain_id, f"e.entity_type_id = ANY(entity_type_family({kind})) AND {_unplaced_filter(own)}", {}, q, limit, offset)
    edge = next((e for e in all_edges if e["group_key"] == group), None)
    if edge is None:
        raise HTTPException(404, "no such group in this domain")
    if parent is None:
        raise HTTPException(422, "a ref: or rel: group needs the parent record")
    where = (f"e.id IN (SELECT r.{edge['child_end']} FROM relationship r"
             f" WHERE r.relationship_type_id = :rt AND r.{_parent_end(edge)} = :p)")
    return _page(db, domain_id, where, {"rt": edge["relationship_type_id"], "p": parent}, q, limit, offset)


@router.get("/domains/{domain_id}/workbench/groups")
def groups(domain_id: int, parent: int, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    """The kinds of record that can sit under this one, each with how many do."""
    _domain(db, domain_id)
    me = db.execute(text("SELECT id, entity_type_id FROM entity WHERE id = :e"), {"e": parent}).mappings().one_or_none()
    if me is None:
        raise HTTPException(404, "entity not found")
    lineage = set(db.execute(text("SELECT unnest(entity_type_lineage(:t))"), {"t": me["entity_type_id"]}).scalars())
    names = dict(db.execute(text("SELECT id, name FROM entity_type WHERE domain_id = :d"), {"d": domain_id}).all())
    out = []
    for edge in edges(db, domain_id):
        if edge["parent_kind"] not in lineage:
            continue
        n = db.execute(text(f"SELECT count(*) FROM relationship WHERE relationship_type_id = :rt AND {_parent_end(edge)} = :p"),
                       {"rt": edge["relationship_type_id"], "p": parent}).scalar_one()
        out.append({"group": edge["group_key"], "kind_id": edge["child_kind"], "kind": names.get(edge["child_kind"]),
                    "field": edge["field"], "via": "reference" if edge["group_key"].startswith("ref:") else "hierarchy",
                    "required": edge["required"], "count": n})
    return {"parent": parent, "groups": out}


def path_above(db: Session, domain_id: int, entity_id: int) -> list[dict[str, Any]]:
    """The chain of parents, nearest last, each with the group it was reached through."""
    all_edges = edges(db, domain_id)
    chain: list[dict[str, Any]] = []
    seen = {entity_id}
    here = entity_id
    for _ in range(MAX_PATH):
        kind = db.execute(text("SELECT entity_type_id FROM entity WHERE id = :e"), {"e": here}).scalar_one()
        lineage = set(db.execute(text("SELECT unnest(entity_type_lineage(:t))"), {"t": kind}).scalars())
        step = None
        for edge in (e for e in all_edges if e["child_kind"] in lineage):
            up = db.execute(text(f"SELECT {_parent_end(edge)} FROM relationship WHERE relationship_type_id = :rt"
                                 f" AND {edge['child_end']} = :e LIMIT 1"), {"rt": edge["relationship_type_id"], "e": here}).scalar()
            if up is not None and up not in seen:
                step = (up, edge["group_key"])
                break
        if step is None:
            break
        up, via = step
        row = dict(db.execute(text("SELECT id, key, label, entity_type_id FROM entity WHERE id = :e"), {"e": up}).mappings().one())
        chain.insert(0, {**row, "child_group": via})
        seen.add(up)
        here = up
    return chain


@router.get("/domains/{domain_id}/workbench/search")
def search(domain_id: int, q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50),
           db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    _domain(db, domain_id)
    needle = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = [dict(r) for r in db.execute(text(
        "SELECT e.id, e.key, e.label, e.entity_type_id, t.name AS kind FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
        " WHERE t.domain_id = :d AND (e.key ILIKE :q OR e.label ILIKE :q)"
        " ORDER BY (lower(e.key) = lower(:exact)) DESC, t.name, e.key LIMIT :lim"),
        {"d": domain_id, "q": needle, "exact": q, "lim": limit}).mappings()]
    for r in rows:
        r["path"] = path_above(db, domain_id, r["id"])
    return {"items": rows}


@router.get("/domains/{domain_id}/workbench/problems")
def problems(domain_id: int, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    """Record id -> the codes the domain's quality checks list it under (all records, not a sample)."""
    from app.api import data_checks

    _domain(db, domain_id)
    findings = data_checks.recursive_checks(db, domain_id, 10, sample=None) + data_checks.reference_checks(db, domain_id, sample=None)
    out: dict[int, list[str]] = {}
    for f in findings:
        if f["severity"] == "info":
            continue
        for r in f["records"]:
            out.setdefault(r["id"], []).append(f["code"])
    return {"domain_id": domain_id, "records": {str(k): sorted(set(v)) for k, v in out.items()}}


@router.get("/entities/{entity_id}/values")
def entity_values(entity_id: int, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    """Every parameter this record indexes, with its cells that name it. A parameter over this kind
    alone has one cell -- the record's own value -- and can be edited in place."""
    me = db.execute(text("SELECT id, entity_type_id FROM entity WHERE id = :e"), {"e": entity_id}).mappings().one_or_none()
    if me is None:
        raise HTTPException(404, "entity not found")
    params = db.execute(text(
        "SELECT pd.id, pd.name, pd.unit, pd.default_value, pd.index_type_ids, pd.value_type_id,"
        "       ARRAY(SELECT t.name FROM unnest(pd.index_type_ids) WITH ORDINALITY u(id, n)"
        "             JOIN entity_type t ON t.id = u.id ORDER BY u.n) AS index_kinds"
        "  FROM parameter_def pd"
        " WHERE EXISTS (SELECT 1 FROM unnest(pd.index_type_ids) x WHERE x = ANY(entity_type_lineage(:t)))"
        " ORDER BY cardinality(pd.index_type_ids), pd.name"), {"t": me["entity_type_id"]}).mappings().all()
    out = []
    for p in params:
        cells = [dict(c) for c in db.execute(text(
            "SELECT pv.entity_ids,"
            "       ARRAY(SELECT e.key FROM unnest(pv.entity_ids) WITH ORDINALITY u(id, n) JOIN entity e ON e.id = u.id ORDER BY u.n) AS keys,"
            "       pv.value, (SELECT key FROM entity WHERE id = pv.value_entity_id) AS value_key, pv.updated_at"
            "  FROM parameter_value pv WHERE pv.parameter_def_id = :p AND :e = ANY(pv.entity_ids) ORDER BY 2 LIMIT 200"),
            {"p": p["id"], "e": entity_id}).mappings()]
        for c in cells:
            c["value"] = float(c["value"]) if c["value"] is not None else None
        out.append({"parameter_id": p["id"], "name": p["name"], "unit": p["unit"], "index_kinds": list(p["index_kinds"]),
                    "default_value": float(p["default_value"]) if p["default_value"] is not None else None,
                    "entity_valued": p["value_type_id"] is not None,
                    "single": len(p["index_type_ids"]) == 1, "cells": cells})
    return {"entity_id": entity_id, "parameters": out}
