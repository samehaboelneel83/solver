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
from typing import Any, Literal

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
    #: A property of each line that closes it (true, yes, 1, "closed"): a flooded or blocked road.
    closed_field: str | None = Field(default=None, max_length=255)
    #: A property of each line with minutes added to travel along it: a checkpoint, roadworks.
    delay_field: str | None = Field(default=None, max_length=255)
    #: A kind of record whose areas no route may enter (flood zones, no-go areas).
    avoid_type_id: int | None = None
    #: For a cost along the lines (metric `network_cost`): a property of each line holding its cost per
    #: km, lines without one at `default_cost_per_km`; and a property with a cost added once per line
    #: (a toll). Benchmark round 5: transport cost per pallet-km and tolls could not follow the roads.
    cost_field: str | None = Field(default=None, max_length=255)
    default_cost_per_km: float = Field(default=1.0, gt=0, le=1e9)
    toll_field: str | None = Field(default=None, max_length=255)


Metric = Literal["straight", "road", "time", "network", "network_time", "network_cost"]


class ByPeriod(BaseModel):
    """Travel times per period (benchmark re-test, October 2026: road speeds differ at the morning peak).
    A kind of record for the periods, and on each either the name of the lines' property holding its
    speeds (`speed_field_from`: a field of the period, "am_peak" -> "speed_am"), or a number scaling
    every speed (`factor_from`: 0.6 at the peak). The data is then indexed [from, to, period]."""
    type_id: int
    speed_field_from: str | None = Field(default=None, max_length=255)
    factor_from: str | None = Field(default=None, max_length=255)


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
    unit: Literal["m", "km", "s", "min", "cost"] = "m"
    #: Keep each place's nearest this many; the rest take a recorded "far" default, never 0.
    nearest: int | None = Field(default=None, ge=1, le=10_000)
    by_period: ByPeriod | None = None


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
    #: Within reach in each period, as a parameter name[from, to, period].
    by_period: ByPeriod | None = None


class WithinReport(BaseModel):
    relationship_type_id: int | None = None
    parameter_id: int | None = None
    edges: int
    missing: list[str]
    source: dict


_UNITS = {"straight": ("m", "km"), "road": ("m", "km"), "time": ("s", "min"),
          "network": ("m", "km"), "network_time": ("s", "min"), "network_cost": ("cost",)}
_TIMED = ("time", "network_time")
#: Each unit's divisor from the base (metres or minutes) and its decimal places.
_SCALE = {"m": (1.0, 0), "km": (1000.0, 3), "s": (1 / 60.0, 0), "min": (1.0, 1), "cost": (1.0, 2)}


