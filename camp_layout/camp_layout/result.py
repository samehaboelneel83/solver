"""The answer as shapes: what a validator, a map or a report reads.

A LayoutResult holds no variables and no grid indices -- only beds (their
exact rectangles and sizes), corridor squares, each zone's chosen depth, and
the numbers the solver reported. The validator and the GIS export work from
this alone, so they check the layout, not the model's opinion of it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .discretize import Grid


@dataclass
class PlacedBed:
    id: str
    bed_type: str
    length: float
    width: float
    rotated: bool
    polygon: Polygon
    slot: Polygon


@dataclass
class LayoutResult:
    problem_name: str
    beds: list[PlacedBed]
    corridor_squares: list[Polygon]
    zone_depth: dict[str, float]
    door_load_model: dict[str, int]
    objectives: dict[str, float]
    stages: list[dict] = field(default_factory=list)
    solver: str = ""
    model_size: dict = field(default_factory=dict)

    @property
    def corridor(self):
        return unary_union(self.corridor_squares) if self.corridor_squares else Polygon()


def layout_from_values(grid: Grid, builder, values, objectives: dict[str, float], stages, solver: str) -> LayoutResult:
    beds = []
    for p in grid.placements:
        if values[builder.y[p.index].index] > 0.5:
            beds.append(PlacedBed(f"B{len(beds) + 1:03d}", p.bed_type, p.length, p.width, p.rotated,
                                  grid.bed_rectangle(p), grid.block_box(p.anchor, p.span)))
    squares = []
    for tile in grid.tiles:
        if values[builder.t[tile.index].index] > 0.5:
            i, j = tile.anchor
            squares.append(box(grid.x0 + i * grid.g, grid.y0 + j * grid.g,
                               grid.x0 + (i + grid.s) * grid.g, grid.y0 + (j + grid.s) * grid.g))
    depth = {}
    for (door, level), var in builder.e.items():
        if values[var.index] > 0.5:
            depth[door] = grid.levels[door][level]
    loads = {door: int(round(values[var.index])) for door, var in builder.load.items()}
    return LayoutResult(grid.problem.name, beds, squares, depth, loads, objectives,
                        [s if isinstance(s, dict) else s.__dict__ for s in stages], solver)


def to_json(layout: LayoutResult) -> dict:
    """Everything needed to validate or draw the layout again, without the solver."""
    rect = lambda poly: [round(v, 6) for v in poly.bounds]
    return {
        "problem": layout.problem_name, "solver": layout.solver,
        "beds": [{"id": b.id, "type": b.bed_type, "length": b.length, "width": b.width, "rotated": b.rotated,
                  "bed": rect(b.polygon), "slot": rect(b.slot)} for b in layout.beds],
        "corridor_squares": [rect(sq) for sq in layout.corridor_squares],
        "zone_depth": layout.zone_depth, "door_load_model": layout.door_load_model,
        "objectives": layout.objectives, "stages": layout.stages,
    }


def from_json(data: dict) -> LayoutResult:
    beds = [PlacedBed(b["id"], b["type"], b["length"], b["width"], b["rotated"], box(*b["bed"]), box(*b["slot"]))
            for b in data["beds"]]
    return LayoutResult(data["problem"], beds, [box(*r) for r in data["corridor_squares"]], data["zone_depth"],
                        data.get("door_load_model", {}), data.get("objectives", {}), data.get("stages", []),
                        data.get("solver", ""))
