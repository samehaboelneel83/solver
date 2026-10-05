"""A run's answer as a CAD drawing: GET /api/v1/runs/{id}/export?format=dxf.

What a planner opens in AutoCAD next to the drawing the problem came from. Everything the answer map
draws (`app.api.answer_map`), plus the records that carry their position as numbers in metres rather than
as a shape (a layout's generated candidates: `x_m`, `y_m`, a width and a height, or `shape_m` WKT), in
the drawing's own coordinates whenever the domain holds the drawing:

- **the frame**: the domain's map data says where its drawing is. A drawing placed in local engineering
  coordinates (`placement.kind == "local"`, what a CAD file with no projection gets) is written back in
  its own units and numbers, so the export lies exactly on the original; one placed in a projected CRS
  (UTM, the Egyptian belts) is written in that CRS; with no map data, or only degrees, the answer is
  written in local metres around its own centre and the note in the drawing says so;
- **the original drawing** under the answer, from the stored source coordinates (exact, not re-projected),
  on grey layers `MAP-<layer>`;
- **each decision** on layers by what happened: `<decision>-CHOSEN` (green, filled), `<decision>-NOT-CHOSEN`
  (grey, turned off: thousands of unused candidates would hide the answer), `UNMET` (red: where a rule
  fell short), context places (white), links between two places as lines, and the labels of what was
  chosen on `<decision>-LABELS`;
- a note at the top left: the run, its status and goal value, the frame, and how many of each were drawn.

Records with metre fields: `shape_m` (WKT) wins; then `min_x_m`, `min_y_m` with a width and height (a box
from its lower-left corner); then `x_m`, `y_m` as the centre, a box when a width and height are given
(`width_m`/`w_m`/`w`, `height_m`/`h_m`/`h`, already turned to the record's orientation), else a point.
Metres are measured from the drawing's lower-left corner, as the Assistant's file reader gives them.
"""
from __future__ import annotations

import io
import math
import re
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.answer_map import _shape_of, answer_map

MAX_ANSWER = 250_000
MAX_CONTEXT = 250_000
MAX_LABELS = 5_000
MAX_FILLS = 50_000
WIDTHS = ("width_m", "w_m", "w")
HEIGHTS = ("height_m", "h_m", "h")
#: AutoCAD colour index per what happened.
COLOURS = {"chosen": 3, "not_chosen": 8, "short": 1, "place": 7, "links": 5, "labels": 2, "map": 9, "note": 7}

XY = Callable[[list[float], list[float]], tuple[list[float], list[float]]]


# -- the frame -------------------------------------------------------------------------------------------


class Frame:
    """Longitude/latitude, and metres from the drawing's corner, to the coordinates the DXF is written in."""

    def __init__(self, to_xy: XY, metres: XY, units: float, describe: str, dataset_id: int | None):
        self.to_xy, self.metres, self.units, self.describe, self.dataset_id = to_xy, metres, units, describe, dataset_id


def _local(placement: dict[str, Any]) -> tuple[XY, XY, float]:
    from pyproj import Transformer

    lon0, lat0 = placement["lonlat"]
    ax, ay = placement["anchor"]
    units = float(placement.get("units") or 1.0)
    k = units * float(placement.get("scale") or 1.0)
    theta = math.radians(float(placement.get("rotation") or 0.0))
    c, s = math.cos(theta), math.sin(theta)
    t = Transformer.from_crs("EPSG:4326", f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +x_0=0 +y_0=0 +units=m "
                             "+ellps=WGS84", always_xy=True)

    def to_xy(lons, lats):
        e, n = t.transform(lons, lats)
        # The inverse of the placement's clockwise turn (app.gis.crs.Placement.transformer).
        return ([ax + (ei * c - ni * s) / k for ei, ni in zip(e, n)],
                [ay + (ei * s + ni * c) / k for ei, ni in zip(e, n)])

    def metres(xs, ys):
        return [ax + x / units for x in xs], [ay + y / units for y in ys]

    return to_xy, metres, units


