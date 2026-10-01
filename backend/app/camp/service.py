"""A drawn camp, checked and explained for the editor.

`check` takes the problem as the map editor holds it (`camp-problem/1`
JSON) and answers what is wrong, each fault naming the shape it is about,
and what the engine will make of it: each door's clear zone at its specified
and its largest depth, the camp's area and how many grid cells it is. The
editor draws those over what was drawn, so a person sees the door zones
before solving, not after.

Errors stop a solve; warnings do not.
"""
from __future__ import annotations

import math
from typing import Any

from app.camp.engine import serial
from camp_layout import examples
from camp_layout.geometry import Geometry
from camp_layout.problem import BedType, CampProblem, Door, DoorZone

#: Beyond this many grid cells a solve takes too long for an interactive service.
MAX_CELLS = 60_000
MAX_SHAPES = 500
MAX_VERTICES = 2_000
TOL = 0.01


def blank(name: str, origin_lonlat: tuple[float, float] = (31.60, 30.10)) -> dict[str, Any]:
    """A plain 30 x 20 m camp with one door and a cot: something to draw over."""
    problem = CampProblem(
        name=name,
        boundary=[(0, 0), (30, 0), (30, 20), (0, 20)],
        doors=(Door("D1", (14, 0), (16, 0)),),
        zones=(DoorZone("D1", area_per_bed=0.25),),
        bed_types=(BedType("cot", 2.0, 0.9),),
        origin_lonlat=origin_lonlat,
    )
    return serial.to_dict(problem)


def example(kind: str, name: str | None = None) -> dict[str, Any]:
    problem = examples.complex_camp() if kind == "complex" else examples.small_camp()
    data = serial.to_dict(problem)
    if name:
        data["name"] = name
    return data


def normalised(data: dict[str, Any]) -> dict[str, Any]:
    """Every door with its zone settings, and no settings for a door that is gone.
    The editor keeps a door's zone with the door; a file may not."""
    doors = [d.get("id") for d in data.get("doors", []) if isinstance(d, dict)]
    zones = [z for z in data.get("zones", []) if isinstance(z, dict) and z.get("door") in doors]
    have = {z["door"] for z in zones}
    zones += [{"door": d, "area_per_bed": 0.25} for d in doors if d not in have]
    return {**data, "zones": zones}


def _fault(where: str, message: str, severity: str = "error") -> dict[str, str]:
    return {"where": where, "message": message, "severity": severity}


def _ring_faults(where: str, ring, camp) -> list[dict[str, str]]:
    from shapely.geometry import Polygon

    if len(ring) < 3:
        return [_fault(where, "needs at least 3 corners")]
    if len(ring) > MAX_VERTICES:
        return [_fault(where, f"has {len(ring)} corners; at most {MAX_VERTICES}")]
    poly = Polygon(ring)
    if not poly.is_valid:
        return [_fault(where, "its outline crosses itself")]
    if poly.area < 1e-6:
        return [_fault(where, "has no area")]
    if camp is not None and not poly.intersects(camp):
        return [_fault(where, "is outside the camp; it has no effect", "warning")]
    return []


def _on_wall(door, camp) -> str | None:
    (ax, ay), (bx, by) = door.a, door.b
    if math.dist(door.a, door.b) < 0.3:
        return "is shorter than 0.3 m"
    if not (math.isclose(ax, bx, abs_tol=1e-9) or math.isclose(ay, by, abs_tol=1e-9)):
        return "is not horizontal or vertical; put it on a horizontal or vertical wall"
    coords = list(camp.exterior.coords)
    for (px, py), (qx, qy) in zip(coords, coords[1:]):
        if not (math.isclose(px, qx, abs_tol=1e-9) or math.isclose(py, qy, abs_tol=1e-9)):
            continue
        from shapely.geometry import LineString, Point
        edge = LineString([(px, py), (qx, qy)])
        if edge.distance(Point(door.a)) <= TOL and edge.distance(Point(door.b)) <= TOL:
            return None
    return "is not on a horizontal or vertical wall of the camp"


