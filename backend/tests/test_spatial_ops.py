"""Spatial measures as data (improvement plan, phase 2): the pure operations, no database."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from app.spatial import layer_network, ops


def _s(i, key, geom):
    return ops.Shape(i, key, geom)


# Two districts side by side along longitude 30.0 at latitude 31.2, 0.05 degrees each.
WEST = Polygon([(29.95, 31.15), (30.0, 31.15), (30.0, 31.25), (29.95, 31.25)])
EAST = Polygon([(30.0, 31.15), (30.05, 31.15), (30.05, 31.25), (30.0, 31.25)])
FAR = Polygon([(31.0, 31.15), (31.05, 31.15), (31.05, 31.25), (31.0, 31.25)])
DISTRICTS = [_s(10, "west", WEST), _s(11, "east", EAST), _s(12, "far", FAR)]


def test_each_place_falls_in_the_area_containing_it_and_outsiders_are_listed():
    places = [_s(1, "a", Point(29.97, 31.2)), _s(2, "b", Point(30.02, 31.2)), _s(3, "c", Point(40, 10))]
    pairs, outside = ops.inside(places, DISTRICTS)
    assert sorted(pairs) == [(1, 10), (2, 11)] and outside == ["c"]


def test_counting_within_a_radius_does_not_count_itself():
    here = _s(1, "h", Point(30.0, 31.2))
    others = [here, _s(2, "near", Point(30.002, 31.2)), _s(3, "far", Point(30.02, 31.2))]  # ~190 m and ~1.9 km
    assert ops.count_within([here], others, 300) == [1]
    assert ops.count_within([here], others, 2500) == [2]


def test_nearest_is_ranked_with_metres():
    here = _s(1, "h", Point(30.0, 31.2))
    others = [_s(2, "b", Point(30.02, 31.2)), _s(3, "a", Point(30.002, 31.2)), _s(4, "c", Point(30.2, 31.2))]
    rows = ops.nearest([here], others, 2)
    assert [(b, rank) for _, b, rank, _ in rows] == [(3, 1), (2, 2)]
    assert 150 < rows[0][3] < 250


def test_areas_sharing_a_border_touch_both_ways_and_a_far_one_does_not():
    pairs = ops.touching(DISTRICTS)
    assert {(a, b) for a, b, _ in pairs} == {(10, 11), (11, 10)}
    assert all(m > 10_000 for _, _, m in pairs)  # the shared side is about 11 km


def test_overlap_is_in_square_metres():
    half = Polygon([(29.975, 31.15), (30.025, 31.15), (30.025, 31.25), (29.975, 31.25)])
    rows = {(a, b): m2 for a, b, m2 in ops.overlap_m2([_s(1, "x", half)], DISTRICTS)}
    assert set(rows) == {(1, 10), (1, 11)}
    assert math.isclose(rows[(1, 10)], rows[(1, 11)], rel_tol=0.01) and rows[(1, 10)] > 20_000_000


def test_a_road_overlaps_a_zone_by_the_metres_it_runs_inside_it_and_is_placed_halfway_along():
    """Benchmark, October 2026: roads kept as lines can be checked against construction zones."""
    road = LineString([(29.96, 31.2), (30.04, 31.2)])  # crosses both districts, ~3.8 km in each
    rows = {(a, b): m for a, b, m in ops.overlap_m2([_s(1, "r", road)], DISTRICTS)}
    assert set(rows) == {(1, 10), (1, 11)} and all(3_500 < m < 4_200 for m in rows.values())
    pairs, _ = ops.inside([_s(1, "r", road)], DISTRICTS)
    assert pairs == [(1, 11)] or pairs == [(1, 10)]  # its middle is on the shared border at 30.0


def test_travel_along_my_own_lines_follows_the_network_and_its_speeds():
    # An L-shaped road: east along 31.2 (fast), then north along 30.02 (slow); a far stub nobody reaches.
    lines = [([[30.0, 31.2], [30.01, 31.2], [30.02, 31.2]], {"speed": 60}),
             ([[30.02, 31.2], [30.02, 31.21]], {"speed": 20}),
             ([[35.0, 31.2], [35.01, 31.2]], {"speed": 60})]
    net = layer_network.build(lines, "speed", 30)
    metres, _ = layer_network.matrix(net, [(30.0, 31.2)], [(30.02, 31.21), (35.005, 31.2), (45.0, 10.0)], minutes=False)
    assert 3000 < metres[0][0] < 3300          # ~1.9 km east + ~1.1 km north, not the 2.2 km straight line
    assert np.isnan(metres[0][1]) and np.isnan(metres[0][2])  # another piece of network; too far to snap
    minutes, info = layer_network.matrix(net, [(30.0, 31.2)], [(30.02, 31.21)], minutes=True)
    assert 4.5 < minutes[0][0] < 6.0           # 1.9 km at 60 km/h (1.9 min) + 1.1 km at 20 km/h (3.3 min)
    assert info["speed_field"] == "speed"


class _Slope:
    """A fake terrain: ground rises 10 m for each 0.001 degree east of longitude 30.0."""

    def height(self, lon, lat):
        if lon > 31:
            return None  # off the tileset
        return (lon - 30.0) * 10_000


def test_heights_of_points_and_areas_with_uncovered_ones_left_out():
    low, high = _s(1, "low", Point(30.0, 31.2)), _s(2, "high", Point(30.01, 31.2))
    area = _s(3, "area", Polygon([(30.0, 31.2), (30.002, 31.2), (30.002, 31.202), (30.0, 31.202)]))
    off = _s(4, "off", Point(32.0, 31.2))
    got = ops.heights([low, high, area, off], _Slope())
    assert got[0] == (0.0, 0.0)
    assert math.isclose(got[1][0], 100.0, abs_tol=1e-6)
    elevation, slope = got[2]
    assert 0 < elevation < 20 and slope > 0  # the area's mean height, and it rises eastwards
    assert got[3] is None


def test_crossing_lines_without_a_shared_vertex_still_join():
    """User retest: roads drawn as long straight lines that cross mid-way, with no vertex at the
    crossing, must still form a junction -- otherwise every road is an island."""
    east_west = ([[30.00, 31.20], [30.02, 31.20]], {"speed_kmh": 60})
    north_south = ([[30.01, 31.19], [30.01, 31.21]], {"speed_kmh": 30})
    net = layer_network.build([east_west, north_south], "speed_kmh", 30)
    west_end, north_end = (30.0, 31.2001), (30.0101, 31.21)
    out, info = layer_network.matrix(net, [west_end], [north_end], minutes=True)
    assert "unreachable_pairs" not in info
    # ~0.95 km east at 60 km/h then ~1.1 km north at 30 km/h: about 3.2 minutes.
    assert 2.5 < out[0, 0] < 4.5


def test_a_place_too_far_from_the_lines_is_named_and_the_limit_can_widen():
    """User test (Alexandria): hotspots 600 m off the road layer were dropped without a word."""
    from app.spatial import layer_network as ln

    net = ln.build([([[0.0, 0.0], [0.02, 0.0]], {})], None, 30)
    far = (0.01, 0.0063)  # about 700 m north of the road
    values, info = ln.matrix(net, [(0.0, 0.0)], [far], minutes=True)
    assert np.isnan(values[0, 0]) and info["off_targets"][0][0] == 0 and info["off_targets"][0][1] > 500
    values, info = ln.matrix(net, [(0.0, 0.0)], [far], minutes=True, snap_m=1000)
    assert np.isfinite(values[0, 0]) and "off_targets" not in info


def test_a_road_is_in_the_area_holding_most_of_it_and_crosses_each_area_it_passes():
    """Benchmark, October 2026: a road was placed by its middle point and its crossings were unknown."""
    # From 29.99 to 30.04 at latitude 31.2: 0.01 in the west, 0.04 in the east.
    road = _s(1, "r1", LineString([(29.99, 31.2), (30.04, 31.2)]))
    pairs, outside = ops.inside([road], DISTRICTS)
    assert pairs == [(1, 11)] and outside == []
    crossed = {area: m for _, area, m in ops.crossing([road], DISTRICTS)}
    assert set(crossed) == {10, 11}
    assert math.isclose(crossed[11] / crossed[10], 4, rel_tol=0.01)
    assert math.isclose(crossed[10], 952, rel_tol=0.02)  # 0.01 degree of longitude at 31.2 N
