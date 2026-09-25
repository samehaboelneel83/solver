"""Road distances from vector tiles (queue R16b): decoded, stitched, noded and measured -- on tiles built here."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.spatial import mvt, roads
from app.spatial.distance import Place

EXTENT = 4096
#: The zoom-12 tile holding central Cairo; every test tile is placed there.
TX, TY = 2403, 1689


# -- a small encoder, the decoder's mirror, so a tile can be written by hand -----------------------------

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(number: int, wire: int, payload) -> bytes:
    key = _varint((number << 3) | wire)
    if wire == 0:
        return key + _varint(payload)
    return key + _varint(len(payload)) + payload


def _zig(n: int) -> int:
    return (n << 1) ^ (n >> 31)


def _geometry(line: list[tuple[int, int]]) -> bytes:
    commands, x, y = [], 0, 0
    commands += [(1 << 3) | 1, _zig(line[0][0] - x), _zig(line[0][1] - y)]
    x, y = line[0]
    commands.append((len(line) - 1) << 3 | 2)
    for px, py in line[1:]:
        commands += [_zig(px - x), _zig(py - y)]
        x, y = px, py
    return b"".join(_varint(c) for c in commands)


def tile(features: list[tuple[dict[str, str], list[tuple[int, int]]]]) -> bytes:
    """A vector tile with one `transportation` layer of string-tagged lines."""
    keys, values, body = [], [], b""
    for props, line in features:
        tags = []
        for k, v in props.items():
            if k not in keys:
                keys.append(k)
            if v not in values:
                values.append(v)
            tags += [keys.index(k), values.index(v)]
        feature = _field(2, 2, b"".join(_varint(t) for t in tags)) + _field(3, 0, mvt.LINESTRING) + _field(4, 2, _geometry(line))
        body += _field(2, 2, feature)
    layer = _field(15, 0, 2) + _field(1, 2, b"transportation") + body
    layer += b"".join(_field(3, 2, k.encode()) for k in keys)
    layer += b"".join(_field(4, 2, _field(1, 2, v.encode())) for v in values)
    layer += _field(5, 0, EXTENT)
    return _field(3, 2, layer)


def lonlat(px: float, py: float) -> tuple[float, float]:
    world = 2 ** roads.ZOOM * EXTENT
    gx, gy = TX * EXTENT + px, TY * EXTENT + py
    return gx / world * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * gy / world))))


def place(i: int, px: float, py: float) -> Place:
    lon, lat = lonlat(px, py)
    return Place(i, f"p{i}", lon, lat)


def fetch_for(features):
    body = tile(features)
    return lambda url: body if url.endswith(f"/{roads.ZOOM}/{TX}/{TY}.pbf") else None


TEMPLATE = "http://tiles/data/osm/{z}/{x}/{y}.pbf"


def test_the_decoder_reads_back_what_was_written():
    line = [(100, 100), (900, 120), (900, 800)]
    [(props, lines, extent)] = list(mvt.lines(tile([({"class": "primary"}, line)]), "transportation"))
    assert props == {"class": "primary"} and lines == [line] and extent == EXTENT


def test_a_crossing_with_no_shared_point_is_a_junction():
    """Two straight roads crossing mid-segment (the tiles drop the shared vertex): one can be driven onto the other."""
    fetch = fetch_for([({"class": "primary"}, [(1000, 2000), (3000, 2000)]),
                       ({"class": "primary"}, [(2000, 1000), (2000, 3000)])])
    west, north = place(0, 1000, 2000), place(1, 2000, 1000)
    net = roads.network([west, north], TEMPLATE, fetch)
    metres, info = roads.matrix(net, [west], [north], minutes=False)
    # West end to the crossing, then north: two arms of 1,000 tile units each.
    arm = _units_to_m(1000)
    assert metres[0, 0] == pytest.approx(2 * arm, rel=0.01)
    assert info["unreachable"] == 0


def test_a_bridge_over_a_road_is_not_a_junction():
    fetch = fetch_for([({"class": "primary"}, [(1000, 2000), (3000, 2000)]),
                       ({"class": "primary", "brunnel": "bridge"}, [(2000, 1000), (2000, 3000)])])
    west, north = place(0, 1000, 2000), place(1, 2000, 1000)
    net = roads.network([west, north], TEMPLATE, fetch)
    metres, info = roads.matrix(net, [west], [north], minutes=False)
    # The bridge is on another piece: north is snapped to the main piece's nearest point, the road below.
    assert np.isnan(metres[0, 0]) or metres[0, 0] > 0.9 * _units_to_m(1000)


def test_a_road_that_stops_just_short_of_another_meets_it():
    """A dead end 5 tile units (about 10 m) short of a road: joined, not left an island."""
    fetch = fetch_for([({"class": "secondary"}, [(1000, 2000), (3000, 2000)]),
                       ({"class": "secondary"}, [(2000, 1000), (2000, 1995)])])
    west, north = place(0, 1000, 2000), place(1, 2000, 1000)
    net = roads.network([west, north], TEMPLATE, fetch)
    metres, _ = roads.matrix(net, [west], [north], minutes=False)
    assert metres[0, 0] == pytest.approx(2 * _units_to_m(1000), rel=0.02)


def test_time_follows_the_class_speed():
    fetch = fetch_for([({"class": "motorway"}, [(500, 2000), (3500, 2000)])])
    a, b = place(0, 500, 2000), place(1, 3500, 2000)
    net = roads.network([a, b], TEMPLATE, fetch)
    minutes, _ = roads.matrix(net, [a], [b], minutes=True)
    assert minutes[0, 0] == pytest.approx(_units_to_m(3000) / (roads.SPEED_KMH["motorway"] * 1000 / 60), rel=0.01)


def test_a_place_far_from_any_road_is_unreachable_never_guessed():
    fetch = fetch_for([({"class": "minor"}, [(100, 100), (400, 100)])])
    near, far = place(0, 100, 100), place(1, 4000, 4000)  # about 12 km of open ground away
    net = roads.network([near, far], TEMPLATE, fetch)
    metres, info = roads.matrix(net, [near], [far], minutes=False)
    assert np.isnan(metres[0, 0]) and info["off_road"] == ["p1"]


def test_classes_that_carry_no_traffic_are_left_out():
    fetch = fetch_for([({"class": "rail"}, [(100, 100), (4000, 100)])])
    with pytest.raises(roads.RoadsError, match="no roads"):
        roads.network([place(0, 100, 100), place(1, 4000, 100)], TEMPLATE, fetch)


def _units_to_m(units: float) -> float:
    """Tile units at this tile, east-west, in metres."""
    from pyproj import Geod

    a, b = lonlat(1000, 2000), lonlat(1000 + units, 2000)
    return Geod(ellps="WGS84").inv(a[0], a[1], b[0], b[1])[2]
