"""Camps as domain data: record types, relationships and parameters (camp layout engine).

A camp is not a private document: it is records in its domain, like any other
data the platform plans with -- seen and edited on the Records, Relationships
and Parameters pages, drawn on the map from their geometry, and read by the
camp layout engine. `STRUCTURE` is the encoding, planted into a domain the
first time a camp is made there (`ensure`), and never twice.

**Record types** (geometry in the domain's CRS, longitude/latitude by default)

| type          | what it is                    | attributes |
|---------------|-------------------------------|------------|
| camp          | one camp                      | boundary, origin, bearing, goals, solve settings |
| door          | an opening in its wall        | location (the opening's middle), width_m, frame_depth_m |
| closed_area   | nothing goes here             | shape, kind |
| no_beds_area  | people walk, no beds          | shape |
| bed_zone      | where a bed type must go      | shape |
| bed_type      | a kind of bed                 | length_m, width_m, ranges, other_sizes, may_rotate, side_gap_m |

**Relationships**: door_of, closed_area_of, no_beds_area_of, bed_zone_of (each
to its camp), camp_uses (camp -> its bed types), must_go_in (bed type -> zone).

**Parameters** (numbers a planner tunes): corridor_width_m[camp],
grid_m[camp], door_capacity[door] (0: no limit), zone_depth_m,
zone_max_depth_m, zone_step_m, zone_margin_m, zone_area_per_bed_m2[door]
(0: no rule), min_beds[camp, bed_type], max_beds[camp, bed_type] (0: no
limit), bed_priority[bed_type].

**The camp's frame.** The engine works in metres on the camp's own grid:
`origin` is its (0, 0) and `bearing` how far its +y axis is turned clockwise
from north, so a camp whose walls run at an angle keeps them on the grid.
Shapes are stored on the Earth and read back into the frame, corners within
2 mm of a wall's line put back on it. A door is stored as the middle of its
opening and its width, and read back onto the nearest straight wall.

Records of a camp are keyed `<camp key>:<name>` (keys are unique per type in
a domain, and two camps may both have a door D1); their labels are the names.
"""
from __future__ import annotations

import math
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.camp.engine import serial

GOALS = "beds,distance,corridor,modifications"

