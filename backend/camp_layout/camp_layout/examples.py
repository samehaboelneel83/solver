"""Example camps.

`complex_camp` -- an irregular nine-sided camp of about 940 m² with:

- four doors on different walls, each with its own evacuation capacity;
- a clear zone inside each door, 2 m deep, that may be deepened to 4 m when
  the beds it serves need more assembly room (0.25 m² per bed);
- five closed areas: a latrine block, a generator, a round water tank, a
  tree cluster and a medical store;
- a fire break across the camp (walkable, never a bed) and a no-bed area
  under the generator's exhaust;
- a medical area near the east door where 4 to 6 wide medical beds must go;
- standard cots, 2.2 m long, which may be shortened to 2.0 m if that fits
  more beds -- at a small modification cost.

`small_camp` -- a 14 x 9 m room with one door and one obstacle, for tests
and the worked example in the model document.
"""
from __future__ import annotations

import math

from .problem import BedType, CampProblem, CorridorSpec, Door, DoorZone, Obstacle, PlacementZone, Prohibited


def _circle(cx: float, cy: float, r: float, n: int = 20) -> list[tuple[float, float]]:
    return [(round(cx + r * math.cos(2 * math.pi * k / n), 4), round(cy + r * math.sin(2 * math.pi * k / n), 4))
            for k in range(n)]


def complex_camp(**overrides) -> CampProblem:
    defaults = dict(
        name="Irregular camp, four doors",
        boundary=[(0, 0), (34, 0), (40, 5), (40, 20), (34, 26), (14, 26), (14, 22), (5, 22), (0, 17)],
        doors=(
            Door("D1-south", (6, 0), (8, 0), capacity=80),
            Door("D2-east", (40, 11), (40, 13), capacity=60),
            Door("D3-north", (22, 26), (24, 26), capacity=80),
            Door("D4-west", (0, 8), (0, 9.5), capacity=40),
        ),
        zones=tuple(DoorZone(d, depth=2.0, max_depth=4.0, step=1.0, margin=0.5, area_per_bed=0.25)
                    for d in ("D1-south", "D2-east", "D3-north", "D4-west")),
        obstacles=(
            Obstacle("latrines", [(1, 12.5), (5, 12.5), (5, 15.5), (1, 15.5)], "sanitation"),
            Obstacle("generator", [(30, 6), (34, 6), (34, 9), (30, 9)], "power"),
            Obstacle("water-tank", _circle(24, 13, 1.5), "water"),
            Obstacle("trees", [(9, 16), (12, 15), (13, 18), (10, 19)], "vegetation"),
            Obstacle("medical-store", [(29, 20), (33, 20), (33, 23), (29, 23)], "storage"),
        ),
        prohibited=(
            Prohibited("fire-break", [(18, 0), (19.5, 0), (19.5, 26), (18, 26)]),
            Prohibited("exhaust", [(34, 6), (37, 6), (37, 9.5), (34, 9.5)]),
        ),
        placement_zones=(PlacementZone("medical-area", [(32, 10), (39.5, 10), (39.5, 19), (32, 19)]),),
        bed_types=(
            BedType("cot", length=2.2, width=0.9, min_length=2.0, max_length=2.2, min_width=0.8, max_width=0.9,
                    sizes=((2.0, 0.9),), rotation=True, side_gap=0.1),
            BedType("medical", length=2.2, width=1.2, rotation=True, side_gap=0.1, min_count=4, max_count=6,
                    zone="medical-area", priority=1.0),
        ),
        corridor=CorridorSpec(min_width=1.0, access="long_sides"),
        grid=0.5,
        origin_lonlat=(31.60, 30.10),
    )
    defaults.update(overrides)
    return CampProblem(**defaults)


def small_camp(**overrides) -> CampProblem:
    defaults = dict(
        name="Small room",
        boundary=[(0, 0), (14, 0), (14, 9), (0, 9)],
        doors=(Door("D1", (6, 0), (7.5, 0), capacity=40),),
        zones=(DoorZone("D1", depth=2.0, max_depth=3.0, step=1.0, margin=0.5, area_per_bed=0.25),),
        obstacles=(Obstacle("pillar", [(9, 5), (10, 5), (10, 6), (9, 6)]),),
        bed_types=(BedType("cot", length=2.0, width=0.9, rotation=True, side_gap=0.1),),
        corridor=CorridorSpec(min_width=1.0),
        grid=0.5,
    )
    defaults.update(overrides)
    return CampProblem(**defaults)
