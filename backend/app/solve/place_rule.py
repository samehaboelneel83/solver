"""`place`, compiled: items on a drawing's free area, without a list of positions (plan of 8 October 2026, 1C).

The rule names slots (each may hold one item: chosen or not, where, turned or not, which side its aisle is on),
each slot's size in grid cells, and the free areas as polygons in metres with the grid's step and origin. The
compiler turns the polygons into a grid of free cells (a cell is free when it lies wholly inside an area; each
area is a zone, and an item stays in one zone), and keeps the slots' decisions. Only the placement solver
(`app.solve.placement`, backend `layout`) holds such a rule: no solver here takes a grid of half a billion links.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import numpy as np

#: The largest grid a place rule is laid on (the camp at 0.05 m: 2.2 million cells).
MAX_GRID_CELLS = 40_000_000
SIDE_NAMES = ("bottom", "top", "left", "right")


@dataclass(frozen=True)
class Slot:
    id: str
    chosen: Any
    x: Any
    y: Any
    turn: Any | None
    side: Any | None
    length: int
    width: int
    can_turn: bool


@dataclass
class PlacementDef:
    rule: str
    slots: list[Slot]
    zone_grid: np.ndarray  # (nx, ny) int32: the area (zone) of each free cell, -1 where not free
    zones: list[str]
    step: float
    origin: tuple[float, float]
    aisle: int
    aisle_sides: str
    #: Free cells at an access feature (a door, an exit): every item's aisle must join one through free cells
    #: no item covers. None: no access rule.
    entrance: np.ndarray | None = None

    def keys(self) -> list[Any]:
        return [k for s in self.slots for k in (s.chosen, s.x, s.y, s.turn, s.side) if k is not None]

    def to_metres(self, i: int, j: int) -> tuple[float, float]:
        return self.origin[0] + i * self.step, self.origin[1] + j * self.step


def raster(shapes: list[Any], step: float, origin: tuple[float, float], rule: str) -> np.ndarray:
    """The free cells of each area (index in `shapes`), on the grid from `origin` with `step`."""
    import shapely

    from app.solve.compile import Unsupported

    union_bounds = [s.bounds for s in shapes if not s.is_empty]
    if not union_bounds:
        raise Unsupported(f"{rule}: the areas are empty")
    maxx = max(b[2] for b in union_bounds)
    maxy = max(b[3] for b in union_bounds)
    x0, y0 = origin
    nx, ny = int(math.ceil((maxx - x0) / step - 1e-9)), int(math.ceil((maxy - y0) / step - 1e-9))
    if nx <= 0 or ny <= 0:
        raise Unsupported(f"{rule}: the areas lie below or left of the grid's origin")
    if nx * ny > MAX_GRID_CELLS:
        raise Unsupported(f"{rule}: a {step:g} m grid over these areas is {nx * ny:,} cells, more than "
                          f"{MAX_GRID_CELLS:,}; use a coarser step")
    zone = np.full((nx, ny), -1, dtype=np.int32)
    for z, shape in enumerate(shapes):
        if shape.is_empty:
            continue
        bx0, by0, bx1, by1 = shape.bounds
        i0, j0 = max(0, int((bx0 - x0) // step)), max(0, int((by0 - y0) // step))
        i1, j1 = min(nx, int(math.ceil((bx1 - x0) / step)) + 1), min(ny, int(math.ceil((by1 - y0) / step)) + 1)
        if i1 <= i0 or j1 <= j0:
            continue
        gi, gj = np.meshgrid(np.arange(i0, i1), np.arange(j0, j1), indexing="ij")
        boxes = shapely.box(x0 + gi.ravel() * step, y0 + gj.ravel() * step,
                            x0 + (gi.ravel() + 1) * step, y0 + (gj.ravel() + 1) * step)
        shapely.prepare(shape)
        inside = shapely.contains(shape, boxes).reshape(gi.shape)
        block = zone[i0:i1, j0:j1]
        block[inside & (block < 0)] = z
    return zone


#: How far beyond the nearest free cell an access feature reaches (in cells): a door drawn on a wall, or behind a
#: door-front area kept clear, still opens onto the free cells next to it.
ACCESS_REACH = 1.25


def entrances(zone: np.ndarray, features: list[Any], step: float, origin: tuple[float, float]) -> np.ndarray:
    """The free cells each access feature opens onto: those within a cell and a quarter of the feature's nearest
    free cell (so a door on a wall, or behind a clear door front, reaches into the room)."""
    import shapely

    nx, ny = zone.shape
    out = np.zeros(zone.shape, dtype=bool)
    x0, y0 = origin
    for feature in features:
        if feature.is_empty:
            continue
        reach = 3.0
        while True:
            bx0, by0, bx1, by1 = feature.bounds
            i0, j0 = max(0, int((bx0 - reach - x0) // step)), max(0, int((by0 - reach - y0) // step))
            i1, j1 = min(nx, int((bx1 + reach - x0) // step) + 1), min(ny, int((by1 + reach - y0) // step) + 1)
            fi, fj = np.nonzero(zone[i0:i1, j0:j1] >= 0)
            if len(fi) or reach > 50:
                break
            reach *= 2
        if not len(fi):
            continue
        fi, fj = fi + i0, fj + j0
        centres = shapely.points(x0 + (fi + 0.5) * step, y0 + (fj + 0.5) * step)
        dist = shapely.distance(feature, centres)
        near = dist <= dist.min() + ACCESS_REACH * step
        out[fi[near], fj[near]] = True
    return out


def expand(compiler: Any, spec: dict[str, Any]) -> None:
    from shapely import wkt

    from app.solve.compile import Constraint, Linear, Schedule, Unsupported

    rule, body = spec["id"], spec["place"]
    slot_rows = compiler.sets.get(body["slots"]["set"], [])
    area_rows = compiler.sets.get(body["areas"]["set"], [])
    if not slot_rows:
        compiler._note_empty(rule, "slots", {})
        return
    shapes = []
    for row in area_rows:
        text = row.get(body["shape"])
        try:
            shapes.append(wkt.loads(str(text)))
        except Exception:  # noqa: BLE001 -- named, never guessed
            raise Unsupported(f"{rule}: the area {row['id']!r} has no readable {body['shape']!r} "
                              "(a polygon in metres, as WKT)") from None
    step = float(body["step"])
    origin = (float(body["origin"][0]), float(body["origin"][1]))
    zone_grid = raster(shapes, step, origin, rule)

    def key(part: str, slot_id: str):
        ref = body.get(part)
        if ref is None:
            return None
        k = (ref["var"], (slot_id,))
        if k not in compiler.variables:
            raise Unsupported(f"{rule}: no variable {ref['var']}[{slot_id}]")
        return k

    slots = []
    for row in slot_rows:
        sid = row["id"]
        try:
            length, width = int(Decimal(str(row[body["length"]]))), int(Decimal(str(row[body["width"]])))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise Unsupported(f"{rule}: the slot {sid!r} has no whole {body['length']!r} and {body['width']!r} "
                              "(its size in cells)") from None
        if length <= 0 or width <= 0:
            raise Unsupported(f"{rule}: the slot {sid!r} has no positive size")
        turn = key("turn", sid)
        can_turn = turn is not None
        if can_turn and body.get("can_turn"):
            try:
                can_turn = bool(int(Decimal(str(row.get(body["can_turn"]) or 0))))
            except (TypeError, ValueError, ArithmeticError):
                can_turn = False
        slots.append(Slot(sid, key("chosen", sid), key("x", sid), key("y", sid), turn, key("side", sid),
                          length, width, can_turn))
    aisle = int(body.get("aisle") or 0)
    entrance = None
    if body.get("access"):
        features = []
        for row in compiler.sets.get(body["access"]["set"], []):
            try:
                features.append(wkt.loads(str(row.get(body["access_shape"]))))
            except Exception:  # noqa: BLE001
                raise Unsupported(f"{rule}: the access feature {row['id']!r} has no readable "
                                  f"{body['access_shape']!r} (a shape in metres, as WKT)") from None
        entrance = entrances(zone_grid, features, step, origin)
        if not entrance.any():
            raise Unsupported(f"{rule}: no access feature lies at a free cell, so no item could be reached")
    compiler.placements.append(PlacementDef(rule, slots, zone_grid, [str(r["id"]) for r in area_rows], step, origin,
                                            aisle, str(body.get("aisle_sides") or "none") if aisle else "none",
                                            entrance))
    # The rule as one row with no expression (as a scheduling rule is): solvers that do not hold it refuse the
    # model by its need ("placement"); the placement solver and its check read `placements`.
    compiler.constraints.append(Constraint(rule, {}, Linear(), "<=", Linear(), schedule=Schedule("place", (), None)))


def placed_items(ir: dict[str, Any], data: dict[str, Any], value_of) -> list[dict[str, Any]]:
    """Every chosen slot of every place rule as a rectangle in metres: the reports, the exports and the map read
    these. `value_of(var, slot)` is the answer's value of a decision at a slot (0 when absent)."""
    out = []
    rows_of = {name: {str(r.get("id")): r for r in rows if isinstance(r, dict)}
               for name, rows in (data.get("sets") or {}).items() if isinstance(rows, list)}
    for c in ir.get("constraints") or []:
        body = c.get("place") if isinstance(c, dict) else None
        if not isinstance(body, dict):
            continue
        step = float(body["step"])
        x0, y0 = float(body["origin"][0]), float(body["origin"][1])
        aisle = int(body.get("aisle") or 0)

        def var(part):
            return (body.get(part) or {}).get("var")

        for sid, row in rows_of.get(body["slots"]["set"], {}).items():
            if not round(float(value_of(var("chosen"), sid) or 0)):
                continue
            turned = bool(round(float(value_of(var("turn"), sid) or 0))) if var("turn") else False
            length, width = int(float(row[body["length"]])), int(float(row[body["width"]]))
            w, h = (width, length) if turned else (length, width)
            i, j = int(round(float(value_of(var("x"), sid) or 0))), int(round(float(value_of(var("y"), sid) or 0)))
            side = SIDE_NAMES[int(round(float(value_of(var("side"), sid) or 0)))] if aisle and var("side") else None
            out.append({"rule": c.get("id"), "slot": sid, "kind": row.get("kind"), "turned": turned,
                        "min_x_m": round(x0 + i * step, 6), "min_y_m": round(y0 + j * step, 6),
                        "width_m": round(w * step, 6), "height_m": round(h * step, 6),
                        "x_m": round(x0 + (i + w / 2) * step, 6), "y_m": round(y0 + (j + h / 2) * step, 6),
                        "aisle_side": side, "aisle_m": round(aisle * step, 6)})
    return out


