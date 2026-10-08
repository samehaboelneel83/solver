"""Placing items on a drawing: the candidate positions and the links a placement model needs, made by the
platform instead of by model-written code.

Any "how many of these fit, and where" problem is the same model: rooms or plots (areas), what may not be
covered (obstacles, door fronts), items of given sizes that can be turned, and a free aisle each item needs
on one side to be reached -- beds in a camp, desks in an office, parking stalls, shelves in a store, panels
on a roof. The model is a choice of candidate positions:

- a grid of square cells over the free area (the step divides every item size, so an item covers whole
  cells and nothing is rounded away);
- every position and turn of every item kind whose cells are all free -- one candidate per position, turn
  and aisle side when an aisle is asked for;
- `occupies` (candidate -> each cell it covers) and `keeps_free` (candidate -> each cell of its aisle);
- the rules: a cell is covered at most once; a chosen candidate's aisle cells are covered by nothing.

The camp-bed field test (October 2026) is why: Qwen wrote this geometry itself, nine minutes a turn, and
got it wrong (a 1 m grid for 1.5 x 0.5 m beds, aisles only near doors). Here it is a few seconds of numpy,
the counts and an upper bound are reported, and the plan to build comes back ready.

Positions are in metres from the drawing's lower-left corner -- the frame of the file reader's `shape_m`
and `x_m` (app.agent.files), and of the DXF export, which draws the chosen ones back on the drawing.
"""
from __future__ import annotations

import csv
import math
import os
import re
from typing import Any

import numpy as np
from app.core import limits

STEPS = (1.0, 0.5, 0.25, 0.2, 0.1, 0.05)
MAX_CELLS = 400_000
MAX_CANDIDATES = limits.LAYOUT_CANDIDATES  # app/core/limits.py
MAX_LINKS = limits.LAYOUT_LINKS
SIDES = {"bottom": (0, -1), "top": (0, 1), "left": (-1, 0), "right": (1, 0)}


class LayoutRefused(ValueError):
    """The request cannot be laid out as asked; the message says why and what to change."""

    def __init__(self, message: str, coarser: list[float] | None = None):
        super().__init__(message)
        self.coarser = coarser or []  # exact coarser grid steps, when too many candidates were the reason


def _sheet(files: list[dict[str, Any]], file: str | None, layer: str) -> dict[str, Any]:
    spatial = [f for f in files if f.get("spatial")] if not file else [f for f in files if f.get("name") == file]
    if not spatial:
        raise LayoutRefused(f'no attached map file{" named " + repr(file) if file else ""}; attach the drawing first')
    names = []
    for f in spatial:
        for s in f.get("sheets") or []:
            names.append(s.get("name"))
            short = str(s.get("name")).split("__")[-1]
            if layer in (s.get("name"), short) or layer.lower() == short.lower():
                return s
    raise LayoutRefused(f'no layer "{layer}" in the drawing; its layers: '
                        f'{sorted({str(n).split("__")[-1] for n in names})}')


def _shapes(files, file, layers) -> list[Any]:
    from shapely import wkt

    out = []
    for layer in layers or []:
        s = _sheet(files, file, layer)
        cols = s.get("columns") or []
        if "shape_m" not in cols:
            raise LayoutRefused(f'layer "{layer}" has no positions in metres (shape_m): the drawing must be read in '
                                "local metres or a projected system")
        at = cols.index("shape_m")
        if s.get("truncated"):
            raise LayoutRefused(f'layer "{layer}" has more features than were read ({s.get("total_rows")}); '
                                "split the drawing")
        for row in s.get("rows") or []:
            if row[at]:
                try:
                    out.append((wkt.loads(str(row[at])), row))
                except Exception:  # noqa: BLE001 -- a shape that cannot be read is left out
                    continue
    return out


def _zones(areas, files, file, label_layer) -> list[str]:
    """A name for each area: the text of a label inside it, else A1, A2, ..."""
    names = [f"A{n + 1}" for n in range(len(areas))]
    if not label_layer:
        return names
    s = _sheet(files, file, label_layer)
    cols = s.get("columns") or []
    text_col = next((c for c in ("text", "label", "name", "value") if c in cols), None)
    if text_col is None or "shape_m" not in cols:
        return names
    from shapely import wkt

    for row in s.get("rows") or []:
        try:
            point = wkt.loads(str(row[cols.index("shape_m")])).representative_point()
        except Exception:  # noqa: BLE001
            continue
        for n, (shape, _) in enumerate(areas):
            if shape.buffer(1e-6).contains(point) and str(row[cols.index(text_col)] or "").strip():
                names[n] = str(row[cols.index(text_col)]).strip()
    return names


