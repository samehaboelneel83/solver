"""Spatial files other than DXF as map data: GeoJSON, KML/KMZ, GPX, Shapefile,
GeoPackage and CSV (step 1: parse, as `app.gis.cad` does for drawings).

Each reader gives the same `CadDrawing` a DXF gives -- layers of point, line
and polygon features in the file's own coordinates, with their attributes as
properties -- so placing, storing, viewing and making records from a layer work
the same for every format.

| format       | files                         | layers are                     | coordinate system |
|--------------|-------------------------------|--------------------------------|-------------------|
| GeoJSON      | .geojson, .json               | a `layer` property, else the geometry type | WGS 84 (RFC 7946), or its legacy `crs` member |
| KML / KMZ    | .kml, .kmz                    | the folder a placemark is in   | WGS 84 |
| GPX          | .gpx                          | waypoints, routes, tracks      | WGS 84 |
| Shapefile    | .zip holding .shp, .dbf, .prj | each .shp in the zip           | the .prj |
| GeoPackage   | .gpkg                         | each feature table             | the table's SRS |
| CSV          | .csv                          | a `layer` column, else the file | none: chosen when placing |

A CSV row's shape is a WKT column (`wkt`, `geometry`, `geom`, `the_geom`,
`shape`) or a pair of coordinate columns (`lon`/`lat`, `longitude`/`latitude`,
`x`/`y`, `easting`/`northing`).

Multi-part shapes become one feature per part, all with the same attributes
and a `part` number; a polygon keeps its holes. Z is dropped. Nothing here
needs a library beyond shapely and pyproj: a Shapefile and a GeoPackage are
read directly.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import struct
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from xml.etree import ElementTree

from app.gis.cad import MAX_FEATURES, CadDrawing, CadError, CadFeature, CadLayer, _points

#: File endings each reader takes; `.dxf` stays with `app.gis.cad`.
SUFFIXES = {
    ".geojson": "GeoJSON", ".json": "GeoJSON", ".kml": "KML", ".kmz": "KMZ", ".gpx": "GPX",
    ".zip": "Shapefile", ".shp": "Shapefile", ".gpkg": "GeoPackage", ".csv": "CSV",
}
ACCEPTED = (".dxf", *SUFFIXES)
#: Layer colours, in turn: a file of these formats rarely says one.
PALETTE = ("#2563eb", "#059669", "#dc2626", "#7e22ce", "#d97706", "#0891b2", "#be185d", "#4d7c0f", "#475569")
WKT_COLUMNS = ("wkt", "geometry", "geom", "the_geom", "shape", "wkt_geom")
XY_COLUMNS = (("lon", "lat"), ("lng", "lat"), ("long", "lat"), ("longitude", "latitude"), ("x", "y"),
              ("easting", "northing"), ("east", "north"))


class _Builder:
    """Features and layers as a reader finds them."""

    def __init__(self, fmt: str, max_features: int = MAX_FEATURES):
        self.fmt = fmt
        self.max = max_features
        self.features: list[CadFeature] = []
        self.layers: dict[str, CadLayer] = {}
        self.skipped: dict[str, int] = {}
        self.notes: list[str] = []
        self.truncated = False

    def layer(self, name: str, color: str | None = None) -> CadLayer:
        name = (name or "features").strip()[:255] or "features"
        if name not in self.layers:
            self.layers[name] = CadLayer(name=name, color=color or PALETTE[len(self.layers) % len(PALETTE)])
        return self.layers[name]

    def skip(self, what: str) -> None:
        self.skipped[what] = self.skipped.get(what, 0) + 1

    def add(self, geometry, layer: str, props: dict[str, Any], entity: str | None = None) -> None:
        """A shapely geometry (any type) as features of `layer`."""
        if geometry is None or geometry.is_empty:
            self.skip("empty geometry")
            return
        parts = list(_explode(geometry))
        for n, g in enumerate(parts, start=1):
            if len(self.features) >= self.max:
                self.truncated = True
                return
            extra = {"part": n} if len(parts) > 1 else {}
            kind, coords = _coords(g)
            if kind is None:
                self.skip(g.geom_type)
                continue
            lay = self.layer(layer)
            name = entity or geometry.geom_type
            self.features.append(CadFeature(kind, coords, lay.name, name, {**_clean(props), **extra}))
            lay.kinds[kind] = lay.kinds.get(kind, 0) + 1
            lay.entities[name] = lay.entities.get(name, 0) + 1

    def drawing(self, *, crs: int | None, crs_name: str | None = None, reason: str | None = None) -> CadDrawing:
        if self.truncated:
            self.notes.append(f"the file has more than {self.max:,} features; only the first {self.max:,} were read")
        if not self.features:
            raise CadError(f"the {self.fmt} file has no shapes we can show on a map")
        xs, ys = [], []
        for f in self.features:
            for x, y in _points(f):
                xs.append(x)
                ys.append(y)
        geodata: dict[str, Any] | None = None
        if crs:
            geodata = {"epsg": crs, "reason": reason or f"the {self.fmt} file names it"}
            if crs_name:
                geodata["crs_name"] = crs_name
        return CadDrawing(version=self.fmt, units_code=0, units_name=None, unit_metres=None,
                          extent=(min(xs), min(ys), max(xs), max(ys)), layers=self.layers, features=self.features,
                          geodata=geodata, notes=self.notes, skipped=self.skipped)


def _clean(props: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (props or {}).items():
        if k in ("layer", "kind", "entity"):
            k = f"{k}_"
        if isinstance(v, bytes):
            continue
        out[str(k)[:100]] = v if isinstance(v, (str, int, float, bool)) or v is None else json.dumps(v, default=str)
    return out


def _explode(g) -> Iterable:
    if hasattr(g, "geoms"):
        for part in g.geoms:
            yield from _explode(part)
    else:
        yield g


def _xy(seq) -> list[list[float]]:
    return [[float(p[0]), float(p[1])] for p in seq]


def _coords(g) -> tuple[str | None, Any]:
    t = g.geom_type
    if t == "Point":
        return "point", [float(g.x), float(g.y)]
    if t in ("LineString", "LinearRing"):
        pts = _xy(g.coords)
        return ("line", pts) if len(pts) >= 2 else (None, None)
    if t == "Polygon":
        rings = [_xy(g.exterior.coords)] + [_xy(r.coords) for r in g.interiors]
        return ("polygon", rings) if len(rings[0]) >= 4 else (None, None)
    return None, None


def _epsg(definition: str | None) -> tuple[int | None, str | None]:
    """An EPSG code (and name) from a CRS definition: a URN, `EPSG:n`, or WKT (a .prj)."""
    if not definition:
        return None, None
    match = re.search(r"EPSG(?::|::|/0/|/)(\d{4,6})", definition, re.I)
    if match:
        return int(match.group(1)), None
    if re.search(r"CRS84|OGC::?CRS84", definition, re.I):
        return 4326, None
    try:
        from pyproj import CRS

        crs = CRS.from_user_input(definition)
        code = crs.to_epsg(min_confidence=60)
        return code, crs.name
    except Exception:  # noqa: BLE001 -- an unknown definition: chosen when placing
        return None, None


# -- GeoJSON -----------------------------------------------------------------------------------

def read_geojson(data: bytes) -> CadDrawing:
    from shapely.geometry import shape

    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CadError(f"this is not GeoJSON: {exc}") from exc
    b = _Builder("GeoJSON")
    if isinstance(doc, dict) and doc.get("type") == "Topology":
        raise CadError("this is TopoJSON; save it as GeoJSON first")
    if isinstance(doc, dict) and doc.get("type") == "FeatureCollection":
        feats = doc.get("features") or []
    elif isinstance(doc, dict) and doc.get("type") == "Feature":
        feats = [doc]
    elif isinstance(doc, dict) and doc.get("type") in ("Point", "MultiPoint", "LineString", "MultiLineString",
                                                       "Polygon", "MultiPolygon", "GeometryCollection"):
        feats = [{"type": "Feature", "geometry": doc, "properties": {}}]
    elif isinstance(doc, list):
        feats = doc
    else:
        raise CadError("this JSON is not GeoJSON: it needs a FeatureCollection, a Feature or a geometry")
    for f in feats:
        if not isinstance(f, dict) or not f.get("geometry"):
            b.skip("feature without geometry")
            continue
        props = f.get("properties") or {}
        try:
            g = shape(f["geometry"])
        except Exception:  # noqa: BLE001 -- a broken geometry: counted, the rest read
            b.skip("unreadable geometry")
            continue
        if f.get("id") is not None:
            props = {"id": f["id"], **props}
        key = next((k for k in ("layer", "Layer", "LAYER") if props.get(k)), None)
        layer = str(props[key]) if key else _plural(g.geom_type)
        b.add(g, layer, {k: v for k, v in props.items() if k != key}, entity=g.geom_type)
    legacy = ((doc.get("crs") or {}).get("properties") or {}).get("name") if isinstance(doc, dict) else None
    code, name = _epsg(legacy) if legacy else (4326, None)
    reason = "the GeoJSON file names it (its crs member)" if legacy else \
        "GeoJSON is longitude and latitude in WGS 84 (RFC 7946)"
    return b.drawing(crs=code, crs_name=name, reason=reason)


def _plural(geometry_type: str) -> str:
    return {"Point": "points", "MultiPoint": "points", "LineString": "lines", "MultiLineString": "lines",
            "Polygon": "polygons", "MultiPolygon": "polygons"}.get(geometry_type, "features")


# -- KML / KMZ ---------------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, name: str):
    return next((c for c in el if _local(c.tag) == name), None)


def _text(el, name: str) -> str | None:
    c = _child(el, name)
    return c.text.strip() if c is not None and c.text else None


def _kml_points(text: str | None) -> list[tuple[float, float]]:
    out = []
    for token in (text or "").split():
        parts = token.split(",")
        if len(parts) >= 2:
            try:
                out.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    return out


def _kml_geometry(el):
    from shapely.geometry import GeometryCollection, LineString, Point, Polygon

    kind = _local(el.tag)
    if kind == "Point":
        pts = _kml_points(_text(el, "coordinates"))
        return Point(pts[0]) if pts else None
    if kind in ("LineString", "LinearRing"):
        pts = _kml_points(_text(el, "coordinates"))
        return LineString(pts) if len(pts) >= 2 else None
    if kind == "Polygon":
        def ring(boundary):
            ring_el = next((c for c in boundary.iter() if _local(c.tag) == "LinearRing"), None)
            return _kml_points(_text(ring_el, "coordinates")) if ring_el is not None else []
        outer = next((c for c in el if _local(c.tag) == "outerBoundaryIs"), None)
        if outer is None:
            return None
        shell = ring(outer)
        holes = [h for h in (ring(c) for c in el if _local(c.tag) == "innerBoundaryIs") if len(h) >= 3]
        return Polygon(shell, holes) if len(shell) >= 3 else None
    if kind == "MultiGeometry":
        parts = [g for g in (_kml_geometry(c) for c in el) if g is not None]
        return GeometryCollection(parts) if parts else None
    return None


GEOMETRY_TAGS = ("Point", "LineString", "LinearRing", "Polygon", "MultiGeometry")


def read_kml(data: bytes, fmt: str = "KML") -> CadDrawing:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise CadError(f"this is not KML: {exc}") from exc
    b = _Builder(fmt)

    def walk(el, folder: str) -> None:
        for c in el:
            tag = _local(c.tag)
            if tag in ("Folder", "Document"):
                name = _text(c, "name")
                walk(c, name if tag == "Folder" and name else folder or name or "placemarks")
            elif tag == "Placemark":
                props: dict[str, Any] = {}
                for key in ("name", "description"):
                    if _text(c, key):
                        props[key] = _text(c, key)
                ext = _child(c, "ExtendedData")
                if ext is not None:
                    for d in ext.iter():
                        if _local(d.tag) == "Data" and d.get("name"):
                            props[d.get("name")] = _text(d, "value")
                        elif _local(d.tag) == "SimpleData" and d.get("name"):
                            props[d.get("name")] = (d.text or "").strip()
                geom_el = next((g for g in c if _local(g.tag) in GEOMETRY_TAGS), None)
                g = _kml_geometry(geom_el) if geom_el is not None else None
                if g is None:
                    b.skip("placemark without a shape we read")
                    continue
                b.add(g, folder or "placemarks", props, entity=_local(geom_el.tag))
            elif tag in ("GroundOverlay", "ScreenOverlay", "PhotoOverlay", "NetworkLink"):
                b.skip(tag)

    walk(root, "")
    return b.drawing(crs=4326, reason=f"{fmt} is longitude and latitude in WGS 84")


def read_kmz(data: bytes) -> CadDrawing:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".kml")), None)
            if name is None:
                raise CadError("the KMZ holds no .kml")
            return read_kml(z.read(name), "KMZ")
    except zipfile.BadZipFile as exc:
        raise CadError("this KMZ is not a zip file") from exc


# -- GPX ---------------------------------------------------------------------------------------

def read_gpx(data: bytes) -> CadDrawing:
    from shapely.geometry import LineString, Point

    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise CadError(f"this is not GPX: {exc}") from exc
    b = _Builder("GPX")

    def point(el) -> tuple[float, float] | None:
        try:
            return float(el.get("lon")), float(el.get("lat"))
        except (TypeError, ValueError):
            return None

    def info(el) -> dict[str, Any]:
        return {k: _text(el, k) for k in ("name", "desc", "type", "ele", "time") if _text(el, k)}

    for el in root:
        tag = _local(el.tag)
        if tag == "wpt" and point(el):
            b.add(Point(point(el)), "waypoints", info(el), entity="waypoint")
        elif tag == "rte":
            pts = [p for p in (point(c) for c in el if _local(c.tag) == "rtept") if p]
            if len(pts) >= 2:
                b.add(LineString(pts), "routes", info(el), entity="route")
        elif tag == "trk":
            for seg in (c for c in el if _local(c.tag) == "trkseg"):
                pts = [p for p in (point(c) for c in seg if _local(c.tag) == "trkpt") if p]
                if len(pts) >= 2:
                    b.add(LineString(pts), "tracks", info(el), entity="track")
    return b.drawing(crs=4326, reason="GPX is longitude and latitude in WGS 84")


# -- Shapefile ---------------------------------------------------------------------------------

def _dbf(data: bytes, encoding: str) -> list[dict[str, Any]]:
    if len(data) < 32:
        return []
    count, header, size = struct.unpack("<IHH", data[4:12])
    fields = []
    at = 32
    while at + 32 <= header and data[at] != 0x0D:
        name = data[at:at + 11].split(b"\x00", 1)[0].decode("latin-1").strip()
        fields.append((name, chr(data[at + 11]), data[at + 16], data[at + 17]))
        at += 32
    rows = []
    for i in range(count):
        start = header + i * size
        rec = data[start:start + size]
        if len(rec) < size or rec[:1] == b"*":
            rows.append({})
            continue
        row: dict[str, Any] = {}
        pos = 1
        for name, kind, length, decimals in fields:
            raw = rec[pos:pos + length]
            pos += length
            try:
                text_value = raw.decode(encoding).strip()
            except UnicodeDecodeError:
                text_value = raw.decode("latin-1").strip()
            if kind in ("N", "F"):
                try:
                    value: Any = (float(text_value) if decimals or "." in text_value else int(text_value)) \
                        if text_value and set(text_value) != {"*"} else None
                except ValueError:
                    value = None
            elif kind == "L":
                value = {"T": True, "Y": True, "F": False, "N": False}.get(text_value[:1].upper())
            elif kind == "D" and len(text_value) == 8:
                value = f"{text_value[:4]}-{text_value[4:6]}-{text_value[6:]}"
            else:
                value = text_value or None
            row[name] = value
        rows.append(row)
    return rows


def _shp(data: bytes) -> list:
    """Each record's shape (shapely, or None for a null shape), in file order."""
    from shapely.geometry import LineString, MultiPoint, Point, Polygon
    from shapely.geometry.polygon import orient

    out: list = []
    at = 100
    while at + 8 <= len(data):
        _, words = struct.unpack(">ii", data[at:at + 8])
        body = data[at + 8:at + 8 + words * 2]
        at += 8 + words * 2
        if len(body) < 4:
            out.append(None)
            continue
        kind = struct.unpack("<i", body[:4])[0]
        base = kind % 10  # 1 point, 3 polyline, 5 polygon, 8 multipoint; +10 with Z, +20 with M
        if kind == 0 or kind == 31:  # null; multipatch is not a map shape
            out.append(None)
        elif base == 1:  # point, point Z, point M
            x, y = struct.unpack("<2d", body[4:20])
            out.append(Point(x, y))
        elif base == 8:  # multipoint
            n = struct.unpack("<i", body[36:40])[0]
            pts = struct.unpack(f"<{2 * n}d", body[40:40 + 16 * n])
            out.append(MultiPoint([(pts[2 * i], pts[2 * i + 1]) for i in range(n)]))
        elif base in (3, 5):  # polyline, polygon
            parts_n, points_n = struct.unpack("<2i", body[36:44])
            parts = list(struct.unpack(f"<{parts_n}i", body[44:44 + 4 * parts_n]))
            start = 44 + 4 * parts_n
            flat = struct.unpack(f"<{2 * points_n}d", body[start:start + 16 * points_n])
            pts = [(flat[2 * i], flat[2 * i + 1]) for i in range(points_n)]
            rings = [pts[a:b] for a, b in zip(parts, parts[1:] + [points_n])]
            if base == 3:
                lines = [LineString(r) for r in rings if len(r) >= 2]
                out.append(lines[0] if len(lines) == 1 else _multi(lines))
            else:
                out.append(_polygons(rings, Polygon, orient))
        else:
            out.append(None)
    return out


