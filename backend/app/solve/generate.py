"""Generated sets: a large candidate set stored as its recipe and built by the worker (plan of 8 October 2026, 1B).

A model may name, under `generate`, recipes for sets (and the links between their members) that are not stored as
records: the run's frozen data holds only what a recipe reads (a few areas and item kinds, two sets to pair), and
the worker builds the members just before compiling. A million candidate positions then cost no rows in the
database, no snapshot of them and no transfer -- only the seconds to build them, in the run's own process.

Recipes, in order (a later one may read what an earlier one made):

- `range`: whole numbers `from`..`to` by `step` -- members "0", "1", ... with the attribute `value`.
- `product`: the combinations of the members of the sets `of` (two to four), each member "a|b" with one attribute
  per set naming its part (a set named twice: "cell", "cell_2"), and a link `<set>_<part>` from each member to each
  part. Kept only where `linked` (a relationship from the first part to the second) has that link, where every
  `same` pair of attributes ([first's, second's]) is equal, without repeats (`distinct`), and once per unordered
  pair (`unordered`).
- `positions`: every place an item of each kind fits on the free cells of polygon areas laid on a grid -- the
  candidate list of a layout. Areas (`areas`, WKT polygons in metres in attribute `shape`) on a grid of `step`
  metres from `origin`; kinds (`kinds`) with their size in cells (`length`, `width`), whether they turn
  (`can_turn`) and their `value`; optionally an aisle of `aisle` cells kept free on one side (`aisle_sides`: long,
  short, any) and access features (`access`, `access_shape`). It makes the sets `items` and `cells` and the links
  `occupies` (item -> each cell it covers), `keeps_free` (item -> its aisle's cells) and `next_to` (free cell ->
  the next one east and north, in the same area) -- the same model the stored candidate list has.

Every recipe's outputs are known from the recipe alone (names and attributes), so a model using them is checked
before it runs; their sizes are known only once built, and a recipe that would make more than the limits refuses.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from threading import Lock
from typing import Any, Callable

import numpy as np

from app.core import limits

KINDS = ("range", "product", "positions")
#: The keys each recipe reads, and which of them are required.
KEYS = {
    "range": ({"kind", "set", "from", "to", "step"}, {"kind", "set", "from", "to"}),
    "product": ({"kind", "set", "of", "linked", "same", "distinct", "unordered"}, {"kind", "set", "of"}),
    "positions": ({"kind", "areas", "shape", "kinds", "length", "width", "can_turn", "value", "step", "origin",
                   "aisle", "aisle_sides", "access", "access_shape", "items", "cells", "occupies", "keeps_free",
                   "next_to"},
                  {"kind", "areas", "shape", "kinds", "length", "width", "step", "origin", "items", "cells",
                   "occupies"}),
}
AISLE_SIDES = ("long", "short", "any")
SIDE_NAMES = ("bottom", "top", "left", "right")
ITEM_ATTRS = {"kind": "text", "rot": "integer", "aisle_side": "text", "x_m": "number", "y_m": "number",
              "min_x_m": "number", "min_y_m": "number", "width_m": "number", "height_m": "number",
              "zone": "text", "value": "number"}
CELL_ATTRS = {"x_m": "number", "y_m": "number", "zone": "text", "entrance": "integer"}


#: Marks data whose recipes are built, so a second `apply` (the compile after the worker's own) builds nothing.
BUILT = "generated"


class Refused(Exception):
    """A recipe that cannot be built on this data (too large, malformed areas)."""


def _is_name(value: Any) -> bool:
    import re

    return isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]*", value) is not None


def _parts(of: list[str]) -> list[str]:
    """Each part's attribute name: the set's name, then "<set>_2", "<set>_3" for a set named again."""
    seen: dict[str, int] = {}
    out = []
    for name in of:
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return out


def outputs(recipe: dict[str, Any]) -> tuple[dict[str, dict[str, str]], dict[str, tuple[str, str]]]:
    """What a (shape-valid) recipe makes: {set: {attribute: data type}} and {relationship: (from set, to set)}."""
    kind = recipe["kind"]
    if kind == "range":
        return {recipe["set"]: {"value": "integer"}}, {}
    if kind == "product":
        parts = _parts(recipe["of"])
        name = recipe["set"]
        return ({name: {p: "text" for p in parts}},
                {f"{name}_{p}": (name, s) for p, s in zip(parts, recipe["of"])})
    items, cells = recipe["items"], recipe["cells"]
    rels = {recipe["occupies"]: (items, cells)}
    if recipe.get("keeps_free"):
        rels[recipe["keeps_free"]] = (items, cells)
    if recipe.get("next_to"):
        rels[recipe["next_to"]] = (cells, cells)
    cell_attrs = {k: v for k, v in CELL_ATTRS.items() if k != "entrance" or recipe.get("access")}
    return {items: dict(ITEM_ATTRS), cells: cell_attrs}, rels


def check(recipe: Any, sets: set[str], relationships: set[str]) -> tuple[str, list[Any], str] | None:
    """The first fault of one recipe, as (code, location inside it, message), given the sets and relationships
    known before it (the model's own and earlier recipes'). Mirrored in frontend/src/ir/validate.ts."""
    if not isinstance(recipe, dict) or recipe.get("kind") not in KINDS:
        return ("generate_malformed", ["kind"], f"a recipe is an object whose kind is one of {', '.join(KINDS)}")
    kind = recipe["kind"]
    allowed, required = KEYS[kind]
    for key in sorted(recipe):
        if key not in allowed:
            return ("generate_malformed", [key], f"a {kind} recipe reads {', '.join(sorted(allowed))}; not {key!r}")
    for key in sorted(required):
        if key not in recipe:
            return ("generate_malformed", [key], f"a {kind} recipe needs {key}")

    def is_int(v):
        return isinstance(v, int) and not isinstance(v, bool)

    def known_set(key, value):
        if not _is_name(value):
            return ("generate_malformed", [key], f"{key} is a set's name")
        if value not in sets:
            return ("generate_unknown_set", [key], f"{value!r} is not a set of this model (list it in sets, or "
                    "make it in an earlier recipe)")
        return None

    def attr_name(key):
        if not isinstance(recipe.get(key), str) or not recipe[key]:
            return ("generate_malformed", [key], f"{key} is an attribute's name")
        return None

    if kind == "range":
        if not all(is_int(recipe.get(k, 1)) for k in ("from", "to", "step")) or recipe.get("step", 1) <= 0:
            return ("generate_malformed", ["step"], "from, to and step are whole numbers, step above 0")
        if recipe["to"] < recipe["from"]:
            return ("generate_malformed", ["to"], "to is at least from")
        made = [recipe["set"]]
    elif kind == "product":
        of = recipe["of"]
        if not isinstance(of, list) or not 2 <= len(of) <= 4:
            return ("generate_malformed", ["of"], "of names two to four sets")
        for i, name in enumerate(of):
            problem = known_set("of", name)
            if problem:
                return (problem[0], ["of", i], problem[2])
        if "linked" in recipe:
            if not _is_name(recipe["linked"]) or recipe["linked"] not in relationships:
                return ("generate_unknown_relationship", ["linked"], f"{recipe['linked']!r} is not a relationship "
                        "of this model (list it in relationships)")
        same = recipe.get("same", [])
        if not isinstance(same, list) or not all(
                isinstance(p, list) and len(p) == 2 and all(isinstance(a, str) and a for a in p) for p in same):
            return ("generate_malformed", ["same"], 'same is a list of [attribute of the first, attribute of the '
                    'second] pairs, e.g. [["ward", "ward"]]')
        for key in ("distinct", "unordered"):
            if key in recipe and not isinstance(recipe[key], bool):
                return ("generate_malformed", [key], f"{key} is true or false")
        made = [recipe["set"]]
    else:
        for key in ("areas", "kinds", *(("access",) if "access" in recipe else ())):
            problem = known_set(key, recipe[key])
            if problem:
                return problem
        for key in ("shape", "length", "width", *(k for k in ("can_turn", "value", "access_shape") if k in recipe)):
            problem = attr_name(key)
            if problem:
                return problem
        if "access" in recipe and "access_shape" not in recipe:
            return ("generate_malformed", ["access_shape"], "access needs access_shape: its features' WKT attribute")
        step = recipe["step"]
        if isinstance(step, bool) or not isinstance(step, (int, float)) or not math.isfinite(step) or not step > 0:
            return ("generate_malformed", ["step"], "step is the grid's step in metres, above 0")
        origin = recipe["origin"]
        if not isinstance(origin, list) or len(origin) != 2 or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in origin):
            return ("generate_malformed", ["origin"], "origin is [x, y] in metres")
        aisle = recipe.get("aisle", 0)
        if not is_int(aisle) or aisle < 0:
            return ("generate_malformed", ["aisle"], "aisle is a whole number of cells, 0 or more")
        if aisle and recipe.get("aisle_sides", "long") not in AISLE_SIDES:
            return ("generate_malformed", ["aisle_sides"], f"aisle_sides is one of {', '.join(AISLE_SIDES)}")
        if aisle and not recipe.get("keeps_free"):
            return ("generate_malformed", ["keeps_free"], "an aisle needs keeps_free: the name of its links")
        if "access" in recipe and not recipe.get("next_to"):
            return ("generate_malformed", ["next_to"], "access needs next_to: the name of the links between cells")
        made = [recipe["items"], recipe["cells"]]
        for key in ("items", "cells", "occupies", "keeps_free", "next_to"):
            if key in recipe and not _is_name(recipe[key]):
                return ("generate_malformed", [key], f"{key} is a name: ^[a-z][a-z0-9_]*$")
        if recipe["items"] == recipe["cells"]:
            return ("generate_malformed", ["cells"], "items and cells are two sets")
    if not all(_is_name(n) for n in made):
        return ("generate_malformed", ["set"], "set is a name: ^[a-z][a-z0-9_]*$")
    new_sets, new_rels = outputs(recipe)
    for name in new_sets:
        if name in sets or name in relationships:
            return ("generate_name_taken", ["set"] if kind != "positions" else
                    ["items" if name == recipe["items"] else "cells"], f"{name!r} is already a set or relationship "
                    "of this model")
    names = list(new_rels)
    if len(set(names)) != len(names) or any(n in new_sets for n in names):
        return ("generate_name_taken", [], "a recipe's links and sets each need their own name")
    for name in names:
        if name in sets or name in relationships:
            return ("generate_name_taken", [], f"{name!r} is already a set or relationship of this model")
    return None


def declared(ir: dict[str, Any]) -> tuple[dict[str, dict[str, str]], dict[str, tuple[str, str]]]:
    """Everything a (shape-valid) model's recipes make."""
    sets: dict[str, dict[str, str]] = {}
    rels: dict[str, tuple[str, str]] = {}
    for recipe in ir.get("generate") or []:
        s, r = outputs(recipe)
        sets.update(s)
        rels.update(r)
    return sets, rels


