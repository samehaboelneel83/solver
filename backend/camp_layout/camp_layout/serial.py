"""A problem as plain JSON and back: what the platform stores and the map editor edits.

The shape follows the dataclasses one to one (`problem.py`), with points as
`[x, y]` lists in local metres. `from_dict` fills a missing field with the
dataclass default, so an editor may send only what a person set; it refuses
an unknown key rather than dropping it, so a typo is not a silent default.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from .problem import (BedType, CampProblem, CorridorSpec, Door, DoorZone, ObjectiveSpec, Obstacle,
                      PlacementZone, Prohibited)

FORMAT = "camp-problem/1"


class ProblemFormatError(ValueError):
    """The JSON is not a camp problem; the message names the field."""


def _pt(p) -> list[float]:
    return [float(p[0]), float(p[1])]


def _ring(ring) -> list[list[float]]:
    return [_pt(p) for p in ring]


def to_dict(problem: CampProblem) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "name": problem.name,
        "grid": problem.grid,
        "origin_lonlat": _pt(problem.origin_lonlat),
        "boundary": _ring(problem.boundary),
        "doors": [{"id": d.id, "a": _pt(d.a), "b": _pt(d.b), "depth": d.depth, "capacity": d.capacity}
                  for d in problem.doors],
        "zones": [dataclasses.asdict(z) for z in problem.zones],
        "obstacles": [{"id": o.id, "ring": _ring(o.ring), "kind": o.kind} for o in problem.obstacles],
        "prohibited": [{"id": p.id, "ring": _ring(p.ring)} for p in problem.prohibited],
        "placement_zones": [{"id": z.id, "ring": _ring(z.ring)} for z in problem.placement_zones],
        "bed_types": [{**dataclasses.asdict(b), "sizes": [list(s) for s in b.sizes]} for b in problem.bed_types],
        "corridor": dataclasses.asdict(problem.corridor),
        "objectives": {**dataclasses.asdict(problem.objectives), "order": list(problem.objectives.order)},
    }


def _build(cls, data: Any, where: str, convert: dict[str, Any] | None = None):
    if not isinstance(data, dict):
        raise ProblemFormatError(f"{where} is not an object")
    names = {f.name for f in dataclasses.fields(cls)}
    unknown = sorted(set(data) - names)
    if unknown:
        raise ProblemFormatError(f"{where}: unknown field {unknown[0]!r}")
    kwargs = {}
    for key, value in data.items():
        try:
            kwargs[key] = convert[key](value) if convert and key in convert and value is not None else value
        except (TypeError, ValueError, IndexError) as exc:
            raise ProblemFormatError(f"{where}.{key}: {exc}") from exc
    try:
        return cls(**kwargs)
    except TypeError as exc:
        raise ProblemFormatError(f"{where}: {exc}") from exc


def _point(p) -> tuple[float, float]:
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        raise ValueError(f"{p!r} is not a point [x, y]")
    return (float(p[0]), float(p[1]))


def _points(ring) -> list[tuple[float, float]]:
    if not isinstance(ring, list):
        raise ValueError("not a list of points")
    return [_point(p) for p in ring]


def _list(data: dict, key: str) -> list:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ProblemFormatError(f"{key} is not a list")
    return value


def from_dict(data: dict[str, Any]) -> CampProblem:
    if not isinstance(data, dict):
        raise ProblemFormatError("the problem is not an object")
    known = {f.name for f in dataclasses.fields(CampProblem)} | {"format"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ProblemFormatError(f"unknown field {unknown[0]!r}")
    if data.get("format", FORMAT) != FORMAT:
        raise ProblemFormatError(f"format {data.get('format')!r} is not {FORMAT}")
    ring = {"ring": _points}
    door = {"a": _point, "b": _point, "depth": float, "capacity": int}
    bed_convert = {"sizes": lambda s: tuple(_point(x) for x in s), "length": float, "width": float}
    objectives = data.get("objectives", {})
    if isinstance(objectives, dict) and "order" in objectives:
        objectives = {**objectives, "order": tuple(objectives["order"])}
    try:
        return CampProblem(
            name=str(data.get("name") or "camp"),
            boundary=_points(data.get("boundary", [])),
            doors=tuple(_build(Door, d, f"doors[{i}]", door) for i, d in enumerate(_list(data, "doors"))),
            zones=tuple(_build(DoorZone, z, f"zones[{i}]") for i, z in enumerate(_list(data, "zones"))),
            obstacles=tuple(_build(Obstacle, o, f"obstacles[{i}]", ring) for i, o in enumerate(_list(data, "obstacles"))),
            prohibited=tuple(_build(Prohibited, p, f"prohibited[{i}]", ring)
                             for i, p in enumerate(_list(data, "prohibited"))),
            placement_zones=tuple(_build(PlacementZone, z, f"placement_zones[{i}]", ring)
                                  for i, z in enumerate(_list(data, "placement_zones"))),
            bed_types=tuple(_build(BedType, b, f"bed_types[{i}]", bed_convert)
                            for i, b in enumerate(_list(data, "bed_types"))),
            corridor=_build(CorridorSpec, data.get("corridor", {}), "corridor"),
            objectives=_build(ObjectiveSpec, objectives, "objectives"),
            grid=float(data.get("grid", 0.5)),
            origin_lonlat=_point(data.get("origin_lonlat", (31.60, 30.10))),
        )
    except ValueError as exc:
        if isinstance(exc, ProblemFormatError):
            raise
        raise ProblemFormatError(str(exc)) from exc
