"""A camp from map data: any imported drawing's layers, each given a role.

The camp engine needs nothing camp-specific from a drawing: the person says
which layer is the boundary, which hold doors, closed areas, no-bed areas and
bed zones, and this builds the problem from those layers' features.

**The camp's own frame.** The camp is laid out in the drawing's own grid --
its coordinates times the placement's units (and scale) -- with (0, 0) at
the boundary's lower-left corner, so walls the drawing drew straight stay
straight and doors can sit on them. The origin's longitude and latitude
come from the dataset's placement. (A drawing in degrees is put into metres
around that corner instead.) The grid may differ from true north by the
projection's convergence (under 3° in a UTM zone); the camp's map shows it
north-up.

- boundary: the largest closed shape in its layer (or the largest area its lines enclose)
- doors: features in door layers that touch each other form one door (a
  leaf and its swing arc, a gate block); each is snapped onto the
  horizontal or vertical wall it touches; a text nearby names it
- closed / no-bed / zone areas: closed shapes, named by a text inside them
"""
from __future__ import annotations

import math
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.camp.engine import serial
from app.gis import crs
from camp_layout.dxf import _snap_block, _snap_door
from camp_layout.problem import CampProblem, Door, DoorZone, Obstacle, PlacementZone, Prohibited
from camp_layout.workbook import DEFAULT_BEDS

DOOR_GAP = 0.3
SNAP = 0.5


class FromMapError(ValueError):
    """The chosen layers do not make a camp; the message says why."""


def _slug(words: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "-", words.strip()).strip("-")[:60] or "unnamed"


