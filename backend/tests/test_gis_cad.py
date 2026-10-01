"""DXF -> GIS: any drawing read by layer, placed with a chosen CRS, as WGS 84 GeoJSON."""
from __future__ import annotations

import math

import pytest

from app.gis import cad, crs
from app.gis.convert import bounds, to_geojson
from tests.cad_fixtures import E0, N0, site_drawing


@pytest.fixture(scope="module")
def drawing(tmp_path_factory):
    path = tmp_path_factory.mktemp("cad") / "site.dxf"
    site_drawing(path)
    return cad.read(path)


def _by(drawing, layer, kind=None, entity=None):
    return [f for f in drawing.features if f.layer == layer and (kind is None or f.kind == kind)
            and (entity is None or f.entity == entity)]


def test_every_kind_of_entity_becomes_a_feature_on_its_layer(drawing):
    s = drawing.summary()
    assert drawing.units_name == "metres" and drawing.unit_metres == 1.0
    layers = {l["name"]: l for l in s["layers"]}
    assert {"Buildings", "Roads", "Trees", "Labels", "Hatch", "Dims"} <= set(layers)
    assert layers["Buildings"]["color"] == "#ff0000"
    # Closed polylines and solids are polygons; the bulge makes the second one round at one end.
    polys = _by(drawing, "Buildings", "polygon")
    assert len(polys) == 3
    rounded = max(polys, key=lambda f: len(f.coords[0]))
    assert len(rounded.coords[0]) > 10
    # Lines: a line, an open polyline, an arc, a spline.
    entities = {f.entity for f in _by(drawing, "Roads", "line")}
    assert {"LINE", "LWPOLYLINE", "ARC", "SPLINE"} <= entities
    assert [f.props["color"] for f in _by(drawing, "Roads", entity="LWPOLYLINE")] == ["#ff0000"]
    # A circle and an ellipse are polygons, close to their true areas.
    from shapely.geometry import Polygon
    circle = next(f for f in _by(drawing, "Trees", "polygon") if f.entity == "CIRCLE" and "block" not in f.props)
    assert Polygon(circle.coords[0]).area == pytest.approx(math.pi * 4, rel=0.01)
    # The hatch keeps its hole.
    (hatch,) = _by(drawing, "Hatch", "polygon")
    assert len(hatch.coords) == 2 and Polygon(hatch.coords[0], [hatch.coords[1]]).area == pytest.approx(100 - 16)
    # Text keeps its words.
    texts = {f.props["text"] for f in _by(drawing, "Labels", "text")}
    assert "Main gate" in texts and any("Store" in t and "block A" in t for t in texts)
    assert _by(drawing, "Dims", "text") and _by(drawing, "Dims", "line")


def test_blocks_are_exploded_with_their_attributes_on_the_inserts_layer(drawing):
    refs = [f for f in drawing.features if f.props.get("block_reference") and f.props["block"] == "TREE"]
    assert sorted(r.props["attributes"]["SPECIES"] for r in refs) == ["olive", "palm"]
    pieces = [f for f in drawing.features if f.props.get("block") == "TREE" and not f.props.get("block_reference")]
    # The tree circle was drawn on layer 0 in the block: it is on Trees where inserted, in the insert's colour.
    rings = [f for f in pieces if f.entity == "CIRCLE"]
    assert len(rings) == 2 and all(f.layer == "Trees" and f.props["color"] == "#00ff00" for f in rings)
    nested = [f for f in drawing.features if f.props.get("block_path") == "TREE/MARK"]
    assert len(nested) == 2
    assert {f.props["text"] for f in drawing.features if f.entity == "ATTRIB"} == {"palm", "olive"}


def test_the_crs_is_offered_by_where_the_drawing_would_land(drawing):
    offered = crs.candidates(drawing.extent, drawing.unit_metres, near=(31.2, 30.0))
    codes = [c["placement"]["code"] for c in offered]
    assert 32636 in codes
    utm = next(c for c in offered if c["placement"]["code"] == 32636)
    lon, lat = utm["centre"]
    assert 31 < lon < 32.5 and 29.5 < lat < 31 and utm["fits"]
    # The numbers alone cannot tell the zone: every zone is listed with its place.
    zones = {z["zone"]: z for z in crs.utm_zones(drawing.extent, drawing.unit_metres)}
    assert len(zones) == 120 and zones["36N"]["centre"][0] == pytest.approx(lon, abs=0.01)
    assert 22992 in [c["code"] for c in crs.search("Red Belt")]
    assert crs.search("32636")[0]["name"] == "WGS 84 / UTM zone 36N"


def test_placed_features_are_geojson_in_wgs84(drawing):
    placement = crs.Placement.parse({"kind": "epsg", "code": 32636}, 1.0)
    feats, stats = to_geojson(drawing.features, placement)
    assert stats["dropped"] == 0 and len(feats) == len(drawing.features)
    w, s, e, n = bounds(feats)
    assert 31 < w < e < 32.5 and 29.5 < s < n < 31 and (e - w) < 0.002
    gate = next(f for f in feats if f["properties"].get("text") == "Main gate")
    assert gate["geometry"]["type"] == "Point" and gate["properties"]["layer"] == "Labels"


def test_a_millimetre_drawing_and_local_coordinates_land_in_the_same_place(tmp_path, drawing):
    site_drawing(tmp_path / "mm.dxf", units=4, scale=1000.0)
    mm = cad.read(tmp_path / "mm.dxf")
    assert mm.unit_metres == 0.001
    a, _ = to_geojson(mm.features[:5], crs.Placement.parse({"kind": "epsg", "code": 32636}, mm.unit_metres))
    b, _ = to_geojson(drawing.features[:5], crs.Placement.parse({"kind": "epsg", "code": 32636}, 1.0))
    assert a[0]["geometry"]["coordinates"][0][0] == pytest.approx(b[0]["geometry"]["coordinates"][0][0], abs=1e-6)
    # Local engineering coordinates: the drawing's (E0, N0) is put at a chosen place, turned 90° clockwise.
    local = crs.Placement.parse({"kind": "local", "anchor": [E0, N0], "lonlat": [31.6, 30.1], "rotation": 90}, 1.0)
    feats, _ = to_geojson(drawing.features, local)
    first = next(f for f in feats if f["properties"]["entity"] == "LWPOLYLINE")
    (x0, y0), (x1, y1) = first["geometry"]["coordinates"][0][:2]
    assert (x0, y0) == pytest.approx((31.6, 30.1), abs=1e-7)
    # The drawing's +x (east, 20 m) now points south.
    assert y1 < y0 and abs(x1 - x0) < 1e-6 and (y0 - y1) * 110_860 == pytest.approx(20, abs=0.05)
    with pytest.raises(crs.PlacementError):
        crs.Placement.parse({"kind": "epsg", "code": 999999}, 1.0)


def test_a_file_that_is_not_a_drawing_is_refused(tmp_path):
    bad = tmp_path / "x.dxf"
    bad.write_bytes(b"%PDF-1.4 not a drawing")
    with pytest.raises(cad.CadError):
        cad.read(bad)
