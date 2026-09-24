"""The grid, worked by hand on boundaries whose answers are known (GIS 2).

Boundaries are drawn in metres in the UTM zone around (3.0 E, 0.0 N) and
handed to the grid in lon/lat, so the grid's own projection must bring them
back to the metres they were drawn in.
"""

from __future__ import annotations

import math

import pytest
from shapely.geometry import box, mapping

from app.spatial.grid import TooManyCells, make_grid, sum_points
from app.spatial.project import OutOfRange, Projection, utm_epsg

AT = (3.0, 0.0)


def _drawn(geom_in_metres) -> dict:
    """A shape drawn in metres from the origin at AT, as lon/lat GeoJSON."""
    from shapely.affinity import translate

    p = Projection(4326, around=AT)
    x0, y0 = p.forward_point(AT)
    return mapping(p.back(translate(geom_in_metres, x0, y0)))


def test_the_utm_zone_is_the_one_around_the_centroid():
    assert (utm_epsg(3.0, 0.1), utm_epsg(31.2, 30.0), utm_epsg(-70.6, -33.4)) == (32631, 32636, 32719)


def test_a_square_boundary_holds_exactly_the_cells_that_fit():
    cells, edges, dropped = make_grid(_drawn(box(0, 0, 1000, 1000)), crs=4326, shape="square", size_m=500, keep="centre")
    assert sorted(c.key for c in cells) == ["c_r0_c0", "c_r0_c1", "c_r1_c0", "c_r1_c1"]
    assert all(c.area_m2 == pytest.approx(250_000, rel=1e-6) for c in cells)
    assert sorted((e.a, e.b) for e in edges) == [
        ("c_r0_c0", "c_r0_c1"), ("c_r0_c0", "c_r1_c0"), ("c_r0_c1", "c_r1_c1"), ("c_r1_c0", "c_r1_c1")]
    assert all(e.shared_m == pytest.approx(500, rel=1e-6) for e in edges)
    assert dropped == 0
    assert all(c.geometry["type"] == "Polygon" and c.centroid["type"] == "Point" for c in cells)


def test_hex_cells_have_six_neighbours_in_the_middle():
    cells, edges, _ = make_grid(_drawn(box(0, 0, 5000, 5000)), crs=4326, shape="hex", size_m=500, keep="centre")
    degree: dict[str, int] = {}
    for e in edges:
        degree[e.a] = degree.get(e.a, 0) + 1
        degree[e.b] = degree.get(e.b, 0) + 1
    assert max(degree.values()) == 6 and min(degree.values()) >= 1
    # A hex of flat-to-flat width w has area (sqrt(3)/2) w^2, and sides of w / sqrt(3).
    assert all(c.area_m2 == pytest.approx(math.sqrt(3) / 2 * 500**2, rel=1e-6) for c in cells)
    assert all(e.shared_m == pytest.approx(500 / math.sqrt(3), rel=1e-6) for e in edges)
    assert all(c.key.startswith("h_q") and "-" not in c.key for c in cells)


def test_a_lake_keeps_its_cells_out():
    """Review Focus 2: a cell whose centre is in the water is not land."""
    land = box(0, 0, 1500, 500).difference(box(500, 0, 1000, 500))
    cells, edges, dropped = make_grid(_drawn(land), crs=4326, shape="square", size_m=500, keep="centre")
    assert sorted(c.key for c in cells) == ["c_r0_c0", "c_r0_c2"] and edges == [] and dropped == 1


def test_two_shores_of_a_channel_are_not_neighbours():
    """Review Focus 2: a 10 m channel runs exactly along the side two cells share."""
    land = box(0, 0, 1000, 500).difference(box(495, 0, 505, 500))
    cells, edges, _ = make_grid(_drawn(land), crs=4326, shape="square", size_m=500, keep="centre")
    assert sorted(c.key for c in cells) == ["c_r0_c0", "c_r0_c1"]
    assert edges == []
    # Without the channel they are.
    _, joined, _ = make_grid(_drawn(box(0, 0, 1000, 500)), crs=4326, shape="square", size_m=500, keep="centre")
    assert [(e.a, e.b) for e in joined] == [("c_r0_c0", "c_r0_c1")]


def test_overlap_keeps_edge_cells_with_their_share():
    cells, _, _ = make_grid(_drawn(box(0, 0, 750, 750)), crs=4326, shape="square", size_m=500, keep="overlap")
    assert sorted(round(c.coverage, 3) for c in cells) == [0.25, 0.5, 0.5, 1.0]


def test_too_many_cells_is_refused_with_the_count():
    with pytest.raises(TooManyCells) as caught:
        make_grid(_drawn(box(0, 0, 10_000, 10_000)), crs=4326, shape="square", size_m=50, keep="centre")
    assert caught.value.count == 40_000 and "40000 cells" in str(caught.value)


@pytest.mark.parametrize("boundary, fault", [
    ({"type": "Polygon", "coordinates": [[[179, 0], [-179, 0], [-179, 1], [179, 1], [179, 0]]]}, "crosses longitude 180"),
    ({"type": "Polygon", "coordinates": [[[0, 0], [8, 0], [8, 1], [0, 1], [0, 0]]]}, "8.0 degrees of longitude wide"),
])
def test_a_boundary_one_projection_cannot_hold_is_refused(boundary, fault):
    """Review Focus 1."""
    with pytest.raises(OutOfRange, match=fault):
        make_grid(boundary, crs=4326, shape="square", size_m=500, keep="centre")


def test_points_are_summed_into_their_cells_and_the_rest_reported():
    cells, _, _ = make_grid(_drawn(box(0, 0, 1000, 1000)), crs=4326, shape="square", size_m=500, keep="centre")
    inside = {c.key: c for c in cells}["c_r0_c0"].centroid["coordinates"]
    sums, lost = sum_points(cells, [(inside[0], inside[1], {"population": 120}),
                                    (inside[0], inside[1], {"population": 30}),
                                    (inside[0] + 1.0, inside[1], {"population": 7})], crs=4326)
    assert sums == {"c_r0_c0": {"population": 150}}
    assert lost == {"population": 7}


def test_a_projected_crs_is_read_in_its_own_metres():
    """A domain written in UTM 31N already: the grid's cells are its metres."""
    p = Projection(4326, around=AT)
    x0, y0 = p.forward_point(AT)
    boundary = mapping(box(x0, y0, x0 + 1000, y0 + 500))
    cells, edges, _ = make_grid(boundary, crs=32631, shape="square", size_m=500, keep="centre")
    assert len(cells) == 2 and len(edges) == 1
    assert cells[0].geometry["coordinates"][0][0] == pytest.approx((x0, y0))
