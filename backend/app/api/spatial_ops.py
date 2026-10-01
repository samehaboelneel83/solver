"""Spatial measures written into the workspace (improvement plan, phase 2).

    POST /api/v1/domains/{id}/spatial/inside    {name, from_type_id, to_type_id}        -> a link: each place to its area
    POST /api/v1/domains/{id}/spatial/count     {name, from_type_id, to_type_id, max_m} -> a whole-number field on `from`
    POST /api/v1/domains/{id}/spatial/nearest   {name, from_type_id, to_type_id, k}     -> links to the k nearest, rank + metres
    POST /api/v1/domains/{id}/spatial/touching  {name, type_id}                         -> links between areas sharing a border
    POST /api/v1/domains/{id}/spatial/overlap   {name, from_type_id, to_type_id}        -> a parameter name[from, to] in m2
    POST /api/v1/domains/{id}/spatial/elevation {name, type_id}                         -> number fields `name` (m) and `name`_slope (%)

With `distances` and `within` (`app.api.distances`) these are the "From the
map" operations: each reads records with a shape (`app.spatial.ops`) and
writes an ordinary field, parameter or relationship, recording in `source`
how it was made, so a model reads it like any typed-in value. Writing again
recomputes and replaces: the places may have moved.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.api.deps import requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_domain import AttributeDef, EntityType, ParameterDef, ParameterValue, Relationship, RelationshipType
from app.spatial import ops

router = APIRouter(prefix="/api/v1", tags=["spatial"])

NAME = r"^[a-z][a-z0-9_]*$"
MAX_PAIRS = 4_000_000


class Pair(BaseModel):
    name: str = Field(pattern=NAME, max_length=63)
    from_type_id: int
    to_type_id: int


class CountBody(Pair):
    max_m: float = Field(gt=0, le=1_000_000)


class NearestBody(Pair):
    k: int = Field(ge=1, le=50)


class TouchingBody(BaseModel):
    name: str = Field(pattern=NAME, max_length=63)
    type_id: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _type(db: Session, domain_id: int, type_id: int, which: str) -> EntityType:
    found = db.execute(select(EntityType).where(EntityType.domain_id == domain_id, EntityType.id == type_id)).scalar_one_or_none()
    if found is None:
        raise HTTPException(422, f"{which} {type_id} is not a kind of record in this workspace")
    return found


def _shapes(db: Session, entity_type: EntityType) -> tuple[list[ops.Shape], list[str]]:
    found, missing = ops.load(db, entity_type.id)
    if not found:
        raise HTTPException(422, f"no {entity_type.name} has a shape; give them one first (Map data → Use in models)")
    return found, missing


def _relationship(db: Session, domain_id: int, name: str, a: EntityType, b: EntityType, cardinality: str,
                  source: dict[str, Any], attributes: dict[str, str]) -> RelationshipType:
    rel = db.execute(select(RelationshipType).where(RelationshipType.domain_id == domain_id,
                                                    RelationshipType.name == name)).scalar_one_or_none()
    if rel is not None and (rel.from_type_id, rel.to_type_id) != (a.id, b.id):
        raise HTTPException(409, f"{name!r} is already a relationship between other kinds; choose another name")
    if rel is None:
        rel = RelationshipType(domain_id=domain_id, name=name, from_type_id=a.id, to_type_id=b.id,
                               cardinality=cardinality, source=source)
        db.add(rel)
        db.flush()
    else:
        rel.source = source
        db.execute(delete(Relationship).where(Relationship.relationship_type_id == rel.id))
    for attr, unit in attributes.items():
        if db.execute(select(AttributeDef.id).where(AttributeDef.relationship_type_id == rel.id,
                                                    AttributeDef.name == attr)).first() is None:
            db.add(AttributeDef(relationship_type_id=rel.id, name=attr, data_type="number", unit=unit or None))
    db.flush()
    return rel


def _links(db: Session, rel: RelationshipType, rows: list[tuple[int, int, dict[str, Any]]]) -> None:
    for start in range(0, len(rows), 20_000):
        chunk = rows[start:start + 20_000]
        if chunk:
            db.execute(pg_insert(Relationship).values([
                {"relationship_type_id": rel.id, "from_entity_id": a, "to_entity_id": b, "attrs": attrs}
                for a, b, attrs in chunk]))


@router.post("/domains/{domain_id}/spatial/inside", status_code=201)
def make_inside(domain_id: int, body: Pair, db: Session = Depends(get_db),
                _: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    """Each place linked to the area it lies in (many to one): a rule walks it as `via name`."""
    places_type = _type(db, domain_id, body.from_type_id, "from_type_id")
    areas_type = _type(db, domain_id, body.to_type_id, "to_type_id")
    places, missing_p = _shapes(db, places_type)
    areas, missing_a = _shapes(db, areas_type)
    pairs, outside = ops.inside(places, areas)
    source = {"kind": "inside", "from": places_type.name, "to": areas_type.name, "links": len(pairs),
              **({"outside": outside[:200]} if outside else {}),
              **({"missing": (missing_p + missing_a)[:200]} if missing_p or missing_a else {}), "computed_at": _now()}
    rel = _relationship(db, domain_id, body.name, places_type, areas_type, "many_to_one", source, {})
    _links(db, rel, [(a, b, {}) for a, b in pairs])
    db.commit()
    return {"relationship_type_id": rel.id, "links": len(pairs), "outside": outside[:200],
            "missing": (missing_p + missing_a)[:200], "source": source}


@router.post("/domains/{domain_id}/spatial/count", status_code=201)
def make_count(domain_id: int, body: CountBody, db: Session = Depends(get_db),
               _: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    """How many of `to` lie within max_m metres of each `from`, as a whole-number field on `from`."""
    origin_type = _type(db, domain_id, body.from_type_id, "from_type_id")
    target_type = _type(db, domain_id, body.to_type_id, "to_type_id")
    origins, missing_o = _shapes(db, origin_type)
    targets, missing_t = _shapes(db, target_type)
    if len(origins) * len(targets) > MAX_PAIRS:
        raise HTTPException(422, f"{len(origins)} x {len(targets)} places is too many to compare at once")
    counts = ops.count_within(origins, targets, body.max_m)
    existing = db.execute(select(AttributeDef).where(AttributeDef.entity_type_id == origin_type.id,
                                                     AttributeDef.name == body.name)).scalar_one_or_none()
    if existing is not None and existing.data_type != "integer":
        raise HTTPException(409, f"{origin_type.name} already has a {existing.data_type} field {body.name!r}; choose another name")
    if existing is None:
        db.add(AttributeDef(entity_type_id=origin_type.id, name=body.name, data_type="integer"))
        db.flush()
    for o, c in zip(origins, counts, strict=True):
        db.execute(text("UPDATE entity SET attrs = jsonb_set(attrs, ARRAY[:f], to_jsonb(CAST(:v AS integer))) WHERE id = :i"),
                   {"f": body.name, "v": c, "i": o.entity_id})
    db.commit()
    source = {"kind": "count_within", "of": target_type.name, "max_m": body.max_m, "computed_at": _now()}
    return {"field": body.name, "on": origin_type.name, "records": len(origins),
            "with_any": sum(1 for c in counts if c > 0), "missing": (missing_o + missing_t)[:200], "source": source}


@router.post("/domains/{domain_id}/spatial/nearest", status_code=201)
def make_nearest(domain_id: int, body: NearestBody, db: Session = Depends(get_db),
                 _: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    """Each `from` linked to its k nearest `to`, each link with its `rank` and `metres`."""
    origin_type = _type(db, domain_id, body.from_type_id, "from_type_id")
    target_type = _type(db, domain_id, body.to_type_id, "to_type_id")
    origins, missing_o = _shapes(db, origin_type)
    targets, missing_t = _shapes(db, target_type)
    if len(origins) * len(targets) > MAX_PAIRS:
        raise HTTPException(422, f"{len(origins)} x {len(targets)} places is too many to compare at once")
    rows = ops.nearest(origins, targets, body.k)
    source = {"kind": "nearest", "k": body.k, "from": origin_type.name, "to": target_type.name, "links": len(rows),
              "metric": "straight line (geodesic, WGS84)", "computed_at": _now()}
    rel = _relationship(db, domain_id, body.name, origin_type, target_type, "many_to_many", source,
                        {"rank": "", "metres": "m"})
    _links(db, rel, [(a, b, {"rank": rank, "metres": int(round(m))}) for a, b, rank, m in rows])
    db.commit()
    return {"relationship_type_id": rel.id, "links": len(rows), "missing": (missing_o + missing_t)[:200], "source": source}


@router.post("/domains/{domain_id}/spatial/touching", status_code=201)
def make_touching(domain_id: int, body: TouchingBody, db: Session = Depends(get_db),
                  _: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    """Areas of a kind that share a border, linked both ways, each link with the border's metres."""
    area_type = _type(db, domain_id, body.type_id, "type_id")
    areas, missing = _shapes(db, area_type)
    pairs = ops.touching(areas)
    source = {"kind": "touching", "of": area_type.name, "links": len(pairs), "computed_at": _now()}
    rel = _relationship(db, domain_id, body.name, area_type, area_type, "many_to_many", source, {"border_m": "m"})
    _links(db, rel, [(a, b, {"border_m": m}) for a, b, m in pairs])
    db.commit()
    return {"relationship_type_id": rel.id, "links": len(pairs), "missing": missing[:200], "source": source}