def _multi(parts):
    from shapely.geometry import GeometryCollection

    return GeometryCollection(parts) if parts else None


def _polygons(rings, Polygon, orient):
    """Shapefile rings: outer rings clockwise, holes counter-clockwise; each hole to the outer ring holding it."""
    shells, holes = [], []
    for r in rings:
        if len(r) < 4:
            continue
        p = Polygon(r)
        if not p.is_valid and p.area == 0:
            continue
        # The shoelace sign: clockwise (negative) is an outer ring.
        area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:]))
        (shells if area < 0 else holes).append(r)
    if not shells:  # rings drawn the other way round: each its own polygon
        shells, holes = holes, []
    polys = [[s, []] for s in shells]
    for h in holes:
        hp = Polygon(h)
        home = next((p for p in polys if Polygon(p[0]).contains(hp.representative_point())), None)
        if home is not None:
            home[1].append(h)
        else:
            polys.append([h, []])
    made = [orient(Polygon(s, hs)) for s, hs in polys]
    return made[0] if len(made) == 1 else _multi(made)


def read_shapefile(data: bytes, filename: str) -> CadDrawing:
    if filename.lower().endswith(".shp"):
        raise CadError("a shapefile is several files: put the .shp, .shx, .dbf and .prj in one .zip and send that")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise CadError("this .zip cannot be opened") from exc
    names = {n.lower(): n for n in z.namelist() if not n.startswith("__MACOSX")}
    shps = sorted(n for n in names if n.endswith(".shp"))
    if not shps:
        raise CadError("the .zip holds no shapefile (.shp); a zip of other files is not map data we read")
    b = _Builder("Shapefile")
    codes: dict[int | None, str | None] = {}
    for shp in shps:
        stem = shp[:-4]
        layer = PurePosixPath(names[shp]).name[:-4]
        cpg = names.get(stem + ".cpg")
        encoding = (z.read(cpg).decode("ascii", "ignore").strip() if cpg else "") or "utf-8"
        try:
            "".encode(encoding)
        except LookupError:
            encoding = "utf-8"
        rows = _dbf(z.read(names[stem + ".dbf"]), encoding) if stem + ".dbf" in names else []
        prj = names.get(stem + ".prj")
        code, name = _epsg(z.read(prj).decode("utf-8", "ignore")) if prj else (None, None)
        codes[code] = name
        for i, g in enumerate(_shp(z.read(names[shp]))):
            if g is None:
                b.skip("null shape")
                continue
            b.add(g, layer, rows[i] if i < len(rows) else {}, entity=_plural(g.geom_type).rstrip("s"))
    known = [c for c in codes if c]
    if len(set(known)) > 1:
        b.notes.append("the shapefiles in the zip are in different coordinate systems; "
                       f"they are placed with the first (EPSG:{known[0]})")
    if None in codes and not known:
        b.notes.append("no .prj says the coordinate system: choose it when placing")
    return b.drawing(crs=known[0] if known else None, crs_name=codes.get(known[0]) if known else None,
                     reason="the shapefile's .prj names it")


