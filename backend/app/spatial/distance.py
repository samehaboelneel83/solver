"""Distances between places, from their shapes (queue R16a).

A place is an entity with a geometry attribute: a point, or a polygon read
at its representative point (a point inside it, unlike a centroid, which a
crescent can put outside). Distances are geodesic -- on the WGS84 ellipsoid,
by pyproj's `Geod`, vectorised a row at a time -- in metres. Straight-line
distance is a floor on the road distance, not an estimate of it; the
source a caller records says which it was.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Place:
    entity_id: int
    key: str
    lon: float
    lat: float


def places(db: Session, entity_type_id: int) -> tuple[list[Place], list[str]]:
    """Every entity of the type with a shape, at a point; and the keys of those without one."""
    from shapely.geometry import shape

    rows = db.execute(
        text(
            "SELECT e.id, e.key, (SELECT e.attrs -> ad.name FROM attribute_def ad"
            "   WHERE ad.entity_type_id = e.entity_type_id AND ad.data_type::text = 'geometry' AND e.attrs ? ad.name"
            "   ORDER BY ad.sort_order, ad.name LIMIT 1) AS geometry"
            " FROM entity e WHERE e.entity_type_id = :t ORDER BY e.sort_order, e.key"
        ),
        {"t": entity_type_id},
    ).all()
    found, missing = [], []
    for entity_id, key, geometry in rows:
        if not geometry:
            missing.append(key)
            continue
        point = shape(geometry)
        if point.geom_type != "Point":
            point = point.representative_point()
        found.append(Place(entity_id, key, float(point.x), float(point.y)))
    return found, missing


def row(origin: Place, targets: list[Place], lons: np.ndarray | None = None, lats: np.ndarray | None = None) -> np.ndarray:
    """Metres from one place to each of many."""
    from pyproj import Geod

    if lons is None or lats is None:
        lons = np.array([t.lon for t in targets])
        lats = np.array([t.lat for t in targets])
    _, _, metres = Geod(ellps="WGS84").inv(np.full(len(lons), origin.lon), np.full(len(lats), origin.lat), lons, lats)
    return np.asarray(metres)


def matrix(origins: list[Place], targets: list[Place]) -> np.ndarray:
    """Metres from each origin to each target, one row per origin."""
    lons = np.array([t.lon for t in targets])
    lats = np.array([t.lat for t in targets])
    if not origins or not targets:
        return np.zeros((len(origins), len(targets)))
    return np.vstack([row(o, targets, lons, lats) for o in origins])


def describe(unit: str, nearest: int | None) -> dict[str, Any]:
    return {"kind": "distance", "metric": "straight line (geodesic, WGS84)", "unit": unit,
            **({"nearest": nearest} if nearest else {})}
