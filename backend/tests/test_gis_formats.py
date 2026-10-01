"""Spatial files other than DXF read as map data: GeoJSON, KML/KMZ, GPX, Shapefile (zip),
GeoPackage and CSV -- layers, kinds, attributes and the coordinate system each names."""

from __future__ import annotations

import io
import json
import sqlite3
import struct
import zipfile

import pytest

from app.gis import crs
from app.gis.cad import CadError
from app.gis.formats import read_any

# A camp-sized square at Mina, Makkah, and the same in UTM 37N metres.
LON, LAT = 39.893, 21.413
E, N = 592_553.5, 2_368_119.9


def _square(x, y, d):
    return [[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]


def _kinds(drawing):
    return {name: dict(layer.kinds) for name, layer in drawing.layers.items()}


def test_geojson_layers_by_property_or_shape_and_wgs84_named():
    doc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": 7, "properties": {"layer": "CAMP_BOUNDARY", "name": "North camp"},
         "geometry": {"type": "Polygon", "coordinates": [_square(LON, LAT, 0.0004)]}},
        {"type": "Feature", "properties": {"name": "gate"},
         "geometry": {"type": "MultiPoint", "coordinates": [[LON, LAT], [LON + 0.0001, LAT]]}},
        {"type": "Feature", "properties": {}, "geometry": None},
    ]}
    d = read_any(json.dumps(doc).encode(), "camp.geojson")
    assert _kinds(d) == {"CAMP_BOUNDARY": {"polygon": 1}, "points": {"point": 2}}
    boundary = next(f for f in d.features if f.layer == "CAMP_BOUNDARY")
    assert boundary.props == {"id": 7, "name": "North camp"}
    assert [f.props["part"] for f in d.features if f.layer == "points"] == [1, 2]
    assert d.skipped == {"feature without geometry": 1}
    assert d.geodata["epsg"] == 4326
    best = crs.candidates(d.extent, d.unit_metres, geodata=d.geodata)[0]
    assert best["placement"]["code"] == 4326 and best["sure"]
    assert best["centre"] == pytest.approx([LON + 0.0002, LAT + 0.0002], abs=1e-6)


def test_geojson_legacy_crs_member_names_a_projected_system():
    doc = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32637"}},
           "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [_square(E, N, 40)]}}]}
    d = read_any(json.dumps(doc).encode(), "utm.json")
    assert d.geodata["epsg"] == 32637
    best = crs.candidates(d.extent, d.unit_metres, geodata=d.geodata)[0]
    assert best["placement"]["code"] == 32637
    assert best["centre"] == pytest.approx([LON, LAT], abs=0.001)


KML = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Site</name>
  <Folder><name>Doors</name>
    <Placemark><name>D1</name><Point><coordinates>{LON},{LAT},0</coordinates></Point></Placemark>
  </Folder>
  <Folder><name>Areas</name>
    <Placemark><name>tank</name>
      <ExtendedData><Data name="kind"><value>water</value></Data></ExtendedData>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>
        {LON},{LAT} {LON + 0.001},{LAT} {LON + 0.001},{LAT + 0.001} {LON},{LAT + 0.001} {LON},{LAT}
      </coordinates></LinearRing></outerBoundaryIs>
      <innerBoundaryIs><LinearRing><coordinates>
        {LON + 0.0004},{LAT + 0.0004} {LON + 0.0006},{LAT + 0.0004} {LON + 0.0006},{LAT + 0.0006} {LON + 0.0004},{LAT + 0.0004}
      </coordinates></LinearRing></innerBoundaryIs></Polygon></Placemark>
    <Placemark><name>road</name><MultiGeometry>
      <LineString><coordinates>{LON},{LAT} {LON + 0.002},{LAT}</coordinates></LineString>
      <LineString><coordinates>{LON},{LAT + 0.002} {LON + 0.002},{LAT + 0.002}</coordinates></LineString>
    </MultiGeometry></Placemark>
  </Folder>
  <GroundOverlay><name>photo</name></GroundOverlay>
