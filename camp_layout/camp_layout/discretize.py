"""From exact geometry to what a model can choose from.

The camp is covered by square cells of side g (the grid pitch). Three kinds
of candidate come out of it, each checked against the exact geometry:

- bed placements: a bed type, a size variant, an orientation and an anchor
  cell; the placement covers a block of cells (its slot: the bed plus its side
  gap, rounded up to whole cells). Only placements whose slot lies wholly on
  cells where beds are allowed -- and inside the type's zone, if it has one --
  are generated.
- corridor tiles: w x w squares (w the minimum corridor width, a multiple of
  g) anchored on the grid. A corridor is a set of tiles; two tiles are
  neighbours when their anchors are one cell apart. A chain of neighbouring
  tiles sweeps a band at least w wide, so any corridor built from tiles is at
  least w wide everywhere -- the width rule holds by construction.
- zone bands: the cells each door zone takes when it is deepened one step.

This is where continuous geometry becomes finite: the model is exact on the
grid, and the validator re-checks the answer on the exact geometry.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import box
from shapely.prepared import prep

from .geometry import EPS, Geometry
from .problem import CampProblem

Cell = tuple[int, int]


@dataclass(frozen=True)
class Placement:
    index: int
    bed_type: str
    length: float  # the bed itself, before the side gap
    width: float
    rotated: bool  # False: length along x
    anchor: Cell
    span: tuple[int, int]  # cells along x, along y
    deviation: float  # |area - nominal area|, m²

    def cells(self) -> list[Cell]:
        i, j = self.anchor
        return [(i + a, j + b) for a in range(self.span[0]) for b in range(self.span[1])]


@dataclass(frozen=True)
class Tile:
    index: int
    anchor: Cell
    zone: str | None  # the door whose specified zone wholly holds it (a source)


@dataclass
class Grid:
    problem: CampProblem
    geometry: Geometry
    g: float
    x0: float
    y0: float
    nx: int
    ny: int
    s: int  # tile side in cells
    bed_ok: set[Cell] = field(default_factory=set)
    walk_ok: set[Cell] = field(default_factory=set)
    base_zone: dict[Cell, str] = field(default_factory=dict)  # cell -> door, specified depth
    band: dict[Cell, tuple[str, int]] = field(default_factory=dict)  # cell -> (door, level >= 1)
    levels: dict[str, list[float]] = field(default_factory=dict)
    level_area: dict[str, list[float]] = field(default_factory=dict)
    placements: list[Placement] = field(default_factory=list)
    tiles: list[Tile] = field(default_factory=list)
    tile_at: dict[Cell, int] = field(default_factory=dict)
    neighbours: list[tuple[int, int]] = field(default_factory=list)  # directed tile arcs
    access: dict[int, list[int]] = field(default_factory=dict)  # placement -> tiles that serve it

    def cell_box(self, cell: Cell):
        i, j = cell
        return box(self.x0 + i * self.g, self.y0 + j * self.g, self.x0 + (i + 1) * self.g, self.y0 + (j + 1) * self.g)

    def block_box(self, anchor: Cell, span: tuple[int, int]):
        i, j = anchor
        return box(self.x0 + i * self.g, self.y0 + j * self.g,
                   self.x0 + (i + span[0]) * self.g, self.y0 + (j + span[1]) * self.g)

    def tile_cells(self, tile: Tile) -> list[Cell]:
        i, j = tile.anchor
        return [(i + a, j + b) for a in range(self.s) for b in range(self.s)]

    def bed_rectangle(self, p: Placement):
        """The bed itself, centred in its slot."""
        slot = self.block_box(p.anchor, p.span)
        minx, miny, maxx, maxy = slot.bounds
        along, across = (p.length, p.width)
        w, h = (across, along) if p.rotated else (along, across)
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        return box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    def stats(self) -> dict[str, int]:
        return {"cells_bed": len(self.bed_ok), "cells_walk": len(self.walk_ok), "placements": len(self.placements),
                "tiles": len(self.tiles), "tile_arcs": len(self.neighbours),
                "access_arcs": sum(len(v) for v in self.access.values())}


def discretize(problem: CampProblem, geometry: Geometry | None = None) -> Grid:
    geo = geometry or Geometry(problem)
    g = problem.grid
    s = round(problem.corridor.min_width / g)
    if abs(s * g - problem.corridor.min_width) > 1e-9:
        raise ValueError("the corridor width must be a whole number of grid cells")
    minx, miny, maxx, maxy = geo.camp.bounds
    x0, y0 = math.floor(minx / g) * g, math.floor(miny / g) * g
    grid = Grid(problem, geo, g, x0, y0, math.ceil((maxx - x0) / g), math.ceil((maxy - y0) / g), s)

    camp = prep(geo.camp.buffer(EPS))
    blocked = prep(geo.blocked) if not geo.blocked.is_empty else None
    no_beds = prep(geo.no_beds)
    for i in range(grid.nx):
        for j in range(grid.ny):
            cell = grid.cell_box((i, j))
            if not camp.contains(cell):
                continue
            if blocked is not None and blocked.intersects(cell) and geo.blocked.intersection(cell).area > 1e-7:
                continue
            grid.walk_ok.add((i, j))
            if not (no_beds.intersects(cell) and geo.no_beds.intersection(cell).area > 1e-7):
                grid.bed_ok.add((i, j))

    # Door zones: the specified depth is never a bed; each deeper level is a band the model may take.
    for zone in problem.zones:
        levels = geo.zone_levels(zone)
        grid.levels[zone.door] = levels
        polys = [geo.zone_polygon(zone, d) for d in levels]
        grid.level_area[zone.door] = [p.area for p in polys]
        base = prep(polys[0].union(geo.door_frames[zone.door]).buffer(EPS))
        for cell in grid.walk_ok:
            if base.contains(grid.cell_box(cell)):
                grid.base_zone[cell] = zone.door
        for level in range(1, len(polys)):
            ring = polys[level].difference(polys[level - 1])
            for cell in list(grid.bed_ok):
                shape = grid.cell_box(cell)
                if ring.intersection(shape).area > 1e-7:
                    grid.band.setdefault(cell, (zone.door, level))

    # Corridor tiles, and which lie wholly in a specified zone (where people enter).
    for i in range(grid.nx):
        for j in range(grid.ny):
            cells = [(i + a, j + b) for a in range(s) for b in range(s)]
            if all(c in grid.walk_ok for c in cells):
                doors = {grid.base_zone.get(c) for c in cells}
                zone = doors.pop() if len(doors) == 1 and None not in doors else None
                grid.tile_at[(i, j)] = len(grid.tiles)
                grid.tiles.append(Tile(len(grid.tiles), (i, j), zone))
    for (i, j), k in grid.tile_at.items():
        for di, dj in ((1, 0), (0, 1)):
            other = grid.tile_at.get((i + di, j + dj))
            if other is not None:
                grid.neighbours += [(k, other), (other, k)]

    # Bed placements, and the tiles that give each its access.
    zones = {zid: prep(poly.buffer(EPS)) for zid, poly in geo.placement_zones.items()}
    for bed in problem.bed_types:
        nominal = bed.length * bed.width
        for length, width in bed.variants():
            along = math.ceil(length / g - 1e-9)
            across = math.ceil((width + bed.side_gap) / g - 1e-9)
            for rotated in ((False, True) if bed.rotation and along != across else (False,)):
                span = (across, along) if rotated else (along, across)
                for i in range(grid.nx - span[0] + 1):
                    for j in range(grid.ny - span[1] + 1):
                        cells = [(i + a, j + b) for a in range(span[0]) for b in range(span[1])]
                        if not all(c in grid.bed_ok for c in cells):
                            continue
                        if bed.zone is not None and not zones[bed.zone].contains(grid.block_box((i, j), span)):
                            continue
                        p = Placement(len(grid.placements), bed.id, length, width, rotated, (i, j), span,
                                      round(abs(length * width - nominal), 6))
                        tiles = _access_tiles(grid, p)
                        if tiles:  # a bed no corridor could ever reach is not a candidate
                            grid.placements.append(p)
                            grid.access[p.index] = tiles
    return grid


def _access_tiles(grid: Grid, p: Placement) -> list[int]:
    """Tiles standing against the middle of a long side (or of any side),
    where a person steps in and out of the bed."""
    i, j = p.anchor
    sx, sy = p.span
    s = grid.s
    sides = []
    long_along_x = not p.rotated
    if long_along_x or grid.problem.corridor.access == "any_side":
        a = i + (sx - s) // 2
        sides += [(a, j - s), (a, j + sy)]  # below, above
    if (not long_along_x) or grid.problem.corridor.access == "any_side":
        b = j + (sy - s) // 2
        sides += [(i - s, b), (i + sx, b)]  # left, right
    return [grid.tile_at[c] for c in sides if c in grid.tile_at]