STRUCTURE: dict[str, Any] = {
    "entity_types": [
        {"name": "camp", "role": "location", "colour": "#0f766e", "attributes": [
            {"name": "boundary", "data_type": "geometry", "required": True},
            {"name": "origin", "data_type": "geometry"},
            {"name": "bearing", "data_type": "number", "unit": "degrees", "default_value": 0},
            {"name": "access", "data_type": "enum", "enum_values": ["long_sides", "any_side"], "default_value": "long_sides"},
            {"name": "objective_mode", "data_type": "enum", "enum_values": ["lexicographic", "weighted"],
             "default_value": "lexicographic"},
            {"name": "objective_order", "data_type": "text", "default_value": GOALS},
            {"name": "objective_weights", "data_type": "text"},
            {"name": "tolerance_distance", "data_type": "number", "default_value": 0.02},
            {"name": "tolerance_corridor", "data_type": "number", "default_value": 0.02},
            {"name": "trade_beds", "data_type": "boolean", "default_value": False},
            {"name": "solver", "data_type": "enum", "enum_values": ["cpsat", "highs", "scip", "cbc", "heuristic"],
             "default_value": "cpsat"},
            {"name": "beds_seconds", "data_type": "integer", "unit": "s", "default_value": 120},
            {"name": "seconds", "data_type": "integer", "unit": "s", "default_value": 60},
        ]},
        {"name": "door", "role": "location", "colour": "#059669", "attributes": [
            {"name": "location", "data_type": "geometry", "required": True},
            {"name": "width_m", "data_type": "number", "unit": "m", "default_value": 2},
            {"name": "frame_depth_m", "data_type": "number", "unit": "m", "default_value": 0.3},
        ]},
        {"name": "closed_area", "role": "location", "colour": "#475569", "attributes": [
            {"name": "shape", "data_type": "geometry", "required": True},
            {"name": "kind", "data_type": "text", "default_value": "closed"},
        ]},
        {"name": "no_beds_area", "role": "location", "colour": "#dc2626", "attributes": [
            {"name": "shape", "data_type": "geometry", "required": True},
        ]},
        {"name": "bed_zone", "role": "location", "colour": "#7e22ce", "attributes": [
            {"name": "shape", "data_type": "geometry", "required": True},
        ]},
        {"name": "bed_type", "role": "resource", "colour": "#2563eb", "attributes": [
            {"name": "length_m", "data_type": "number", "unit": "m", "required": True},
            {"name": "width_m", "data_type": "number", "unit": "m", "required": True},
            {"name": "min_length_m", "data_type": "number", "unit": "m"},
            {"name": "max_length_m", "data_type": "number", "unit": "m"},
            {"name": "min_width_m", "data_type": "number", "unit": "m"},
            {"name": "max_width_m", "data_type": "number", "unit": "m"},
            {"name": "other_sizes", "data_type": "text"},
            {"name": "may_rotate", "data_type": "boolean", "default_value": True},
            {"name": "side_gap_m", "data_type": "number", "unit": "m", "default_value": 0.1},
        ]},
    ],
    "relationship_types": [
        {"name": "door_of", "from": "door", "to": "camp", "cardinality": "many_to_one", "colour": "#059669"},
        {"name": "closed_area_of", "from": "closed_area", "to": "camp", "cardinality": "many_to_one", "colour": "#475569"},
        {"name": "no_beds_area_of", "from": "no_beds_area", "to": "camp", "cardinality": "many_to_one", "colour": "#dc2626"},
        {"name": "bed_zone_of", "from": "bed_zone", "to": "camp", "cardinality": "many_to_one", "colour": "#7e22ce"},
        {"name": "camp_uses", "from": "camp", "to": "bed_type", "cardinality": "many_to_many", "colour": "#2563eb"},
        {"name": "must_go_in", "from": "bed_type", "to": "bed_zone", "cardinality": "many_to_one", "colour": "#7e22ce"},
    ],
    "parameters": [
        {"name": "corridor_width_m", "index": ["camp"], "default_value": 1, "unit": "m"},
        {"name": "grid_m", "index": ["camp"], "default_value": 0.5, "unit": "m"},
        {"name": "door_capacity", "index": ["door"], "default_value": 0, "unit": "beds"},
        {"name": "zone_depth_m", "index": ["door"], "default_value": 2, "unit": "m"},
        {"name": "zone_max_depth_m", "index": ["door"], "default_value": 4, "unit": "m"},
        {"name": "zone_step_m", "index": ["door"], "default_value": 1, "unit": "m"},
        {"name": "zone_margin_m", "index": ["door"], "default_value": 0.5, "unit": "m"},
        {"name": "zone_area_per_bed_m2", "index": ["door"], "default_value": 0.25, "unit": "m2"},
        {"name": "min_beds", "index": ["camp", "bed_type"], "default_value": 0, "unit": "beds"},
        {"name": "max_beds", "index": ["camp", "bed_type"], "default_value": 0, "unit": "beds"},
        {"name": "bed_priority", "index": ["bed_type"], "default_value": 1},
    ],
}
CHILD = {"door": "door_of", "closed_area": "closed_area_of", "no_beds_area": "no_beds_area_of", "bed_zone": "bed_zone_of"}
SHAPE_OF = {"closed_area": "obstacles", "no_beds_area": "prohibited", "bed_zone": "placement_zones"}
SQUARE = 0.002
PRECISION = 9


class CampRecordsError(ValueError):
    """The records do not make a camp; the message says which."""


def ensure(db: Session, domain_id: int) -> dict[str, int]:
    """Plant the camp structure in the domain (what is there already is left alone); type ids by name."""
    from app.seed import plant_domain_seed

    plant_domain_seed(db, domain_id, STRUCTURE)
    return types(db, domain_id)


def types(db: Session, domain_id: int) -> dict[str, int]:
    names = [t["name"] for t in STRUCTURE["entity_types"]]
    rows = db.execute(text("SELECT name, id FROM entity_type WHERE domain_id = :d AND name = ANY(:n)"),
                      {"d": domain_id, "n": names}).all()
    return {name: identity for name, identity in rows}


