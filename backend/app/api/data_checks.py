"""A domain's data checked as a whole: recursive relationships and reference fields.

    GET /api/v1/domains/{domain_id}/data-checks?max_depth=10

The database refuses a bad row one at a time (types, cardinality, a loop in a hierarchy, a
required field left empty). What it cannot see is the shape of the data together:

- `loop` (error) -- records whose chain comes back to itself. Refused in a hierarchy, but a
  self-referencing reference field or an ordinary self-relationship can hold one.
- `too_deep` (warning) -- records more than `max_depth` levels below the top of their tree.
- `outside_tree` (warning) -- records of a nested kind with neither parent nor children, when
  the rest of their kind is placed in the tree.
- `inactive_target` (warning) -- a reference naming a record that is switched off: a solve
  leaves inactive records out, so the reference points at nothing there.
- `empty_reference` (info) -- an optional reference left empty on some records.

Each finding lists up to `SAMPLE` records by key, with the total.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["domains"])

SAMPLE = 50


def loops(edges: list[tuple[int, int]]) -> list[list[int]]:
    """Groups of records that reach each other (strongly connected, more than one record, or
    one record pointing at itself) -- iterative Tarjan, so a long chain cannot overflow."""
    graph: dict[int, list[int]] = defaultdict(list)
    for a, b in edges:
        graph[a].append(b)
        graph.setdefault(b, [])
    index: dict[int, int] = {}
    low: dict[int, int] = {}
    on_stack: set[int] = set()
    stack: list[int] = []
    out: list[list[int]] = []
    counter = 0
    for root in list(graph):
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            node, i = work.pop()
            if i == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            recurse = False
            for j in range(i, len(graph[node])):
                nxt = graph[node][j]
                if nxt not in index:
                    work.append((node, j + 1))
                    work.append((nxt, 0))
                    recurse = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if recurse:
                continue
            if low[node] == index[node]:
                group = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    group.append(w)
                    if w == node:
                        break
                if len(group) > 1 or node in graph[node]:
                    out.append(sorted(group))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return out


def depths(child_to_parents: dict[int, list[int]], nodes: set[int]) -> dict[int, int]:
    """Levels below the top for every record not in a loop (a top record is 0)."""
    children: dict[int, list[int]] = defaultdict(list)
    for child, parents in child_to_parents.items():
        for p in parents:
            children[p].append(child)
    level = {n: 0 for n in nodes if not child_to_parents.get(n)}
    frontier = list(level)
    while frontier:
        nxt = []
        for n in frontier:
            for c in children.get(n, []):
                if c not in level:
                    level[c] = level[n] + 1
                    nxt.append(c)
        frontier = nxt
    return level


def _records(db: Session, ids: list[int], sample: int | None = SAMPLE) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = db.execute(text("SELECT id, key, label FROM entity WHERE id = ANY(:ids) ORDER BY key"),
                      {"ids": ids[:sample] if sample else ids}).mappings()
    return [dict(r) for r in rows]


def _finding(db: Session, code: str, severity: str, subject: dict[str, Any], says: str, ids: list[int],
             sample: int | None = SAMPLE) -> dict[str, Any]:
    return {"code": code, "severity": severity, **subject, "says": says, "count": len(ids), "records": _records(db, ids, sample)}


def recursive_checks(db: Session, domain_id: int, max_depth: int, sample: int | None = SAMPLE) -> list[dict[str, Any]]:
    found = []
    types = db.execute(text(
        "SELECT rt.id, rt.name, rt.is_hierarchy, rt.from_type_id, rt.to_type_id, ad.name AS via_attribute"
        "  FROM relationship_type rt LEFT JOIN attribute_def ad ON ad.references_id = rt.id"
        " WHERE rt.domain_id = :d"
        "   AND (entity_type_is_a(rt.from_type_id, rt.to_type_id) OR entity_type_is_a(rt.to_type_id, rt.from_type_id))"
        " ORDER BY rt.name"), {"d": domain_id}).mappings().all()
    for rt in types:
        subject = {"relationship_type_id": rt["id"], "relationship": rt["name"], "attribute": rt["via_attribute"]}
        edges = [tuple(r) for r in db.execute(text(
            "SELECT from_entity_id, to_entity_id FROM relationship WHERE relationship_type_id = :rt"), {"rt": rt["id"]}).all()]
        # Parent -> child, whichever way the relationship is written (see hierarchies.py).
        down = [(b, a) for a, b in edges] if rt["via_attribute"] else edges
        looped = loops(down)
        in_loop = {n for g in looped for n in g}
        if looped:
            found.append(_finding(db, "loop", "error", subject,
                                  f"{len(looped)} loop{'s' if len(looped) != 1 else ''} through “{rt['name']}”: following it "
                                  "comes back to where it started. Change one link in each to break it.", sorted(in_loop), sample=sample))
        parents: dict[int, list[int]] = defaultdict(list)
        for p, c in down:
            parents[c].append(p)
        kind = db.execute(text("SELECT id FROM entity WHERE entity_type_id = ANY(entity_type_family(:t)) AND active"),
                          {"t": rt["to_type_id"]}).scalars().all()
        nodes = set(kind) | {n for e in down for n in e}
        level = depths({c: ps for c, ps in parents.items() if c not in in_loop}, nodes - in_loop)
        deep = sorted(n for n, d in level.items() if d > max_depth)
        if deep:
            found.append(_finding(db, "too_deep", "warning", subject,
                                  f"More than {max_depth} levels below the top of “{rt['name']}” (the deepest is "
                                  f"{max(level.values())}).", deep, sample=sample))
        linked = {n for e in down for n in e}
        if linked:
            alone = sorted(set(kind) - linked)
            if alone:
                found.append(_finding(db, "outside_tree", "warning", subject,
                                      f"Not placed in “{rt['name']}”: no parent and nothing below, while "
                                      f"{len(linked)} other records are.", alone, sample=sample))
    return found


def reference_checks(db: Session, domain_id: int, sample: int | None = SAMPLE) -> list[dict[str, Any]]:
    found = []
    attrs = db.execute(text(
        "SELECT ad.id, ad.name, ad.required, ad.entity_type_id, t.name AS kind, ad.references_id"
        "  FROM attribute_def ad JOIN entity_type t ON t.id = ad.entity_type_id"
        " WHERE t.domain_id = :d AND ad.data_type::text = 'reference' ORDER BY t.name, ad.name"), {"d": domain_id}).mappings().all()
    for a in attrs:
        subject = {"attribute": a["name"], "kind": a["kind"], "relationship_type_id": a["references_id"]}
        inactive = db.execute(text(
            "SELECT src.id FROM relationship r JOIN entity src ON src.id = r.from_entity_id"
            " JOIN entity dst ON dst.id = r.to_entity_id"
            " WHERE r.relationship_type_id = :rt AND src.active AND NOT dst.active ORDER BY src.key"),
            {"rt": a["references_id"]}).scalars().all()
        if inactive:
            found.append(_finding(db, "inactive_target", "warning", subject,
                                  f"“{a['kind']}.{a['name']}” names a record that is switched off; a solve leaves it out, "
                                  "so these references point at nothing there.", list(inactive), sample=sample))
        if not a["required"]:
            empty = db.execute(text(
                "SELECT id FROM entity WHERE entity_type_id = ANY(entity_type_family(:t)) AND active"
                " AND (NOT attrs ? :n OR attrs -> :n = 'null') ORDER BY key"),
                {"t": a["entity_type_id"], "n": a["name"]}).scalars().all()
            if empty:
                found.append(_finding(db, "empty_reference", "info", subject,
                                      f"“{a['kind']}.{a['name']}” is empty on {len(empty)} record{'s' if len(empty) != 1 else ''}.",
                                      list(empty), sample=sample))
    return found


@router.get("/domains/{domain_id}/data-checks")
def data_checks(domain_id: int, max_depth: int = Query(10, ge=1, le=1000),
                db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    if db.execute(text("SELECT 1 FROM domain WHERE id = :d"), {"d": domain_id}).first() is None:
        raise HTTPException(404, "domain not found")
    order = {"error": 0, "warning": 1, "info": 2}
    findings = recursive_checks(db, domain_id, max_depth) + reference_checks(db, domain_id)
    findings.sort(key=lambda f: order[f["severity"]])
    return {"domain_id": domain_id, "max_depth": max_depth, "findings": findings}