# --- building -----------------------------------------------------------------------------------------------------


def apply(ir: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """`data` with every recipe's members and links in it (a copy; the frozen data is untouched). Data without
    recipes comes back as it is."""
    recipes = ir.get("generate") or []
    if not recipes or data.get(BUILT):
        return data
    out = dict(data)
    out[BUILT] = True
    out["sets"] = dict(data.get("sets") or {})
    out["relationships"] = dict(data.get("relationships") or {})
    for recipe in recipes:
        BUILDERS[recipe["kind"]](recipe, out)
    return out


def _cap(what: str, count: int, limit: int) -> None:
    if count > limit:
        raise Refused(f"{what}: {count:,} is more than the {limit:,} one generated set may hold")


def _range(recipe: dict[str, Any], data: dict[str, Any]) -> None:
    lo, hi, step = recipe["from"], recipe["to"], recipe.get("step", 1)
    _cap(f"the range {recipe['set']}", (hi - lo) // step + 1, limits.GENERATED_MEMBERS)
    data["sets"][recipe["set"]] = [{"id": str(v), "value": v} for v in range(lo, hi + 1, step)]


def _product(recipe: dict[str, Any], data: dict[str, Any]) -> None:
    import itertools

    of, name = recipe["of"], recipe["set"]
    parts = _parts(of)
    pools = [data["sets"].get(s) or [] for s in of]
    linked = None
    if recipe.get("linked"):
        linked = {(str(e["from"]), str(e["to"])) for e in data["relationships"].get(recipe["linked"]) or []}
    same = recipe.get("same") or []
    distinct, unordered = recipe.get("distinct", False), recipe.get("unordered", False)
    size = math.prod(len(p) for p in pools)
    rows: list[dict[str, Any]] = []
    for combo in itertools.product(*pools) if size else ():
        keys = [str(m["id"]) for m in combo]
        if linked is not None and (keys[0], keys[1]) not in linked:
            continue
        if any(combo[0].get(a) != combo[1].get(b) for a, b in same):
            continue
        if distinct and len(set(keys)) < len(keys):
            continue
        if unordered and keys != sorted(keys):
            continue
        rows.append({"id": "|".join(keys), **dict(zip(parts, keys))})
        if len(rows) > limits.GENERATED_MEMBERS:
            _cap(f"the combinations {name}", len(rows), limits.GENERATED_MEMBERS)
    data["sets"][name] = rows
    for part in parts:
        data["relationships"][f"{name}_{part}"] = [{"from": r["id"], "to": r[part]} for r in rows]


def strip(i, j, w, h, side: str, n: int):
    """The aisle beside a w x h block at (i, j): (i0, j0, width, height) in cells."""
    if side == "bottom":
        return i, j - n, w, n
    if side == "top":
        return i, j + h, w, n
    if side == "left":
        return i - n, j, n, h
    return i + w, j, n, h


def candidates(zone: np.ndarray, kinds: list[tuple[int, int, tuple[int, ...]]], n_aisle: int,
               aisle_sides: str) -> list[tuple[int, int, str | None, np.ndarray, np.ndarray, int, int]]:
    """Every place an item fits: (kind index, rotation, aisle side, i array, j array, width, height in cells) for
    each kind (length and width in cells along x and y unturned, its rotations among 0 and 90), on the free cells
    of `zone` ((nx, ny); the area of each free cell, -1 where none), within one area, its aisle free beside it."""
    nx, ny = zone.shape
    ok = zone >= 0
    integral = np.zeros((nx + 1, ny + 1), dtype=np.int64)
    integral[1:, 1:] = ok.astype(np.int64).cumsum(0).cumsum(1)

    def full(i0, j0, w, h):
        i1, j1 = i0 + w, j0 + h
        on = (i0 >= 0) & (j0 >= 0) & (i1 <= nx) & (j1 <= ny)
        a, b = np.clip(i0, 0, nx), np.clip(j0, 0, ny)
        c, d = np.clip(i1, 0, nx), np.clip(j1, 0, ny)
        total = integral[c, d] - integral[a, d] - integral[c, b] + integral[a, b]
        return on & (total == w * h)

    ii, jj = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    ii, jj = ii.ravel(), jj.ravel()
    out = []
    for k, (length, width, rotations) in enumerate(kinds):
        for rot in rotations:
            w, h = (length, width) if rot == 0 else (width, length)
            fits = full(ii, jj, w, h)
            # One area per item: never astride two.
            fits &= zone[ii, jj] == zone[np.clip(ii + w - 1, 0, nx - 1), np.clip(jj + h - 1, 0, ny - 1)]
            if not n_aisle:
                sides: list[str | None] = [None]
            else:
                horizontal = w >= h
                long_sides = ["bottom", "top"] if horizontal else ["left", "right"]
                short_sides = ["left", "right"] if horizontal else ["bottom", "top"]
                sides = {"long": long_sides, "short": short_sides, "any": long_sides + short_sides}[aisle_sides]
            for side in sides:
                keep = fits.copy()
                if side is not None:
                    si, sj, sw, sh = strip(ii, jj, w, h, side, n_aisle)
                    keep &= full(si, sj, sw, sh)
                out.append((k, rot, side, ii[keep], jj[keep], w, h))
    return out


def _block_cells(i_sel: np.ndarray, j_sel: np.ndarray, w: int, h: int, ny: int) -> np.ndarray:
    """(len(i_sel), w * h): the flat index (i * ny + j) of every cell of each w x h block."""
    da, db = np.meshgrid(np.arange(w), np.arange(h), indexing="ij")
    return (i_sel[:, None] + da.ravel()[None, :]) * ny + (j_sel[:, None] + db.ravel()[None, :])


def _positions(recipe: dict[str, Any], data: dict[str, Any]) -> None:
    from shapely import wkt

    from app.solve import place_rule

    sets = data["sets"]
    step, origin = float(recipe["step"]), (float(recipe["origin"][0]), float(recipe["origin"][1]))
    shapes, zones = [], []
    for row in sets.get(recipe["areas"]) or []:
        try:
            shapes.append(wkt.loads(str(row.get(recipe["shape"]))))
        except Exception:  # noqa: BLE001
            raise Refused(f"the area {row['id']!r} has no polygon in {recipe['shape']!r}") from None
        zones.append(str(row.get("zone") or row["id"]))
    items_set, cells_set = recipe["items"], recipe["cells"]
    if not shapes:
        sets[items_set], sets[cells_set] = [], []
        for key in ("occupies", "keeps_free", "next_to"):
            if recipe.get(key):
                data["relationships"][recipe[key]] = []
        return
    zone = place_rule.raster(shapes, step, origin, f"generate {items_set}")
    nx, ny = zone.shape
    kinds, names, values = [], [], []
    for row in sets.get(recipe["kinds"]) or []:
        try:
            length, width = int(row[recipe["length"]]), int(row[recipe["width"]])
        except (KeyError, TypeError, ValueError):
            raise Refused(f"the kind {row['id']!r} has no whole number of cells in {recipe['length']!r} and "
                          f"{recipe['width']!r}") from None
        if length <= 0 or width <= 0:
            raise Refused(f"the kind {row['id']!r} has a size of no cells")
        turns = bool(row.get(recipe["can_turn"])) if recipe.get("can_turn") else False
        kinds.append((length, width, (0, 90) if turns and length != width else (0,)))
        names.append(str(row["id"]))
        values.append(float(row.get(recipe["value"], 1) if recipe.get("value") else 1))
    n_aisle = int(recipe.get("aisle", 0))
    found = candidates(zone, kinds, n_aisle, recipe.get("aisle_sides", "long"))
    total = sum(len(c[3]) for c in found)
    _cap(f"the positions {items_set}", total, limits.GENERATED_MEMBERS)
    links = sum(len(i) * w * h for _, _, _, i, _, w, h in found) + sum(
        len(i) * (w * n_aisle if side in ("bottom", "top") else n_aisle * h)
        for _, _, side, i, _, w, h in found if side is not None)
    _cap(f"the links of the positions {items_set}", links, limits.GENERATED_LINKS)

    item_rows: list[dict[str, Any]] = []
    occupies: list[dict[str, Any]] = []
    keeps_free: list[dict[str, Any]] = []
    used = np.zeros(nx * ny, dtype=bool)
    flat_zone = zone.ravel()
    for k, rot, side, i_sel, j_sel, w, h in found:
        if not len(i_sel):
            continue
        first = len(item_rows) + 1
        ids = [f"{names[k]}_{n}" for n in range(first, first + len(i_sel))]
        xs, ys = origin[0] + i_sel * step, origin[1] + j_sel * step
        zs = flat_zone[i_sel * ny + j_sel]
        for n, (key, x, y, z) in enumerate(zip(ids, xs.tolist(), ys.tolist(), zs.tolist())):
            item_rows.append({"id": key, "kind": names[k], "rot": rot, "aisle_side": side or "",
                              "x_m": round(x + w * step / 2, 4), "y_m": round(y + h * step / 2, 4),
                              "min_x_m": round(x, 4), "min_y_m": round(y, 4), "width_m": round(w * step, 4),
                              "height_m": round(h * step, 4), "zone": zones[int(z)], "value": values[k]})
        covered = _block_cells(i_sel, j_sel, w, h, ny)
        used[covered.ravel()] = True
        for key, row in zip(ids, covered.tolist()):
            occupies.extend({"from": key, "to": f"k{c}"} for c in row)
        if side is not None:
            si, sj, sw, sh = strip(i_sel, j_sel, w, h, side, n_aisle)
            aisle = _block_cells(si, sj, sw, sh, ny)
            used[aisle.ravel()] = True
            for key, row in zip(ids, aisle.tolist()):
                keeps_free.extend({"from": key, "to": f"k{c}"} for c in row)
    entrance = None
    if recipe.get("access"):
        features = []
        for row in sets.get(recipe["access"]) or []:
            try:
                features.append(wkt.loads(str(row.get(recipe["access_shape"]))))
            except Exception:  # noqa: BLE001
                raise Refused(f"the access feature {row['id']!r} has no shape in {recipe['access_shape']!r}") from None
        entrance = place_rule.entrances(zone, features, step, origin).ravel()
        used |= flat_zone >= 0  # every free cell may be part of a way
    cells = np.flatnonzero(used)
    cell_rows = []
    for c, z in zip(cells.tolist(), flat_zone[cells].tolist()):
        row = {"id": f"k{c}", "x_m": round(origin[0] + (c // ny + 0.5) * step, 4),
               "y_m": round(origin[1] + (c % ny + 0.5) * step, 4), "zone": zones[int(z)] if z >= 0 else ""}
        if entrance is not None:
            row["entrance"] = int(entrance[c])
        cell_rows.append(row)
    sets[items_set], sets[cells_set] = item_rows, cell_rows
    data["relationships"][recipe["occupies"]] = occupies
    if recipe.get("keeps_free"):
        data["relationships"][recipe["keeps_free"]] = keeps_free
    if recipe.get("next_to"):
        free = flat_zone >= 0
        pairs = []
        for d in (ny, 1):  # the next cell east, and north (within its column)
            a = np.arange(nx * ny - d)
            b = a + d
            keep = free[a] & free[b] & (flat_zone[a] == flat_zone[b])
            if d == 1:
                keep &= (b % ny) != 0
            pairs.append((a[keep], b[keep]))
        data["relationships"][recipe["next_to"]] = [
            {"from": f"k{a}", "to": f"k{b}"} for aa, bb in pairs for a, b in zip(aa.tolist(), bb.tolist())]


BUILDERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], None]] = {
    "range": _range, "product": _product, "positions": _positions}


def sizes(ir: dict[str, Any], data: dict[str, Any]) -> dict[str, int]:
    """How many members each generated set has on this data (built, so exact; for the quota's count)."""
    if not ir.get("generate"):
        return {}
    built = apply(ir, data)
    names, _ = declared(ir)
    return {name: len(built["sets"].get(name) or []) for name in names}


_RUNS: OrderedDict[int, dict[str, Any]] = OrderedDict()
_RUNS_LOCK = Lock()
#: Runs whose built data is kept for the readers (exports, maps, the Assistant's read-back): a run's model and
#: data never change, and building a large candidate list takes seconds.
RUNS_KEPT = 4


def for_run(run_id: int, ir: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """A run's frozen data with its recipes built, for reading its answer; kept for the last few runs read. Data
    that cannot be built (a limit lowered since) comes back as frozen: the answer still reads, without them."""
    if not (ir or {}).get("generate"):
        return data
    with _RUNS_LOCK:
        if run_id in _RUNS:
            _RUNS.move_to_end(run_id)
            return _RUNS[run_id]
    try:
        built = apply(ir, data)
    except Refused:
        return data
    with _RUNS_LOCK:
        _RUNS[run_id] = built
        while len(_RUNS) > RUNS_KEPT:
            _RUNS.popitem(last=False)
    return built
