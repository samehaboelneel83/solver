"""A. Problem definition: what the camp is, and what may change.

Everything here is data. Nothing refers to a solver, a grid or a variable:
the same definition is discretised (`discretize`), modelled (`builder`),
solved by any adapter (`adapters`) and checked (`validate`) without being
rewritten. Units are metres in a local, flat coordinate system (x east,
y north); `origin_lonlat` places it on the Earth for GIS output only.

Three kinds of object, kept apart (spec §6):

- fixed      -- the camp boundary, doors, obstacles, prohibited areas: never move.
- flexible   -- door zones: fixed position, depth may grow within bounds.
- decision   -- beds (existence, position, orientation, size) and corridors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Point = tuple[float, float]
Ring = list[Point]


@dataclass(frozen=True)
class Door:
    """A fixed opening on the boundary. `a`-`b` is the opening on an
    axis-aligned boundary edge; `depth` is how far its frame reaches into the
    camp. Beds never cover it; people walk through it."""

    id: str
    a: Point
    b: Point
    depth: float = 0.3
    capacity: int | None = None  # most beds it may serve (evacuation), None = any


@dataclass(frozen=True)
class DoorZone:
    """The clear area inside a door: as wide as the door plus `margin` on each
    side, `depth` deep, and deeper in `step` increments up to `max_depth` if
    the beds it serves need more room (flexible object, spec §2)."""

    door: str
    depth: float = 2.0
    max_depth: float = 4.0
    step: float = 1.0
    margin: float = 0.5
    area_per_bed: float | None = 0.5  # m² of zone per bed served; None = no rule


@dataclass(frozen=True)
class Obstacle:
    """A closed area: never a bed, never a corridor."""

    id: str
    ring: Ring
    kind: str = "closed"


@dataclass(frozen=True)
class Prohibited:
    """No beds, but people may walk through it (a fire break, a clear lane)."""

    id: str
    ring: Ring


@dataclass(frozen=True)
class PlacementZone:
    """Where a bed type may (mandatory) be placed; see BedType.zone."""

    id: str
    ring: Ring


@dataclass(frozen=True)
class BedType:
    """A kind of bed. Length is along the bed, width across it. Flexible
    dimensions are the allowed range; `sizes` picks the variants the model may
    choose from inside it (a continuous size would add nothing on a grid).

    `min_count` / `max_count` bound how many are placed; `zone` confines them
    to a placement zone; `priority` weighs them in the bed count."""

    id: str
    length: float
    width: float
    min_length: float | None = None
    max_length: float | None = None
    min_width: float | None = None
    max_width: float | None = None
    sizes: tuple[tuple[float, float], ...] = ()
    rotation: bool = True
    side_gap: float = 0.1  # clear space kept beside a bed, inside its slot
    min_count: int = 0
    max_count: int | None = None
    zone: str | None = None
    priority: float = 1.0

    def variants(self) -> list[tuple[float, float]]:
        """(length, width) pairs the model may choose; the nominal first."""
        out = [(self.length, self.width)]
        for size in self.sizes:
            if size not in out:
                out.append(size)
        return out

    def within(self, length: float, width: float, tol: float = 1e-9) -> bool:
        lo_l = self.min_length if self.min_length is not None else self.length
        hi_l = self.max_length if self.max_length is not None else self.length
        lo_w = self.min_width if self.min_width is not None else self.width
        hi_w = self.max_width if self.max_width is not None else self.width
        return lo_l - tol <= length <= hi_l + tol and lo_w - tol <= width <= hi_w + tol


@dataclass(frozen=True)
class CorridorSpec:
    min_width: float = 1.0
    access: Literal["long_sides", "any_side"] = "long_sides"


ObjectiveName = Literal["beds", "distance", "corridor", "modifications"]


@dataclass(frozen=True)
class ObjectiveSpec:
    """How the objectives combine (spec §8). `order` is the lexicographic
    order; `weights` are used in weighted mode, after normalisation.
    `tolerance` is how much a later stage may give back of an earlier one
    (0 keeps it exactly; beds are never given back unless `trade_beds`)."""

    mode: Literal["lexicographic", "weighted"] = "lexicographic"
    order: tuple[ObjectiveName, ...] = ("beds", "distance", "corridor", "modifications")
    weights: dict[str, float] = field(default_factory=lambda: {"beds": 1000.0, "distance": 1.0, "corridor": 1.0, "modifications": 0.1})
    tolerance: dict[str, float] = field(default_factory=lambda: {"distance": 0.02, "corridor": 0.02})
    trade_beds: bool = False


@dataclass(frozen=True)
class CampProblem:
    name: str
    boundary: Ring
    doors: tuple[Door, ...]
    zones: tuple[DoorZone, ...]
    obstacles: tuple[Obstacle, ...] = ()
    prohibited: tuple[Prohibited, ...] = ()
    placement_zones: tuple[PlacementZone, ...] = ()
    bed_types: tuple[BedType, ...] = ()
    corridor: CorridorSpec = CorridorSpec()
    objectives: ObjectiveSpec = ObjectiveSpec()
    grid: float = 0.5
    origin_lonlat: Point = (31.60, 30.10)

    def door(self, door_id: str) -> Door:
        return next(d for d in self.doors if d.id == door_id)

    def bed_type(self, type_id: str) -> BedType:
        return next(t for t in self.bed_types if t.id == type_id)

    def check(self) -> list[str]:
        """What is wrong with the definition itself, before any modelling."""
        faults: list[str] = []
        ids = [d.id for d in self.doors]
        if len(set(ids)) != len(ids):
            faults.append("door ids repeat")
        for zone in self.zones:
            if zone.door not in ids:
                faults.append(f"zone for unknown door {zone.door}")
            if zone.max_depth < zone.depth:
                faults.append(f"zone {zone.door}: max_depth below depth")
        for door in self.doors:
            if door.a[0] != door.b[0] and door.a[1] != door.b[1]:
                faults.append(f"door {door.id} is not on an axis-aligned edge")
        zone_ids = {z.id for z in self.placement_zones}
        for bed in self.bed_types:
            if bed.zone is not None and bed.zone not in zone_ids:
                faults.append(f"bed type {bed.id}: unknown zone {bed.zone}")
            for length, width in bed.variants():
                if not bed.within(length, width):
                    faults.append(f"bed type {bed.id}: size {length}x{width} outside its range")
        if self.corridor.min_width < self.grid - 1e-9:
            faults.append("corridor width below the grid pitch")
        return faults