def choose_step(sizes: list[float], aisle: float, area: float, step: float | None) -> float:
    def divides(s: float) -> bool:
        return all(abs(v / s - round(v / s)) < 1e-6 for v in sizes)

    if step:
        if not divides(step):
            raise LayoutRefused(f"a grid step of {step:g} m does not divide the item sizes {sizes}: an item would not "
                                f"cover whole cells. Steps that do: {[s for s in STEPS if divides(s)]}")
        return float(step)
    fitting = [s for s in STEPS if divides(s) and area / (s * s) <= MAX_CELLS]
    if not fitting:
        raise LayoutRefused(f"no grid step from {STEPS} divides the item sizes {sizes} with at most {MAX_CELLS:,} "
                            "cells; give a step")
    # The coarsest that keeps the aisle within half a cell of what was asked, else the finest that fits.
    for s in fitting:
        if aisle <= 0 or (math.ceil(aisle / s - 1e-9) * s - aisle) <= s / 2:
            return s
    return fitting[-1]


def make(files: list[dict[str, Any]], folder: str, *, step: float | None = None, **kwargs: Any) -> dict[str, Any]:
    """`_make`, and -- when the grid was the platform's own choice and gave too many candidates -- the same on the
    next coarser exact grid (the camp test: 1.75 m beds with a 0.35 m aisle chose 0.05 m to keep the aisle exact,
    460,980 positions, and was refused although the exact 0.25 m grid was there). The aisle modelled is reported."""
    try:
        return _make(files, folder, step=step, **kwargs)
    except LayoutRefused as refused:
        if step is not None or not refused.coarser:
            raise
        for coarser in sorted(refused.coarser):  # finest first: closest to the aisle asked
            try:
                out = _make(files, folder, step=coarser, **kwargs)
            except LayoutRefused as again:
                if again.coarser:
                    continue
                raise
            out["grid_note"] = (f"the exact grid for the aisle asked ({refused}) was too fine; laid out on the "
                                f"coarser exact {coarser:g} m grid, so the aisle is modelled as "
                                f"{out['aisle_m']['modelled']:g} m")
            return out
        raise