# -- GeoPackage --------------------------------------------------------------------------------

_ENVELOPE = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


def _gpkg_geometry(blob: bytes):
    from shapely import wkb

    if not blob or blob[:2] != b"GP":
        return wkb.loads(bytes(blob)) if blob else None
    flags = blob[3]
    if flags & 0x10:  # empty
        return None
    start = 8 + _ENVELOPE.get((flags >> 1) & 0x07, 0)
    return wkb.loads(bytes(blob[start:]))


def read_geopackage(data: bytes) -> CadDrawing:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "data.gpkg"
        path.write_bytes(data)
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            tables = con.execute(
                "SELECT c.table_name, g.column_name, g.srs_id, s.organization, s.organization_coordsys_id, s.srs_name"
                " FROM gpkg_contents c JOIN gpkg_geometry_columns g ON g.table_name = c.table_name"
                " LEFT JOIN gpkg_spatial_ref_sys s ON s.srs_id = g.srs_id"
                " WHERE c.data_type = 'features' ORDER BY c.table_name").fetchall()
        except sqlite3.DatabaseError as exc:
            raise CadError("this is not a GeoPackage (a SQLite file with gpkg_contents)") from exc
        b = _Builder("GeoPackage")
        first: tuple[int | None, str | None] | None = None
        try:
            for table, column, srs_id, org, org_id, srs_name in tables:
                code = int(org_id) if org and str(org).upper() == "EPSG" and org_id and int(org_id) > 0 else None
                if first is None:
                    first = (code, srs_name)
                elif code != first[0]:
                    b.notes.append(f"layer {table} is in another coordinate system (EPSG:{code}); "
                                   f"it is placed with the first's (EPSG:{first[0]})")
                cur = con.execute(f'SELECT * FROM "{table}"')
                cols = [d[0] for d in cur.description]
                for row in cur:
                    rec = dict(zip(cols, row))
                    try:
                        g = _gpkg_geometry(rec.pop(column))
                    except Exception:  # noqa: BLE001 -- a broken shape: counted
                        b.skip("unreadable geometry")
                        continue
                    if g is None:
                        b.skip("empty geometry")
                        continue
                    b.add(g, table, rec, entity=g.geom_type)
        finally:
            con.close()
    if first is None:
        raise CadError("the GeoPackage has no feature tables")
    return b.drawing(crs=first[0], crs_name=first[1], reason="the GeoPackage names it")


