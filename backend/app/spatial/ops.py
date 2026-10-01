"""Spatial measures as ordinary data (improvement plan, phase 2).

Each operation reads the shapes of records -- any kind with a `geometry`
field -- and answers in plain numbers and pairs, which `app.api.spatial_ops`
writes as a field, a parameter or a relationship, with where they came from.
Nothing here knows what the places are.

- `inside`:  each place in the area that contains it (a stop in its zone, a
  hotspot in its district). A place on no area, or on a shared border,
  takes the area it is nearest the inside of; one on none at all is listed.
- `count_within`: how many of the others lie within so many metres
  (schools near a hotspot, customers near a depot).
- `nearest`: each place's k nearest others, ranked, with the metres.
- `touching`: areas that share a border (fields, districts, zones).
- `overlap_m2`: the area two shapes share, in square metres.

Distances are geodesic on WGS 84, as `app.spatial.distance` measures them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Shape:
    entity_id: int
    key: str
    geometry: Any  # a shapely geometry, WGS 84 lon/lat


def shapes_fingerprint(db, entity_type_ids: list[int]) -> str:
    """One hash of where every record of these kinds is (its id and its first shape), so data
    computed from the map can tell later whether the places moved, came or went -- and not mistake
    an edited field (a name, a count, a height) for a move."""
    from sqlalchemy import text

    return db.execute(
        text(
            "SELECT md5(coalesce(string_agg(e.id::text || ':' || coalesce((SELECT (e.attrs -> ad.name)::text"
            "   FROM attribute_def ad WHERE ad.entity_type_id = e.entity_type_id AND ad.data_type::text = 'geometry'"
            "   AND e.attrs ? ad.name ORDER BY ad.sort_order, ad.name LIMIT 1), ''), ',' ORDER BY e.id), ''))"
            " FROM entity e WHERE e.entity_type_id = ANY(:t)"
        ),
        {"t": list(entity_type_ids)},
    ).scalar_one()


def load(db, entity_type_id: int) -> tuple[list[Shape], list[str]]:
    """Every record of the kind with a shape; and the keys of those without one."""
    from shapely.geometry import shape
    from sqlalchemy import text

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
        found.append(Shape(entity_id, key, shape(geometry)))
    return found, missing


def _point(geometry) -> tuple[float, float]:
    p = geometry if geometry.geom_type == "Point" else geometry.representative_point()
    return float(p.x), float(p.y)


def metres(origins: list[Shape], targets: list[Shape]) -> np.ndarray:
    """Geodesic metres between each origin's point and each target's point."""
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    if not origins or not targets:
        return np.zeros((len(origins), len(targets)))
    tx = np.array([_point(t.geometry)[0] for t in targets])
    ty = np.array([_point(t.geometry)[1] for t in targets])
    rows = []
    for o in origins:
        ox, oy = _point(o.geometry)
        _, _, d = geod.inv(np.full(len(tx), ox), np.full(len(ty), oy), tx, ty)
        rows.append(np.asarray(d))
    return np.vstack(rows)


def inside(places: list[Shape], areas: list[Shape]) -> tuple[list[tuple[int, int]], list[str]]:
    """(place id, area id) for each place in an area; the keys of places in none."""
    from shapely.strtree import STRtree

    polys = [a for a in areas if a.geometry.geom_type in ("Polygon", "MultiPolygon")]
    if not polys:
        return [], [p.key for p in places]
    tree = STRtree([a.geometry for a in polys])
    pairs, outside = [], []
    for place in places:
        from shapely.geometry import Point

        pt = Point(*_point(place.geometry))
        hits = [polys[int(i)] for i in tree.query(pt) if polys[int(i)].geometry.covers(pt)]
        if not hits:
            outside.append(place.key)
            continue
        # On a shared border: the area whose inside is nearest wins, the same way every time.
        best = min(hits, key=lambda a: (a.geometry.boundary.distance(pt) * (-1 if a.geometry.contains(pt) else 1), a.key))
        pairs.append((place.entity_id, best.entity_id))
    return pairs, outside


def count_within(origins: list[Shape], targets: list[Shape], max_m: float) -> list[int]:
    """How many targets lie within `max_m` metres of each origin (itself not counted)."""
    d = metres(origins, targets)
    counts = []
    for i, o in enumerate(origins):
        near = d[i] <= max_m
        counts.append(int(sum(1 for j in np.flatnonzero(near) if targets[int(j)].entity_id != o.entity_id)))
    return counts


def nearest(origins: list[Shape], targets: list[Shape], k: int) -> list[tuple[int, int, int, float]]:
    """(origin id, target id, rank from 1, metres) for each origin's k nearest targets."""
    d = metres(origins, targets)
    out = []
    for i, o in enumerate(origins):
        order = [int(j) for j in np.argsort(d[i], kind="stable") if targets[int(j)].entity_id != o.entity_id][:k]
        out += [(o.entity_id, targets[j].entity_id, rank, float(d[i][j])) for rank, j in enumerate(order, start=1)]
    return out


