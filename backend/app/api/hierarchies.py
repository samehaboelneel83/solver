"""A record's place in every relationship that nests its kind inside itself.

    GET /api/v1/entities/{id}/trees

A relationship whose two ends are the same kind of record (or kinds along one inheritance line)
is recursive: regions inside regions, a manager who is an employee, a depot that supplies
depots. For each such relationship type that applies to this record, the answer gives:

- `ancestors`, nearest first, and `descendants` as a tree (`parent_id`, `depth`);
- `loop`: whether walking either way comes back to a record already passed -- the database
  refuses that for a hierarchy (migration 0006), but nothing refuses it for a reference
  attribute or an ordinary self-relationship, so it can be in the data;
- `blocked`: the keys this record may not take as its parent -- itself and everything below
  it -- so a form can grey them out before a save is refused.

Which end is the parent: a hierarchy reads **from is the parent of to** (relationships.py); a
reference attribute's mirror reads the other way, **from refers to its parent** (a depot's
`region` names the region above it). Any other self-relationship is read like a hierarchy.

The walk is breadth-first in Python, one query per level, with a seen set: bounded by
`MAX_DEPTH` levels and `MAX_NODES` records, so a dense many-to-many graph cannot run away the
way a recursive CTE over paths can.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/v1", tags=["entities"])

MAX_DEPTH = 50
MAX_NODES = 1000


def recursive_types(db: Session, entity_type_id: int) -> list[dict[str, Any]]:
    """The relationship types both of whose ends a record of this kind can stand at."""
    return [dict(r) for r in db.execute(text(
        "SELECT rt.id, rt.name, rt.is_hierarchy, rt.cardinality, ad.name AS via_attribute"
        "  FROM relationship_type rt LEFT JOIN attribute_def ad ON ad.references_id = rt.id"
        " WHERE entity_type_is_a(:t, rt.from_type_id) AND entity_type_is_a(:t, rt.to_type_id)"
        " ORDER BY rt.name"), {"t": entity_type_id}).mappings()]


def _ends(rt: dict[str, Any]) -> tuple[str, str]:
    """(the parent's column, the child's column) in `relationship` for this type."""
    return ("to_entity_id", "from_entity_id") if rt["via_attribute"] else ("from_entity_id", "to_entity_id")


def walk(db: Session, rt: dict[str, Any], start: int, upward: bool) -> tuple[list[tuple[int, int, int]], bool, bool]:
    """Breadth-first from `start`: [(id, parent_or_child_it_was_reached_from, depth)], loop, truncated."""
    parent_col, child_col = _ends(rt)
    here, there = (child_col, parent_col) if upward else (parent_col, child_col)
    seen = {start}
    frontier = [start]
    found: list[tuple[int, int, int]] = []
    loop = truncated = False
    depth = 0
    while frontier:
        depth += 1
        if depth > MAX_DEPTH:
            truncated = True
            break
        rows = db.execute(text(
            f"SELECT {here} AS here, {there} AS there FROM relationship"
            f" WHERE relationship_type_id = :rt AND {here} = ANY(:f) ORDER BY {there}"),
            {"rt": rt["id"], "f": frontier}).all()
        nxt = []
        for came_from, node in rows:
            if node in seen:
                loop = True
                continue
            if len(found) >= MAX_NODES:
                truncated = True
                break
            seen.add(node)
            found.append((node, came_from, depth))
            nxt.append(node)
        frontier = nxt
    return found, loop, truncated


def _names(db: Session, ids: list[int]) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    rows = db.execute(text("SELECT id, key, label, entity_type_id FROM entity WHERE id = ANY(:ids)"), {"ids": ids}).mappings()
    return {r["id"]: dict(r) for r in rows}


@router.get("/entities/{entity_id}/trees")
def entity_trees(entity_id: int, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)) -> dict[str, Any]:
    me = db.execute(text("SELECT id, key, entity_type_id FROM entity WHERE id = :e"), {"e": entity_id}).mappings().one_or_none()
    if me is None:
        raise HTTPException(404, "entity not found")
    trees = []
    for rt in recursive_types(db, me["entity_type_id"]):
        up, up_loop, up_cut = walk(db, rt, entity_id, upward=True)
        down, down_loop, down_cut = walk(db, rt, entity_id, upward=False)
        names = _names(db, [n for n, _, _ in up] + [n for n, _, _ in down])
        trees.append({
            "relationship_type_id": rt["id"],
            "name": rt["name"],
            "is_hierarchy": rt["is_hierarchy"],
            "via_attribute": rt["via_attribute"],
            "ancestors": [{**names[n], "depth": d} for n, _, d in up if n in names],
            "descendants": [{**names[n], "parent_id": p, "depth": d} for n, p, d in down if n in names],
            "loop": up_loop or down_loop,
            "truncated": up_cut or down_cut,
            # Choosing any of these as this record's parent closes a loop.
            "blocked": [me["key"]] + [names[n]["key"] for n, _, _ in down if n in names],
        })
    return {"entity_id": entity_id, "trees": trees}