# -- CSV ---------------------------------------------------------------------------------------

def read_csv(data: bytes, stem: str) -> CadDrawing:
    from shapely import wkt
    from shapely.geometry import Point

    text_data = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text_data[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text_data), dialect=dialect)
    fields = {f.lower().strip(): f for f in (reader.fieldnames or [])}
    shape_col = next((fields[c] for c in WKT_COLUMNS if c in fields), None)
    pair = next(((fields[x], fields[y]) for x, y in XY_COLUMNS if x in fields and y in fields), None)
    if shape_col is None and pair is None:
        raise CadError("the CSV needs a WKT column (wkt, geometry) or coordinate columns (lon and lat, or x and y)")
    layer_col = fields.get("layer")
    b = _Builder("CSV")
    for row in reader:
        props = {k: v for k, v in row.items() if k and k not in (shape_col, *(pair or ()), layer_col)}
        props = {k: _number(v) for k, v in props.items()}
        try:
            if shape_col and (row.get(shape_col) or "").strip():
                g = wkt.loads(row[shape_col])
            elif pair:
                g = Point(float(row[pair[0]]), float(row[pair[1]]))
            else:
                b.skip("row without a shape")
                continue
        except Exception:  # noqa: BLE001 -- a row we cannot read: counted
            b.skip("row with an unreadable shape")
            continue
        b.add(g, (row.get(layer_col) or stem) if layer_col else stem, props, entity=g.geom_type)
    return b.drawing(crs=None)