def _per_km(props: dict[str, Any] | None, field: str | None, default: float) -> float:
    """A line's cost per km: its field when that holds a number above 0, else the default."""
    try:
        value = float((props or {}).get(field)) if field else default
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def _measure(db: Session, domain_id: int, metric: str, origins, targets,
             network: "NetworkSource | None" = None) -> tuple[np.ndarray, dict]:
    """Metres (straight or road) or minutes (time) from each origin to each target, NaN where no road
    joins them, and what the source should say about how."""
    if metric == "straight":
        return distance.matrix(origins, targets), {"metric": "straight line (geodesic, WGS84)"}
    if metric in ("network", "network_time", "network_cost"):
        from app.spatial import layer_network

        if network is None:
            raise HTTPException(422, "travel along a layer names it: network = {dataset_id, layer}")
        owner = db.execute(text("SELECT domain_id FROM gis_dataset WHERE id = :i"), {"i": network.dataset_id}).scalar_one_or_none()
        if owner != domain_id:
            raise HTTPException(422, f"map data {network.dataset_id} is not in this workspace")
        try:
            avoid = None
            if network.avoid_type_id is not None:
                from app.spatial import ops

                if db.execute(text("SELECT domain_id FROM entity_type WHERE id = :t"), {"t": network.avoid_type_id}).scalar_one_or_none() != domain_id:
                    raise HTTPException(422, f"kind {network.avoid_type_id} is not in this workspace")
                avoid = [a.geometry for a in ops.load(db, network.avoid_type_id)[0] if a.geometry.geom_type in ("Polygon", "MultiPolygon")]
                if not avoid:
                    raise HTTPException(422, "the kind to avoid has no areas")
            lines = layer_network.from_layer(db, network.dataset_id, network.layer)
            costed = metric == "network_cost"
            asked = [f for f in ((network.cost_field, network.toll_field) if costed else (network.speed_field, network.delay_field)) if f]
            asked += [network.closed_field] if network.closed_field else []
            lines, borrowed = _record_fields(db, domain_id, lines, asked, network.layer)
            if costed:
                # A cost per km is a "speed" of 60 / cost (so a km takes `cost` minutes), and a toll a
                # delay of that many minutes on its line: the cheapest path's minutes are its cost.
                lines = [(c, {**(p or {}), "__speed": 60.0 / _per_km(p, network.cost_field, network.default_cost_per_km),
                              **({"__toll": (p or {}).get(network.toll_field)} if network.toll_field else {})})
                         for c, p in lines]
                net = layer_network.build(lines, "__speed", 60.0 / network.default_cost_per_km, closed_field=network.closed_field,
                                          delay_field="__toll" if network.toll_field else None, avoid=avoid)
            else:
                net = layer_network.build(lines, network.speed_field, network.default_kmh, closed_field=network.closed_field,
                                          delay_field=network.delay_field, avoid=avoid)
            values, info = layer_network.matrix(net, [(o.lon, o.lat) for o in origins], [(t.lon, t.lat) for t in targets],
                                                minutes=metric in ("network_time", "network_cost"), snap_m=network.join_m)
            # Name the places too far from any line to join it: their pairs are left out, not zero.
            off = [f"{origins[i].key} ({m} m)" for i, m in info.pop("off_origins", [])]
            off += [f"{targets[i].key} ({m} m)" for i, m in info.pop("off_targets", [])]
            if off:
                info["off_network"] = sorted(set(off))[:200]
        except layer_network.NetworkError as exc:
            raise HTTPException(422, f"layer {network.layer!r}: {exc}") from exc
        extra = {k: v for k, v in (("closed_by", network.closed_field), ("delay_by", None if metric == "network_cost" else network.delay_field),
                                   ("avoiding", network.avoid_type_id),
                                   ("cost_per_km_by", network.cost_field if metric == "network_cost" else None),
                                   ("toll_by", network.toll_field if metric == "network_cost" else None)) if v is not None}
        if borrowed:
            extra["fields_from_records"] = borrowed
        return values, {"metric": f"along layer {network.layer!r} of map data {network.dataset_id}", **extra, **info}
    from app.settings_resolve import resolve
    from app.spatial import roads

    tiles = str(resolve(db, domain_id=domain_id)["spatial.tiles_index"].value or "").strip()
    if not tiles:
        # No road tiles set: the workspace's own imported roads, when it has a lines layer
        # (benchmark, October 2026: road distances failed with a settings message instead).
        found = db.execute(text(
            "SELECT l.dataset_id, l.name FROM gis_layer l JOIN gis_dataset d ON d.id = l.dataset_id"
            " WHERE d.domain_id = :d AND EXISTS (SELECT 1 FROM gis_feature f WHERE f.layer_id = l.id AND f.kind = 'line')"
            " ORDER BY (l.name ~* '(road|street|route|highway|path)') DESC, l.id LIMIT 1"), {"d": domain_id}).first()
        if found is not None:
            values, info = _measure(db, domain_id, "network_time" if metric == "time" else "network", origins, targets,
                                    NetworkSource(dataset_id=found[0], layer=found[1]))
            return values, {**info, "note": "no road tiles are set, so the workspace's own lines layer was used"}
    try:
        template = roads.vector_source(tiles)
        net = roads.network([*origins, *targets], template)
        values, info = roads.matrix(net, origins, targets, minutes=metric == "time")
    except roads.RoadsError as exc:
        raise HTTPException(422, str(exc)) from exc
    return values, {"metric": roads.describe(template), **info}


