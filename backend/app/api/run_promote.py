"""An answer kept as data (improvement plan 3.5).

    POST /api/v1/runs/{id}/promote   {decision, name, as: relationship|parameter}

A plan is often the input of the next plan: trucks placed in yards, then
crews rostered for the placed trucks; zones drawn, then routes inside them.
This writes one decision of an answered run into the workspace as ordinary
data, with where it came from:

- `relationship` (a yes/no decision over two kinds of record): one link per
  chosen pair -- `station[yard, truck]` becomes links yard -> truck;
- `parameter` (any decision over kinds of record): its values, chosen cells
  as 1 and amounts as they are, the rest the default 0.

Writing again replaces what that name held: a newer plan supersedes.

**Chains** (improvement plan 5.1). With `follow: true` the kept data follows its problem's *approved*
plan: whenever another run of that problem is approved, the data is rewritten from it
(`refresh_followers`, called by the approval). So problem B that reads `station_plan` always plans
on the placement people approved in problem A -- placement, then roster; zones, then routes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.api.deps import requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_domain import EntityType, ParameterDef, ParameterValue, Relationship, RelationshipType

router = APIRouter(prefix="/api/v1", tags=["runs"])


class Promote(BaseModel):
    decision: str = Field(min_length=1, max_length=63)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=63)
    as_: Literal["relationship", "parameter"] = Field(alias="as")
    follow: bool = False


@router.post("/runs/{run_id}/promote", status_code=201)
def promote(run_id: int, body: Promote, db: Session = Depends(get_db),
            _: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    return keep(db, run_id, body)


def refresh_followers(db: Session, problem_id: int, run_id: int) -> list[str]:
    """Rewrite every kept data that follows this problem's approved plan from the newly approved run.
    Returns the names refreshed; one that no longer fits (its decision gone) is left as it was."""
    rows = db.execute(text(
        "SELECT name, source, 'parameter' AS as_ FROM parameter_def"
        " WHERE source ->> 'follow' = 'approved' AND (source ->> 'problem_id')::bigint = :p"
        " UNION ALL SELECT name, source, 'relationship' FROM relationship_type"
        " WHERE source ->> 'follow' = 'approved' AND (source ->> 'problem_id')::bigint = :p"), {"p": problem_id}).mappings().all()
    done = []
    for row in rows:
        try:
            keep(db, run_id, Promote(decision=row["source"]["decision"], name=row["name"], follow=True, **{"as": row["as_"]}))
            done.append(row["name"])
        except HTTPException:
            db.rollback()
    return done


def keep(db: Session, run_id: int, body: Promote) -> dict[str, Any]:
    row = db.execute(
        text("SELECT r.status, p.domain_id, p.id AS problem_id, mv.ir, sol.assignments, sol.amounts FROM run r"
             " JOIN scenario s ON s.id = r.scenario_id JOIN problem p ON p.id = s.problem_id"
             " JOIN model_version mv ON mv.id = s.model_version_id LEFT JOIN solution sol ON sol.run_id = r.id"
             " WHERE r.id = :r"), {"r": run_id}).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "run not found")
    if row["assignments"] is None and row["amounts"] is None:
        raise HTTPException(409, f"run {run_id} has no answer to keep (it is {row['status']})")
    spec = ((row["ir"] or {}).get("variables") or {}).get(body.decision)
    if not isinstance(spec, dict):
        raise HTTPException(422, f"the model has no decision {body.decision!r}")
    index = list(spec.get("index") or [])
    binary = (spec.get("domain") or "binary") == "binary"
    domain_id = row["domain_id"]
    types = {t.name: t for t in db.execute(select(EntityType).where(EntityType.domain_id == domain_id,
                                                                    EntityType.name.in_(index))).scalars()}
    missing = [s for s in index if s not in types]
    if missing:
        raise HTTPException(422, f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not a kind of record here")
    ids: dict[str, dict[str, int]] = {}
    for s in set(index):
        ids[s] = dict(db.execute(text("SELECT key, id FROM entity WHERE entity_type_id = :t"), {"t": types[s].id}).all())
    if not binary and body.as_ == "parameter" and row["amounts"] is None:
        # Too many cells to keep inline: the roster alone would write every amount as 1.
        raise HTTPException(409, f"run {run_id} keeps {body.decision!r} amounts in chunks; it cannot be kept as data here")
    # The roster names every chosen cell; a whole-number or continuous decision also has its amount
    # there, which wins -- one value per cell.
    found: dict[tuple[str, ...], float] = {tuple(str(k) for k in c): 1.0 for c in (row["assignments"] or {}).get(body.decision, [])}
    for e in (row["amounts"] or {}).get(body.decision, []):
        value = float(e.get("value") or 0)
        key = tuple(str(k) for k in e.get("index") or [])
        if abs(value) > 1e-9:
            found[key] = value
        else:
            found.pop(key, None)
    cells: list[tuple[list[str], float]] = [(list(keys), v) for keys, v in found.items()]
    gone = sorted({k for keys, _ in cells for s, k in zip(index, keys) if k not in ids[s]})
    cells = [(keys, v) for keys, v in cells if all(k in ids[s] for s, k in zip(index, keys))]
    source = {"kind": "answer", "run_id": run_id, "decision": body.decision, "cells": len(cells),
              "problem_id": row["problem_id"], **({"follow": "approved"} if body.follow else {}),
              "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if body.as_ == "relationship":
        if len(index) != 2 or not binary:
            raise HTTPException(422, "a relationship keeps a yes/no decision over two kinds of record; keep this one as a parameter")
        a, b = types[index[0]], types[index[1]]
        rel = db.execute(select(RelationshipType).where(RelationshipType.domain_id == domain_id,
                                                        RelationshipType.name == body.name)).scalar_one_or_none()
        if rel is not None and (rel.from_type_id, rel.to_type_id) != (a.id, b.id):
            raise HTTPException(409, f"{body.name!r} is already a relationship between other kinds; choose another name")
        if rel is None:
            rel = RelationshipType(domain_id=domain_id, name=body.name, from_type_id=a.id, to_type_id=b.id,
                                   cardinality="many_to_many", source=source)
            db.add(rel)
            db.flush()
        else:
            rel.source = source
            db.execute(delete(Relationship).where(Relationship.relationship_type_id == rel.id))
        if cells:
            db.execute(pg_insert(Relationship).values([
                {"relationship_type_id": rel.id, "from_entity_id": ids[index[0]][k[0]], "to_entity_id": ids[index[1]][k[1]],
                 "attrs": {}} for k, _ in cells]))
        db.commit()
        return {"relationship_type_id": rel.id, "links": len(cells), "left_out": gone, "source": source}
    parameter = db.execute(select(ParameterDef).where(ParameterDef.domain_id == domain_id,
                                                      ParameterDef.name == body.name)).scalar_one_or_none()
    type_ids = [types[s].id for s in index]
    if parameter is not None and list(parameter.index_type_ids) != type_ids:
        raise HTTPException(409, f"{body.name!r} is already a parameter over other kinds; choose another name")
    if parameter is None:
        parameter = ParameterDef(domain_id=domain_id, name=body.name, index_type_ids=type_ids, default_value=0, source=source)
        db.add(parameter)
        db.flush()
    else:
        parameter.source = source
        db.execute(delete(ParameterValue).where(ParameterValue.parameter_def_id == parameter.id))
    if cells:
        db.execute(pg_insert(ParameterValue).values([
            {"parameter_def_id": parameter.id, "entity_ids": [ids[s][k] for s, k in zip(index, keys)], "value": v}
            for keys, v in cells]))
    db.commit()
    return {"parameter_id": parameter.id, "cells": len(cells), "left_out": gone, "source": source}
