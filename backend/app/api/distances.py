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
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.api.deps import requires
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_domain import AttributeDef, EntityType, ParameterDef, ParameterValue, Relationship, RelationshipType
import numpy as np

from app.spatial import distance
from app.spatial.ops import shapes_fingerprint

router = APIRouter(prefix="/api/v1", tags=["spatial"])

#: The most pairs one request writes in full: 500 x 500. Measured (bench/results/2026-09-25-distances.md):
#: computing a 1,000 x 1,000 matrix takes 0.45 s, but writing its million values 134 s (each value is
#: checked by the parameter_value trigger) -- too long for a request. Past this, keep the nearest few.
MAX_PAIRS = 250_000
#: The most edges a `within` writes.
MAX_EDGES = 200_000
NAME = r"^[a-z][a-z0-9_]*$"


class NetworkSource(BaseModel):
    """A lines layer of imported map data to travel along (improvement plan 2.9)."""
    dataset_id: int
    layer: str = Field(min_length=1, max_length=255)
    #: A property of each line holding its speed in km/h; lines without one take `default_kmh`.
    speed_field: str | None = Field(default=None, max_length=255)
    default_kmh: float = Field(default=30.0, gt=0, le=300)
    #: How far off the lines a place may be and still join them, in metres.
    join_m: float = Field(default=500.0, gt=0, le=20_000)


Metric = Literal["straight", "road", "time", "network", "network_time"]


class DistanceRequest(BaseModel):
    name: str = Field(pattern=NAME, max_length=63)
    from_type_id: int
    to_type_id: int
    #: A straight line, the road, or the time the road takes (queue R16b); or along a lines layer
    #: the person imported, in metres or minutes (improvement plan 2.9).
    metric: Metric = "straight"
    network: NetworkSource | None = None
    #: Distance in whole metres (what CP-SAT and the network lane take) or km to three places;
    #: time in whole seconds or minutes to one place.
    unit: Literal["m", "km", "s", "min"] = "m"
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
    metric: Metric = "straight"
    network: NetworkSource | None = None
    #: A relationship (one link per pair within reach), or a 0/1 parameter name[from, to] that a rule
    #: multiplies by -- `sum(reach[y, h] * x[y] for y in yard)` (improvement plan 2.2).
    output: Literal["relationship", "parameter"] = "relationship"
    #: For a straight line or the road: metres. For time: minutes.
    max_m: float | None = Field(default=None, gt=0, le=20_000_000)
    max_min: float | None = Field(default=None, gt=0, le=100_000)


class WithinReport(BaseModel):
    relationship_type_id: int | None = None
    parameter_id: int | None = None
    edges: int
    missing: list[str]
    source: dict


_UNITS = {"straight": ("m", "km"), "road": ("m", "km"), "time": ("s", "min"),
          "network": ("m", "km"), "network_time": ("s", "min")}
_TIMED = ("time", "network_time")
#: Each unit's divisor from the base (metres or minutes) and its decimal places.
_SCALE = {"m": (1.0, 0), "km": (1000.0, 3), "s": (1 / 60.0, 0), "min": (1.0, 1)}