@router.post("/domains/{domain_id}/spatial/overlap", status_code=201)
def make_overlap(domain_id: int, body: Pair, db: Session = Depends(get_db),
                 _: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    """The m2 each pair of areas shares, as a parameter name[from, to] (0 where they do not overlap)."""
    a_type = _type(db, domain_id, body.from_type_id, "from_type_id")
    b_type = _type(db, domain_id, body.to_type_id, "to_type_id")
    a_shapes, missing_a = _shapes(db, a_type)
    b_shapes, missing_b = _shapes(db, b_type)
    rows = ops.overlap_m2(a_shapes, b_shapes)
    parameter = db.execute(select(ParameterDef).where(ParameterDef.domain_id == domain_id,
                                                      ParameterDef.name == body.name)).scalar_one_or_none()
    index = [a_type.id, b_type.id]
    if parameter is not None and list(parameter.index_type_ids) != index:
        raise HTTPException(409, f"{body.name!r} is already a parameter over other kinds; choose another name")
    source = {"kind": "overlap", "from": a_type.name, "to": b_type.name, "pairs": len(rows), "unit": "m2",
              "computed_at": _now()}
    if parameter is None:
        parameter = ParameterDef(domain_id=domain_id, name=body.name, index_type_ids=index, default_value=0,
                                 unit="m2", source=source)
        db.add(parameter)
        db.flush()
    else:
        parameter.source = source
        db.execute(delete(ParameterValue).where(ParameterValue.parameter_def_id == parameter.id))
    if rows:
        db.execute(pg_insert(ParameterValue).values([
            {"parameter_def_id": parameter.id, "entity_ids": [a, b], "value": int(round(m2))} for a, b, m2 in rows]))
    db.commit()
    return {"parameter_id": parameter.id, "pairs": len(rows), "missing": (missing_a + missing_b)[:200],
            "source": json.loads(json.dumps(source))}


class ElevationBody(BaseModel):
    name: str = Field(pattern=NAME, max_length=56)
    type_id: int


def _number_field(db: Session, entity_type: EntityType, name: str, unit: str) -> None:
    existing = db.execute(select(AttributeDef).where(AttributeDef.entity_type_id == entity_type.id,
                                                     AttributeDef.name == name)).scalar_one_or_none()
    if existing is not None and existing.data_type not in ("number", "decimal"):
        raise HTTPException(409, f"{entity_type.name} already has a {existing.data_type} field {name!r}; choose another name")
    if existing is None:
        db.add(AttributeDef(entity_type_id=entity_type.id, name=name, data_type="number", unit=unit))
        db.flush()


@router.post("/domains/{domain_id}/spatial/elevation", status_code=201)
def make_elevation(domain_id: int, body: ElevationBody, db: Session = Depends(get_db),
                   _: UserAccount = Depends(requires("domain.edit"))) -> dict[str, Any]:
    """Each place's ground height (m) and slope (%) from the terrain tiles, as two number fields
    (improvement plan 2.8): low ground floods first, a pump lifts further uphill, a slope limits a site."""
    from app.settings_resolve import resolve
    from app.spatial import terrain

    place_type = _type(db, domain_id, body.type_id, "type_id")
    places, missing = _shapes(db, place_type)
    address = str(resolve(db, domain_id=domain_id)["spatial.tiles_index"].value or "").strip()
    try:
        source = terrain.terrain_source(address, fetch=terrain.fetch_bytes)
    except terrain.TerrainError as exc:
        raise HTTPException(422, str(exc)) from exc
    latitude = sum(ops._point(p.geometry)[1] for p in places) / len(places)
    # A place is sampled at about 30 m a pixel -- fine enough for a street, a field or a yard.
    sampler = terrain.Sampler(source, terrain.zoom_for(240.0, latitude, source), fetch=terrain.fetch_bytes)
    try:
        values = ops.heights(places, sampler)
    except OSError as exc:
        raise HTTPException(422, f"the terrain tiles could not be read from the tile server ({exc})") from exc
    slope_name = f"{body.name}_slope"
    _number_field(db, place_type, body.name, "m")
    _number_field(db, place_type, slope_name, "%")
    uncovered: list[str] = []
    for place, value in zip(places, values, strict=True):
        if value is None:
            uncovered.append(place.key)
            continue
        db.execute(text("UPDATE entity SET attrs = attrs || CAST(:v AS jsonb) WHERE id = :i"),
                   {"v": json.dumps({body.name: round(value[0], 1), slope_name: round(value[1], 1)}), "i": place.entity_id})
    db.commit()
    record = {"kind": "elevation", "of": place_type.name, "encoding": source.encoding, "computed_at": _now()}
    return {"field": body.name, "slope_field": slope_name, "on": place_type.name, "records": len(places) - len(uncovered),
            "uncovered": uncovered[:200], "missing": missing[:200], "source": record}
