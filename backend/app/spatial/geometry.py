"""GeoJSON geometry, judged once, in words (spatial spec §2).

The database checks only that a geometry is an object of one of the three
types (migration 0049); this names the ring or position at fault, which is
what a planner fixing a file needs.
"""

from __future__ import annotations

from typing import Any

GEOMETRY_TYPES = ("Point", "Polygon", "MultiPolygon")
MAX_VERTICES = 10_000


def _position(p: Any) -> str | None:
    if not (
        isinstance(p, list)
        and len(p) in (2, 3)
        and all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in p)
    ):
        return f"position {p!r} is not two numbers"
    lon, lat = p[0], p[1]
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return f"position {p!r} is outside longitude -180..180 or latitude -90..90"
    return None


def _ring(ring: Any, n: int) -> tuple[str | None, int]:
    if not isinstance(ring, list):
        return f"ring {n} is not an array of positions", 0
    for p in ring:
        fault = _position(p)
        if fault:
            return fault, 0
    if len(ring) < 4:
        return f"ring {n} has {len(ring)} positions; a ring needs at least 4 (the first repeated last)", len(ring)
    if ring[0][:2] != ring[-1][:2]:
        return f"ring {n} is not closed: it starts at {ring[0]} and ends at {ring[-1]}", len(ring)
    return None, len(ring)


def _polygon(rings: Any, count: list[int]) -> str | None:
    if not isinstance(rings, list) or not rings:
        return "a polygon is a non-empty array of rings"
    for n, ring in enumerate(rings):
        fault, size = _ring(ring, n)
        count[0] += size
        if fault:
            return fault
    return None


def validate_geometry(value: Any) -> str | None:
    """None when `value` is a geometry this platform stores, else why not."""
    if not isinstance(value, dict):
        return "a geometry is a GeoJSON object, not text" if isinstance(value, str) else "a geometry is a GeoJSON object"
    kind = value.get("type")
    if kind not in GEOMETRY_TYPES:
        return f"a geometry is a Point, Polygon or MultiPolygon, not {kind}"
    coordinates = value.get("coordinates")
    if kind == "Point":
        return _position(coordinates)
    count = [0]
    if kind == "Polygon":
        fault = _polygon(coordinates, count)
    else:
        if not isinstance(coordinates, list) or not coordinates:
            return "a multipolygon is a non-empty array of polygons"
        fault = next((f for f in (_polygon(p, count) for p in coordinates) if f), None)
    if fault:
        return fault
    if count[0] > MAX_VERTICES:
        return f"this geometry has {count[0]} positions; the limit is {MAX_VERTICES}"
    return None
