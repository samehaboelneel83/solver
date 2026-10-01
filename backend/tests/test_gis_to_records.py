"""Map layers as records, and spreadsheet places (improvement plan 1.1-1.3): no database needed."""
from __future__ import annotations

import pytest

from app.api.start import LocationPlan, find_location, location_value
from app.gis import to_records


def _point(name, lon, lat, **props):
    return {"kind": "point", "layer": "YARDS", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"layer": "YARDS", "entity": "Point", "name": name, **props}}


SQUARE = {"type": "Polygon", "coordinates": [[[29.9, 31.2], [29.901, 31.2], [29.901, 31.201], [29.9, 31.201], [29.9, 31.2]]]}
LINE = {"type": "LineString", "coordinates": [[29.9, 31.2], [29.91, 31.2]]}


def test_a_proposal_picks_the_name_as_key_and_types_the_rest():
    feats = [_point("Y1", 29.90, 31.18, max_trucks=6), _point("Y2", 29.94, 31.18, max_trucks=12)]
    plan = to_records.propose(feats, ["YARDS"], set())
    assert plan["name"] == "yard" and plan["key"] == "name"
    assert [(f["name"], f["data_type"]) for f in plan["fields"]] == [("max_trucks", "integer")]
    assert plan["geometry_field"] == "shape" and plan["measures"] == []


def test_records_carry_their_shape_and_fields():
    feats = [_point("Y1", 29.90, 31.18, max_trucks=6), _point("Y2", 29.94, 31.18, max_trucks=12)]
    plan = to_records.propose(feats, ["YARDS"], set())
    seed, faults = to_records.build_seed(feats, plan)
    assert not faults
    attrs = {e["key"]: e["attrs"] for e in seed["entities"]}
    assert attrs["Y2"] == {"max_trucks": 12, "shape": {"type": "Point", "coordinates": [29.94, 31.18]}}
    kinds = {a["name"]: a["data_type"] for a in seed["entity_types"][0]["attributes"]}
    assert kinds == {"max_trucks": "integer", "shape": "geometry"}


def test_an_area_is_measured_and_a_line_keeps_its_length_and_a_point():
    area = {"kind": "polygon", "geometry": SQUARE, "properties": {"name": "A"}}
    road = {"kind": "line", "geometry": LINE, "properties": {"name": "R"}}
    seed, faults = to_records.build_seed([area, road], {"name": "place", "key": "name", "fields": []})
    assert not faults
    a, r = (e["attrs"] for e in seed["entities"])
    assert 10_000 < a["area_m2"] < 13_000  # about 95 m x 111 m at 31 N
    assert a["shape"]["type"] == "Polygon"
    assert 900 < r["length_m"] < 1000 and r["shape"]["type"] == "Point"


def test_text_labels_are_left_out_and_duplicate_keys_refused():
    feats = [_point("Y1", 29.9, 31.18), _point("Y1", 29.91, 31.18),
             {"kind": "text", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {"name": "note"}}]
    plan = {"name": "yard", "key": "name", "fields": []}
    seed, faults = to_records.build_seed(feats, plan)
    assert len(seed["entities"]) == 1 and any("used twice" in f for f in faults)


def test_shapes_attach_by_key_and_misses_are_reported():
    feats = [_point("Y1", 29.9, 31.18), _point("Y9", 29.95, 31.18)]
    shapes, unmatched = to_records.match(feats, "name", {"Y1", "Y2"})
    assert set(shapes) == {"Y1"} and unmatched == ["Y9"]


@pytest.mark.parametrize("header, rows, expected", [
    (["yard_id", "lon", "lat"], [["Y1", 29.9, 31.18]], LocationPlan(lon="lon", lat="lat")),
    (["id", "Longitude", "Latitude"], [["a", "30.1", "31.2"]], LocationPlan(lon="Longitude", lat="Latitude")),
    (["id", "wkt"], [["a", "POINT (30 31)"]], LocationPlan(wkt="wkt")),
    (["id", "lon", "lat"], [["a", 592553, 3368120]], None),  # metres, not degrees: not guessed
    (["id", "x"], [["a", 1]], None),
])
def test_a_spreadsheet_place_is_found_by_name_and_checked_by_value(header, rows, expected):
    assert find_location(header, rows) == expected


def test_a_row_becomes_a_point_and_bad_cells_say_so():
    at = {"lon": 0, "lat": 1}
    assert location_value(LocationPlan(lon="lon", lat="lat"), [29.9, 31.18], at) == {"type": "Point", "coordinates": [29.9, 31.18]}
    assert location_value(LocationPlan(lon="lon", lat="lat"), ["", 31.18], at) is None
    with pytest.raises(ValueError):
        location_value(LocationPlan(lon="lon", lat="lat"), [200, 31.18], at)