def _by_period(db: Session, domain_id: int, body, origins, targets) -> tuple[list[tuple[int | None, np.ndarray]], dict, int | None]:
    """The measure once, or once per period: [(period entity id or None, values)], what the source says, and the
    period kind's id for the index."""
    if body.by_period is None:
        values, how = _measure(db, domain_id, body.metric, origins, targets, body.network)
        return [(None, values)], how, None
    ask = body.by_period
    if body.metric not in _TIMED:
        raise HTTPException(422, "a measure by period is a travel time: metric time or network_time")
    if (ask.speed_field_from is None) == (ask.factor_from is None):
        raise HTTPException(422, "by period, each period names the lines' speed field (speed_field_from) or scales every speed (factor_from)")
    kind = db.execute(select(EntityType).where(EntityType.domain_id == domain_id, EntityType.id == ask.type_id)).scalar_one_or_none()
    if kind is None:
        raise HTTPException(422, f"kind {ask.type_id} is not in this workspace")
    periods = db.execute(text("SELECT id, key, attrs FROM entity WHERE entity_type_id = :t AND active ORDER BY sort_order, key"),
                         {"t": kind.id}).all()
    if not periods:
        raise HTTPException(422, f"there are no {kind.name} records to measure for")
    field = ask.speed_field_from or ask.factor_from
    out: list[tuple[int | None, np.ndarray]] = []
    how: dict = {}
    if ask.factor_from:
        values, how = _measure(db, domain_id, body.metric, origins, targets, body.network)
        for pid, key, attrs in periods:
            factor = (attrs or {}).get(field)
            if isinstance(factor, bool) or not isinstance(factor, (int, float)) or factor <= 0:
                raise HTTPException(422, f"the {kind.name} {key} has {field} {factor!r}: a speed factor is a number above 0")
            out.append((pid, values / float(factor)))  # half the speed, twice the time
    else:
        if body.metric != "network_time" or body.network is None:
            raise HTTPException(422, "speeds by period are read from an imported lines layer: metric network_time with its network")
        for pid, key, attrs in periods:
            speed = (attrs or {}).get(field)
            if not isinstance(speed, str) or not speed.strip():
                raise HTTPException(422, f"the {kind.name} {key} has no {field}: the lines' property holding its speeds")
            values, how = _measure(db, domain_id, body.metric, origins, targets, body.network.model_copy(update={"speed_field": speed.strip()}))
            out.append((pid, values))
    return out, {**how, "by_period": {"kind": kind.name, ("speed_field_from" if ask.speed_field_from else "factor_from"): field,
                                      "periods": len(periods)}}, kind.id


def _line_key(coords: list) -> tuple:
    return tuple((round(float(p[0]), 6), round(float(p[1]), 6)) for p in coords)


