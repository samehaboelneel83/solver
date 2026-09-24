"""Square and hex grids over a boundary: cells, adjacency and point sums (GIS 2).

Pure: GeoJSON in, cells and edges out; the grid endpoint writes them. Built
in metres (`Projection`, the UTM zone of the boundary's centroid), stored in
the domain's CRS. A cell is kept when its centre is on land (`centre`) or
when any of it is (`overlap`, with the share inside as `coverage`). Two kept
cells are adjacent when they share a side that lies on land -- two shores of
a channel that runs along their common side are not neighbours.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator, Literal

from shapely.geometry import Point, Polygon, mapping
from shapely.geometry import shape as to_shape  # not `shape`: make_grid has a parameter of that name
from shapely.strtree import STRtree

from app.spatial.project import Projection, check_extent, lonlat_bounds

#: Float round-off in a projected boundary must not add a phantom row.
_EPS = 1e-9


class TooManyCells(ValueError):
    def __init__(self, count: int, limit: int):
        super().__init__(f"this grid would have {count} cells; the limit is {limit} -- use a larger cell")
        self.count = count
        self.limit = limit


@dataclass(frozen=True)
class Cell:
    key: str
    row: int
    col: int
    #: GeoJSON, in the domain's CRS.
    geometry: dict
    centroid: dict
    area_m2: float
    #: The share of the cell inside the boundary (1.0 for a whole cell).
    coverage: float


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    shared_m: float


def _axial(n: int) -> str:
    """Keys stay usable in URLs and patches: -3 is written m3."""
    return f"m{-n}" if n < 0 else str(n)


def _count(span: float, step: float) -> int:
    return max(1, math.ceil(span / step - _EPS))


def _square_cells(minx, miny, maxx, maxy, size) -> Iterator[tuple[str, int, int, Polygon]]:
    for r in range(_count(maxy - miny, size)):
        for c in range(_count(maxx - minx, size)):
            x, y = minx + c * size, miny + r * size
            yield f"c_r{r}_c{c}", r, c, Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def _hex_cells(minx, miny, maxx, maxy, size) -> Iterator[tuple[str, int, int, Polygon]]:
    """Pointy-top hexes; `size` is the flat-to-flat width, so the circumradius
    is size / sqrt(3) and rows are 1.5 radii apart."""
    radius = size / math.sqrt(3)
    dy = 1.5 * radius
    for r in range(_count(maxy - miny, dy) + 1):
        for c in range(_count(maxx - minx, size) + 1):
            q = c - (r // 2)  # odd-r offset to axial
            cx, cy = minx + size * (q + r / 2), miny + dy * r
            # Rounded to the micrometre: neighbours compute their shared
            # corners from different centres, and without this the float
            # noise overlaps them in a zero-area sliver whose "length" is
            # its perimeter -- two sides instead of one.
            corners = [
                (round(cx + radius * math.cos(math.radians(60 * k - 30)), 6),
                 round(cy + radius * math.sin(math.radians(60 * k - 30)), 6))
                for k in range(6)
            ]
            yield f"h_q{_axial(q)}_r{_axial(r)}", r, q, Polygon(corners)


def make_grid(
    boundary: dict,
    *,
    crs: int,
    shape: Literal["square", "hex"],
    size_m: float,
    keep: Literal["centre", "overlap"],
    max_cells: int = 20_000,
) -> tuple[list[Cell], list[Edge], int]:
    """The kept cells, their edges, and how many candidates the boundary dropped."""
    area = to_shape(boundary)
    check_extent(lonlat_bounds(area, crs))
    projection = Projection(crs, around=(area.centroid.x, area.centroid.y))
    land = projection.forward(area)
    minx, miny, maxx, maxy = land.bounds
    candidates = list((_square_cells if shape == "square" else _hex_cells)(minx, miny, maxx, maxy, size_m))
    if len(candidates) > max_cells:
        raise TooManyCells(len(candidates), max_cells)
    kept: list[tuple[str, int, int, Polygon, float]] = []
    for key, row, col, poly in candidates:
        inside = poly.intersection(land).area / poly.area
        if (keep == "centre" and land.contains(poly.centroid)) or (keep == "overlap" and inside > _EPS):
            kept.append((key, row, col, poly, min(1.0, inside)))
    cells = [
        Cell(key, row, col, mapping(projection.back(poly)), mapping(projection.back(poly.centroid)),
             round(poly.area, 6), round(inside, 6))
        for key, row, col, poly, inside in kept
    ]
    polys = [poly for _, _, _, poly, _ in kept]
    tree = STRtree(polys)
    edges: list[Edge] = []
    for i, (key, _, _, poly, _) in enumerate(kept):
        for j in tree.query(poly):
            j = int(j)
            if j <= i:
                continue
            # The common boundary, as a line: a shared side, not a touching
            # corner, and on land.
            shared = poly.boundary.intersection(polys[j].boundary)
            if shared.length > 1e-6 and shared.intersection(land).length > 1e-6 * shared.length:
                a, b = sorted((key, kept[j][0]))
                edges.append(Edge(a, b, round(shared.length, 6)))
    return cells, sorted(edges, key=lambda e: (e.a, e.b)), len(candidates) - len(kept)


def sum_points(
    cells: list[Cell], points: list[tuple[float, float, dict[str, float]]], crs: int
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Each point's values added to the cell it falls in (in the domain's
    CRS); and, per column, what fell outside every cell."""
    polys = [to_shape(c.geometry) for c in cells]
    tree = STRtree(polys) if polys else None
    sums: dict[str, dict[str, float]] = {}
    lost: dict[str, float] = {}
    for x, y, values in points:
        point = Point(x, y)
        hit = None
        if tree is not None:
            hit = next((int(i) for i in tree.query(point) if polys[int(i)].covers(point)), None)
        for name, amount in values.items():
            if hit is None:
                lost[name] = lost.get(name, 0) + amount
            else:
                bucket = sums.setdefault(cells[hit].key, {})
                bucket[name] = bucket.get(name, 0) + amount
    return sums, lost