def touching(areas: list[Shape], tolerance_m: float = 1.0) -> list[tuple[int, int, float]]:
    """(a, b, shared border metres) for areas sharing a border -- both ways, a corner is not a border."""
    from pyproj import Geod
    from shapely.strtree import STRtree

    polys = [a for a in areas if a.geometry.geom_type in ("Polygon", "MultiPolygon")]
    if len(polys) < 2:
        return []
    geod = Geod(ellps="WGS84")
    # A tolerance in degrees from metres at the areas' latitude, so a drawing's tiny gaps still touch.
    lat = float(np.mean([_point(p.geometry)[1] for p in polys]))
    tol = tolerance_m / (111_320.0 * max(0.1, np.cos(np.radians(lat))))
    grown = [p.geometry.buffer(tol) for p in polys]
    tree = STRtree(grown)
    pairs = []
    for i, a in enumerate(polys):
        for j in (int(j) for j in tree.query(grown[i])):
            if j <= i:
                continue
            shared = grown[i].intersection(polys[j].geometry.boundary)
            length = geod.geometry_length(shared) if not shared.is_empty else 0.0
            if length > 2 * tolerance_m:
                pairs.append((a.entity_id, polys[j].entity_id, round(length, 1)))
                pairs.append((polys[j].entity_id, a.entity_id, round(length, 1)))
    return pairs


def overlap_m2(origins: list[Shape], targets: list[Shape]) -> list[tuple[int, int, float]]:
    """(origin id, target id, m2 shared) for every pair of areas that overlap."""
    from pyproj import Geod
    from shapely.strtree import STRtree

    geod = Geod(ellps="WGS84")
    tpolys = [t for t in targets if t.geometry.geom_type in ("Polygon", "MultiPolygon")]
    if not tpolys:
        return []
    tree = STRtree([t.geometry for t in tpolys])
    out = []
    for o in origins:
        if o.geometry.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        for j in (int(j) for j in tree.query(o.geometry)):
            shared = o.geometry.intersection(tpolys[j].geometry)
            if shared.is_empty:
                continue
            area = abs(geod.geometry_area_perimeter(shared)[0])
            if area >= 0.5:
                out.append((o.entity_id, tpolys[j].entity_id, round(area, 1)))
    return out


def heights(shapes: list[Shape], sampler) -> list[tuple[float, float] | None]:
    """Each place's ground height (m) and slope (%), from a terrain sampler (`app.spatial.terrain`):
    a point at its spot (slope 0, one sample cannot give one), an area or a line's buffer averaged over
    its samples. None where the terrain does not reach -- listed by the caller, never a made-up zero."""
    from app.spatial.terrain import cell_terrain

    out: list[tuple[float, float] | None] = []
    for s in shapes:
        geometry = s.geometry
        if geometry.geom_type == "Point":
            h = sampler.height(float(geometry.x), float(geometry.y))
            out.append(None if h is None else (float(h), 0.0))
            continue
        if geometry.geom_type in ("LineString", "MultiLineString"):
            geometry = geometry.buffer(0.0001)
        area = geometry if geometry.geom_type == "Polygon" else max(getattr(geometry, "geoms", [geometry]), key=lambda g: g.area)
        out.append(cell_terrain(area, sampler))
    return out