def _number(v: Any) -> Any:
    if not isinstance(v, str):
        return v
    s = v.strip()
    if re.fullmatch(r"-?\d+", s) and len(s) < 16:
        return int(s)
    if re.fullmatch(r"-?\d+\.\d*(e-?\d+)?", s, re.I):
        return float(s)
    return s or None


# -- any ---------------------------------------------------------------------------------------

def read_any(data: bytes, filename: str) -> CadDrawing:
    """A file's features by its ending: a DXF drawing or one of the formats above."""
    from app.gis import cad

    suffix = Path(filename or "").suffix.lower()
    stem = Path(filename or "features").stem.replace("_", " ") or "features"
    if suffix in ("", ".dxf"):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "drawing.dxf"
            path.write_bytes(data)
            return cad.read(path)
    fmt = SUFFIXES.get(suffix)
    if fmt == "GeoJSON":
        return read_geojson(data)
    if fmt == "KML":
        return read_kml(data)
    if fmt == "KMZ":
        return read_kmz(data)
    if fmt == "GPX":
        return read_gpx(data)
    if fmt == "Shapefile":
        return read_shapefile(data, filename)
    if fmt == "GeoPackage":
        return read_geopackage(data)
    if fmt == "CSV":
        return read_csv(data, stem)
    raise CadError(f"{suffix} files are not read here; send one of {', '.join(ACCEPTED)}")