def check(data: Any) -> dict[str, Any]:
    """Faults and what the engine derives, for a problem as JSON."""
    from shapely.geometry import Polygon

    faults: list[dict[str, str]] = []
    derived: dict[str, Any] = {"door_zones": [], "area_m2": None, "cells": None}
    try:
        problem = serial.from_dict(normalised(data) if isinstance(data, dict) else data)
    except serial.ProblemFormatError as exc:
        return {"ok": False, "faults": [_fault("problem", str(exc))], "derived": derived}

    camp = None
    if len(problem.boundary) < 3:
        faults.append(_fault("boundary", "draw the camp boundary: at least 3 corners"))
    else:
        poly = Polygon(problem.boundary)
        if not poly.is_valid:
            faults.append(_fault("boundary", "the camp boundary crosses itself"))
        elif poly.area < 1:
            faults.append(_fault("boundary", "the camp is smaller than 1 m²"))
        else:
            camp = poly
            derived["area_m2"] = round(poly.area, 1)
            cells = int(poly.area / (problem.grid ** 2))
            derived["cells"] = cells
            if cells > MAX_CELLS:
                faults.append(_fault("camp", f"{cells:,} grid cells of {problem.grid:g} m is more than "
                                             f"{MAX_CELLS:,}: use a coarser grid or split the camp"))

    shapes = len(problem.obstacles) + len(problem.prohibited) + len(problem.placement_zones) + len(problem.doors)
    if shapes > MAX_SHAPES:
        faults.append(_fault("camp", f"{shapes} shapes; at most {MAX_SHAPES}"))
    if not problem.doors:
        faults.append(_fault("doors", "add at least one door on the boundary"))
    if not problem.bed_types:
        faults.append(_fault("bed_types", "add at least one bed type"))
    if not 0.1 <= problem.grid <= 2:
        faults.append(_fault("grid", "the grid is 0.1 to 2 m"))
    if not (-180 <= problem.origin_lonlat[0] <= 180 and -90 <= problem.origin_lonlat[1] <= 90):
        faults.append(_fault("origin", "the origin is not a longitude and latitude"))

    for kind, items in (("obstacle", problem.obstacles), ("no-beds area", problem.prohibited),
                        ("zone", problem.placement_zones)):
        seen: set[str] = set()
        for item in items:
            where = f"{kind} {item.id}"
            if not item.id:
                faults.append(_fault(kind, f"a {kind} has no name"))
            elif item.id in seen:
                faults.append(_fault(where, f"two shapes are called {item.id}"))
            seen.add(item.id)
            faults += _ring_faults(where, item.ring, camp)
    used_zones = {b.zone for b in problem.bed_types if b.zone}
    for z in problem.placement_zones:
        if z.id not in used_zones:
            faults.append(_fault(f"zone {z.id}", "no bed type is assigned to it, so it has no effect", "warning"))

    door_ok = []
    for d in problem.doors:
        if not d.id:
            faults.append(_fault("door", "a door has no name"))
            continue
        if camp is not None:
            wrong = _on_wall(d, camp)
            if wrong:
                faults.append(_fault(f"door {d.id}", wrong))
                continue
        door_ok.append(d.id)
        if d.capacity is not None and d.capacity < 1:
            faults.append(_fault(f"door {d.id}", "capacity must be at least 1 bed"))

    for b in problem.bed_types:
        if b.length <= 0 or b.width <= 0:
            faults.append(_fault(f"bed type {b.id}", "length and width must be positive"))
        if b.max_count is not None and b.max_count < b.min_count:
            faults.append(_fault(f"bed type {b.id}", "the most is below the least"))
    for zone in problem.zones:
        if zone.depth <= 0 or zone.step <= 0:
            faults.append(_fault(f"door {zone.door}", "zone depth and step must be positive"))

    for message in problem.check():
        if not any(message in f["message"] for f in faults):
            faults.append(_fault("problem", message))

    if camp is not None and door_ok:
        try:
            geo = Geometry(problem)
            ring = lambda p: [[round(x, 4), round(y, 4)] for x, y in p.exterior.coords] if not p.is_empty else []
            for zone in problem.zones:
                if zone.door not in door_ok:
                    continue
                at, most = geo.zone_polygon(zone, zone.depth), geo.zone_polygon(zone, zone.max_depth)
                derived["door_zones"].append({
                    "door": zone.door, "depth": ring(at) if at.geom_type == "Polygon" else [],
                    "max_depth": ring(most) if most.geom_type == "Polygon" else [],
                    "area_m2": round(at.area, 1),
                    "beds_room": None if not zone.area_per_bed else int(at.area / zone.area_per_bed),
                })
        except ValueError as exc:
            faults.append(_fault("doors", str(exc)))

    return {"ok": not any(f["severity"] == "error" for f in faults), "faults": faults, "derived": derived}
