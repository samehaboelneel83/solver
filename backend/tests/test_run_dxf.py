"""A run's answer as DXF (app.api.run_dxf): on the drawing's own coordinates, chosen apart from not."""

from __future__ import annotations

import io

import ezdxf
import numpy as np
import pytest
from fastapi import HTTPException

from app.api.run_dxf import _local, metre_shape, to_dxf
from app.gis.crs import Placement


def _read(raw: bytes):
    return ezdxf.read(io.StringIO(raw.decode("utf-8")))


def _square(lon, lat, d=0.0001):
    return {"type": "Polygon", "coordinates": [[[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]]}


def test_a_local_placement_is_written_back_exactly_where_the_drawing_was():
    p = {"kind": "local", "anchor": [1000.0, 2000.0], "lonlat": [31.2357, 30.0444], "rotation": 17.0, "scale": 1, "units": 1}
    forward = Placement.parse(p, 1.0).transformer()
    xs, ys = np.array([1000.0, 1088.5, 1012.25]), np.array([2000.0, 2064.0, 2033.75])
    lons, lats = forward(xs, ys)
    to_xy, metres, units = _local(p)
    bx, by = to_xy(list(lons), list(lats))
    assert np.allclose(bx, xs, atol=1e-6) and np.allclose(by, ys, atol=1e-6)
    assert metres([0.0, 88.5], [0.0, 64.0]) == ([1000.0, 1088.5], [2000.0, 2064.0])


def test_metre_fields_make_a_shape():
    assert metre_shape({"shape_m": "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"}).area == pytest.approx(1)
    assert metre_shape({"min_x_m": 2, "min_y_m": 3, "width_m": 1.5, "height_m": 0.5}).bounds == (2, 3, 3.5, 3.5)
    assert metre_shape({"x_m": 10, "y_m": 10, "w": 1.5, "h": 0.5}).bounds == (9.25, 9.75, 10.75, 10.25)
    assert metre_shape({"x_m": 1, "y_m": 2}).geom_type == "Point"
    assert metre_shape({"name": "no place"}) is None


def _rec():
    ir = {"variables": {"open": {"index": ["site"], "domain": "binary"},
                        "pick": {"index": ["cand"], "domain": "binary"}},
          "constraints": [], "objective": {}}
    data = {"sets": {
        "site": [{"id": "A", "label": "Site A", "loc": _square(31.0, 30.0)},
                 {"id": "B", "label": "Site B", "loc": _square(31.001, 30.0)}],
        "cand": [{"id": f"c{i}", "x_m": 1.0 + 2 * i, "y_m": 1.0, "w_m": 1.5, "h_m": 0.5} for i in range(4)]}}
    return {"id": 7, "problem": "Beds", "scenario": "base", "status": "optimal", "objective": 2, "domain_id": None,
            "ir": ir, "data": data, "assignments": {"open": [["A"]], "pick": [["c0"], ["c2"]]}, "amounts": {},
            "results": []}


def test_the_answer_is_drawn_on_layers_by_what_happened():
    doc = _read(to_dxf(_rec()))
    msp = doc.modelspace()
    by_layer = {}
    for e in msp:
        by_layer.setdefault(e.dxf.layer, []).append(e.dxftype())
    assert by_layer["OPEN-CHOSEN"] == ["LWPOLYLINE"] and by_layer["OPEN-NOT-CHOSEN"] == ["LWPOLYLINE"]
    assert by_layer["PICK-CHOSEN"].count("LWPOLYLINE") == 2 and by_layer["PICK-NOT-CHOSEN"].count("LWPOLYLINE") == 2
    assert "HATCH" in by_layer["PICK-CHOSEN-FILL"]
    assert doc.layers.get("PICK-NOT-CHOSEN").is_off() and doc.layers.get("PICK-CHOSEN").is_on()
    texts = sorted(e.dxf.text for e in msp if e.dxftype() == "TEXT")
    assert texts == ["Site A", "c0", "c2"]
    # A chosen bed is 1.5 x 0.5 in metres: drawn at its size (no drawing in the domain: local metres as given).
    beds = [e for e in msp if e.dxf.layer == "PICK-CHOSEN"]
    xs = sorted(round(p[0], 6) for p in beds[0].get_points("xy"))
    assert xs[-1] - xs[0] == pytest.approx(1.5)
    note = next(e for e in msp if e.dxftype() == "MTEXT")
    assert "run 7" in note.text and "PICK-CHOSEN: 2" in note.text


def test_an_answer_with_nothing_placed_is_refused_with_the_reason():
    rec = _rec()
    rec["data"] = {"sets": {"site": [{"id": "A"}], "cand": [{"id": "c0"}]}}
    with pytest.raises(HTTPException, match="nothing in this answer has a place to draw"):
        to_dxf(rec)


class _OneMap:
    """A database that holds one local drawing placement for the domain."""

    def __init__(self, placement):
        self.placement = placement

    def execute(self, *a, **k):
        return [(self.placement,)]


def test_records_placed_by_metres_are_drawn_on_the_map_through_the_drawing():
    from app.api.answer_map import answer_map, with_metre_shapes

    placement = {"kind": "local", "anchor": [7.2, -65.0], "lonlat": [31.2357, 30.0444], "rotation": 0, "scale": 1, "units": 1}
    rec = _rec()
    data = with_metre_shapes(_OneMap(placement), 5, rec["data"])
    bed = next(r for r in data["sets"]["cand"] if r["id"] == "c0")
    assert bed["_shape"]["type"] == "Polygon"
    lon, lat = bed["_shape"]["coordinates"][0][0]
    assert abs(lon - 31.2357) < 0.001 and abs(lat - 30.0444) < 0.001  # metres from the drawing's corner, near its anchor
    mapped = answer_map(rec["ir"], data, rec["assignments"], {}, [])
    assert {f["properties"]["layer"] for f in mapped["features"]} >= {"pick"}


def test_a_huge_placed_set_draws_only_what_was_chosen():
    from app.api.answer_map import CHOSEN_ONLY_ABOVE, answer_map

    n = CHOSEN_ONLY_ABOVE + 10
    rows = [{"id": f"b{i}", "loc": _square(31.0 + i * 1e-5, 30.0)} for i in range(n)]
    ir = {"variables": {"pick": {"index": ["bed"], "domain": "binary"}}, "constraints": []}
    mapped = answer_map(ir, {"sets": {"bed": rows}}, {"pick": [["b1"], ["b7"]]}, {}, [])
    assert len(mapped["features"]) == 2 and "only the chosen drawn" in mapped["layers"][0]["title"]


def test_the_report_draws_records_placed_by_metres_on_its_map():
    """A placement run's report has a map: its chosen slots carry only metres, so the report gives them their
    shape through the domain's drawing, as the GeoJSON export does (live camp test, October 2026)."""
    from app.api.run_export import to_html, with_map_shapes

    placement = {"kind": "local", "anchor": [7.2, -65.0], "lonlat": [31.2357, 30.0444], "rotation": 0, "scale": 1, "units": 1}
    rec = _rec()
    rec = {**rec, "domain_id": 5, "solver": "layout", "params": {}, "error": None, "finished_at": None,
           "ir": {**rec["ir"], "variables": {"pick": rec["ir"]["variables"]["pick"]}},
           "data": {"sets": {"cand": rec["data"]["sets"]["cand"]}}, "assignments": {"pick": [["c0"], ["c2"]]}}
    assert "On the map" not in to_html(rec)  # metres alone: nothing to draw
    assert "On the map" in to_html(with_map_shapes(_OneMap(placement), rec))
    assert with_map_shapes(None, rec)["data"] == rec["data"]  # no drawing in the domain: left as it is