</Document></kml>"""


def test_kml_and_kmz_folders_are_layers():
    d = read_any(KML.encode(), "site.kml")
    assert _kinds(d) == {"Doors": {"point": 1}, "Areas": {"polygon": 1, "line": 2}}
    tank = next(f for f in d.features if f.kind == "polygon")
    assert tank.props == {"name": "tank", "kind_": "water"} and len(tank.coords) == 2  # its hole kept
    assert d.skipped == {"GroundOverlay": 1} and d.geodata["epsg"] == 4326
    kmz = io.BytesIO()
    with zipfile.ZipFile(kmz, "w") as z:
        z.writestr("doc.kml", KML)
    assert _kinds(read_any(kmz.getvalue(), "site.kmz")) == _kinds(d)


def test_gpx_waypoints_routes_and_tracks():
    gpx = f"""<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">
      <wpt lat="{LAT}" lon="{LON}"><name>gate</name></wpt>
      <rte><name>supply</name><rtept lat="{LAT}" lon="{LON}"/><rtept lat="{LAT + 0.001}" lon="{LON}"/></rte>
      <trk><name>walk</name><trkseg><trkpt lat="{LAT}" lon="{LON}"/><trkpt lat="{LAT}" lon="{LON + 0.001}"/></trkseg></trk>
    </gpx>"""
    d = read_any(gpx.encode(), "walk.gpx")
    assert _kinds(d) == {"waypoints": {"point": 1}, "routes": {"line": 1}, "tracks": {"line": 1}}
    assert next(f for f in d.features if f.layer == "waypoints").props == {"name": "gate"}


def _shapefile(rings_by_record, names, prj: str | None) -> bytes:
    """A polygon shapefile (type 5) with a NAME column, zipped -- written byte by byte."""
    records = b""
    for i, rings in enumerate(rings_by_record, start=1):
        pts = [p for r in rings for p in r]
        parts, at = [], 0
        for r in rings:
            parts.append(at)
            at += len(r)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        body = struct.pack("<i4d2i", 5, min(xs), min(ys), max(xs), max(ys), len(parts), len(pts))
        body += struct.pack(f"<{len(parts)}i", *parts)
        body += struct.pack(f"<{2 * len(pts)}d", *[c for p in pts for c in p])
        records += struct.pack(">2i", i, len(body) // 2) + body
    shp = struct.pack(">i5i", 9994, 0, 0, 0, 0, 0) + struct.pack(">i", (100 + len(records)) // 2) \
        + struct.pack("<2i4d4d", 1000, 5, 0, 0, 0, 0, 0, 0, 0, 0) + records
    width = 20
    fields = b"NAME".ljust(11, b"\x00") + b"C" + b"\x00" * 4 + bytes([width, 0]) + b"\x00" * 14
    header = struct.pack("<4BIHH", 3, 26, 1, 1, len(names), 32 + len(fields) + 1, 1 + width) + b"\x00" * 20
    dbf = header + fields + b"\x0D" + b"".join(b" " + n.encode().ljust(width) for n in names) + b"\x1A"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("site/areas.shp", shp)
        z.writestr("site/areas.dbf", dbf)
        if prj:
            z.writestr("site/areas.prj", prj)
    return out.getvalue()


def test_shapefile_zip_with_prj_and_holes():
    from pyproj import CRS

    outer = [[E, N], [E, N + 40], [E + 40, N + 40], [E + 40, N], [E, N]]  # clockwise: an outer ring
    hole = [[E + 10, N + 10], [E + 20, N + 10], [E + 20, N + 20], [E + 10, N + 20], [E + 10, N + 10]]  # counter-clockwise
    other = [[E + 50, N], [E + 50, N + 5], [E + 55, N + 5], [E + 55, N], [E + 50, N]]
    data = _shapefile([[outer, hole], [other]], ["camp", "store"], CRS.from_epsg(32637).to_wkt("WKT1_ESRI"))
    d = read_any(data, "site.zip")
    assert _kinds(d) == {"areas": {"polygon": 2}}
    camp = d.features[0]
    assert camp.props == {"NAME": "camp"} and len(camp.coords) == 2
    assert d.features[1].props == {"NAME": "store"}
    assert d.geodata["epsg"] == 32637
    with pytest.raises(CadError, match="zip"):
        read_any(b"x", "areas.shp")


def test_shapefile_without_prj_is_placed_by_hand():
    d = read_any(_shapefile([[_square(E, N, 40)[::-1]]], ["camp"], None), "site.zip")
    assert d.geodata is None and any("no .prj" in n for n in d.notes)


def test_geopackage_tables_are_layers_with_their_srs(tmp_path):
    from shapely import wkb
    from shapely.geometry import LineString, Polygon

    path = tmp_path / "site.gpkg"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT, srs_id INTEGER PRIMARY KEY, organization TEXT,
          organization_coordsys_id INTEGER, definition TEXT, description TEXT);
        CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY, data_type TEXT, identifier TEXT);
        CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, geometry_type_name TEXT,
          srs_id INTEGER, z INTEGER, m INTEGER);
        INSERT INTO gpkg_spatial_ref_sys VALUES ('WGS 84 / UTM zone 37N', 32637, 'EPSG', 32637, '', '');
        INSERT INTO gpkg_contents VALUES ('buildings', 'features', 'buildings'), ('roads', 'features', 'roads');
        INSERT INTO gpkg_geometry_columns VALUES ('buildings', 'geom', 'POLYGON', 32637, 0, 0),
          ('roads', 'geom', 'LINESTRING', 32637, 0, 0);
        CREATE TABLE buildings (fid INTEGER PRIMARY KEY, geom BLOB, name TEXT, floors INTEGER);
        CREATE TABLE roads (fid INTEGER PRIMARY KEY, geom BLOB, name TEXT);
    """)

    def blob(g):  # GeoPackage header: magic, version, flags (little-endian, no envelope), srs id
        return b"GP" + bytes([0, 1]) + struct.pack("<i", 32637) + wkb.dumps(g)

    con.execute("INSERT INTO buildings (geom, name, floors) VALUES (?, 'store', 2)",
                (blob(Polygon(_square(E, N, 10))),))
    con.execute("INSERT INTO roads (geom, name) VALUES (?, 'ring road')", (blob(LineString([(E, N - 5), (E + 50, N - 5)])),))
    con.commit()
    con.close()
    d = read_any(path.read_bytes(), "site.gpkg")
    assert _kinds(d) == {"buildings": {"polygon": 1}, "roads": {"line": 1}}
    assert d.features[0].props == {"fid": 1, "name": "store", "floors": 2}
    assert d.geodata["epsg"] == 32637


