"""F. Geometry / collision engine: exact shapes and the tests on them.

Built on Shapely. It knows nothing of grids or solvers: it turns the
definition into polygons (the camp, each door's frame and each of its zone's
depths, obstacles, prohibited and placement zones), and answers containment
and overlap questions. The discretiser asks it which cells and placements
are allowed; the validator asks it again, independently, about the answer.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from shapely import STRtree
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from .problem import CampProblem, Door, DoorZone

EPS = 1e-6


def inward(problem_boundary: Polygon, door: Door) -> tuple[float, float]:
    """The unit normal of the door's edge that points into the camp."""
    (ax, ay), (bx, by) = door.a, door.b
    mx, my = (ax + bx) / 2, (ay + by) / 2
    normals = [(0.0, 1.0), (0.0, -1.0)] if ay == by else [(1.0, 0.0), (-1.0, 0.0)]
    for nx, ny in normals:
        if problem_boundary.contains(Point(mx + nx * 0.05, my + ny * 0.05)):
            return nx, ny
    raise ValueError(f"door {door.id}: neither side of it is inside the camp")


def rect_from_edge(door: Door, normal: tuple[float, float], depth: float, margin: float = 0.0) -> Polygon:
    """The rectangle standing on the door's opening (widened by `margin` each
    side), reaching `depth` into the camp."""
    (ax, ay), (bx, by) = door.a, door.b
    nx, ny = normal
    if ay == by:
        x0, x1 = min(ax, bx) - margin, max(ax, bx) + margin
        y0, y1 = sorted((ay, ay + ny * depth))
        return box(x0, y0, x1, y1)
    y0, y1 = min(ay, by) - margin, max(ay, by) + margin
    x0, x1 = sorted((ax, ax + nx * depth))
    return box(x0, y0, x1, y1)


@dataclass
class Geometry:
    problem: CampProblem

    @cached_property
    def camp(self) -> Polygon:
        polygon = Polygon(self.problem.boundary)
        if not polygon.is_valid:
            raise ValueError("the camp boundary crosses itself")
        return polygon

    @cached_property
    def normals(self) -> dict[str, tuple[float, float]]:
        return {d.id: inward(self.camp, d) for d in self.problem.doors}

    @cached_property
    def door_frames(self) -> dict[str, Polygon]:
        return {d.id: rect_from_edge(d, self.normals[d.id], d.depth).intersection(self.camp) for d in self.problem.doors}

    def zone_levels(self, zone: DoorZone) -> list[float]:
        """Every depth the zone may take, the specified one first."""
        levels, depth = [], zone.depth
        while depth <= zone.max_depth + EPS:
            levels.append(round(depth, 6))
            depth += zone.step
        return levels

    def zone_polygon(self, zone: DoorZone, depth: float) -> Polygon:
        door = self.problem.door(zone.door)
        return rect_from_edge(door, self.normals[door.id], depth, zone.margin).intersection(self.camp)

    @cached_property
    def obstacles(self) -> dict[str, Polygon]:
        return {o.id: Polygon(o.ring) for o in self.problem.obstacles}

    @cached_property
    def prohibited(self) -> dict[str, Polygon]:
        return {p.id: Polygon(p.ring) for p in self.problem.prohibited}

    @cached_property
    def placement_zones(self) -> dict[str, Polygon]:
        return {z.id: Polygon(z.ring) for z in self.problem.placement_zones}

    @cached_property
    def blocked(self):
        """Nothing may be here: obstacles."""
        return unary_union(list(self.obstacles.values())) if self.obstacles else Polygon()

    @cached_property
    def no_beds(self):
        """No bed may be here: obstacles, prohibited areas, door frames and each
        zone at its specified depth (deeper levels are the model's choice)."""
        parts = [*self.obstacles.values(), *self.prohibited.values(), *self.door_frames.values()]
        parts += [self.zone_polygon(z, z.depth) for z in self.problem.zones]
        return unary_union(parts)

    @cached_property
    def walkable(self):
        """Where a corridor may run: the camp less obstacles."""
        return self.camp.difference(self.blocked)

    @cached_property
    def blocked_tree(self) -> STRtree:
        return STRtree(list(self.obstacles.values()))

    def inside(self, shape) -> bool:
        return self.camp.buffer(EPS).contains(shape)

    def overlaps(self, shape, other) -> bool:
        """Overlap with area, not merely touching along an edge."""
        return shape.intersection(other).area > 1e-7
