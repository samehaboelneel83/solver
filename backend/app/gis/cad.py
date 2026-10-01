"""Any DXF drawing as GIS features, layer by layer (DXF -> GIS, step 1: parse).

Nothing here knows what the drawing is of. Every model-space entity becomes
features of four kinds, in the drawing's own coordinates and units:

- **point**   POINT, a block reference's insertion point (with its attributes)
- **line**    LINE, open polylines, arcs, open splines and ellipse arcs
- **polygon** closed polylines, circles, ellipses, closed splines, hatches
              (with their holes), solids, 3D faces
- **text**    TEXT, MTEXT and block attributes: a point carrying the words,
              their height and rotation

Blocks are exploded where they are inserted (nested blocks too): each piece
keeps the block's name and the insert's attributes, and a piece drawn on
layer 0 takes the insert's layer, as AutoCAD draws it. Dimensions and leaders
become their lines and text. Colours are resolved (BYLAYER, BYBLOCK, true
colour) to `#rrggbb`. Curves are flattened to within `flatten_m` metres.

What cannot be a feature (images, viewports, OLE objects, 3D solids) is
counted under `skipped`, never dropped silently. Z is dropped and kept as
`elevation`. Paper space is not read: a GIS wants the model.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

#: $INSUNITS code -> (name, metres per unit). 0 is "unitless".
UNITS: dict[int, tuple[str, float]] = {
    1: ("inches", 0.0254), 2: ("feet", 0.3048), 3: ("miles", 1609.344), 4: ("millimetres", 0.001),
    5: ("centimetres", 0.01), 6: ("metres", 1.0), 7: ("kilometres", 1000.0), 10: ("yards", 0.9144),
    14: ("decimetres", 0.1), 21: ("US survey feet", 1200 / 3937),
}
UNIT_CHOICES = {"mm": 0.001, "cm": 0.01, "dm": 0.1, "m": 1.0, "km": 1000.0, "in": 0.0254, "ft": 0.3048,
                "us-ft": 1200 / 3937, "yd": 0.9144}
MAX_FEATURES = 250_000
MAX_DEPTH = 8
SKIP = {"IMAGE", "WIPEOUT", "VIEWPORT", "OLE2FRAME", "OLEFRAME", "3DSOLID", "BODY", "REGION", "SURFACE",
        "UNDERLAY", "PDFUNDERLAY", "DWFUNDERLAY", "DGNUNDERLAY", "ATTDEF", "SEQEND", "VERTEX", "XLINE", "RAY",
        "LIGHT", "SUN", "MESH"}


class CadError(ValueError):
    """The file is not a drawing we can read; the message says why."""


@dataclass
class CadFeature:
    kind: str                      # point | line | polygon | text
    coords: Any                    # [x, y] | [[x, y], ...] | [ring, hole, ...]
    layer: str
    entity: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class CadLayer:
    name: str
    color: str = "#000000"
    linetype: str = "Continuous"
    on: bool = True
    frozen: bool = False
    locked: bool = False
    kinds: dict[str, int] = field(default_factory=dict)
    entities: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {"name": self.name, "color": self.color, "linetype": self.linetype, "on": self.on,
                "frozen": self.frozen, "locked": self.locked, "kinds": self.kinds, "entities": self.entities,
                "features": sum(self.kinds.values())}


@dataclass
class CadDrawing:
    version: str
    units_code: int
    units_name: str | None
    unit_metres: float | None
    extent: tuple[float, float, float, float] | None
    layers: dict[str, CadLayer]
    features: list[CadFeature]
    geodata: dict[str, Any] | None
    notes: list[str]
    skipped: dict[str, int]

    def summary(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for f in self.features:
            kinds[f.kind] = kinds.get(f.kind, 0) + 1
        return {
            "version": self.version, "units_code": self.units_code, "units_name": self.units_name,
            "unit_metres": self.unit_metres, "extent": list(self.extent) if self.extent else None,
            "layers": [l.summary() for l in sorted(self.layers.values(), key=lambda l: l.name.lower())],
            "kinds": kinds, "features": len(self.features), "geodata": self.geodata, "notes": self.notes,
            "skipped": self.skipped,
        }


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*[int(c) for c in rgb])


def _aci(index: int) -> str:
    from ezdxf.colors import aci2rgb

    if index in (7, 255):  # white on black, black on white: dark on a map
        return "#1f2937"
    try:
        return _hex(aci2rgb(index))
    except (IndexError, ValueError):
        return "#1f2937"


@dataclass
class _Ctx:
    zero_layer: str | None = None
    byblock: str | None = None
    block: list[str] = field(default_factory=list)
    attribs: dict[str, str] | None = None


class _Reader:
    def __init__(self, doc, tolerance: float, max_features: int):
        self.doc = doc
        self.tolerance = tolerance
        self.max_features = max_features
        self.features: list[CadFeature] = []
        self.skipped: dict[str, int] = {}
        self.layers: dict[str, CadLayer] = {}
        self.truncated = False
        for layer in doc.layers:
            colour = layer.dxf.get("color", 7)
            true = layer.rgb if layer.dxf.hasattr("true_color") else None
            self.layers[layer.dxf.name] = CadLayer(
                name=layer.dxf.name, color=_hex(true) if true else _aci(abs(colour)),
                linetype=layer.dxf.get("linetype", "Continuous"), on=colour >= 0 and layer.is_on(),
                frozen=layer.is_frozen(), locked=layer.is_locked())

    # -- helpers ----------------------------------------------------------------------------
    def _layer(self, e, ctx: _Ctx) -> str:
        name = e.dxf.get("layer", "0") or "0"
        if name == "0" and ctx.zero_layer:
            name = ctx.zero_layer
        if name not in self.layers:
            self.layers[name] = CadLayer(name=name)
        return name

    def _colour(self, e, layer: str, ctx: _Ctx) -> str:
        if e.dxf.hasattr("true_color"):
            return _hex(e.rgb)
        index = e.dxf.get("color", 256)
        if index == 256:
            return self.layers[layer].color
        if index == 0:
            return ctx.byblock or self.layers[layer].color
        return _aci(index)

    def _add(self, kind: str, coords, e, ctx: _Ctx, **props) -> None:
        if len(self.features) >= self.max_features:
            self.truncated = True
            return
        layer = self._layer(e, ctx)
        base = {"handle": e.dxf.get("handle"), "color": self._colour(e, layer, ctx)}
        linetype = e.dxf.get("linetype")
        if linetype and linetype.upper() not in ("BYLAYER",):
            base["linetype"] = linetype
        if ctx.block:
            base["block"] = ctx.block[-1]
            if len(ctx.block) > 1:
                base["block_path"] = "/".join(ctx.block)
        if ctx.attribs:
            base["attributes"] = ctx.attribs
        props = {k: v for k, v in {**base, **props}.items() if v is not None and v != ""}
        self.features.append(CadFeature(kind, coords, layer, e.dxftype(), props))
        lay = self.layers[layer]
        lay.kinds[kind] = lay.kinds.get(kind, 0) + 1
        lay.entities[e.dxftype()] = lay.entities.get(e.dxftype(), 0) + 1

    def _flat(self, path) -> list[list[float]]:
        return [[v.x, v.y] for v in path.flattening(self.tolerance)]

    def _skip(self, kind: str) -> None:
        self.skipped[kind] = self.skipped.get(kind, 0) + 1

    # -- entities ---------------------------------------------------------------------------
    def visit(self, e, ctx: _Ctx, depth: int = 0) -> None:
        if self.truncated:
            return
        kind = e.dxftype()
        try:
            handler = getattr(self, f"_{kind.lower()}", None)
            if handler is not None:
                handler(e, ctx, depth)
            elif kind in SKIP:
                self._skip(kind)
            elif hasattr(e, "virtual_entities"):
                for v in e.virtual_entities():
                    self.visit(v, ctx, depth + 1)
            else:
                self._skip(kind)
        except Exception:  # noqa: BLE001 -- one broken entity must not lose the drawing
            self._skip(f"{kind} (unreadable)")

    def _point(self, e, ctx, depth):
        p = e.dxf.location
        self._add("point", [p.x, p.y], e, ctx, elevation=p.z or None)

    def _line(self, e, ctx, depth):
        a, b = e.dxf.start, e.dxf.end
        if (a.x, a.y) != (b.x, b.y):
            self._add("line", [[a.x, a.y], [b.x, b.y]], e, ctx, elevation=a.z or None)

    def _curve(self, e, ctx, closed: bool, **props):
        from ezdxf import path as dxfpath

        pts = self._flat(dxfpath.make_path(e))
        pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
        if closed and len(pts) >= 3:
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            if len(pts) >= 4:
                self._add("polygon", [pts], e, ctx, **props)
                return
        if len(pts) >= 2:
            self._add("line", pts, e, ctx, **props)

    def _lwpolyline(self, e, ctx, depth):
        self._curve(e, ctx, bool(e.closed), elevation=e.dxf.get("elevation") or None,
                    width=e.dxf.get("const_width") or None)

    def _polyline(self, e, ctx, depth):
        if e.is_polygon_mesh or e.is_poly_face_mesh:
            for v in e.virtual_entities():
                self.visit(v, ctx, depth + 1)
            return
        self._curve(e, ctx, bool(e.is_closed))

    def _circle(self, e, ctx, depth):
        self._curve(e, ctx, True, radius=e.dxf.radius)

    def _arc(self, e, ctx, depth):
        self._curve(e, ctx, False, radius=e.dxf.radius)

    def _ellipse(self, e, ctx, depth):
        full = math.isclose(abs(e.dxf.end_param - e.dxf.start_param), 2 * math.pi, abs_tol=1e-6)
        self._curve(e, ctx, full)

    def _spline(self, e, ctx, depth):
        self._curve(e, ctx, bool(e.closed))

    def _hatch(self, e, ctx, depth):
        from ezdxf import path as dxfpath
        from shapely.geometry import MultiPolygon, Polygon

        shape = None
        for p in dxfpath.from_hatch(e):
            ring = self._flat(p)
            if len(ring) < 3:
                continue
            poly = Polygon(ring).buffer(0)
            if poly.is_empty:
                continue
            # Even-odd: a ring inside another is a hole; a ring inside a hole is an island.
            shape = poly if shape is None else shape.symmetric_difference(poly)
        if shape is None or shape.is_empty:
            return
        parts = list(shape.geoms) if isinstance(shape, MultiPolygon) else [shape] if isinstance(shape, Polygon) else \
            [g for g in getattr(shape, "geoms", []) if isinstance(g, Polygon)]
        pattern = e.dxf.get("pattern_name")
        for part in parts:
            rings = [[list(c) for c in part.exterior.coords]] + [[list(c) for c in r.coords] for r in part.interiors]
            self._add("polygon", rings, e, ctx, pattern=pattern, solid=bool(e.dxf.get("solid_fill", 0)))

    _mpolygon = _hatch

    def _solid(self, e, ctx, depth):
        v = [e.dxf.get(f"vtx{i}") for i in range(4)]
        pts = [v[0], v[1], v[3] if v[3] is not None else v[2], v[2]]
        ring = []
        for p in pts:
            if p is not None and (not ring or [p.x, p.y] != ring[-1]):
                ring.append([p.x, p.y])
        if len(ring) >= 3:
            self._add("polygon", [ring + [ring[0]]], e, ctx)

    _trace = _solid

    def _3dface(self, e, ctx, depth):
        ring = []
        for i in range(4):
            p = e.dxf.get(f"vtx{i}")
            if p is not None and (not ring or [p.x, p.y] != ring[-1]):
                ring.append([p.x, p.y])
        if len(ring) >= 3 and ring[0] != ring[-1]:
            self._add("polygon", [ring + [ring[0]]], e, ctx)

    def _text(self, e, ctx, depth):
        p = e.dxf.insert
        if e.dxf.get("halign", 0) or e.dxf.get("valign", 0):
            p = e.dxf.get("align_point", p) or p
        words = e.plain_text() if hasattr(e, "plain_text") else e.dxf.text
        if words and words.strip():
            self._add("text", [p.x, p.y], e, ctx, text=words.strip(), height=e.dxf.get("height"),
                      rotation=e.dxf.get("rotation") or None, style=e.dxf.get("style"))

    def _attrib(self, e, ctx, depth):
        p = e.dxf.insert
        words = e.dxf.get("text", "")
        if words and words.strip() and not e.is_invisible:
            self._add("text", [p.x, p.y], e, ctx, text=words.strip(), tag=e.dxf.get("tag"),
                      height=e.dxf.get("height"), rotation=e.dxf.get("rotation") or None)

    def _mtext(self, e, ctx, depth):
        p = e.dxf.insert
        words = e.plain_text()
        if words and words.strip():
            self._add("text", [p.x, p.y], e, ctx, text=words.strip(), height=e.dxf.get("char_height"),
                      rotation=e.get_rotation() or None)

    def _insert(self, e, ctx, depth):
        if depth >= MAX_DEPTH:
            self._skip("INSERT (nested too deep)")
            return
        name = e.dxf.name
        attribs = {a.dxf.tag: a.dxf.text for a in e.attribs if a.dxf.get("text")}
        layer = self._layer(e, ctx)
        p = e.dxf.insert
        scale = (e.dxf.get("xscale", 1), e.dxf.get("yscale", 1))
        extra: dict[str, Any] = {"attributes": {**(ctx.attribs or {}), **attribs}} if attribs else {}
        self._add("point", [p.x, p.y], e, ctx, block=name, block_reference=True,
                  rotation=e.dxf.get("rotation") or None, scale=list(scale) if scale != (1, 1) else None, **extra)
        inner = _Ctx(zero_layer=layer, byblock=self._colour(e, layer, ctx), block=[*ctx.block, name],
                     attribs={**(ctx.attribs or {}), **attribs} or None)
        for v in e.virtual_entities():
            self.visit(v, inner, depth + 1)
        for a in e.attribs:
            self._attrib(a, inner, depth + 1)

    def _dimension(self, e, ctx, depth):
        inner = _Ctx(zero_layer=self._layer(e, ctx), byblock=ctx.byblock, block=ctx.block, attribs=ctx.attribs)
        for v in e.virtual_entities():
            self.visit(v, inner, depth + 1)

    _leader = _dimension
    _multileader = _dimension
    _acad_table = _dimension
    _arc_dimension = _dimension
    _large_radial_dimension = _dimension


def _geodata(msp) -> dict[str, Any] | None:
    """AutoCAD's geographic location (GEODATA), when the drawing carries one."""
    try:
        geo = msp.get_geodata()
    except Exception:  # noqa: BLE001
        return None
    if geo is None:
        return None
    out: dict[str, Any] = {}
    try:
        d, r = geo.dxf.design_point, geo.dxf.reference_point
        out["design_point"] = [d.x, d.y]
        out["reference_point"] = [r.x, r.y]
        out["north_direction"] = [geo.dxf.north_direction.x, geo.dxf.north_direction.y]
        out["unit_scale"] = geo.dxf.get("horizontal_unit_scale", 1.0)
    except Exception:  # noqa: BLE001
        pass
    definition = getattr(geo, "coordinate_system_definition", "") or ""
    match = re.search(r"EPSG[^0-9]{0,4}(\d{4,5})", definition) or re.search(r'<Alias id="(\d{4,5})"', definition)
    if match:
        out["epsg"] = int(match.group(1))
    name = re.search(r'<Name>([^<]+)</Name>', definition)
    if name:
        out["crs_name"] = name.group(1)
    return out or None


