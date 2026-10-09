"""A spatial run's answer on a map (GIS 7, spatial spec §6).

    GET /api/v1/runs/{id}/map[?dissolve=true]

GeoJSON from the run's own records -- the frozen dataset it solved and the
solution it stored, never today's entities: a cell edited since the run is
drawn as the run saw it. One Feature per unit, with its group (and
sub-group, when a second `connected` rule nests one), or, dissolved, one per
group with its cell count and the totals of its units' numbers.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from shapely.geometry import mapping, shape
from shapely import normalize
from shapely.ops import unary_union
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.iam import UserAccount
from app.models.v1_problem import Run

router = APIRouter(prefix="/api/v1", tags=["spatial"])

NOT_SPATIAL = "this run has no connected rule over units with a geometry"
#: A grid cell's own bookkeeping: not a quantity to add up per zone.
_NOT_TOTALLED = frozenset({"row", "col", "coverage"})


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _shape_attribute(rows: list[dict[str, Any]]) -> str | None:
    """The attribute holding each unit's area: `geometry` when a grid made
    it, else the first polygon-valued one (never a centroid)."""
    def is_area(value: Any) -> bool:
        return isinstance(value, dict) and value.get("type") in ("Polygon", "MultiPolygon")

    if rows and all(is_area(row.get("geometry")) for row in rows):
        return "geometry"
    for row in rows:
        for key, value in row.items():
            if is_area(value):
                return key
    return None


def _groups(assignments: dict[str, Any], rule: dict[str, Any] | None) -> dict[str, str]:
    if rule is None:
        return {}
    return {str(pair[0]): str(pair[1]) for pair in assignments.get(rule["assign"]["var"], []) if len(pair) == 2}


def run_features(db: Session, run_id: int) -> list[dict[str, Any]]:
    """One Feature per unit of the run's first `connected` rule; 404 when there is none to draw."""
    row = db.execute(
        text(
            "SELECT mv.ir, d.data, sol.assignments FROM run r JOIN scenario s ON s.id = r.scenario_id"
            " JOIN model_version mv ON mv.id = r.model_version_id JOIN dataset d ON d.id = r.dataset_id"
            " LEFT JOIN solution sol ON sol.run_id = r.id WHERE r.id = :r"
        ),
        {"r": run_id},
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "run not found")
    ir, data, assignments = row
    from app.solve.generate import for_run

    data = for_run(run_id, ir or {}, data or {})
    rules = [c["connected"] for c in ir.get("constraints", []) if isinstance(c, dict) and "connected" in c]
    if not rules:
        raise HTTPException(404, NOT_SPATIAL)
    top = rules[0]
    # A second rule over the same units nests sub-groups inside the groups.
    sub = next((r for r in rules[1:] if r["units"]["set"] == top["units"]["set"]), None)
    units = (data.get("sets") or {}).get(top["units"]["set"], [])
    attribute = _shape_attribute(units)
    if attribute is None:
        raise HTTPException(404, NOT_SPATIAL)
    if not assignments:
        raise HTTPException(404, "this run has no answer to draw yet")
    group, subgroup = _groups(assignments, top), _groups(assignments, sub)
    features = []
    for unit in units:
        if not isinstance(unit.get(attribute), dict):
            continue  # a unit with no shape is not drawn, and not guessed
        key = str(unit["id"])
        numbers = {k: v for k, v in unit.items() if k != "id" and _is_number(v)}
        features.append(
            {
                "type": "Feature",
                "geometry": unit[attribute],
                "properties": {"key": key, "group": group.get(key), "subgroup": subgroup.get(key), **numbers},
            }
        )
    return features


def dissolve(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One Feature per (group, sub-group): the union of its units, its cell
    count and the totals of their numbers. Units in no group are a group of
    their own (`null`), so nothing drawn per cell disappears here."""
    by: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for feature in features:
        properties = feature["properties"]
        by.setdefault((properties["group"], properties["subgroup"]), []).append(feature)
    out = []
    for (group, subgroup), members in sorted(by.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        totals: dict[str, float] = {}
        for member in members:
            for key, value in member["properties"].items():
                if key not in ("key", "group", "subgroup") and key not in _NOT_TOTALLED and _is_number(value):
                    totals[key] = totals.get(key, 0) + value
        # The points where two cells met stay on the outline, a hair off the
        # straight line after reprojection; a tolerance of 1e-9 CRS units (a
        # tenth of a millimetre in degrees) drops them and moves nothing else.
        # Normalized first: simplifying never drops a ring's first point, and a
        # union of two stacked cells can start its outline on such a point.
        union = normalize(unary_union([shape(member["geometry"]).buffer(0) for member in members])).simplify(1e-9)
        out.append(
            {
                "type": "Feature",
                "geometry": mapping(union),
                "properties": {"group": group, "subgroup": subgroup, "cells": len(members), **totals},
            }
        )
    return out


@router.get("/runs/{run_id}/map")
def run_map(
    run_id: int,
    dissolve_groups: bool = Query(default=False, alias="dissolve"),
    quiet: bool = Query(default=False, description="a run with no map answers 200, empty, with why (F7)"),
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> dict[str, Any]:
    if db.get(Run, run_id) is None:
        raise HTTPException(404, "run not found")
    try:
        features = run_features(db, run_id)
    except HTTPException as exc:
        # A run page asks every answered run for its map; most have none, which is not an error.
        if not quiet:
            raise
        return {"type": "FeatureCollection", "features": [], "none": exc.detail}
    return {"type": "FeatureCollection", "features": dissolve(features) if dissolve_groups else features}


def _is_shape(value: Any) -> bool:
    return (isinstance(value, dict) and value.get("type") in ("Point", "LineString", "MultiLineString", "Polygon", "MultiPolygon")
            and isinstance(value.get("coordinates"), list))


@router.get("/runs/{run_id}/places")
def run_places(
    run_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
) -> dict[str, dict[str, list[float]]]:
    """Where each member of each located set stood when the run was made (queue R17b's answer
    maps): `{set: {key: [x, y]}}`, a point as given and a shape at its centroid, from the frozen
    dataset. Sets with no shape are left out; an empty object means nothing to map."""
    if db.get(Run, run_id) is None:
        raise HTTPException(404, "run not found")
    found_run = db.execute(
        text("SELECT mv.ir, d.data -> 'sets' FROM run r JOIN dataset d ON d.id = r.dataset_id"
             " JOIN model_version mv ON mv.id = r.model_version_id WHERE r.id = :r"),
        {"r": run_id},
    ).one()
    data = found_run[1] or {}
    if (found_run[0] or {}).get("generate"):
        from app.solve.generate import for_run

        full = db.execute(text("SELECT d.data FROM run r JOIN dataset d ON d.id = r.dataset_id WHERE r.id = :r"),
                          {"r": run_id}).scalar() or {}
        data = for_run(run_id, found_run[0], full).get("sets") or {}
    places: dict[str, dict[str, list[float]]] = {}
    for set_name, rows in data.items():
        found: dict[str, list[float]] = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            geometry = next((v for v in row.values() if _is_shape(v)), None)
            if geometry is None:
                continue
            try:
                point = shape(geometry).centroid if geometry["type"] != "Point" else shape(geometry)
            except Exception:  # noqa: BLE001 -- a shape the run cannot read is simply not placed
                continue
            found[str(row.get("id"))] = [round(point.x, 7), round(point.y, 7)]
        if found:
            places[set_name] = found
    return places
