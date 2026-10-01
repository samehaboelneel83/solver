"""Drawing features to GIS features (DXF -> GIS, step 3: geometry in WGS 84).

`to_geojson` places every feature of a drawing with one `Placement`
(`app.gis.crs`): all coordinates are transformed in one vectorised call, then
split back into GeoJSON geometries in longitude and latitude, rounded to
1e-7 degrees (about a centimetre). A polygon that crosses itself is repaired
(`make_valid`) and noted; one that collapses is dropped and counted.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from app.gis.cad import CadFeature
from app.gis.crs import Placement

PRECISION = 7


def _flat(f: CadFeature) -> list[list[float]]:
    if f.kind in ("point", "text"):
        return [f.coords]
    if f.kind == "line":
        return f.coords
    return [p for ring in f.coords for p in ring]


def _rebuild(f: CadFeature, pts: np.ndarray) -> dict[str, Any]:
    r = lambda a: [round(float(a[0]), PRECISION), round(float(a[1]), PRECISION)]
    if f.kind in ("point", "text"):
        return {"type": "Point", "coordinates": r(pts[0])}
    if f.kind == "line":
        return {"type": "LineString", "coordinates": [r(p) for p in pts]}
    rings, at = [], 0
    for ring in f.coords:
        rings.append([r(p) for p in pts[at:at + len(ring)]])
        at += len(ring)
    return {"type": "Polygon", "coordinates": rings}


def _valid(geometry: dict[str, Any]) -> list[dict[str, Any]]:
    """A polygon as one or more valid polygons; others as they are."""
    if geometry["type"] != "Polygon":
        return [geometry]
    from shapely.geometry import mapping, shape
    from shapely.validation import make_valid

    g = shape(geometry)
    if g.is_valid and not g.is_empty:
        return [geometry]
    fixed = make_valid(g)
    parts = [p for p in getattr(fixed, "geoms", [fixed]) if p.geom_type == "Polygon" and not p.is_empty]
    if fixed.geom_type == "Polygon" and not fixed.is_empty:
        parts = [fixed]
    out = []
    for p in parts:
        m = mapping(p)
        out.append({"type": "Polygon", "coordinates": [[list(c[:2]) for c in ring] for ring in m["coordinates"]]})
    return out


def transform_all(features: list[CadFeature], placement: Placement) -> list[np.ndarray]:
    """Each feature's points in longitude and latitude, from one transform call."""
    counts = [len(_flat(f)) for f in features]
    if not counts:
        return []
    xy = np.array([p[:2] for f in features for p in _flat(f)], dtype=float)
    lon, lat = placement.transformer()(xy[:, 0], xy[:, 1])
    both = np.column_stack([lon, lat])
    out, at = [], 0
    for n in counts:
        out.append(both[at:at + n])
        at += n
    return out


def place(features: list[CadFeature], placement: Placement) -> tuple[list[tuple[int, dict[str, Any]]], dict[str, int]]:
    """Each feature's geometry in WGS 84, as (index of the drawing feature, GeoJSON geometry) pairs:
    a polygon repaired into two parts gives two pairs with the same index."""
    out: list[tuple[int, dict[str, Any]]] = []
    stats = {"repaired": 0, "dropped": 0}
    for i, (f, pts) in enumerate(zip(features, transform_all(features, placement))):
        if not np.all(np.isfinite(pts)):
            stats["dropped"] += 1
            continue
        geometry = _rebuild(f, pts)
        parts = _valid(geometry)
        if not parts:
            stats["dropped"] += 1
            continue
        if parts[0] is not geometry:
            stats["repaired"] += 1
        out.extend((i, g) for g in parts)
    return out, stats


def to_geojson(features: Iterable[CadFeature], placement: Placement) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """GeoJSON features (WGS 84) and what happened on the way: repaired and dropped polygons."""
    features = list(features)
    placed, stats = place(features, placement)
    out = [{"type": "Feature", "geometry": g,
            "properties": {"layer": features[i].layer, "kind": features[i].kind, "entity": features[i].entity,
                           **features[i].props}} for i, g in placed]
    return out, stats


def bounds(features: list[dict[str, Any]]) -> list[float] | None:
    xs, ys = [], []
    for f in features:
        g = f["geometry"]
        pts = [g["coordinates"]] if g["type"] == "Point" else g["coordinates"] if g["type"] == "LineString" \
            else g["coordinates"][0]
        for x, y in pts:
            xs.append(x)
            ys.append(y)
    return [min(xs), min(ys), max(xs), max(ys)] if xs else None