def _measure(db: Session, domain_id: int, metric: str, origins, targets,
             network: "NetworkSource | None" = None) -> tuple[np.ndarray, dict]:
    """Metres (straight or road) or minutes (time) from each origin to each target, NaN where no road
    joins them, and what the source should say about how."""
    if metric == "straight":
        return distance.matrix(origins, targets), {"metric": "straight line (geodesic, WGS84)"}
    if metric in ("network", "network_time"):
        from app.spatial import layer_network

        if network is None:
            raise HTTPException(422, "travel along a layer names it: network = {dataset_id, layer}")
        owner = db.execute(text("SELECT domain_id FROM gis_dataset WHERE id = :i"), {"i": network.dataset_id}).scalar_one_or_none()
        if owner != domain_id:
            raise HTTPException(422, f"map data {network.dataset_id} is not in this workspace")
        try:
            net = layer_network.build(layer_network.from_layer(db, network.dataset_id, network.layer),
                                      network.speed_field, network.default_kmh)
            values, info = layer_network.matrix(net, [(o.lon, o.lat) for o in origins], [(t.lon, t.lat) for t in targets],
                                                minutes=metric == "network_time", snap_m=network.join_m)
            # Name the places too far from any line to join it: their pairs are left out, not zero.
            off = [f"{origins[i].key} ({m} m)" for i, m in info.pop("off_origins", [])]
            off += [f"{targets[i].key} ({m} m)" for i, m in info.pop("off_targets", [])]
            if off:
                info["off_network"] = sorted(set(off))[:200]
        except layer_network.NetworkError as exc:
            raise HTTPException(422, f"layer {network.layer!r}: {exc}") from exc
        return values, {"metric": f"along layer {network.layer!r} of map data {network.dataset_id}", **info}
    from app.settings_resolve import resolve
    from app.spatial import roads

    try:
        template = roads.vector_source(str(resolve(db, domain_id=domain_id)["spatial.tiles_index"].value or "").strip())
        net = roads.network([*origins, *targets], template)
        values, info = roads.matrix(net, origins, targets, minutes=metric == "time")
    except roads.RoadsError as exc:
        raise HTTPException(422, str(exc)) from exc
    return values, {"metric": roads.describe(template), **info}



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
    if body.unit not in _UNITS[body.metric]:
        raise HTTPException(422, f"a {body.metric} measure is in {' or '.join(_UNITS[body.metric])}, not {body.unit}")
    origins, missing_o = _places(db, origin_type)
    targets, missing_t = _places(db, target_type)
    pairs = len(origins) * len(targets)
    if pairs > MAX_PAIRS and body.nearest is None:
        raise HTTPException(422, f"{len(origins)} x {len(targets)} is {pairs:,} pairs, more than {MAX_PAIRS:,}: "
                                 "keep each place's nearest few (`nearest`) instead")
    parameter = db.execute(select(ParameterDef).where(ParameterDef.domain_id == domain_id,
                                                      ParameterDef.name == body.name)).scalar_one_or_none()
    index = [origin_type.id, target_type.id]
    if parameter is not None and list(parameter.index_type_ids) != index:
        raise HTTPException(409, f"{body.name!r} is already a parameter over other types; choose another name")
    values, how = _measure(db, domain_id, body.metric, origins, targets, body.network)
    scale, places_ = _SCALE[body.unit]
    reached = values[~np.isnan(values)]
    longest = float(reached.max(initial=0.0))
    keep = body.nearest if body.nearest is not None else len(targets)
    cells, left_out = [], 0
    for i, origin in enumerate(origins):
        row = values[i]
        order = np.argsort(np.where(np.isnan(row), np.inf, row), kind="stable")
        for j in order[:keep]:
            if np.isnan(row[j]):
                left_out += 1  # no road joins them: left to the far default, never guessed
                continue
            value = 0 if origin.entity_id == targets[j].entity_id else round(float(row[j]) / scale, places_)
            if places_ == 0:
                value = int(value)
            cells.append({"entity_ids": [origin.entity_id, targets[int(j)].entity_id], "value": value})
    far = None
    if keep < len(targets) or left_out:
        # Pairs left out are far, not free: ten times the longest measured.
        far = math.ceil(longest * 10 / scale) if places_ == 0 else round(longest * 10 / scale, places_)
    source = {"kind": "distance", "unit": body.unit, **how, **({"nearest": body.nearest} if body.nearest else {}),
              "from": origin_type.name, "to": target_type.name, "pairs": len(cells),
              **({"far": far} if far is not None else {}), **({"no_road": left_out} if left_out else {}),
              **({"missing": missing_o + missing_t} if missing_o or missing_t else {}),
              "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "shapes": shapes_fingerprint(db, index),
              # The exact ask, so "compute again" (and "again, but within 25 min") needs no retyping.
              "request": body.model_dump(mode="json", exclude_none=True)}
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
    timed = body.metric in _TIMED
    limit = body.max_min if timed else body.max_m
    if limit is None:
        raise HTTPException(422, "a time reach is max_min (minutes); a straight or road reach is max_m (metres)")
    origins, missing_o = _places(db, origin_type)
    targets, missing_t = _places(db, target_type)
    if len(origins) * len(targets) > 4_000_000:
        raise HTTPException(422, f"{len(origins)} x {len(targets)} places is too many to compare at once")
    if body.output == "parameter":
        return _within_parameter(db, domain_id, body, origin_type, target_type, origins, targets,
                                 missing_o + missing_t, limit, commit=commit)
    rel = db.execute(select(RelationshipType).where(RelationshipType.domain_id == domain_id,
                                                    RelationshipType.name == body.name)).scalar_one_or_none()
    if rel is not None and (rel.from_type_id, rel.to_type_id) != (origin_type.id, target_type.id):
        raise HTTPException(409, f"{body.name!r} is already a relationship between other types; choose another name")
    values, how = _measure(db, domain_id, body.metric, origins, targets, body.network)
    edges = []
    for i, origin in enumerate(origins):
        for j in np.flatnonzero(values[i] <= limit):  # NaN (no road) compares false: never linked
            if targets[j].entity_id != origin.entity_id:
                edges.append((origin.entity_id, targets[int(j)].entity_id, float(values[i][j])))
        if len(edges) > MAX_EDGES:
            raise HTTPException(422, f"more than {MAX_EDGES:,} pairs are within {limit:g}; choose a shorter reach")
    source = {"kind": "within", **how, **({"max_min": body.max_min} if timed else {"max_m": body.max_m}),
              "from": origin_type.name, "to": target_type.name, "edges": len(edges),
              "attribute": "minutes" if timed else "metres",
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
    # Declared on the type, so a rule offers it and checks it as a number.
    if db.execute(select(AttributeDef.id).where(AttributeDef.relationship_type_id == rel.id,
                                                AttributeDef.name == source["attribute"])).first() is None:
        db.add(AttributeDef(relationship_type_id=rel.id, name=source["attribute"], data_type="number",
                            unit="min" if timed else "m"))
        db.flush()
    # Each edge keeps its own measure (queue R19), so a rule reads it as
    # `attr of e` on the edge it walks: metres, or minutes for a time reach.
    unit = source["attribute"]
    places = 1 if timed else 0
    for start in range(0, len(edges), 20_000):
        db.execute(pg_insert(Relationship).values([
            {"relationship_type_id": rel.id, "from_entity_id": a, "to_entity_id": b,
             "attrs": {unit: round(value, places) if places else int(round(value))}}
            for a, b, value in edges[start:start + 20_000]]))
    if commit:
        db.commit()
    return WithinReport(relationship_type_id=rel.id, edges=len(edges), missing=missing_o + missing_t, source=source)


def _within_parameter(db: Session, domain_id: int, body: WithinRequest, origin_type, target_type, origins, targets,
                      missing: list[str], limit: float, *, commit: bool) -> WithinReport:
    """Within reach as a 0/1 parameter name[from, to]: 1 where the pair is within `limit`, else the default 0."""
    parameter = db.execute(select(ParameterDef).where(ParameterDef.domain_id == domain_id,
                                                      ParameterDef.name == body.name)).scalar_one_or_none()
    index = [origin_type.id, target_type.id]
    if parameter is not None and list(parameter.index_type_ids) != index:
        raise HTTPException(409, f"{body.name!r} is already a parameter over other types; choose another name")
    values, how = _measure(db, domain_id, body.metric, origins, targets, body.network)
    timed = body.metric in _TIMED
    cells = []
    for i, origin in enumerate(origins):
        for j in np.flatnonzero(values[i] <= limit):
            cells.append({"entity_ids": [origin.entity_id, targets[int(j)].entity_id], "value": 1})
    source = {"kind": "within", "output": "parameter", **how,
              **({"max_min": body.max_min} if timed else {"max_m": body.max_m}),
              "from": origin_type.name, "to": target_type.name, "pairs": len(cells),
              **({"missing": missing} if missing else {}),
              "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "shapes": shapes_fingerprint(db, index),
              # The exact ask, so "compute again" (and "again, but within 25 min") needs no retyping.
              "request": body.model_dump(mode="json", exclude_none=True)}
    if parameter is None:
        parameter = ParameterDef(domain_id=domain_id, name=body.name, index_type_ids=index, default_value=0,
                                 unit=None, source=source)
        db.add(parameter)
        db.flush()
    else:
        parameter.default_value, parameter.source = 0, source
        db.execute(delete(ParameterValue).where(ParameterValue.parameter_def_id == parameter.id))
    for start in range(0, len(cells), 20_000):
        db.execute(pg_insert(ParameterValue).values([{"parameter_def_id": parameter.id, **c}
                                                     for c in cells[start:start + 20_000]]))
    if commit:
        db.commit()
    return WithinReport(parameter_id=parameter.id, edges=len(cells), missing=missing, source=source)


class RecomputeBody(BaseModel):
    """Changes to the remembered ask; anything left out is as it was."""
    max_min: float | None = Field(default=None, gt=0)
    max_m: float | None = Field(default=None, gt=0)
    nearest: int | None = Field(default=None, ge=1)
    join_m: float | None = Field(default=None, gt=0, le=20_000)
    default_kmh: float | None = Field(default=None, gt=0, le=300)


@router.post("/parameters/{parameter_id}/recompute", status_code=201)
def recompute(parameter_id: int, body: RecomputeBody | None = None, db: Session = Depends(get_db),
              _: UserAccount = Depends(requires("domain.edit"))) -> dict:
    """Compute a map-made parameter again from the ask it remembers -- after places moved, a layer
    was re-imported, or with a new limit ("within 25 min, not 15")."""
    parameter = db.get(ParameterDef, parameter_id)
    if parameter is None:
        raise HTTPException(404, "parameter not found")
    ask = dict((parameter.source or {}).get("request") or {})
    if not ask:
        raise HTTPException(422, f"{parameter.name} was not computed from the map here (or before it remembered how); "
                                 "compute it once from Data › Parameters › Compute from the map")
    changes = (body or RecomputeBody()).model_dump(exclude_none=True)
    for key in ("join_m", "default_kmh"):
        if key in changes:
            if not ask.get("network"):
                raise HTTPException(422, f"{key} applies to travel along an imported lines layer")
            ask["network"] = {**ask["network"], key: changes.pop(key)}
    ask.update(changes)
    from pydantic import ValidationError

    try:
        request = DistanceRequest(**ask) if (parameter.source or {}).get("kind") == "distance" else WithinRequest(**ask)
    except ValidationError as exc:
        raise HTTPException(422, f"the remembered ask with these changes does not hold: {exc.errors()[0].get('msg')}") from exc
    if isinstance(request, DistanceRequest):
        report = write_distances(db, parameter.domain_id, request)
        return {"kind": "distance", "pairs": report.pairs, "missing": report.missing, "source": report.source}
    report = write_within(db, parameter.domain_id, request)
    return {"kind": "within", "edges": report.edges, "missing": report.missing, "source": report.source}


@router.post("/domains/{domain_id}/distances", status_code=201, response_model=DistanceReport)
def make_distances(domain_id: int, body: DistanceRequest, db: Session = Depends(get_db),
                   _: UserAccount = Depends(requires("domain.edit"))) -> DistanceReport:
    return write_distances(db, domain_id, body)


@router.post("/domains/{domain_id}/within", status_code=201, response_model=WithinReport)
def make_within(domain_id: int, body: WithinRequest, db: Session = Depends(get_db),
                _: UserAccount = Depends(requires("domain.edit"))) -> WithinReport:
    return write_within(db, domain_id, body)