def _projected(code: int, units: float) -> XY:
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:4326", f"EPSG:{code}", always_xy=True)

    def to_xy(lons, lats):
        x, y = t.transform(lons, lats)
        return [v / units for v in x], [v / units for v in y]

    return to_xy


def _around(lon0: float, lat0: float) -> XY:
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:4326", f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +x_0=0 +y_0=0 +units=m "
                             "+ellps=WGS84", always_xy=True)

    def to_xy(lons, lats):
        x, y = t.transform(lons, lats)
        return list(x), list(y)

    return to_xy


def _same(xs, ys):
    return list(xs), list(ys)


def frame(db: Session | None, domain_id: int | None, features: list[dict[str, Any]]) -> Frame:
    """The drawing the domain holds decides the coordinates; else local metres around the answer."""
    rows = [] if db is None or domain_id is None else db.execute(
        text("SELECT id, name, placement FROM gis_dataset WHERE domain_id = :d ORDER BY id DESC"),
        {"d": domain_id}).mappings().all()
    for row in rows:  # a drawing in its own coordinates first: the export then lies on it exactly
        p = row["placement"] or {}
        if p.get("kind") == "local":
            to_xy, metres, units = _local(p)
            return Frame(to_xy, metres, units, f"the drawing's own coordinates (map data \"{row['name']}\")", row["id"])
    for row in rows:
        p = row["placement"] or {}
        if p.get("kind") == "epsg" and p.get("code") and int(p["code"]) != 4326:
            from app.gis.crs import crs_info

            try:
                geographic = crs_info(int(p["code"]))["geographic"]
            except Exception:  # noqa: BLE001 -- an unknown code: not a frame
                continue
            if not geographic:
                units = float(p.get("units") or 1.0)
                return Frame(_projected(int(p["code"]), units), _same, units,
                             f"EPSG:{p['code']} (map data \"{row['name']}\")", row["id"])
    lon0, lat0 = _centre(features)
    return Frame(_around(lon0, lat0), _same, 1.0,
                 f"local metres around {lon0:.5f}, {lat0:.5f} (the domain holds no drawing in metres)", None)