def _ids(db: Session, domain_id: int, table: str, names: list[str]) -> dict[str, int]:
    return {n: i for n, i in db.execute(text(f"SELECT name, id FROM {table} WHERE domain_id = :d AND name = ANY(:n)"),
                                        {"d": domain_id, "n": names}).all()}


# -- the frame -----------------------------------------------------------------------------------

class Frame:
    """Metres on the camp's grid <-> the domain's coordinates (WGS 84 unless `spatial.crs` says otherwise)."""

    def __init__(self, origin: tuple[float, float], bearing: float, domain_crs: int = 4326):
        """`origin` is longitude and latitude in degrees, whatever the domain's CRS."""
        from pyproj import Transformer

        self.origin, self.bearing = origin, bearing
        lon0, lat0 = origin
        aeqd = f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +x_0=0 +y_0=0 +units=m +ellps=WGS84"
        self._to_m = Transformer.from_crs("EPSG:4326", aeqd, always_xy=True)
        self._from_m = Transformer.from_crs(aeqd, "EPSG:4326", always_xy=True)
        self._in = Transformer.from_crs(f"EPSG:{domain_crs}", "EPSG:4326", always_xy=True) if domain_crs != 4326 else None
        self._out = Transformer.from_crs("EPSG:4326", f"EPSG:{domain_crs}", always_xy=True) if domain_crs != 4326 else None
        self.c, self.s = math.cos(math.radians(bearing)), math.sin(math.radians(bearing))

    def local(self, p) -> tuple[float, float]:
        x, y = p[0], p[1]
        if self._in:
            x, y = self._in.transform(x, y)
        e, n = self._to_m.transform(x, y)
        return (e * self.c - n * self.s, e * self.s + n * self.c)

    def earth(self, p) -> list[float]:
        x, y = p
        lon, lat = self._from_m.transform(x * self.c + y * self.s, -x * self.s + y * self.c)
        if self._out:
            lon, lat = self._out.transform(lon, lat)
        return [round(lon, PRECISION), round(lat, PRECISION)]