def value_reader(assignments: dict[str, Any] | None, amounts: dict[str, Any] | None):
    """`value_of(var, slot)` over a stored solution: yes/no cells listed when chosen, amounts when not zero."""
    values: dict[tuple[str, str], float] = {}
    for var, cells in (assignments or {}).items():
        for cell in cells or []:
            if isinstance(cell, list) and len(cell) == 1:
                values[(var, str(cell[0]))] = 1.0
    for var, entries in (amounts or {}).items():
        for e in entries or []:
            index = e.get("index") or []
            if len(index) == 1:
                values[(var, str(index[0]))] = float(e.get("value") or 0)
    return lambda var, sid: values.get((var, sid), 0.0)


def with_positions(rec: dict[str, Any]) -> dict[str, Any]:
    """A stored run whose model places items: each chosen slot given its rectangle in metres (min_x_m, min_y_m,
    width_m, height_m, x_m, y_m), so the reports, the map and the CAD drawing show it like any placed record."""
    ir, data = rec.get("ir") or {}, rec.get("data") or {}
    if not any(isinstance(c, dict) and "place" in c for c in ir.get("constraints") or []):
        return rec
    items = {it["slot"]: it for it in placed_items(ir, data, value_reader(rec.get("assignments"), rec.get("amounts")))}
    sets = {}
    for name, rows in (data.get("sets") or {}).items():
        if isinstance(rows, list):
            rows = [{**r, **{k: items[str(r.get("id"))][k] for k in ("min_x_m", "min_y_m", "width_m", "height_m",
                                                                       "x_m", "y_m")}}
                    if isinstance(r, dict) and str(r.get("id")) in items else r for r in rows]
        sets[name] = rows
    return {**rec, "data": {**data, "sets": sets}}