def _record_fields(db: Session, domain_id: int, lines: list, fields: list[str], layer: str) -> tuple[list, dict[str, str]]:
    """A speed, closure or delay field the lines do not hold, read from the records made from them --
    the same line, kept in a geometry field -- where one was computed (benchmark round 4: weather-adjusted
    speeds on the road records were ignored, and every road ran at the default speed, without a word).
    A field neither the lines nor any such records hold is refused by name."""
    missing = [f for f in fields if not any(f in (props or {}) for _, props in lines)]
    if not missing:
        return lines, {}
    keys = {_line_key(c) for c, _ in lines}
    found: dict[str, dict[tuple, Any]] = {f: {} for f in missing}
    kinds: dict[str, str] = {}
    rows = db.execute(text(
        "SELECT et.name, e.attrs, ad.name AS geo FROM entity e JOIN entity_type et ON et.id = e.entity_type_id"
        " JOIN attribute_def ad ON ad.entity_type_id = et.id AND ad.data_type = 'geometry'"
        " WHERE et.domain_id = :d AND e.active AND e.attrs ?| :f"), {"d": domain_id, "f": missing}).all()
    for kind, attrs, geo in rows:
        shape = (attrs or {}).get(geo)
        if not isinstance(shape, dict) or shape.get("type") != "LineString":
            continue
        key = _line_key(shape.get("coordinates") or [])
        if key not in keys:
            continue
        for f in missing:
            if (attrs or {}).get(f) is not None:
                found[f][key] = attrs[f]
                kinds[f] = kind
    absent = [f for f in missing if not found[f]]
    if absent:
        raise HTTPException(422, f"no line of layer {layer!r} holds {absent[0]!r}, and no record made from its lines has a field "
                                 f"of that name: choose one the lines or their records hold")
    out = [(c, {**(p or {}), **{f: found[f][_line_key(c)] for f in missing if _line_key(c) in found[f]}}) for c, p in lines]
    return out, {f: kinds[f] for f in missing}


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
    measured, how, period_type = _by_period(db, domain_id, body, origins, targets)
    index = [origin_type.id, target_type.id, *([period_type] if period_type else [])]
    if parameter is not None and list(parameter.index_type_ids) != index:
        raise HTTPException(409, f"{body.name!r} is already a parameter over other types; choose another name")
    if len(measured) * len(origins) * min(len(targets), body.nearest or len(targets)) > MAX_PAIRS * 4:
        raise HTTPException(422, f"{len(measured)} periods of {len(origins)} x {len(targets)} pairs is too many: keep each place's nearest few")
    scale, places_ = _SCALE[body.unit]
    longest = max(float(values[~np.isnan(values)].max(initial=0.0)) for _, values in measured)
    keep = body.nearest if body.nearest is not None else len(targets)
    cells, left_out, unreached = [], 0, []
    for period, values in measured:
        tail = [period] if period is not None else []
        for i, origin in enumerate(origins):
            row = values[i]
            order = np.argsort(np.where(np.isnan(row), np.inf, row), kind="stable")
            for j in order[:keep]:
                if np.isnan(row[j]):
                    left_out += 1  # no road joins them: left to the far default, never guessed
                    if len(unreached) < 20:
                        # Named, so the grid's far values can be told apart (benchmark round 5).
                        unreached.append(f"{origin.key} → {targets[int(j)].key}")
                    continue
                value = 0 if origin.entity_id == targets[j].entity_id else round(float(row[j]) / scale, places_)
                if places_ == 0:
                    value = int(value)
                cells.append({"entity_ids": [origin.entity_id, targets[int(j)].entity_id, *tail], "value": value})
    far = None
    if keep < len(targets) or left_out:
        # Pairs left out are far, not free: ten times the longest measured.
        far = math.ceil(longest * 10 / scale) if places_ == 0 else round(longest * 10 / scale, places_)
    source = {"kind": "distance", "unit": body.unit, **how, **({"nearest": body.nearest} if body.nearest else {}),
              "from": origin_type.name, "to": target_type.name, "pairs": len(cells),
              **({"far": far} if far is not None else {}), **({"no_road": left_out} if left_out else {}),
              **({"no_road_pairs": unreached} if unreached else {}),
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
    if body.by_period is not None and body.output != "parameter":
        raise HTTPException(422, "within reach by period is a 0/1 parameter name[from, to, period]: output parameter")
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
    measured, how, period_type = _by_period(db, domain_id, body, origins, targets)
    index = [origin_type.id, target_type.id, *([period_type] if period_type else [])]
    if parameter is not None and list(parameter.index_type_ids) != index:
        raise HTTPException(409, f"{body.name!r} is already a parameter over other types; choose another name")
    timed = body.metric in _TIMED
    cells = []
    for period, values in measured:
        tail = [period] if period is not None else []
        for i, origin in enumerate(origins):
            for j in np.flatnonzero(values[i] <= limit):
                cells.append({"entity_ids": [origin.entity_id, targets[int(j)].entity_id, *tail], "value": 1})
        if len(cells) > MAX_EDGES * 5:
            raise HTTPException(422, f"more than {MAX_EDGES * 5:,} pairs are within {limit:g}; choose a shorter reach")
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