def build(db: Session, dataset_id: int, roles: dict[str, list[int]], name: str) -> tuple[dict[str, Any], list[str]]:
    from shapely.geometry import LineString, MultiLineString, Point, Polygon, box, shape
    from shapely.ops import polygonize, unary_union

    ds = db.execute(text("SELECT placement, source FROM gis_dataset WHERE id = :d"), {"d": dataset_id}).mappings().one()
    wanted = sorted({i for ids in roles.values() for i in ids})
    rows = db.execute(text(
        "SELECT f.kind, f.geometry, f.source, f.properties, f.layer_id, l.name AS layer FROM gis_feature f"
        " JOIN gis_layer l ON l.id = f.layer_id WHERE f.dataset_id = :d AND f.layer_id = ANY(:ids)"),
        {"d": dataset_id, "ids": wanted}).mappings().all()
    notes: list[str] = []
    placement = crs.Placement.parse(ds["placement"], ds["placement"].get("units"))
    geographic = placement.kind == "epsg" and crs.crs_info(placement.code)["geographic"]
    k = placement.units * (placement.scale if placement.kind == "local" else 1.0)

    def coords_of(row) -> Any:
        """The feature in drawing metres (or WGS 84 degrees for a drawing in degrees)."""
        if geographic or not row["source"]:
            g = row["geometry"]
            return g["coordinates"]
        c = row["source"]["coords"]
        if row["kind"] in ("point", "text"):
            return [c[0] * k, c[1] * k]
        if row["kind"] == "line":
            return [[p[0] * k, p[1] * k] for p in c]
        return [[[p[0] * k, p[1] * k] for p in ring] for ring in c]

    def geom(row):
        c = coords_of(row)
        if row["kind"] in ("point", "text"):
            return Point(c)
        if row["kind"] == "line":
            return LineString(c) if len(c) >= 2 else None
        return Polygon(c[0], c[1:]) if len(c[0]) >= 4 else None

    by_role: dict[str, list[Any]] = {r: [] for r in ("boundary", "doors", "obstacles", "prohibited", "zones")}
    texts: dict[int, list[tuple[Any, str]]] = {}
    for row in rows:
        g = geom(row)
        if g is None or g.is_empty:
            continue
        if row["kind"] == "text":
            texts.setdefault(row["layer_id"], []).append((g, str(row["properties"].get("text", ""))))
        for role, ids in roles.items():
            if row["layer_id"] in ids and row["kind"] != "text":
                by_role[role].append((row, g))

    def areas(items) -> list[tuple[Any, Any]]:
        """Closed shapes, and the areas lines enclose."""
        polys = [(row, g.buffer(0)) for row, g in items if g.geom_type == "Polygon"]
        lines = [g for _, g in items if g.geom_type == "LineString"]
        if lines:
            for p in polygonize(unary_union(MultiLineString([list(l.coords) for l in lines]))):
                polys.append((None, p))
        return [(r, p) for r, p in polys if p.area > 0.01]

    outline = areas(by_role["boundary"])
    if not outline:
        raise FromMapError("the boundary layer has no closed shape (and its lines enclose no area)")
    camp = max(outline, key=lambda rp: rp[1].area)[1]
    if len(outline) > 1:
        notes.append(f"{len(outline)} closed shapes on the boundary layer: the largest is the camp")
    camp = camp.simplify(0.001)
    minx, miny = camp.bounds[0], camp.bounds[1]

    if geographic:
        from pyproj import Transformer
        lon0, lat0 = minx, miny
        to_m = Transformer.from_crs("EPSG:4326", f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +units=m +ellps=WGS84", always_xy=True)
        from shapely.ops import transform as shp_transform
        local = lambda g: shp_transform(lambda x, y, z=None: to_m.transform(x, y), g)
        origin = (lon0, lat0)
        notes.append("the drawing is in degrees: the camp is laid out in metres around its south-west corner")
    else:
        from shapely.affinity import translate
        local = lambda g: translate(g, -minx, -miny)
        lon, lat = placement.transformer()(minx / k, miny / k)
        origin = (round(float(lon), 7), round(float(lat), 7))

    def ring(p) -> list[tuple[float, float]]:
        pts = [(round(x, 3), round(y, 3)) for x, y in list(p.exterior.coords)[:-1]]
        return [q for i, q in enumerate(pts) if i == 0 or q != pts[i - 1]]

    boundary = ring(local(camp))
    camp_local = Polygon(boundary)
    edges = list(zip(boundary, boundary[1:] + boundary[:1]))
    axis = sum(1 for a, b in edges if math.isclose(a[0], b[0], abs_tol=1e-6) or math.isclose(a[1], b[1], abs_tol=1e-6))
    if axis == 0:
        notes.append("no wall of the boundary is horizontal or vertical in the drawing's grid: doors cannot sit on it")

    def named(poly, layer_id_list: list[int], fallback: str) -> str:
        for lid in layer_id_list:
            for point, words in texts.get(lid, []):
                if words and poly.buffer(0.5).contains(local(point)):
                    return _slug(words)
        return fallback

    # Doors: touching pieces are one door.
    pieces = [local(g) for _, g in by_role["doors"]]
    clusters = list(getattr(unary_union([p.buffer(DOOR_GAP / 2) for p in pieces]), "geoms", [])) if pieces else []
    if pieces and not clusters:
        clusters = [unary_union([p.buffer(DOOR_GAP / 2) for p in pieces])]
    doors: list[Door] = []
    skipped = 0
    for n, blob in enumerate(sorted(clusters, key=lambda c: (c.centroid.x, c.centroid.y)), start=1):
        inside = [p for p in pieces if p.intersects(blob)]
        straight = [p for p in inside if p.geom_type == "LineString" and len(p.coords) == 2]
        if len(inside) == 1 and straight:
            got = _snap_door(straight[0], edges, SNAP)
        else:
            x0, y0, x1, y1 = unary_union(inside).bounds
            got = _snap_block(box(x0, y0, x1, y1), edges, SNAP)
        if got is None:
            skipped += 1
            continue
        a, b = got
        mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        label = None
        for lid in roles.get("doors", []):
            for point, words in texts.get(lid, []):
                if words and local(point).distance(mid) < 3:
                    label = _slug(words)
        door_id = label if label and label not in {d.id for d in doors} else f"D{n}"
        doors.append(Door(door_id, a, b))
    if skipped:
        notes.append(f"{skipped} door shapes are not on a horizontal or vertical wall of the camp and were left out")
    if not doors:
        notes.append("no door was found on the boundary's walls: add them on the map")

    def shapes(role: str, base: str) -> list[tuple[str, list[tuple[float, float]]]]:
        out = []
        found = areas(by_role[role])
        per_layer: dict[str, int] = {}
        for row, _ in found:
            per_layer[row["layer"] if row else base] = per_layer.get(row["layer"] if row else base, 0) + 1
        for i, (row, p) in enumerate(found, start=1):
            lp = local(p).intersection(camp_local.buffer(0.001))
            if lp.is_empty or lp.geom_type != "Polygon":
                continue
            layer_ids = [row["layer_id"]] if row else roles.get(role, [])
            layer_name = row["layer"] if row else base
            stem = re.sub(r"^zone[_ -]+", "", layer_name, flags=re.I).lower() if role == "zones" else layer_name
            # One shape on its layer is named for the layer; several are numbered.
            fallback = _slug(stem if per_layer[layer_name] == 1 else f"{stem}-{i}")
            sid = named(lp, layer_ids, fallback)
            while sid in {s for s, _ in out}:
                sid = f"{sid}-{i}"
            out.append((sid, ring(lp)))
        return out

    problem = CampProblem(
        name=name,
        boundary=boundary,
        doors=tuple(doors),
        zones=tuple(DoorZone(d.id, area_per_bed=0.25) for d in doors),
        obstacles=tuple(Obstacle(i, r) for i, r in shapes("obstacles", "closed")),
        prohibited=tuple(Prohibited(i, r) for i, r in shapes("prohibited", "no-beds")),
        placement_zones=tuple(PlacementZone(i, r) for i, r in shapes("zones", "zone")),
        bed_types=tuple(DEFAULT_BEDS),
        origin_lonlat=origin,
    )
    notes.insert(0, f"{len(doors)} doors, {len(problem.obstacles)} closed areas, {len(problem.prohibited)} no-bed areas, "
                    f"{len(problem.placement_zones)} bed zones from the map data; review the beds and door settings")
    return serial.to_dict(problem), notes