def read(path: str | Path, *, flatten_m: float = 0.01, max_features: int = MAX_FEATURES) -> CadDrawing:
    """Read a DXF file into features in its own coordinates and units."""
    import ezdxf
    from ezdxf import bbox, recover

    notes: list[str] = []
    try:
        doc = ezdxf.readfile(str(path))
    except IOError as exc:
        raise CadError(f"the file cannot be opened: {exc}") from exc
    except ezdxf.DXFStructureError:
        try:
            doc, auditor = recover.readfile(str(path))
        except Exception as exc:  # noqa: BLE001
            raise CadError("this is not a DXF file we can read (a DWG must be saved as DXF first)") from exc
        if auditor.has_errors:
            notes.append(f"the file was damaged: {len(auditor.errors)} problems were repaired while reading")
    msp = doc.modelspace()
    code = int(doc.header.get("$INSUNITS", 0) or 0)
    unit = UNITS.get(code)
    extent = None
    try:
        box = bbox.extents(msp, fast=True)
        if box.has_data:
            extent = (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y)
    except Exception:  # noqa: BLE001
        pass
    degrees = extent is not None and all(abs(v) <= 180 for v in (extent[0], extent[2])) and \
        all(abs(v) <= 90 for v in (extent[1], extent[3])) and (extent[2] - extent[0]) < 30 and unit is None
    if degrees:
        tolerance = 1e-7
    else:
        tolerance = flatten_m / (unit[1] if unit else 1.0)
    reader = _Reader(doc, tolerance, max_features)
    for e in msp:
        reader.visit(e, _Ctx())
    if reader.truncated:
        notes.append(f"the drawing has more than {max_features:,} features; only the first {max_features:,} were read")
    if code and not unit:
        notes.append(f"the drawing's units (code {code}) are not ones we convert; give them when placing it")
    if not code:
        notes.append("the drawing does not say its units")
    feats = reader.features
    if feats:
        xs, ys = [], []
        for f in feats:
            for x, y in _points(f):
                xs.append(x)
                ys.append(y)
        extent = (min(xs), min(ys), max(xs), max(ys))
    layers = {k: v for k, v in reader.layers.items() if v.kinds or k != "Defpoints"}
    return CadDrawing(
        version=doc.dxfversion, units_code=code, units_name=unit[0] if unit else None,
        unit_metres=unit[1] if unit else None, extent=extent, layers=layers, features=feats,
        geodata=_geodata(msp), notes=notes, skipped=reader.skipped,
    )


def _points(f: CadFeature) -> Iterator[tuple[float, float]]:
    if f.kind in ("point", "text"):
        yield f.coords[0], f.coords[1]
    elif f.kind == "line":
        for p in f.coords:
            yield p[0], p[1]
    else:
        for p in f.coords[0]:
            yield p[0], p[1]
