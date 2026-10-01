"""CAD drawing (.dxf) -> camp geometry.

The drawing says *where* things are; a layer says *what* they are:

| role            | layers (case-insensitive)                                   | entities |
|-----------------|-------------------------------------------------------------|----------|
| boundary        | CAMP_BOUNDARY, BOUNDARY, CAMP, SITE                          | the largest closed shape |
| doors           | DOORS, DOOR, GATES, GATE, ENTRANCES                           | a line or open polyline along the boundary, or a block reference (its extent is projected onto the nearest wall) |
| obstacles       | OBSTACLES, OBSTACLE, CLOSED, CLOSED_AREAS, FIXED              | closed shapes: polylines, circles, ellipses, closed splines, hatches |
| prohibited      | NO_BEDS, PROHIBITED, FIRE_BREAK, KEEP_CLEAR                   | closed shapes: no beds, walkable |
| placement zones | ZONE_<name>                                                   | closed shapes; the zone is named <name> |

A TEXT or MTEXT on the same layer inside a shape (or, for a door, nearest to
it) names it; otherwise it is numbered. Curves are flattened to 5 cm chords.

Units: the drawing's $INSUNITS (mm, cm, m, inch, foot) unless given; an
unitless drawing is taken as metres, and one more than 2 km across as
millimetres -- with a warning either way. Surveyed drawings (coordinates in the
hundreds of thousands) are moved to a local origin; the offset is kept, and
with a CRS (an EPSG code) the origin's longitude/latitude is computed for GIS.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point, Polygon, box

ROLES = {
    "boundary": ("CAMP_BOUNDARY", "BOUNDARY", "CAMP", "SITE"),
    "doors": ("DOORS", "DOOR", "GATES", "GATE", "ENTRANCES", "ENTRANCE"),
    "obstacles": ("OBSTACLES", "OBSTACLE", "CLOSED", "CLOSED_AREAS", "FIXED"),
    "prohibited": ("NO_BEDS", "PROHIBITED", "FIRE_BREAK", "KEEP_CLEAR"),
}
ZONE_PREFIX = "ZONE_"
UNITS = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}
UNIT_NAMES = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254, "ft": 0.3048}
FLATTEN = 0.005  # metres: the most a curve is cut inside its arc


@dataclass
class Shape:
    id: str
    polygon: Polygon
    layer: str


@dataclass
class DoorLine:
    id: str
    a: tuple[float, float]
    b: tuple[float, float]
    layer: str


@dataclass
class Drawing:
    boundary: Polygon
    doors: list[DoorLine] = field(default_factory=list)
    obstacles: list[Shape] = field(default_factory=list)
    prohibited: list[Shape] = field(default_factory=list)
    zones: list[Shape] = field(default_factory=list)
    scale: float = 1.0  # drawing units -> metres
    offset: tuple[float, float] = (0.0, 0.0)  # metres subtracted from every coordinate
    origin_lonlat: tuple[float, float] | None = None
    notes: list[str] = field(default_factory=list)


class DrawingError(ValueError):
    pass


def _role(layer: str) -> tuple[str, str | None] | None:
    name = layer.upper()
    if name.startswith(ZONE_PREFIX) and len(name) > len(ZONE_PREFIX):
        return "zones", layer[len(ZONE_PREFIX):].lower().replace("_", "-")
    for role, names in ROLES.items():
        if name in names:
            return role, None
    return None


def _points(entity, scale: float) -> tuple[list[tuple[float, float]], bool] | None:
    """The entity's outline as points (metres) and whether it is closed."""
    from ezdxf import path as dxfpath

    kind = entity.dxftype()
    try:
        if kind == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            return [(s.x * scale, s.y * scale), (e.x * scale, e.y * scale)], False
        if kind == "HATCH":
            best = None
            for p in dxfpath.from_hatch(entity):
                pts = [(v.x * scale, v.y * scale) for v in p.flattening(FLATTEN / scale)]
                if best is None or len(pts) > len(best):
                    best = pts
            return (best, True) if best else None
        if kind in ("LWPOLYLINE", "POLYLINE", "CIRCLE", "ELLIPSE", "SPLINE", "ARC"):
            p = dxfpath.make_path(entity)
            pts = [(v.x * scale, v.y * scale) for v in p.flattening(FLATTEN / scale)]
            closed = kind in ("CIRCLE",) or (kind == "ELLIPSE" and math.isclose(
                abs(entity.dxf.end_param - entity.dxf.start_param), 2 * math.pi, abs_tol=1e-6)) or \
                bool(getattr(entity, "closed", False)) or getattr(entity.dxf, "flags", 0) & 1 == 1 or \
                (len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6)
            return pts, closed
    except Exception:  # noqa: BLE001 -- an unreadable entity is reported, not fatal
        return None
    return None