def _square(ring: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Corners to the millimetre, and an edge within 2 mm of horizontal or vertical made exactly so."""
    pts = [[round(x, 3), round(y, 3)] for x, y in ring]
    for _ in range(2):
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            if a[0] != b[0] and abs(a[0] - b[0]) <= SQUARE:
                b[0] = a[0]
            if a[1] != b[1] and abs(a[1] - b[1]) <= SQUARE:
                b[1] = a[1]
    out = [(p[0], p[1]) for p in pts]
    return [q for i, q in enumerate(out) if i == 0 or q != out[i - 1]]


def _ring_of(geometry: dict[str, Any] | None) -> list[list[float]]:
    if not geometry:
        return []
    if geometry.get("type") == "Polygon":
        ring = geometry["coordinates"][0]
    elif geometry.get("type") == "MultiPolygon":
        ring = max((poly[0] for poly in geometry["coordinates"]), key=len)
    else:
        return []
    return ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring


def _polygon(frame: Frame, ring) -> dict[str, Any]:
    pts = [frame.earth(p) for p in ring]
    return {"type": "Polygon", "coordinates": [pts + [pts[0]]]}


def _door_on_wall(mid: tuple[float, float], width: float, boundary: list[tuple[float, float]]):
    """A door `width` wide centred at `mid`, on the nearest horizontal or vertical wall (within 1 m)."""
    best = None
    for a, b in zip(boundary, boundary[1:] + boundary[:1]):
        horizontal, vertical = a[1] == b[1], a[0] == b[0]
        if not (horizontal or vertical) or a == b:
            continue
        axis = 0 if horizontal else 1
        lo, hi = sorted((a[axis], b[axis]))
        t = min(max(mid[axis], lo), hi)
        foot = (t, a[1]) if horizontal else (a[0], t)
        d = math.dist(foot, mid)
        if d <= 1.0 and (best is None or d < best[0]):
            best = (d, horizontal, lo, hi, a)
    if best is None:
        return None
    _, horizontal, lo, hi, a = best
    axis = 0 if horizontal else 1
    w = min(width, hi - lo)
    start = min(max(mid[axis] - w / 2, lo), hi - w)
    ends = [round(start, 3), round(start + w, 3)]
    return ((ends[0], a[1]), (ends[1], a[1])) if horizontal else ((a[0], ends[0]), (a[0], ends[1]))


# -- records -> problem ----------------------------------------------------------------------------

def _domain_crs(db: Session, domain_id: int) -> int:
    from app.settings_resolve import resolve

    try:
        return int(resolve(db, domain_id=domain_id)["spatial.crs"].value or 4326)
    except (KeyError, TypeError, ValueError):
        return 4326


def _params(db: Session, domain_id: int) -> dict[str, dict[tuple[int, ...], float]]:
    names = [p["name"] for p in STRUCTURE["parameters"]]
    rows = db.execute(text(
        "SELECT d.name, d.default_value, v.entity_ids, v.value FROM parameter_def d"
        " LEFT JOIN parameter_value v ON v.parameter_def_id = d.id WHERE d.domain_id = :d AND d.name = ANY(:n)"),
        {"d": domain_id, "n": names}).all()
    out: dict[str, dict[tuple[int, ...], float]] = {n: {} for n in names}
    defaults: dict[str, float] = {}
    for name, default, ids, value in rows:
        defaults[name] = float(default)
        if ids is not None and value is not None:
            out[name][tuple(ids)] = float(value)
    out["__defaults__"] = {(): 0.0}
    for name, default in defaults.items():
        out["__defaults__"][(name,)] = default  # type: ignore[index]
    return out


def _p(params, name: str, *ids: int) -> float:
    found = params[name].get(tuple(ids))
    return found if found is not None else params["__defaults__"].get((name,), 0.0)


def camp_row(db: Session, camp_id: int, organization_id) -> Any:
    row = db.execute(text(
        "SELECT e.id, e.key, e.label, e.attrs, e.updated_at, t.domain_id FROM entity e"
        " JOIN entity_type t ON t.id = e.entity_type_id"
        " WHERE e.id = :i AND t.name = 'camp' AND t.organization_id = :o"),
        {"i": camp_id, "o": organization_id}).mappings().one_or_none()
    return row


def children(db: Session, camp_id: int) -> list[Any]:
    """The camp's doors, closed / no-bed areas and zones, and its bed types."""
    return db.execute(text(
        "SELECT e.id, e.key, e.label, e.attrs, t.name AS type FROM relationship r"
        " JOIN relationship_type rt ON rt.id = r.relationship_type_id"
        " JOIN entity e ON e.id = r.from_entity_id JOIN entity_type t ON t.id = e.entity_type_id"
        " WHERE r.to_entity_id = :c AND rt.name = ANY(:names)"
        " UNION ALL"
        " SELECT e.id, e.key, e.label, e.attrs, t.name FROM relationship r"
        " JOIN relationship_type rt ON rt.id = r.relationship_type_id"
        " JOIN entity e ON e.id = r.to_entity_id JOIN entity_type t ON t.id = e.entity_type_id"
        " WHERE r.from_entity_id = :c AND rt.name = 'camp_uses'"
        " ORDER BY 2"), {"c": camp_id, "names": list(CHILD.values())}).mappings().all()


def _name(row, camp_key: str) -> str:
    return row["label"] or row["key"].removeprefix(f"{camp_key}:")


def to_problem(db: Session, camp_id: int, organization_id) -> tuple[dict[str, Any], Any]:
    """The camp's records as a `camp-problem/1` problem in its own frame; and the camp row."""
    camp = camp_row(db, camp_id, organization_id)
    if camp is None:
        raise CampRecordsError("no such camp")
    a = camp["attrs"]
    ring_e = _ring_of(a.get("boundary"))
    origin = (a.get("origin") or {}).get("coordinates")
    if not origin and ring_e:
        origin = min(ring_e, key=lambda p: (p[1], p[0]))
    crs = _domain_crs(db, camp["domain_id"])
    origin_deg = tuple(origin or (31.6, 30.1))
    if crs != 4326 and origin:
        from pyproj import Transformer
        origin_deg = Transformer.from_crs(f"EPSG:{crs}", "EPSG:4326", always_xy=True).transform(*origin)
    frame = Frame(origin_deg, float(a.get("bearing") or 0), crs)
    params = _params(db, camp["domain_id"])
    boundary = _square([frame.local(p) for p in ring_e]) if ring_e else []
    kids = children(db, camp_id)
    zone_name: dict[int, str] = {}
    doors, zones, shapes = [], [], {"obstacles": [], "prohibited": [], "placement_zones": []}
    bed_rows = []
    for k in kids:
        name = _name(k, camp["key"])
        attrs = k["attrs"]
        if k["type"] == "door":
            mid = frame.local((attrs.get("location") or {}).get("coordinates") or [0, 0])
            ab = _door_on_wall(mid, float(attrs.get("width_m") or 2), boundary)
            if ab is None:
                # Kept, so the check names it, a door off every wall.
                w = float(attrs.get("width_m") or 2) / 2
                ab = ((round(mid[0] - w, 3), round(mid[1], 3)), (round(mid[0] + w, 3), round(mid[1], 3) + 0.001))
            cap = _p(params, "door_capacity", k["id"])
            doors.append({"id": name, "a": list(ab[0]), "b": list(ab[1]), "depth": float(attrs.get("frame_depth_m") or 0.3),
                          "capacity": int(cap) if cap > 0 else None})
            per_bed = _p(params, "zone_area_per_bed_m2", k["id"])
            zones.append({"door": name, "depth": _p(params, "zone_depth_m", k["id"]),
                          "max_depth": _p(params, "zone_max_depth_m", k["id"]), "step": _p(params, "zone_step_m", k["id"]),
                          "margin": _p(params, "zone_margin_m", k["id"]), "area_per_bed": per_bed if per_bed > 0 else None})
        elif k["type"] in SHAPE_OF:
            ring = _ring_of(attrs.get("shape"))
            if not ring:
                continue
            shape = {"id": name, "ring": [list(p) for p in _square([frame.local(p) for p in ring])]}
            if k["type"] == "closed_area":
                shape["kind"] = attrs.get("kind") or "closed"
            shapes[SHAPE_OF[k["type"]]].append(shape)
            if k["type"] == "bed_zone":
                zone_name[k["id"]] = name
        elif k["type"] == "bed_type":
            bed_rows.append(k)
    must = dict(db.execute(text(
        "SELECT r.from_entity_id, r.to_entity_id FROM relationship r JOIN relationship_type rt ON rt.id = r.relationship_type_id"
        " WHERE rt.name = 'must_go_in' AND r.from_entity_id = ANY(:ids)"), {"ids": [b["id"] for b in bed_rows] or [0]}).all())
    beds = []
    for b in bed_rows:
        at = b["attrs"]
        sizes = []
        for part in re.split(r"[;,]", at.get("other_sizes") or ""):
            m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*$", part)
            if m:
                sizes.append([float(m.group(1)), float(m.group(2))])
        max_beds = _p(params, "max_beds", camp_id, b["id"])
        beds.append({
            "id": _name(b, camp["key"]), "length": float(at["length_m"]), "width": float(at["width_m"]),
            "min_length": at.get("min_length_m"), "max_length": at.get("max_length_m"),
            "min_width": at.get("min_width_m"), "max_width": at.get("max_width_m"), "sizes": sizes,
            "rotation": bool(at.get("may_rotate", True)), "side_gap": float(at.get("side_gap_m", 0.1)),
            "min_count": int(_p(params, "min_beds", camp_id, b["id"])),
            "max_count": int(max_beds) if max_beds > 0 else None,
            "zone": zone_name.get(must.get(b["id"])), "priority": _p(params, "bed_priority", b["id"]),
        })
    order = [g.strip() for g in (a.get("objective_order") or GOALS).split(",") if g.strip()]
    weights = {"beds": 1000.0, "distance": 1.0, "corridor": 1.0, "modifications": 0.1}
    for part in (a.get("objective_weights") or "").split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            try:
                weights[key.strip()] = float(value)
            except ValueError:
                pass
    problem = {
        "format": serial.FORMAT, "name": camp["label"] or camp["key"], "grid": _p(params, "grid_m", camp_id),
        "origin_lonlat": list(frame.origin), "bearing": frame.bearing,
        "boundary": [list(p) for p in boundary], "doors": doors, "zones": zones, **shapes, "bed_types": beds,
        "corridor": {"min_width": _p(params, "corridor_width_m", camp_id), "access": a.get("access") or "long_sides"},
        "objectives": {"mode": a.get("objective_mode") or "lexicographic", "order": order, "weights": weights,
                       "tolerance": {"distance": float(a.get("tolerance_distance", 0.02)),
                                     "corridor": float(a.get("tolerance_corridor", 0.02))},
                       "trade_beds": bool(a.get("trade_beds", False))},
    }
    return problem, camp


def options_of(camp) -> dict[str, Any]:
    a = camp["attrs"]
    return {"solver": a.get("solver") or "cpsat", "beds_seconds": int(a.get("beds_seconds") or 120),
            "seconds": int(a.get("seconds") or 60), "threads": 4}


# -- problem -> records ----------------------------------------------------------------------------

def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "camp"


def _upsert_entity(db: Session, type_id: int, key: str, label: str, attrs: dict[str, Any]) -> int:
    import json

    return db.execute(text(
        "INSERT INTO entity (entity_type_id, key, label, attrs) VALUES (:t, :k, :l, CAST(:a AS jsonb))"
        " ON CONFLICT (entity_type_id, key) DO UPDATE SET label = EXCLUDED.label, attrs = EXCLUDED.attrs RETURNING id"),
        {"t": type_id, "k": key, "l": label, "a": json.dumps(attrs)}).scalar_one()


def _link(db: Session, rel_id: int, src: int, dst: int) -> None:
    """Link once: the many-to-one rule refuses a second link even to the same target."""
    db.execute(text("INSERT INTO relationship (relationship_type_id, from_entity_id, to_entity_id)"
                    " SELECT :r, :f, :t WHERE NOT EXISTS (SELECT 1 FROM relationship"
                    "   WHERE relationship_type_id = :r AND from_entity_id = :f AND to_entity_id = :t)"),
               {"r": rel_id, "f": src, "t": dst})


def _set(db: Session, param_id: int, ids: list[int], value: float | None) -> None:
    db.execute(text("INSERT INTO parameter_value (parameter_def_id, entity_ids, value) VALUES (:p, :e, :v)"
                    " ON CONFLICT (parameter_def_id, entity_ids) DO UPDATE SET value = EXCLUDED.value"),
               {"p": param_id, "e": ids, "v": value})


def write_problem(db: Session, domain_id: int, problem_data: dict[str, Any], *, camp_id: int | None = None,
                  key: str | None = None, options: dict[str, Any] | None = None) -> int:
    """Write a camp's problem as records: the camp, its shapes, doors and bed types, their links and
    parameters. Records of the camp no longer in the problem are deleted. Returns the camp's id."""
    problem = serial.from_dict(problem_data)
    t = ensure(db, domain_id)
    rel = _ids(db, domain_id, "relationship_type", [r["name"] for r in STRUCTURE["relationship_types"]])
    par = _ids(db, domain_id, "parameter_def", [p["name"] for p in STRUCTURE["parameters"]])
    # The problem's origin is in degrees; the records are written in the domain's CRS.
    frame = Frame(tuple(problem.origin_lonlat), problem.bearing, _domain_crs(db, domain_id))
    if camp_id is not None:
        existing = db.execute(text("SELECT key FROM entity WHERE id = :i"), {"i": camp_id}).scalar_one()
        key = existing
    else:
        base = key or slug(problem.name)
        taken = set(db.execute(text("SELECT key FROM entity WHERE entity_type_id = :t"), {"t": t["camp"]}).scalars())
        key, n = base, 2
        while key in taken:
            key, n = f"{base}-{n}", n + 1
    o = problem.objectives
    origin_out = frame.earth((0.0, 0.0))
    attrs = {
        "boundary": _polygon(frame, problem.boundary), "origin": {"type": "Point", "coordinates": origin_out},
        "bearing": problem.bearing, "access": problem.corridor.access, "objective_mode": o.mode,
        "objective_order": ",".join(o.order),
        "objective_weights": ",".join(f"{k}={v:g}" for k, v in o.weights.items()),
        "tolerance_distance": float(o.tolerance.get("distance", 0.02)),
        "tolerance_corridor": float(o.tolerance.get("corridor", 0.02)), "trade_beds": o.trade_beds,
        **({"solver": options["solver"], "beds_seconds": int(options["beds_seconds"]), "seconds": int(options["seconds"])}
           if options else {}),
    }
    if camp_id is not None and not options:
        old = db.execute(text("SELECT attrs FROM entity WHERE id = :i"), {"i": camp_id}).scalar_one()
        for k in ("solver", "beds_seconds", "seconds"):
            if k in old:
                attrs[k] = old[k]
    camp_id = _upsert_entity(db, t["camp"], key, problem.name, attrs)
    _set(db, par["corridor_width_m"], [camp_id], problem.corridor.min_width)
    _set(db, par["grid_m"], [camp_id], problem.grid)

    keep: set[int] = set()
    zone_ids: dict[str, int] = {}
    for kind, items in (("closed_area", problem.obstacles), ("no_beds_area", problem.prohibited),
                        ("bed_zone", problem.placement_zones)):
        for item in items:
            shape_attrs: dict[str, Any] = {"shape": _polygon(frame, item.ring)}
            if kind == "closed_area":
                shape_attrs["kind"] = getattr(item, "kind", "closed")
            eid = _upsert_entity(db, t[kind], f"{key}:{item.id}", item.id, shape_attrs)
            _link(db, rel[CHILD[kind]], eid, camp_id)
            keep.add(eid)
            if kind == "bed_zone":
                zone_ids[item.id] = eid
    zone_of = {z.door: z for z in problem.zones}
    for d in problem.doors:
        mid = ((d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2)
        eid = _upsert_entity(db, t["door"], f"{key}:{d.id}", d.id, {
            "location": {"type": "Point", "coordinates": frame.earth(mid)},
            "width_m": round(math.dist(d.a, d.b), 3), "frame_depth_m": d.depth})
        _link(db, rel["door_of"], eid, camp_id)
        keep.add(eid)
        _set(db, par["door_capacity"], [eid], d.capacity or 0)
        z = zone_of.get(d.id)
        if z is not None:
            for name, value in (("zone_depth_m", z.depth), ("zone_max_depth_m", z.max_depth), ("zone_step_m", z.step),
                                ("zone_margin_m", z.margin), ("zone_area_per_bed_m2", z.area_per_bed or 0)):
                _set(db, par[name], [eid], value)
    for b in problem.bed_types:
        eid = _upsert_entity(db, t["bed_type"], f"{key}:{b.id}", b.id, {k: v for k, v in {
            "length_m": b.length, "width_m": b.width, "min_length_m": b.min_length, "max_length_m": b.max_length,
            "min_width_m": b.min_width, "max_width_m": b.max_width,
            "other_sizes": "; ".join(f"{l:g}x{w:g}" for l, w in b.sizes) or None,
            "may_rotate": b.rotation, "side_gap_m": b.side_gap}.items() if v is not None})
        _link(db, rel["camp_uses"], camp_id, eid)
        keep.add(eid)
        db.execute(text("DELETE FROM relationship WHERE relationship_type_id = :r AND from_entity_id = :b"),
                   {"r": rel["must_go_in"], "b": eid})
        if b.zone and b.zone in zone_ids:
            _link(db, rel["must_go_in"], eid, zone_ids[b.zone])
        _set(db, par["min_beds"], [camp_id, eid], b.min_count)
        _set(db, par["max_beds"], [camp_id, eid], b.max_count or 0)
        _set(db, par["bed_priority"], [eid], b.priority)
    # Records of this camp that the problem no longer has.
    stale = [k["id"] for k in children(db, camp_id) if k["id"] not in keep and k["key"].startswith(f"{key}:")]
    if stale:
        db.execute(text("DELETE FROM entity WHERE id = ANY(:ids)"), {"ids": stale})
    return camp_id


def delete_camp(db: Session, camp_id: int) -> None:
    camp_key = db.execute(text("SELECT key FROM entity WHERE id = :i"), {"i": camp_id}).scalar_one()
    own = [k["id"] for k in children(db, camp_id) if k["key"].startswith(f"{camp_key}:")]
    db.execute(text("DELETE FROM entity WHERE id = ANY(:ids)"), {"ids": own + [camp_id]})
