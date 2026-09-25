"""Distances and nearness from the map, written into the domain (queue R16a).

    POST /api/v1/domains/{id}/distances   a parameter distance[from, to]
    POST /api/v1/domains/{id}/within      a relationship "within X of"

Both read the two entity types' shapes (`app.spatial.distance`), so a
facility, coverage or routing model runs on data nobody typed in. Each
writes where its numbers came from into `source`, and a run that reads them
records it. Writing again recomputes: the values or edges are replaced, as
the places may have moved; runs already made keep their frozen data.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.api.deps import requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_domain import EntityType, ParameterDef, ParameterValue, Relationship, RelationshipType
from app.spatial import distance

router = APIRouter(prefix="/api/v1", tags=["spatial"])

#: The most pairs one request writes in full: 500 x 500. Measured (bench/results/2026-09-25-distances.md):
#: computing a 1,000 x 1,000 matrix takes 0.45 s, but writing its million values 134 s (each value is
#: checked by the parameter_value trigger) -- too long for a request. Past this, keep the nearest few.
MAX_PAIRS = 250_000
#: The most edges a `within` writes.
MAX_EDGES = 200_000
NAME = r"^[a-z][a-z0-9_]*$"


class DistanceRequest(BaseModel):
    name: str = Field(pattern=NAME, max_length=63)
    from_type_id: int
    to_type_id: int
    #: Whole metres (what CP-SAT and the network lane take), or kilometres to three places.
    unit: Literal["m", "km"] = "m"
    #: Keep each place's nearest this many; the rest take a recorded "far" default, never 0.
    nearest: int | None = Field(default=None, ge=1, le=10_000)


class DistanceReport(BaseModel):
    parameter_id: int
    pairs: int
    missing: list[str]
    source: dict


class WithinRequest(BaseModel):
    name: str = Field(pattern=NAME, max_length=63)
    from_type_id: int
    to_type_id: int
    max_m: float = Field(gt=0, le=20_000_000)


class WithinReport(BaseModel):
    relationship_type_id: int
    edges: int
    missing: list[str]
    source: dict


def _types(db: Session, domain_id: int, from_id: int, to_id: int) -> tuple[EntityType, EntityType]:
    found = {t.id: t for t in db.execute(select(EntityType).where(EntityType.domain_id == domain_id,
                                                                    EntityType.id.in_([from_id, to_id]))).scalars()}
    for which, type_id in (("from", from_id), ("to", to_id)):
        if type_id not in found:
            raise HTTPException(422, f"{which}_type_id {type_id} is not an entity type of this domain")
    return found[from_id], found[to_id]


def _places(db: Session, entity_type: EntityType):
    placed, missing = distance.places(db, entity_type.id)
    if not placed:
        raise HTTPException(422, f"no {entity_type.name} has a shape to measure from; give them a geometry first")
    return placed, missing


def write_distances(db: Session, domain_id: int, body: DistanceRequest, *, commit: bool = True) -> DistanceReport:
    origin_type, target_type = _types(db, domain_id, body.from_type_id, body.to_type_id)
    origins, missing_o = _places(db, origin_type)
    targets, missing_t = _places(db, target_type)
    pairs = len(origins) * len(targets)
    if pairs > MAX_PAIRS and body.nearest is None:
        raise HTTPException(422, f"{len(origins)} x {len(targets)} is {pairs:,} pairs, more than {MAX_PAIRS:,}: "
                                 "keep each place's nearest few (`nearest`) instead")
    scale, places_ = (1.0, 0) if body.unit == "m" else (1000.0, 3)
    parameter = db.execute(select(ParameterDef).where(ParameterDef.domain_id == domain_id,
                                                      ParameterDef.name == body.name)).scalar_one_or_none()
    index = [origin_type.id, target_type.id]
    if parameter is not None and list(parameter.index_type_ids) != index:
        raise HTTPException(409, f"{body.name!r} is already a parameter over other types; choose another name")
    cells, longest = [], 0.0
    keep = body.nearest if body.nearest is not None else len(targets)
    for origin in origins:
        metres = distance.row(origin, targets)
        longest = max(longest, float(metres.max(initial=0.0)))
        chosen = range(len(targets)) if keep >= len(targets) else metres.argsort(kind="stable")[:keep]
        for j in chosen:
            if origin.entity_id == targets[j].entity_id:
                value = 0
            else:
                value = round(float(metres[j]) / scale, places_)
            cells.append({"entity_ids": [origin.entity_id, targets[j].entity_id], "value": value})
    far = None
    if keep < len(targets):
        # Pairs left out are far, not free: ten times the longest distance measured.
        far = math.ceil(longest * 10 / scale) if body.unit == "m" else round(longest * 10 / scale, 3)
    source = {**distance.describe(body.unit, body.nearest), "from": origin_type.name, "to": target_type.name,
              "pairs": len(cells), **({"far": far} if far is not None else {}),
              **({"missing": missing_o + missing_t} if missing_o or missing_t else {}),
              "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if parameter is None:
        parameter = ParameterDef(domain_id=domain_id, name=body.name, index_type_ids=index,
                                 default_value=far if far is not None else 0, unit=body.unit, source=source)
        db.add(parameter)
        db.flush()
    else:
        parameter.default_value = far if far is not None else 0
        parameter.unit, parameter.source = body.unit, source
        db.execute(delete(ParameterValue).where(ParameterValue.parameter_def_id == parameter.id))
    for start in range(0, len(cells), 20_000):
        chunk = [{"parameter_def_id": parameter.id, **c} for c in cells[start:start + 20_000]]
        db.execute(pg_insert(ParameterValue).values(chunk))
    if commit:
        db.commit()
    return DistanceReport(parameter_id=parameter.id, pairs=len(cells), missing=missing_o + missing_t, source=source)


def write_within(db: Session, domain_id: int, body: WithinRequest, *, commit: bool = True) -> WithinReport:
    origin_type, target_type = _types(db, domain_id, body.from_type_id, body.to_type_id)
    origins, missing_o = _places(db, origin_type)
    targets, missing_t = _places(db, target_type)
    if len(origins) * len(targets) > 4_000_000:
        raise HTTPException(422, f"{len(origins)} x {len(targets)} places is too many to compare at once")
    rel = db.execute(select(RelationshipType).where(RelationshipType.domain_id == domain_id,
                                                    RelationshipType.name == body.name)).scalar_one_or_none()
    if rel is not None and (rel.from_type_id, rel.to_type_id) != (origin_type.id, target_type.id):
        raise HTTPException(409, f"{body.name!r} is already a relationship between other types; choose another name")
    edges = []
    for origin in origins:
        metres = distance.row(origin, targets)
        for j in (metres <= body.max_m).nonzero()[0]:
            if targets[j].entity_id != origin.entity_id:
                edges.append((origin.entity_id, targets[int(j)].entity_id))
        if len(edges) > MAX_EDGES:
            raise HTTPException(422, f"more than {MAX_EDGES:,} pairs are within {body.max_m:g} m; choose a shorter distance")
    source = {"kind": "within", "metric": "straight line (geodesic, WGS84)", "max_m": body.max_m,
              "from": origin_type.name, "to": target_type.name, "edges": len(edges),
              **({"missing": missing_o + missing_t} if missing_o or missing_t else {}),
              "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if rel is None:
        rel = RelationshipType(domain_id=domain_id, name=body.name, from_type_id=origin_type.id,
                               to_type_id=target_type.id, cardinality="many_to_many", source=source)
        db.add(rel)
        db.flush()
    else:
        rel.source = source
        db.execute(delete(Relationship).where(Relationship.relationship_type_id == rel.id))
    for start in range(0, len(edges), 20_000):
        db.execute(pg_insert(Relationship).values([
            {"relationship_type_id": rel.id, "from_entity_id": a, "to_entity_id": b}
            for a, b in edges[start:start + 20_000]]))
    if commit:
        db.commit()
    return WithinReport(relationship_type_id=rel.id, edges=len(edges), missing=missing_o + missing_t, source=source)


@router.post("/domains/{domain_id}/distances", status_code=201, response_model=DistanceReport)
def make_distances(domain_id: int, body: DistanceRequest, db: Session = Depends(get_db),
                   _: UserAccount = Depends(requires("domain.edit"))) -> DistanceReport:
    return write_distances(db, domain_id, body)


@router.post("/domains/{domain_id}/within", status_code=201, response_model=WithinReport)
def make_within(domain_id: int, body: WithinRequest, db: Session = Depends(get_db),
                _: UserAccount = Depends(requires("domain.edit"))) -> WithinReport:
    return write_within(db, domain_id, body)