def _polygon(pts) -> Polygon | None:
    if len(pts) < 3:
        return None
    if math.dist(pts[0], pts[-1]) < 1e-9:
        pts = pts[:-1]
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly if isinstance(poly, Polygon) and poly.area > 1e-6 else None


def _clean(ring: list[tuple[float, float]], tol: float = 1e-6) -> list[tuple[float, float]]:
    """Drop repeated and collinear vertices, so a wall is one edge."""
    out: list[tuple[float, float]] = []
    for p in ring:
        if not out or math.dist(out[-1], p) > tol:
            out.append(p)
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
            if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < tol:
                out.pop(i)
                changed = True
                break
    return out


def read_dxf(path: str, *, units: str | None = None, crs: str | None = None, snap: float = 0.25) -> Drawing:
    import ezdxf

    try:
        doc = ezdxf.readfile(path)
    except (OSError, ezdxf.DXFStructureError) as exc:
        raise DrawingError(f"{path} is not a readable DXF file: {exc}") from exc
    notes: list[str] = []
    if units:
        if units not in UNIT_NAMES:
            raise DrawingError(f"unknown units {units!r}; use one of {', '.join(UNIT_NAMES)}")
        scale = UNIT_NAMES[units]
    else:
        code = doc.header.get("$INSUNITS", 0)
        scale = UNITS.get(code, 1.0)
        if code not in UNITS:
            notes.append("the drawing names no units: read as metres")
    msp = doc.modelspace()

    found: dict[str, list] = {"boundary": [], "doors": [], "obstacles": [], "prohibited": [], "zones": []}
    texts: dict[str, list[tuple[Point, str]]] = {}
    ignored: dict[str, int] = {}
    for e in msp:
        layer = e.dxf.layer
        role = _role(layer)
        if e.dxftype() in ("TEXT", "MTEXT"):
            if role:
                txt = e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text
                ins = e.dxf.insert
                texts.setdefault(role[0] + (role[1] or ""), []).append((Point(ins.x * scale, ins.y * scale), txt.strip()))
            continue
        if role is None:
            ignored[layer] = ignored.get(layer, 0) + 1
            continue
        found[role[0]].append((e, role[1]))
    if ignored:
        notes.append("ignored layers: " + ", ".join(f"{k} ({n})" for k, n in sorted(ignored.items())))

    # Boundary: the largest closed shape.
    candidates = []
    for e, _ in found["boundary"]:
        got = _points(e, scale)
        if got and got[1]:
            poly = _polygon(got[0])
            if poly is not None:
                candidates.append(poly)
    if not candidates:
        raise DrawingError("no closed shape on a boundary layer (CAMP_BOUNDARY, BOUNDARY, CAMP or SITE)")
    boundary = max(candidates, key=lambda p: p.area)
    if len(candidates) > 1:
        notes.append(f"{len(candidates)} closed shapes on the boundary layer: the largest is the camp")

    # A surveyed drawing: move it near the origin.
    minx, miny, maxx, maxy = boundary.bounds
    if not units and doc.header.get("$INSUNITS", 0) not in UNITS and max(maxx - minx, maxy - miny) > 2000:
        notes.append("the camp is over 2 km across in unitless drawing units: read as millimetres")
        return read_dxf(path, units="mm", crs=crs, snap=snap)
    offset = (0.0, 0.0)
    if max(abs(minx), abs(miny)) > 10_000:
        offset = (math.floor(minx), math.floor(miny))
        notes.append(f"surveyed coordinates moved by ({offset[0]:.0f}, {offset[1]:.0f}) m to a local origin")

    def local_poly(poly: Polygon) -> Polygon:
        return Polygon([(round(x - offset[0], 4), round(y - offset[1], 4)) for x, y in poly.exterior.coords])

    def local_pt(p) -> tuple[float, float]:
        return (round(p[0] - offset[0], 4), round(p[1] - offset[1], 4))

    boundary_local = Polygon(_clean([local_pt(p) for p in boundary.exterior.coords[:-1]]))
    drawing = Drawing(boundary_local, scale=scale, offset=offset, notes=notes)

    def name_for(key: str, poly: Polygon, fallback: str) -> str:
        for pt, txt in texts.get(key, []):
            if poly.buffer(0.5).contains(Point(pt.x - offset[0], pt.y - offset[1])) and txt:
                return _slug(txt)
        return fallback

    for role in ("obstacles", "prohibited", "zones"):
        n = 0
        for e, zone_name in found[role]:
            got = _points(e, scale)
            if not got or not got[1]:
                notes.append(f"an open {e.dxftype()} on {e.dxf.layer} was skipped: {role} must be closed shapes")
                continue
            poly = _polygon(got[0])
            if poly is None:
                continue
            poly = local_poly(poly)
            n += 1
            key = role + (zone_name or "")
            default = zone_name if role == "zones" else f"{role[:-1] if role != 'prohibited' else 'no-beds'}-{n}"
            sid = zone_name if role == "zones" else name_for(key, poly, default)
            getattr(drawing, role).append(Shape(sid, poly, e.dxf.layer))

    edges = list(zip(boundary_local.exterior.coords[:-1], boundary_local.exterior.coords[1:]))
    for k, (e, _) in enumerate(found["doors"], start=1):
        seg = _door_segment(e, scale, offset)
        if seg is None:
            notes.append(f"a {e.dxftype()} on {e.dxf.layer} is not a door shape (a line, an open polyline or a block)")
            continue
        door = _snap_door(seg, edges, snap)
        if door is None:
            notes.append(f"door {k}: not within {snap} m of an axis-aligned wall -- skipped")
            continue
        a, b = door
        mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        label = None
        best = 3.0
        for pt, txt in texts.get("doors", []):
            d = Point(pt.x - offset[0], pt.y - offset[1]).distance(mid)
            if d < best and txt:
                best, label = d, _slug(txt)
        drawing.doors.append(DoorLine(label or f"D{k}", a, b, e.dxf.layer))
    if not drawing.doors:
        raise DrawingError("no door found: draw each as a line along the boundary on a DOORS layer")

    if crs:
        from pyproj import Transformer
        t = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        lon, lat = t.transform(offset[0], offset[1])
        drawing.origin_lonlat = (round(lon, 7), round(lat, 7))
        if offset == (0.0, 0.0):
            notes.append(f"with {crs}, the drawing's (0, 0) is taken as the local origin")
    return drawing