def grid(files: list[dict[str, Any]], *, area_layers: list[str], items: list[dict[str, Any]],
         file: str | None = None, blocked_layers: list[str] | None = None, label_layer: str | None = None,
         aisle: float = 0.0, aisle_side: str = "long", step: float | None = None, blocked_buffer: float = 0.0,
         area_indices: list[int] | None = None, max_cells: int | None = None) -> dict[str, Any]:
    """The drawing as a grid: the item kinds, the step, and which cells are free in which zone (-1: not free).
    Shared by the candidate list (`make`) and the placement form (`place`), which needs no candidates."""
    import shapely
    from shapely.ops import unary_union

    if not items:
        raise LayoutRefused('give the items: [{"name": "bed", "length": 1.5, "width": 0.5, "rotations": [0, 90]}]')
    kinds = []
    for it in items:
        try:
            length, width = float(it["length"]), float(it["width"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LayoutRefused("each item needs a length and a width in metres") from exc
        if length <= 0 or width <= 0:
            raise LayoutRefused("item sizes must be positive")
        rotations = sorted({int(r) % 180 for r in it.get("rotations") or [0, 90]})
        if any(r not in (0, 90) for r in rotations):
            raise LayoutRefused("rotations are 0 and/or 90 degrees (turned to the drawing's axes)")
        name = re.sub(r"[^A-Za-z0-9_]", "_", str(it.get("name") or "item")).strip("_").lower() or "item"
        kinds.append({"name": name, "length": length, "width": width, "rotations": rotations,
                      "value": float(it.get("value") or 1)})
    if aisle_side not in ("long", "short", "any", "none"):
        raise LayoutRefused('aisle_side is "long", "short", "any" or "none"')
    aisle = max(0.0, float(aisle or 0))
    if aisle == 0:
        aisle_side = "none"

    all_areas = [(shape, row) for shape, row in _shapes(files, file, area_layers) if shape.area > 0]
    if area_indices is not None:
        if any(i < 0 or i >= len(all_areas) for i in area_indices):
            raise LayoutRefused(f"area indices must be between 0 and {len(all_areas) - 1}")
        wanted = set(area_indices)
        areas = [area for i, area in enumerate(all_areas) if i in wanted]
    else:
        areas = all_areas
    if not areas:
        raise LayoutRefused(f"no areas (polygons) on {area_layers}")
    zones = _zones(areas, files, file, label_layer)
    blocked = []
    for shape, _ in _shapes(files, file, blocked_layers or []):
        blocked.append(shape if shape.area > 0 else shape.buffer(max(blocked_buffer, 0.01)))
    if blocked_buffer > 0:
        blocked = [b.buffer(blocked_buffer) for b in blocked]
    blocked_union = unary_union(blocked) if blocked else None

    free_by_zone = []
    for shape, _ in areas:
        free = shape.buffer(0)
        if blocked_union is not None:
            free = free.difference(blocked_union)
        free_by_zone.append(free)
    free_all = unary_union(free_by_zone)
    sizes = sorted({v for k in kinds for v in (k["length"], k["width"])})
    s = choose_step(sizes, aisle, free_all.area, step)
    n_aisle = math.ceil(aisle / s - 1e-9) if aisle > 0 else 0

    minx, miny, maxx, maxy = free_all.bounds
    x0, y0 = math.floor(minx / s) * s, math.floor(miny / s) * s
    nx, ny = int(math.ceil((maxx - x0) / s)), int(math.ceil((maxy - y0) / s))
    if nx * ny > (max_cells or MAX_CELLS * 4):
        raise LayoutRefused(f"a {s:g} m grid over this drawing is {nx * ny:,} cells; use a coarser step")
    xs = x0 + np.arange(nx) * s
    ys = y0 + np.arange(ny) * s
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    boxes = shapely.box(gx.ravel(), gy.ravel(), gx.ravel() + s, gy.ravel() + s)
    zone_of = np.full(nx * ny, -1, dtype=np.int32)
    for z, free in enumerate(free_by_zone):
        if free.is_empty:
            continue
        shapely.prepare(free)
        inside = shapely.contains(free, boxes) & (zone_of < 0)
        zone_of[inside] = z
    ok = (zone_of >= 0).reshape(nx, ny)
    usable_cells = int(ok.sum())
    if usable_cells == 0:
        raise LayoutRefused(f"no whole {s:g} m cell fits in the free area")
    return {"kinds": kinds, "aisle": aisle, "aisle_side": aisle_side, "step": s, "n_aisle": n_aisle,
            "areas": areas, "zones": zones, "free_by_zone": free_by_zone, "free_all": free_all,
            "x0": x0, "y0": y0, "nx": nx, "ny": ny, "zone_of": zone_of, "ok": ok,
            "zone_grid": zone_of.reshape(nx, ny)}


def _make(files: list[dict[str, Any]], folder: str, *, area_layers: list[str], items: list[dict[str, Any]],
         file: str | None = None, blocked_layers: list[str] | None = None, label_layer: str | None = None,
         aisle: float = 0.0, aisle_side: str = "long", step: float | None = None, blocked_buffer: float = 0.0,
         max_file_rows: int = limits.GENERATED_ROWS, area_indices: list[int] | None = None,
         prefix: str = "layout", access_layers: list[str] | None = None) -> dict[str, Any]:
    """Write `<prefix>_items.csv`, `_cells.csv`, `_occupies.csv` (and `_keeps_free.csv`) into `folder`, and
    return the counts, an upper bound and the plan's seed and model."""
    g = grid(files, area_layers=area_layers, items=items, file=file, blocked_layers=blocked_layers,
             label_layer=label_layer, aisle=aisle, aisle_side=aisle_side, step=step, blocked_buffer=blocked_buffer,
             area_indices=area_indices)
    import shapely

    kinds, aisle, aisle_side, s, n_aisle = g["kinds"], g["aisle"], g["aisle_side"], g["step"], g["n_aisle"]
    areas, zones, free_all = g["areas"], g["zones"], g["free_all"]
    x0, y0, nx, ny, zone_of, ok = g["x0"], g["y0"], g["nx"], g["ny"], g["zone_of"], g["ok"]
    sizes = sorted({v for k in kinds for v in (k["length"], k["width"])})

    # Window sums: a w x h block of cells at (i, j) is all free when its sum is w * h.
    integral = np.zeros((nx + 1, ny + 1), dtype=np.int64)
    integral[1:, 1:] = ok.astype(np.int64).cumsum(0).cumsum(1)

    def full(i0, j0, w, h):
        """Boolean array over (i0, j0) arrays: the w x h block from there lies on the grid and is all free."""
        i1, j1 = i0 + w, j0 + h
        on = (i0 >= 0) & (j0 >= 0) & (i1 <= nx) & (j1 <= ny)
        a, b = np.clip(i0, 0, nx), np.clip(j0, 0, ny)
        c, d = np.clip(i1, 0, nx), np.clip(j1, 0, ny)
        total = integral[c, d] - integral[a, d] - integral[c, b] + integral[a, b]
        return on & (total == w * h)

    ii, jj = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    ii, jj = ii.ravel(), jj.ravel()
    cand = []  # (kind index, rot, side, i array, j array, w, h)
    total = 0
    for k, kind in enumerate(kinds):
        for rot in kind["rotations"]:
            length = kind["length"] if rot == 0 else kind["width"]
            depth = kind["width"] if rot == 0 else kind["length"]
            w, h = round(length / s), round(depth / s)
            fits = full(ii, jj, w, h)
            # One zone per item: never astride two areas.
            same = zone_of.reshape(nx, ny)[ii, jj]
            far = zone_of.reshape(nx, ny)[np.clip(ii + w - 1, 0, nx - 1), np.clip(jj + h - 1, 0, ny - 1)]
            fits &= same == far
            if aisle_side == "none":
                sides = [None]
            else:
                horizontal = w >= h
                long_sides = ["bottom", "top"] if horizontal else ["left", "right"]
                short_sides = ["left", "right"] if horizontal else ["bottom", "top"]
                sides = {"long": long_sides, "short": short_sides, "any": long_sides + short_sides}[aisle_side]
            for side in sides:
                keep = fits.copy()
                if side is not None:
                    si, sj, sw, sh = _strip(ii, jj, w, h, side, n_aisle)
                    keep &= full(si, sj, sw, sh)
                i_sel, j_sel = ii[keep], jj[keep]
                total += len(i_sel)
                cand.append((k, rot, side, i_sel, j_sel, w, h))
    if total == 0:
        raise LayoutRefused("no item fits anywhere: check the sizes, the aisle and the layers")
    if total > MAX_CANDIDATES:
        coarser = [x for x in STEPS if x > s and all(abs(v / x - round(v / x)) < 1e-6 for v in sizes)]
        suggestions = ", ".join(f"{x:g} m" for x in coarser) or "none; the current grid is the coarsest exact grid for these item sizes"
        raise LayoutRefused(
            f"a {s:g} m grid gives {total:,} candidate positions, more than the {MAX_CANDIDATES:,} a model can take "
            f"well. Coarser exact steps: {suggestions}. Generate one selected area at a time, or reduce turns only "
            "when the user has not required them.", coarser=coarser)

    # The generated CSVs are read back into the assistant's file table. Keep each relation
    # table within that reader's row budget; otherwise parsing truncates links and the model
    # gets an incomplete optimization problem after spending time building it.
    occupies_count = sum(len(i_sel) * w * h for _, _, _, i_sel, _, w, h in cand)
    keeps_free_count = sum(
        len(i_sel) * (w * n_aisle if side in ("bottom", "top") else n_aisle * h)
        for _, _, side, i_sel, _, w, h in cand if side is not None
    )
    if occupies_count > max_file_rows or keeps_free_count > max_file_rows:
        raise LayoutRefused(
            f"this layout needs {occupies_count:,} occupies links and {keeps_free_count:,} aisle links; "
            f"a generated table can contain at most {max_file_rows:,} rows without truncation. "
            "Reduce the area, use a coarser grid, or ask to model one area at a time."
        )
    if occupies_count + keeps_free_count > max_file_rows:
        raise LayoutRefused(
            f"this layout needs {occupies_count + keeps_free_count:,} total links, above the "
            f"{max_file_rows:,}-row assistant budget. Reduce the area, use a coarser grid, or "
            "ask to model one area at a time."
        )
    if occupies_count + keeps_free_count > MAX_LINKS:
        raise LayoutRefused(f"{occupies_count + keeps_free_count:,} links between positions and cells: too many for a "
                            "model; use a coarser step or one area at a time")

    os.makedirs(folder, exist_ok=True)
    item_rows, occ_rows, aisle_rows = [], [], []
    used_cells: set[int] = set()
    for k, rot, side, i_sel, j_sel, w, h in cand:
        kind = kinds[k]
        for i, j in zip(i_sel.tolist(), j_sel.tolist()):
            n = len(item_rows) + 1
            name = f"{kind['name']}_{n}"
            z = int(zone_of[i * ny + j])
            item_rows.append([name, kind["name"], rot, side or "", round(x0 + (i + w / 2) * s, 4),
                              round(y0 + (j + h / 2) * s, 4), round(x0 + i * s, 4), round(y0 + j * s, 4),
                              round(w * s, 4), round(h * s, 4), zones[z], kind["value"]])
            for a in range(w):
                for b in range(h):
                    c = (i + a) * ny + (j + b)
                    used_cells.add(c)
                    occ_rows.append((name, c))
            if side is not None:
                si, sj, sw, sh = _strip(i, j, w, h, side, n_aisle)
                for a in range(sw):
                    for b in range(sh):
                        c = (si + a) * ny + (sj + b)
                        used_cells.add(c)
                        aisle_rows.append((name, c))
    access: dict[str, Any] | None = None
    entrance: set[int] = set()
    next_rows: list[tuple[int, int]] = []
    if access_layers:
        # Access (the camp field test, October 2026): every chosen item's aisle must join a way to one of these
        # features (doors, exits, gates) through free cells. Every free cell can be part of a way, not only the
        # ones items use; a cell at an access feature (within a cell and a quarter of it) is where ways start.
        features = [shape for shape, _ in _shapes(files, file, access_layers)]
        if not features:
            raise LayoutRefused(f"no features on {access_layers} to give access from")
        free_cells = [int(c) for c in np.flatnonzero(zone_of >= 0)]
        used_cells.update(free_cells)
        centres = shapely.points(x0 + (np.array(free_cells) // ny + 0.5) * s, y0 + (np.array(free_cells) % ny + 0.5) * s)
        near = np.zeros(len(free_cells), dtype=bool)
        for feature in features:
            near |= shapely.dwithin(feature, centres, 1.25 * s)
        entrance = {c for c, hit in zip(free_cells, near.tolist()) if hit}
        free_set = set(free_cells)
        for c in free_cells:
            for d in (ny, 1):  # the next cell east and north, in the same area
                e = c + d
                if e in free_set and (d == ny or e % ny) and zone_of[e] == zone_of[c]:
                    next_rows.append((c, e))
        reached_zones = {zones[int(zone_of[c])] for c in entrance}
        without = sorted({zones[int(zone_of[c])] for c in free_cells} - reached_zones)
        access = {"layers": list(access_layers), "entrance_cells": len(entrance), "links": len(next_rows),
                  "areas_without_access": without}
    if len(used_cells) > max_file_rows:
        raise LayoutRefused(f"this layout needs {len(used_cells):,} used cells, more than the {max_file_rows:,} "
                            "rows the assistant can load without truncation; use a coarser grid or one area at a time")
    cell_rows = [[f"k{c}", round(x0 + (c // ny + 0.5) * s, 4), round(y0 + (c % ny + 0.5) * s, 4), zones[int(zone_of[c])]]
                 + ([1 if c in entrance else 0] if access is not None else [])
                 for c in sorted(used_cells)]
    names = {"items": f"{prefix}_items.csv", "cells": f"{prefix}_cells.csv", "occupies": f"{prefix}_occupies.csv",
             "keeps_free": f"{prefix}_keeps_free.csv"}
    _write(folder, names["items"], ["item", "kind", "rot", "aisle_side", "x_m", "y_m", "min_x_m", "min_y_m",
                                    "width_m", "height_m", "zone", "value"], item_rows)
    _write(folder, names["cells"], ["cell", "x_m", "y_m", "zone"] + (["entrance"] if access is not None else []), cell_rows)
    if access is not None:
        names["next_to"] = f"{prefix}_next_to.csv"
        _write(folder, names["next_to"], ["cell", "cell2"], [(f"k{a}", f"k{b}") for a, b in next_rows])
    _write(folder, names["occupies"], ["item", "cell"], [(a, f"k{c}") for a, c in occ_rows])
    written = [names["items"], names["cells"], names["occupies"]]
    if aisle_rows:
        _write(folder, names["keeps_free"], ["item", "cell"], [(a, f"k{c}") for a, c in aisle_rows])
        written.append(names["keeps_free"])
    if access is not None:
        written.append(names["next_to"])

    free_area = float(free_all.area)
    biggest = max(kinds, key=lambda kd: kd["length"] * kd["width"])
    smallest = min(kinds, key=lambda kd: kd["length"] * kd["width"])
    side_len = {"long": smallest["length"], "short": smallest["width"], "any": smallest["width"],
                "none": 0}[aisle_side]
    # Each item needs its own area and half an aisle along one side (two rows can share one aisle).
    per_item = smallest["length"] * smallest["width"] + side_len * aisle / 2
    bound = int(free_area // per_item)
    spec = _spec(kinds, names, bool(aisle_rows), prefix, access is not None)
    return {
        "files": written,
        "grid_step_m": s,
        "aisle_m": {"asked": aisle, "modelled": round(n_aisle * s, 4), "cells": n_aisle, "side": aisle_side},
        "areas": len(areas), "zones": sorted(set(zones)),
        "free_area_m2": round(free_area, 1),
        "cells": len(cell_rows), "candidates": len(item_rows),
        "candidates_by_kind": {kd["name"]: sum(1 for r in item_rows if r[1] == kd["name"]) for kd in kinds},
        "links": {"occupies": len(occ_rows), "keeps_free": len(aisle_rows)},
        "upper_bound": {"items": bound, "how": f"free area {free_area:,.1f} m2 / ({smallest['length']:g} x "
                        f"{smallest['width']:g} m + half an aisle of {aisle:g} m along its "
                        f"{'side' if aisle_side != 'none' else 'nothing'}) = {per_item:.4g} m2 each"},
        "largest_item_m": [biggest["length"], biggest["width"]],
        "spec": spec,
        "access": access,
        "not_modelled": ("Nothing: every chosen item's aisle joins a way of free cells to "
                         f"{', '.join(access_layers or [])}." + (
                             f" Areas with none of those features ({', '.join(access['areas_without_access'])}) "
                             "can take no item." if access and access["areas_without_access"] else ""))
        if access is not None else ("Each chosen item keeps an aisle free on one side, so none is boxed in by its "
                         "neighbours; whether every aisle joins up with a door across the whole drawing is not "
                         "a rule of this model (give access_layers to make it one).")
        if aisle_rows else "No aisle was asked for: items may be packed with no way between them.",
    }


def _strip(i, j, w, h, side, n):
    """The aisle beside a w x h block at (i, j): (i0, j0, width, height) in cells."""
    if side == "bottom":
        return i, j - n, w, n
    if side == "top":
        return i, j + h, w, n
    if side == "left":
        return i - n, j, n, h
    return i + w, j, n, h


def _write(folder: str, name: str, header: list[str], rows) -> None:
    with open(os.path.join(folder, name), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def _spec(kinds, names, aisles: bool, prefix: str, access: bool = False) -> dict[str, Any]:
    """The plan's seed and model over the files written: ready for check_spec, with domain and names to add."""
    item, cell = "item", "cell"
    seed = {
        "entity_types": [
            {"name": item, "role": "resource", "attributes": [
                {"name": "kind", "data_type": "text"}, {"name": "rot", "data_type": "integer"},
                {"name": "x_m", "data_type": "number", "unit": "m"}, {"name": "y_m", "data_type": "number", "unit": "m"},
                {"name": "min_x_m", "data_type": "number", "unit": "m"},
                {"name": "min_y_m", "data_type": "number", "unit": "m"},
                {"name": "width_m", "data_type": "number", "unit": "m"},
                {"name": "height_m", "data_type": "number", "unit": "m"},
                {"name": "zone", "data_type": "text"}]},
            {"name": cell, "role": "location", "attributes": [
                {"name": "x_m", "data_type": "number", "unit": "m"}, {"name": "y_m", "data_type": "number", "unit": "m"},
                {"name": "zone", "data_type": "text"}]}],
        "relationship_types": [{"name": "occupies", "from": item, "to": cell, "cardinality": "many_to_many"}],
        "entities_from_file": [
            {"file": names["items"], "type": item, "key": "item",
             "attrs": {a: a for a in ("kind", "rot", "x_m", "y_m", "min_x_m", "min_y_m", "width_m", "height_m", "zone")}},
            {"file": names["cells"], "type": cell, "key": "cell", "attrs": {"x_m": "x_m", "y_m": "y_m", "zone": "zone"}}],
        "relationships_from_file": [{"file": names["occupies"], "type": "occupies", "from": [item, "item"],
                                     "to": [cell, "cell"]}],
    }
    i, k = {"index": "i", "set": item}, {"index": "k", "set": cell}
    covering = {"sum": {"var": "place", "index": ["j"]},
                "over": [{"index": "j", "set": item, "via": {"rel": "occupies", "to": "k"}}]}
    rules = [{"id": "c_one_per_cell", "note": "A cell is covered by at most one item", "forall": [k],
              "left": covering, "relation": "<=", "right": {"const": 1}, "severity": "hard"}]
    relationships = ["occupies"]
    if aisles:
        seed["relationship_types"].append({"name": "keeps_free", "from": item, "to": cell, "cardinality": "many_to_many"})
        seed["relationships_from_file"].append({"file": names["keeps_free"], "type": "keeps_free",
                                                "from": [item, "item"], "to": [cell, "cell"]})
        relationships.append("keeps_free")
        rules.append({"id": "c_aisle_free", "note": "A chosen item's aisle is covered by no item",
                      "forall": [i, {"index": "k", "set": cell, "via": {"rel": "keeps_free", "from": "i"}}],
                      "left": {"add": [{"var": "place", "index": ["i"]}, covering]},
                      "relation": "<=", "right": {"const": 1}, "severity": "hard"})
    variables: dict[str, Any] = {"place": {"index": [item], "domain": "binary"}}
    if access:
        # A cell is a way (open) or covered by an item, not both; a chosen item's aisle is way; every way is
        # joined to an entrance cell along next_to (`connected` with `sources`).
        seed["entity_types"][1]["attributes"].append({"name": "entrance", "data_type": "integer"})
        seed["entities_from_file"][1]["attrs"]["entrance"] = "entrance"
        seed["relationship_types"].append({"name": "next_to", "from": cell, "to": cell, "cardinality": "many_to_many"})
        seed["relationships_from_file"].append({"file": names["next_to"], "type": "next_to",
                                                "from": [cell, "cell"], "to": [cell, "cell2"]})
        relationships.append("next_to")
        variables["way"] = {"index": [cell], "domain": "binary"}
        rules[0] = {"id": "c_one_per_cell", "note": "A cell is a way or covered by one item at most", "forall": [k],
                    "left": {"add": [{"var": "way", "index": ["k"]}, covering]}, "relation": "<=",
                    "right": {"const": 1}, "severity": "hard"}
        if aisles:
            rules[1] = {"id": "c_aisle_free", "note": "A chosen item's aisle cells are way",
                        "forall": [i, {"index": "k", "set": cell, "via": {"rel": "keeps_free", "from": "i"}}],
                        "left": {"var": "place", "index": ["i"]}, "relation": "<=",
                        "right": {"var": "way", "index": ["k"]}, "severity": "hard"}
        rules.append({"id": "c_access", "note": "Every way joins an entrance", "severity": "hard", "connected": {
            "assign": {"var": "way", "index": ["k"]}, "units": {"index": "k", "set": cell},
            "via": "next_to", "sources": "entrance"}})
    values = {kd["value"] for kd in kinds}
    goal = {"sum": {"var": "place", "index": ["i"]}, "over": [i]}
    ir: dict[str, Any] = {"version": 2, "sets": [item, cell], "relationships": relationships, "parameters": {},
                          "variables": variables,
                          "constraints": rules,
                          "objective": {"sense": "maximize", "terms": [{"id": "o_items", "weight": 1, "expression": goal}]}}
    if len(values) > 1:
        seed["parameters"] = [{"name": "item_value", "index": [item], "default_value": 1}]
        seed["parameter_values_from_file"] = [{"file": names["items"], "parameter": "item_value",
                                               "entities": [[item, "item"]], "value": "value"}]
        ir["parameters"] = {"item_value": {"index": [item]}}
        ir["objective"]["terms"][0]["expression"] = {
            "sum": {"mul": [{"par": "item_value", "index": ["i"]}, {"var": "place", "index": ["i"]}]}, "over": [i]}
    return {"seed": seed, "ir": ir}


def place(files: list[dict[str, Any]], folder: str, *, area_layers: list[str], items: list[dict[str, Any]],
          file: str | None = None, blocked_layers: list[str] | None = None, label_layer: str | None = None,
          aisle: float = 0.0, aisle_side: str = "long", step: float | None = None, blocked_buffer: float = 0.0,
          area_indices: list[int] | None = None, prefix: str = "layout",
          access_layers: list[str] | None = None) -> dict[str, Any]:
    """The placement form (plan of 8 October 2026, phase 1C): no candidate list. Writes `<prefix>_areas.csv` (each
    free area as a polygon in metres) and `<prefix>_slots.csv` (as many slots of each kind as can fit), and returns
    the plan: a `place` rule the placement solver lays out on the grid itself, at any step -- the exact one for the
    sizes and the aisle, however fine."""
    from shapely import wkt

    from app.solve import placement

    exact = step
    if exact is None:
        sizes = sorted({float(v) for it in items for v in (it.get("length", 0), it.get("width", 0))})
        exact = _exact_step(sizes, float(aisle or 0))
    g = grid(files, area_layers=area_layers, items=items, file=file, blocked_layers=blocked_layers,
             label_layer=label_layer, aisle=aisle, aisle_side=aisle_side, step=exact, blocked_buffer=blocked_buffer,
             area_indices=area_indices, max_cells=40_000_000)
    kinds, s, n_aisle, side = g["kinds"], g["step"], g["n_aisle"], g["aisle_side"]
    zone = g["zone_grid"]
    free_cells = int((zone >= 0).sum())
    slots, slot_rows = {}, []
    for kind in kinds:
        cells = (round(kind["length"] / s), round(kind["width"] / s))
        vs = placement.variants_cells([(cells[0], cells[1], kind["rotations"], kind["value"])], side, n_aisle)
        fit = placement.area_bound(free_cells, vs, n_aisle, side)
        asked = next((int(it["count"]) for it in items if str(it.get("name") or "").lower().startswith(kind["name"])
                      and it.get("count")), None)
        slots[kind["name"]] = min(fit, asked) if asked else fit
        for n in range(slots[kind["name"]]):
            slot_rows.append([f"{kind['name']}_{n + 1}", kind["name"], cells[0], cells[1],
                              1 if 90 in kind["rotations"] and 0 in kind["rotations"] else 0, kind["value"]])
    if not slot_rows:
        raise LayoutRefused("no item fits anywhere: check the sizes, the aisle and the layers")
    area_rows = [[f"{name}_{n + 1}" if g["zones"].count(name) > 1 else name, name,
                  wkt.dumps(shape, rounding_precision=6)]
                 for n, (name, shape) in enumerate(zip(g["zones"], g["free_by_zone"])) if not shape.is_empty]
    os.makedirs(folder, exist_ok=True)
    names = {"areas": f"{prefix}_areas.csv", "slots": f"{prefix}_slots.csv"}
    _write(folder, names["areas"], ["area", "zone", "shape"], area_rows)
    _write(folder, names["slots"], ["slot", "kind", "length_cells", "width_cells", "can_turn", "value"], slot_rows)
    access_rows = []
    if access_layers:
        from app.solve.place_rule import entrances

        features = [shape for shape, _ in _shapes(files, file, access_layers)]
        if not features:
            raise LayoutRefused(f"no features on {access_layers} to give access from")
        reached = entrances(zone, features, s, (g["x0"], g["y0"]))
        zones_reached = {g["zones"][int(z)] for z in np.unique(zone[reached]) if z >= 0}
        without = sorted(set(g["zones"]) - zones_reached)
        access_rows = [[f"access_{n + 1}", wkt.dumps(f, rounding_precision=6)] for n, f in enumerate(features)]
        names["access"] = f"{prefix}_access.csv"
        _write(folder, names["access"], ["feature", "shape"], access_rows)
    nx, ny = g["nx"], g["ny"]
    turns = any(r[4] for r in slot_rows)
    seed = {
        "entity_types": [
            {"name": "area", "role": "location", "attributes": [{"name": "zone", "data_type": "text"},
                                                                 {"name": "shape", "data_type": "text"}]},
            {"name": "slot", "role": "resource", "attributes": [
                {"name": "kind", "data_type": "text"}, {"name": "length_cells", "data_type": "integer"},
                {"name": "width_cells", "data_type": "integer"}, {"name": "can_turn", "data_type": "integer"},
                {"name": "value", "data_type": "number"}]}],
        "entities_from_file": [
            {"file": names["areas"], "type": "area", "key": "area", "attrs": {"zone": "zone", "shape": "shape"}},
            {"file": names["slots"], "type": "slot", "key": "slot",
             "attrs": {a: a for a in ("kind", "length_cells", "width_cells", "can_turn", "value")}}],
    }
    s_ref = {"index": "s", "set": "slot"}
    variables: dict[str, Any] = {"placed": {"index": ["slot"], "domain": "binary"},
                                 "x": {"index": ["slot"], "domain": "integer", "lower": 0, "upper": nx},
                                 "y": {"index": ["slot"], "domain": "integer", "lower": 0, "upper": ny}}
    body: dict[str, Any] = {"slots": s_ref, "chosen": {"var": "placed", "index": ["s"]},
                            "x": {"var": "x", "index": ["s"]}, "y": {"var": "y", "index": ["s"]},
                            "length": "length_cells", "width": "width_cells",
                            "areas": {"index": "a", "set": "area"}, "shape": "shape",
                            "step": s, "origin": [g["x0"], g["y0"]]}
    if turns:
        variables["turned"] = {"index": ["slot"], "domain": "binary"}
        body["turn"] = {"var": "turned", "index": ["s"]}
        body["can_turn"] = "can_turn"
    if access_rows:
        seed["entity_types"].append({"name": "access_point", "role": "location",
                                     "attributes": [{"name": "shape", "data_type": "text"}]})
        seed["entities_from_file"].append({"file": names["access"], "type": "access_point", "key": "feature",
                                           "attrs": {"shape": "shape"}})
        body["access"] = {"index": "e", "set": "access_point"}
        body["access_shape"] = "shape"
    if n_aisle:
        variables["aisle_side"] = {"index": ["slot"], "domain": "integer", "lower": 0, "upper": 3}
        body["side"] = {"var": "aisle_side", "index": ["s"]}
        body["aisle"] = n_aisle
        body["aisle_sides"] = side
    values = {r[5] for r in slot_rows}
    goal = ({"sum": {"var": "placed", "index": ["s"]}, "over": [s_ref]} if len(values) == 1 else
            {"sum": {"mul": [{"attr": {"of": "s", "name": "value"}}, {"var": "placed", "index": ["s"]}]},
             "over": [s_ref]})
    ir = {"version": 2, "sets": ["slot", "area"] + (["access_point"] if access_rows else []), "parameters": {},
          "variables": variables,
          "constraints": [{"id": "c_layout", "severity": "hard",
                           "note": "Items on the free area, no two on one cell, each aisle free", "place": body}],
          "objective": {"sense": "maximize", "terms": [{"id": "o_items", "weight": 1, "expression": goal}]}}
    free_area = float(g["free_all"].area)
    return {
        "form": "place",
        "files": [names["areas"], names["slots"]] + ([names["access"]] if access_rows else []),
        "grid_step_m": s,
        "grid_cells": nx * ny, "free_cells": free_cells,
        "aisle_m": {"asked": g["aisle"], "modelled": round(n_aisle * s, 4), "cells": n_aisle, "side": side},
        "areas": len(area_rows), "zones": sorted(set(g["zones"])),
        "free_area_m2": round(free_area, 1),
        "slots_by_kind": slots,
        "upper_bound": {"items": sum(slots.values()),
                        "how": "free cells / (the item's cells + half its aisle), per kind"},
        "spec": {"seed": seed, "ir": ir},
        "access": ({"layers": list(access_layers or []), "features": len(access_rows),
                    "areas_without_access": without} if access_rows else None),
        "not_modelled": (("Nothing: every placed item's aisle joins a way of uncovered free cells to "
                          f"{', '.join(access_layers or [])}." + (
                              f" Areas with none of those features ({', '.join(without)}) can take no item."
                              if without else "")) if access_rows else
                         "Each placed item keeps its aisle free on one side; whether every aisle joins up with a "
                         "door is not a rule here (give access_layers to make it one)." if n_aisle else
                         "No aisle was asked for: items may be packed with no way between them."),
    }


def _exact_step(sizes: list[float], aisle: float) -> float:
    """The coarsest step that divides every size and the aisle exactly (to 1 cm): the placement form has no
    candidate list, so a fine grid costs it little."""
    for s in (1.0, 0.5, 0.25, 0.2, 0.1, 0.05, 0.02, 0.01):
        values = [v for v in sizes if v > 0] + ([aisle] if aisle > 0 else [])
        if all(abs(v / s - round(v / s)) < 1e-6 for v in values):
            return s
    return 0.01