def _centre(features: list[dict[str, Any]]) -> tuple[float, float]:
    lons, lats = [], []
    for f in features[:5000]:
        for x, y in _points(f.get("geometry") or {}):
            lons.append(x)
            lats.append(y)
    if not lons:
        return 0.0, 0.0
    return (min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2


def _points(g: dict[str, Any]):
    kind, c = g.get("type"), g.get("coordinates")
    if kind == "Point":
        yield c
    elif kind in ("LineString", "MultiPoint"):
        yield from c
    elif kind in ("Polygon", "MultiLineString"):
        for ring in c:
            yield from ring
    elif kind == "MultiPolygon":
        for poly in c:
            for ring in poly:
                yield from ring


# -- records placed by numbers in metres -----------------------------------------------------------------


def _num(row: dict[str, Any], *names: str) -> float | None:
    for n in names:
        v = row.get(n)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                continue
    return None


def metre_shape(row: dict[str, Any]):
    """A record's shape from its metre fields (shapely, in metres from the drawing's corner), or None."""
    from shapely import wkt
    from shapely.geometry import Point, box

    if isinstance(row.get("shape_m"), str) and row["shape_m"].strip():
        try:
            return wkt.loads(row["shape_m"])
        except Exception:  # noqa: BLE001 -- not WKT: try the numbers
            pass
    w, h = _num(row, *WIDTHS), _num(row, *HEIGHTS)
    x0, y0 = _num(row, "min_x_m"), _num(row, "min_y_m")
    if x0 is not None and y0 is not None and w and h:
        return box(x0, y0, x0 + w, y0 + h)
    x, y = _num(row, "x_m"), _num(row, "y_m")
    if x is None or y is None:
        return None
    if w and h:
        return box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
    return Point(x, y)


def metre_features(ir: dict[str, Any], data: dict[str, Any], assignments: dict[str, Any] | None,
                   amounts: dict[str, Any] | None, labels: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Each decision over records placed by metre fields (and no shape): chosen or not, in metres."""
    sets = data.get("sets") or {}
    placed: dict[str, dict[str, tuple[Any, str]]] = {}
    for name, rows in sets.items():
        members = {}
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and _shape_of(row) is None and (shape := metre_shape(row)) is not None:
                key = str(row.get("id"))
                label = (labels.get(name) or {}).get(key) or str(row.get("label") or row.get("name") or key)
                members[key] = (shape, label)
        if members:
            placed[name] = members
    out: list[dict[str, Any]] = []
    for var, spec in (ir.get("variables") or {}).items():
        index = list(spec.get("index") or [])
        if (spec.get("domain") or "binary") == "interval":
            continue
        at = next((i for i, s in enumerate(index) if s in placed), None)
        if at is None:
            continue
        s = index[at]
        value: dict[str, float] = {}
        if (spec.get("domain") or "binary") == "binary":
            for cell in (assignments or {}).get(var) or []:
                if len(cell) == len(index):
                    value[str(cell[at])] = value.get(str(cell[at]), 0.0) + 1
        else:
            for e in (amounts or {}).get(var) or []:
                cell = e.get("index") or []
                v = float(e.get("value") or 0)
                if len(cell) == len(index) and abs(v) > 1e-9:
                    value[str(cell[at])] = value.get(str(cell[at]), 0.0) + v
        for key, (shape, label) in placed[s].items():
            got = value.get(key, 0.0)
            out.append({"shape": shape, "layer": var, "status": "chosen" if abs(got) > 1e-9 else "not_chosen",
                        "label": label if abs(got - 1) < 1e-9 or not got else f"{label} {got:g}"})
            if len(out) >= MAX_ANSWER:
                return out
    return out


# -- writing ---------------------------------------------------------------------------------------------


_BAD = re.compile(r'[<>/\\":;?*|=`,\s]+')


def _layer_name(*parts: str) -> str:
    return _BAD.sub("_", "-".join(p for p in parts if p)).strip("_").upper()[:200] or "ANSWER"


def _units_code(units: float) -> int:
    from app.gis.cad import UNITS

    return next((code for code, (_, m) in UNITS.items() if abs(m - units) < 1e-9), 6 if units == 1 else 0)


class _Writer:
    def __init__(self, msp, doc):
        self.msp, self.doc = msp, doc
        self.counts: dict[str, int] = {}
        self.labels = 0
        self.fills = 0
        self.box = [math.inf, math.inf, -math.inf, -math.inf]

    def layer(self, name: str, colour: int, off: bool = False) -> str:
        if name not in self.doc.layers:
            lay = self.doc.layers.add(name, color=colour)
            if off:
                lay.off()
        return name

    def _seen(self, xs, ys):
        if xs:
            self.box = [min(self.box[0], min(xs)), min(self.box[1], min(ys)), max(self.box[2], max(xs)), max(self.box[3], max(ys))]

    def ring(self, xs, ys, layer: str, closed: bool) -> None:
        pts = list(zip(xs, ys))
        if closed and len(pts) > 1 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) == 1:
            self.msp.add_point(pts[0], dxfattribs={"layer": layer})
        elif pts:
            self.msp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer})
        self._seen(xs, ys)

    def fill(self, rings: list[tuple[list[float], list[float]]], layer: str) -> None:
        if self.fills >= MAX_FILLS:
            return
        hatch = self.msp.add_hatch(color=COLOURS["chosen"], dxfattribs={"layer": layer})
        for i, (xs, ys) in enumerate(rings):
            hatch.paths.add_polyline_path(list(zip(xs, ys)), is_closed=True, flags=1 if i == 0 else 0)
        self.fills += 1

    def label(self, words: str, x: float, y: float, height: float, layer: str) -> None:
        if self.labels >= MAX_LABELS or not words:
            return
        self.msp.add_text(words[:120], height=height, dxfattribs={"layer": layer}).set_placement(
            (x, y), align=_middle())
        self.labels += 1

    def count(self, layer: str) -> None:
        self.counts[layer] = self.counts.get(layer, 0) + 1


def _middle():
    from ezdxf.enums import TextEntityAlignment

    return TextEntityAlignment.MIDDLE_CENTER


def _draw_geojson(w: _Writer, g: dict[str, Any], to_xy: XY, layer: str, fill_layer: str | None) -> tuple[float, float, float] | None:
    """Draw a lon/lat shape; returns (x, y, size) of its middle for a label."""
    kind, c = g.get("type"), g.get("coordinates")
    polys: list[list] = []
    lines: list[list] = []
    points: list[list] = []
    if kind == "Point":
        points = [c]
    elif kind == "MultiPoint":
        points = list(c)
    elif kind == "LineString":
        lines = [c]
    elif kind == "MultiLineString":
        lines = list(c)
    elif kind == "Polygon":
        polys = [c]
    elif kind == "MultiPolygon":
        polys = list(c)
    xs_all: list[float] = []
    ys_all: list[float] = []
    for poly in polys:
        rings = []
        for ring in poly:
            xs, ys = to_xy([p[0] for p in ring], [p[1] for p in ring])
            w.ring(xs, ys, layer, closed=True)
            rings.append((xs, ys))
            xs_all += xs
            ys_all += ys
        if fill_layer and rings:
            w.fill(rings, fill_layer)
    for line in lines:
        xs, ys = to_xy([p[0] for p in line], [p[1] for p in line])
        w.ring(xs, ys, layer, closed=False)
        xs_all += xs
        ys_all += ys
    if points:
        xs, ys = to_xy([p[0] for p in points], [p[1] for p in points])
        for x, y in zip(xs, ys):
            w.msp.add_point((x, y), dxfattribs={"layer": layer})
        w._seen(xs, ys)
        xs_all += xs
        ys_all += ys
    if not xs_all:
        return None
    return ((min(xs_all) + max(xs_all)) / 2, (min(ys_all) + max(ys_all)) / 2,
            min(max(xs_all) - min(xs_all), max(ys_all) - min(ys_all)))


def _draw_shapely(w: _Writer, shape, metres: XY, layer: str, fill_layer: str | None) -> tuple[float, float, float] | None:
    from shapely.geometry import mapping

    g = mapping(shape)
    return _draw_geojson(w, {"type": g["type"], "coordinates": _lists(g["coordinates"])}, metres, layer, fill_layer)


def _lists(c):
    return [_lists(v) for v in c] if isinstance(c, (list, tuple)) and c and isinstance(c[0], (list, tuple)) else list(c)


def _context(db: Session | None, dataset_id: int | None, w: _Writer) -> int:
    """The original drawing, from the coordinates it was read with: exactly where it was."""
    if db is None or dataset_id is None:
        return 0
    rows = db.execute(text(
        "SELECT l.name AS layer, f.kind, f.source FROM gis_feature f JOIN gis_layer l ON l.id = f.layer_id"
        " WHERE f.dataset_id = :d ORDER BY f.id LIMIT :n"), {"d": dataset_id, "n": MAX_CONTEXT}).mappings()
    n = 0
    for row in rows:
        coords = (row["source"] or {}).get("coords")
        if not coords:
            continue
        layer = w.layer(_layer_name("MAP", str(row["layer"])), COLOURS["map"])
        kind = row["kind"]
        try:
            if kind in ("point", "text"):
                w.msp.add_point((float(coords[0]), float(coords[1])), dxfattribs={"layer": layer})
            elif kind == "line":
                w.ring([p[0] for p in coords], [p[1] for p in coords], layer, closed=False)
            elif kind == "polygon":
                for ring in coords:
                    w.ring([p[0] for p in ring], [p[1] for p in ring], layer, closed=True)
            else:
                continue
        except (TypeError, IndexError, ValueError):
            continue
        n += 1
    return n


def to_dxf(rec: dict[str, Any], db: Session | None = None, labels: dict[str, dict[str, str]] | None = None) -> bytes:
    """The run's answer as DXF (R2018) bytes."""
    import ezdxf

    data = rec.get("data") or {}
    ir = rec.get("ir") or {}
    labels = labels or {}
    mapped = answer_map(ir, data, rec.get("assignments"), rec.get("amounts"), rec.get("results") or [], labels,
                        limit=MAX_ANSWER)
    by_metres = metre_features(ir, data, rec.get("assignments"), rec.get("amounts"), labels)
    if not mapped["features"] and not by_metres:
        raise HTTPException(409, "nothing in this answer has a place to draw: no record of the model has a shape "
                                 "(a geometry field) or a position in metres (x_m and y_m, or shape_m)")
    where = frame(db, rec.get("domain_id"), mapped["features"])
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = _units_code(where.units)
    msp = doc.modelspace()
    w = _Writer(msp, doc)
    drawn_map = _context(db, where.dataset_id, w)

    pending_labels: list[tuple[str, float, float, float, str]] = []

    def put(status: str, var: str, middle, words: str) -> None:
        if middle and status in ("chosen", "short"):
            pending_labels.append((words, *middle, _layer_name(var, "LABELS")))

    for f in mapped["features"]:
        p = f.get("properties") or {}
        status = p.get("status") or "place"
        var = str(p.get("layer") or "answer")
        g = f.get("geometry") or {}
        is_link = g.get("type") == "LineString" and "|" in str(p.get("key") or "")
        name = _layer_name(var, "LINKS" if is_link else status.replace("_", "-"))
        layer = w.layer(name, COLOURS["links" if is_link else status] if status in COLOURS else 7,
                        off=status == "not_chosen")
        fill = (w.layer(_layer_name(var, "CHOSEN", "FILL"), COLOURS["chosen"])
                if status == "chosen" and g.get("type") in ("Polygon", "MultiPolygon") else None)
        middle = _draw_geojson(w, g, where.to_xy, layer, fill)
        w.count(name)
        if not is_link:
            put(status, var, middle, str(p.get("label") or p.get("key") or ""))
    for f in by_metres:
        name = _layer_name(f["layer"], f["status"].replace("_", "-"))
        layer = w.layer(name, COLOURS[f["status"]], off=f["status"] == "not_chosen")
        fill = (w.layer(_layer_name(f["layer"], "CHOSEN", "FILL"), COLOURS["chosen"])
                if f["status"] == "chosen" and f["shape"].geom_type in ("Polygon", "MultiPolygon") else None)
        middle = _draw_shapely(w, f["shape"], where.metres, layer, fill)
        w.count(name)
        put(f["status"], f["layer"], middle, f["label"])

    extent = max(w.box[2] - w.box[0], w.box[3] - w.box[1]) if w.box[0] < math.inf else 1.0
    for words, x, y, size, layer in pending_labels:
        height = max(extent / 2000, min(size * 0.3, extent / 100)) if size > 0 else extent / 300
        w.label(words, x, y, height, w.layer(layer, COLOURS["labels"]))

    lines = [f"{rec.get('problem') or 'Problem'} -- run {rec.get('id')} ({rec.get('scenario') or ''})",
             f"status {rec.get('status')}" + (f", goal {rec.get('objective')}" if rec.get("objective") is not None else ""),
             f"coordinates: {where.describe}"]
    lines += [f"{layer}: {n}" for layer, n in sorted(w.counts.items())]
    if drawn_map:
        lines.append(f"original drawing: {drawn_map} features on MAP-* layers")
    if w.labels >= MAX_LABELS:
        lines.append(f"labels: the first {MAX_LABELS:,}")
    if mapped.get("truncated"):
        lines.append(f"answer: the first {MAX_ANSWER:,} features")
    if w.box[0] < math.inf:
        note = w.layer("ANSWER-NOTE", COLOURS["note"])
        msp.add_mtext("\\P".join(lines), dxfattribs={"layer": note, "char_height": extent / 80}).set_location(
            (w.box[0], w.box[3] + extent / 20))
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")