def _slug(text: str) -> str:
    """A name as written, with spaces and punctuation made dashes: `D1` stays `D1`, `Water tank` is `Water-tank`."""
    return re.sub(r"[^A-Za-z0-9_]+", "-", text.strip()).strip("-") or "unnamed"


def _door_segment(entity, scale: float, offset) -> LineString | Polygon | None:
    kind = entity.dxftype()
    if kind == "INSERT":
        try:
            xs, ys = [], []
            for v in entity.virtual_entities():
                got = _points(v, scale)
                if got:
                    for x, y in got[0]:
                        xs.append(x)
                        ys.append(y)
            if not xs:
                return None
            # A door block (leaf, swing arc, frame): its extent, which
            # _snap_door projects onto the wall it sits on.
            return box(min(xs) - offset[0], min(ys) - offset[1], max(xs) - offset[0], max(ys) - offset[1])
        except Exception:  # noqa: BLE001
            return None
    got = _points(entity, scale)
    if not got or got[1] or len(got[0]) < 2:
        return None
    pts = [(x - offset[0], y - offset[1]) for x, y in got[0]]
    return LineString([pts[0], pts[-1]])


def _snap_door(seg, edges, snap: float):
    """The door's opening on the wall it lies along: both ends projected onto
    the nearest axis-aligned boundary edge, rounded to the millimetre. A block
    (a box) gives the stretch of the wall it covers -- its swing arc reaches
    into the room, but the opening is where it meets the wall."""
    if isinstance(seg, Polygon):
        return _snap_block(seg, edges, snap)
    best = None
    for a, b in edges:
        edge = LineString([a, b])
        d = max(edge.distance(Point(seg.coords[0])), edge.distance(Point(seg.coords[-1])))
        if d > snap:
            continue
        if best is None or d < best[0]:
            best = (d, a, b)
    if best is None:
        return None
    _, a, b = best
    if not (math.isclose(a[0], b[0], abs_tol=1e-6) or math.isclose(a[1], b[1], abs_tol=1e-6)):
        return None
    edge = LineString([a, b])
    p = edge.interpolate(edge.project(Point(seg.coords[0])))
    q = edge.interpolate(edge.project(Point(seg.coords[-1])))
    pa, pb = (round(p.x, 3), round(p.y, 3)), (round(q.x, 3), round(q.y, 3))
    if math.dist(pa, pb) < 0.3:
        return None
    return tuple(sorted([pa, pb]))