def test_csv_with_wkt_or_coordinate_columns():
    wkt = ("layer;name;wkt\n"
           f"DOORS;D1;LINESTRING ({E + 6} {N}, {E + 8} {N})\n"
           f"CAMP_BOUNDARY;camp;POLYGON (({E} {N}, {E + 40} {N}, {E + 40} {N + 26}, {E} {N + 26}, {E} {N}))\n"
           "DOORS;broken;POLYGON ((\n")
    d = read_any(wkt.encode(), "camp.csv")
    assert _kinds(d) == {"DOORS": {"line": 1}, "CAMP_BOUNDARY": {"polygon": 1}}
    assert d.skipped == {"row with an unreadable shape": 1} and d.geodata is None
    # No system named: projected numbers are offered the systems they could be in.
    assert any(c["placement"]["code"] == 32637 for c in crs.candidates(d.extent, d.unit_metres, region="Saudi Arabia"))

    points = f"name,Latitude,Longitude,beds\ntent 1,{LAT},{LON},12\ntent 2,{LAT + 0.0001},{LON},8\n"
    d = read_any(points.encode(), "tents.csv")
    assert _kinds(d) == {"tents": {"point": 2}}
    assert d.features[0].coords == [LON, LAT] and d.features[0].props == {"name": "tent 1", "beds": 12}
    with pytest.raises(CadError, match="WKT column"):
        read_any(b"a,b\n1,2\n", "nothing.csv")


def test_other_endings_are_refused_with_the_list():
    with pytest.raises(CadError, match=r"\.geojson"):
        read_any(b"", "photo.png")