def _snap_block(extent: Polygon, edges, snap: float):
    x0, y0, x1, y1 = extent.bounds
    best = None
    for a, b in edges:
        horizontal = math.isclose(a[1], b[1], abs_tol=1e-6)
        if not (horizontal or math.isclose(a[0], b[0], abs_tol=1e-6)):
            continue
        d = LineString([a, b]).distance(extent)
        if d > snap:
            continue
        if horizontal:
            lo, hi = max(x0, min(a[0], b[0])), min(x1, max(a[0], b[0]))
            ends = ((lo, a[1]), (hi, a[1]))
        else:
            lo, hi = max(y0, min(a[1], b[1])), min(y1, max(a[1], b[1]))
            ends = ((a[0], lo), (a[0], hi))
        if hi - lo < 0.3:
            continue
        # The wall the block covers most of, then the nearest.
        key = (-(hi - lo), d)
        if best is None or key < best[0]:
            best = (key, ends)
    if best is None:
        return None
    (pa, pb) = best[1]
    pa, pb = (round(pa[0], 3), round(pa[1], 3)), (round(pb[0], 3), round(pb[1], 3))
    return tuple(sorted([pa, pb]))


def write_dxf(problem, path: str) -> None:
    """A problem as a drawing on the layers this module reads -- a template to
    draw over, and the round trip the tests check."""
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    for name, colour in (("CAMP_BOUNDARY", 7), ("DOORS", 30), ("OBSTACLES", 8), ("NO_BEDS", 1)):
        doc.layers.add(name, color=colour)
    msp.add_lwpolyline(problem.boundary, close=True, dxfattribs={"layer": "CAMP_BOUNDARY"})
    for d in problem.doors:
        msp.add_line(d.a, d.b, dxfattribs={"layer": "DOORS"})
        mid = ((d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2)
        msp.add_text(d.id, dxfattribs={"layer": "DOORS", "height": 0.4}).set_placement(mid)
    for layer, items in (("OBSTACLES", problem.obstacles), ("NO_BEDS", problem.prohibited)):
        for item in items:
            msp.add_lwpolyline(item.ring, close=True, dxfattribs={"layer": layer})
            poly = Polygon(item.ring)
            c = poly.representative_point()
            msp.add_text(item.id, dxfattribs={"layer": layer, "height": 0.4}).set_placement((c.x, c.y))
    for z in problem.placement_zones:
        layer = ZONE_PREFIX + z.id.upper().replace("-", "_")
        if layer not in doc.layers:
            doc.layers.add(layer, color=6)
        msp.add_lwpolyline(z.ring, close=True, dxfattribs={"layer": layer})
    doc.saveas(path)
