"""Placing rectangular items in a drawing's free area without a list of candidate positions (plan of 8 October
2026, phases 1C and 1D).

A candidate list costs one record per position and one link per cell each covers: the camp at 0.5 m is 54,468
positions and 2.7 million links; at 0.05 m it would be some 460,000 positions and half a billion links. Here
the area is a grid of free cells (any step), and the answer is built and improved on it directly:

1. **Start, coarse to fine.** The same items on a coarser grid that divides their sizes (and the aisle rounded
   up to it), placed greedily in scan order. Every coarse placement is a placement on the fine grid too.
2. **Improve, area by area.** A window of the area is solved exactly by CP-SAT on the fine grid: the items
   wholly inside it may move, turn, change aisle side, or be added; everything else stays. Two-dimensional
   no-overlap holds items apart; each item's aisle may touch other aisles but no item. A window's answer
   replaces the old one only when it places more (or more value), so the answer never gets worse.
3. **A bound.** The free area over the smallest item's area plus half its aisle: no layout can place more.

Rules, as for the candidate form (app/agent/layout.py): an item covers whole free cells of one zone; its aisle
(when asked) is a strip of free cells along one of its allowed sides, covered by no item; aisles may be shared.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

SIDES = ("bottom", "top", "left", "right")


@dataclass(frozen=True)
class Variant:
    """One way to place an item: its kind, its footprint in cells (w along x, h along y), and its aisle side."""

    kind: int
    turn: int  # 0 or 90
    w: int
    h: int
    side: str | None
    value: float

    def aisle(self, n: int) -> tuple[int, int, int, int] | None:
        """The aisle strip relative to the item's lower-left cell: (di, dj, width, height), or None."""
        if self.side is None or n <= 0:
            return None
        return {"bottom": (0, -n, self.w, n), "top": (0, self.h, self.w, n),
                "left": (-n, 0, n, self.h), "right": (self.w, 0, n, self.h)}[self.side]


def variants(kinds: list[dict[str, Any]], step: float, aisle_side: str, n_aisle: int) -> list[Variant]:
    """The ways to place items of these kinds (sizes in metres) on a grid of this step."""
    return variants_cells([(round(k["length"] / step), round(k["width"] / step), k["rotations"],
                            float(k.get("value") or 1)) for k in kinds], aisle_side, n_aisle)


def variants_cells(kinds: list[tuple[int, int, list[int], float]], aisle_side: str, n_aisle: int) -> list[Variant]:
    """The same, from each kind's (length, width) in cells, its turns (0 and/or 90) and its value."""
    out = []
    for k, (length_c, width_c, turns, value) in enumerate(kinds):
        for turn in turns:
            w, h = (length_c, width_c) if turn == 0 else (width_c, length_c)
            if aisle_side == "none" or n_aisle <= 0:
                sides: list[str | None] = [None]
            else:
                horizontal = w >= h
                long_sides = ["bottom", "top"] if horizontal else ["left", "right"]
                short_sides = ["left", "right"] if horizontal else ["bottom", "top"]
                sides = {"long": long_sides, "short": short_sides, "any": long_sides + short_sides}[aisle_side]
            for side in sides:
                out.append(Variant(k, turn, w, h, side, float(value)))
    return out


def _window_sum(integral: np.ndarray, i0, j0, w, h, nx, ny):
    i1, j1 = i0 + w, j0 + h
    on = (i0 >= 0) & (j0 >= 0) & (i1 <= nx) & (j1 <= ny)
    a, b = np.clip(i0, 0, nx), np.clip(j0, 0, ny)
    c, d = np.clip(i1, 0, nx), np.clip(j1, 0, ny)
    return on, integral[c, d] - integral[a, d] - integral[c, b] + integral[a, b]


def static_fits(zone_of: np.ndarray, v: Variant, n_aisle: int) -> np.ndarray:
    """Where (lower-left cell) the variant fits the free area: footprint free and in one zone, aisle free."""
    nx, ny = zone_of.shape
    free = zone_of >= 0
    integral = np.zeros((nx + 1, ny + 1), dtype=np.int64)
    integral[1:, 1:] = free.astype(np.int64).cumsum(0).cumsum(1)
    ii, jj = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    on, total = _window_sum(integral, ii, jj, v.w, v.h, nx, ny)
    fits = on & (total == v.w * v.h)
    far = zone_of[np.clip(ii + v.w - 1, 0, nx - 1), np.clip(jj + v.h - 1, 0, ny - 1)]
    fits &= zone_of == far
    strip = v.aisle(n_aisle)
    if strip is not None:
        di, dj, sw, sh = strip
        on, total = _window_sum(integral, ii + di, jj + dj, sw, sh, nx, ny)
        fits &= on & (total == sw * sh)
    return fits


@dataclass
class Layout:
    """Items placed on the grid: who covers each cell, and how many aisles pass over it."""

    zone_of: np.ndarray
    vs: list[Variant]
    n_aisle: int
    owner: np.ndarray = field(init=False)
    aisles: np.ndarray = field(init=False)
    items: dict[int, tuple[int, int, int]] = field(default_factory=dict)  # id -> (variant, i, j)
    #: At most this many items of each kind (its slots); none: no limit.
    limits: dict[int, int] | None = None
    #: Free cells at an access feature: every item's aisle must join one through cells no item covers.
    entrance: np.ndarray | None = None
    _next: int = 0

    def __post_init__(self):
        self.free = self.zone_of >= 0
        self.owner = np.full(self.zone_of.shape, -1, dtype=np.int32)
        self.aisles = np.zeros(self.zone_of.shape, dtype=np.int16)
        self.counts: dict[int, int] = {}

    def _slices(self, v: int, i: int, j: int):
        var = self.vs[v]
        foot = (slice(i, i + var.w), slice(j, j + var.h))
        strip = var.aisle(self.n_aisle)
        aisle = None if strip is None else (slice(i + strip[0], i + strip[0] + strip[2]),
                                            slice(j + strip[1], j + strip[1] + strip[3]))
        return foot, aisle

    def can(self, v: int, i: int, j: int) -> bool:
        if self.limits is not None and self.counts.get(self.vs[v].kind, 0) >= self.limits.get(self.vs[v].kind, 0):
            return False
        foot, aisle = self._slices(v, i, j)
        if (self.owner[foot] >= 0).any() or (self.aisles[foot] > 0).any():
            return False
        return aisle is None or not (self.owner[aisle] >= 0).any()

    def place(self, v: int, i: int, j: int) -> int:
        foot, aisle = self._slices(v, i, j)
        ident = self._next
        self._next += 1
        self.owner[foot] = ident
        if aisle is not None:
            self.aisles[aisle] += 1
        self.items[ident] = (v, i, j)
        self.counts[self.vs[v].kind] = self.counts.get(self.vs[v].kind, 0) + 1
        return ident

    def remove(self, ident: int) -> None:
        v, i, j = self.items.pop(ident)
        self.counts[self.vs[v].kind] -= 1
        foot, aisle = self._slices(v, i, j)
        self.owner[foot] = -1
        if aisle is not None:
            self.aisles[aisle] -= 1

    def value(self) -> float:
        return sum(self.vs[v].value for v, _, _ in self.items.values())

    def check(self) -> list[str]:
        """Every rule, from scratch: what is wrong, or nothing."""
        problems = []
        cover = np.zeros(self.zone_of.shape, dtype=np.int32)
        for ident, (v, i, j) in self.items.items():
            var = self.vs[v]
            foot, aisle = self._slices(v, i, j)
            if i < 0 or j < 0 or i + var.w > self.zone_of.shape[0] or j + var.h > self.zone_of.shape[1]:
                problems.append(f"item {ident} is off the grid")
                continue
            zones = np.unique(self.zone_of[foot])
            if (zones < 0).any() or len(zones) != 1:
                problems.append(f"item {ident} is not wholly in one free zone")
            cover[foot] += 1
        if (cover > 1).any():
            problems.append(f"{int((cover > 1).sum())} cells are covered twice")
        for ident, (v, i, j) in self.items.items():
            _, aisle = self._slices(v, i, j)
            if aisle is None:
                continue
            si, sj = aisle
            if si.start < 0 or sj.start < 0 or si.stop > cover.shape[0] or sj.stop > cover.shape[1]:
                problems.append(f"item {ident}'s aisle is off the grid")
            elif not self.free[aisle].all() or (cover[aisle] > 0).any():
                problems.append(f"item {ident}'s aisle is not free")
        if self.entrance is not None and not problems:
            lost = unreachable_items(self)
            if lost:
                problems.append(f"{len(lost)} items cannot be reached from an entrance (e.g. item {lost[0]})")
        return problems


def _zone_box(lay: Layout, z: int) -> tuple[int, int, int, int]:
    """The bounding box of an area's cells, worked out once per layout."""
    boxes = lay.__dict__.setdefault("_boxes", {})
    if z not in boxes:
        ii, jj = np.nonzero(lay.zone_of == z)
        boxes[z] = (int(ii.min()), int(ii.max()) + 1, int(jj.min()), int(jj.max()) + 1)
    return boxes[z]


def reachable(lay: Layout, zones: set[int] | None = None) -> np.ndarray:
    """The cells a way reaches from an entrance: free cells no item covers (aisles are way), joined side to side
    within one area, from the entrance cells. Everything is reachable when there is no access rule."""
    from scipy import ndimage

    if lay.entrance is None:
        return lay.free.copy()
    way = lay.free & (lay.owner < 0)
    out = np.zeros(way.shape, dtype=bool)
    for z in np.unique(lay.zone_of[lay.entrance]):
        if z < 0 or (zones is not None and int(z) not in zones):
            continue
        i0, i1, j0, j1 = _zone_box(lay, int(z))
        sub = way[i0:i1, j0:j1] & (lay.zone_of[i0:i1, j0:j1] == z)
        labels, _ = ndimage.label(sub)
        doors = np.unique(labels[lay.entrance[i0:i1, j0:j1] & sub])
        doors = doors[doors > 0]
        if len(doors):
            out[i0:i1, j0:j1] |= np.isin(labels, doors)
    return out


def unreachable_items(lay: Layout, reach: np.ndarray | None = None, zones: set[int] | None = None) -> list[int]:
    """The items whose aisle (or, with no aisle, the cells beside them) no way from an entrance reaches; only
    those in `zones` when given (a change in one area cannot cut off an item in another)."""
    if lay.entrance is None:
        return []
    reach = reachable(lay, zones) if reach is None else reach
    nx, ny = reach.shape
    out = []
    for ident, (v, i, j) in lay.items.items():
        if zones is not None and int(lay.zone_of[i, j]) not in zones:
            continue
        var = lay.vs[v]
        strip = var.aisle(lay.n_aisle)
        if strip is not None:
            si, sj = i + strip[0], j + strip[1]
            ok = reach[max(0, si):si + strip[2], max(0, sj):sj + strip[3]].any()
        else:
            ok = any(reach[max(0, a0):a1, max(0, b0):b1].any() for a0, a1, b0, b1 in
                     ((i - 1, i, j, j + var.h), (i + var.w, i + var.w + 1, j, j + var.h),
                      (i, i + var.w, j - 1, j), (i, i + var.w, j + var.h, j + var.h + 1)))
        if not ok:
            out.append(ident)
    return out


def make_reachable(lay: Layout) -> int:
    """Take away every item no way reaches (taking items away never cuts another off); how many."""
    lost = unreachable_items(lay)
    for ident in lost:
        lay.remove(ident)
    return len(lost)


def _block_free(zone_of: np.ndarray, c: int) -> np.ndarray:
    """The zones on a grid c times coarser: a coarse cell is free (in a zone) when all its fine cells are."""
    nx, ny = zone_of.shape
    cx, cy = nx // c, ny // c
    blocks = zone_of[:cx * c, :cy * c].reshape(cx, c, cy, c)
    first = blocks[:, 0, :, 0]
    same = (blocks == first[:, None, :, None]).all(axis=(1, 3)) & (first >= 0)
    return np.where(same, first, -1)


def coarse_factor(vs: list[Variant], n_aisle: int, cells: int, target: int = 400_000) -> int:
    """The largest useful coarsening: a factor dividing every item size (cells), with the coarse grid still
    fine enough (the camp: 0.05 m -> 0.5 m)."""
    sizes = [x for v in vs for x in (v.w, v.h)]
    best = 1
    for c in range(1, min(sizes) + 1):
        if all(x % c == 0 for x in sizes):
            best = c
            if cells / (c * c) <= target:
                return c
    return best


def greedy(lay: Layout, order: list[tuple[int, int, int]], deadline: float) -> int:
    placed = 0
    owner, aisles = lay.owner, lay.aisles
    dims = [(v.w - 1, v.h - 1) for v in lay.vs]
    for n, (v, i, j) in enumerate(order):
        if not n % 4096 and time.monotonic() > deadline:
            break
        # Most positions are taken by then: their corner cells say so at once.
        dw, dh = dims[v]
        if (owner[i, j] >= 0 or aisles[i, j] or owner[i + dw, j] >= 0 or owner[i, j + dh] >= 0
                or owner[i + dw, j + dh] >= 0 or aisles[i + dw, j + dh]):
            continue
        if lay.can(v, i, j):
            lay.place(v, i, j)
            placed += 1
    return placed


def _greedy_at(zone_of: np.ndarray, vs: list[Variant], n_aisle: int, c: int, deadline: float,
               limits: dict[int, int] | None, scan: str = "rows") -> tuple[Layout, int]:
    """Greedy in scan order over the positions of a grid c times coarser (each a fine-grid position)."""
    lay = Layout(zone_of, vs, n_aisle, limits=limits)
    coarse = _block_free(zone_of, c) if c > 1 else zone_of
    n_coarse = math.ceil(n_aisle / c) if n_aisle else 0
    parts = []
    for k, v in enumerate(vs):
        cv = Variant(v.kind, v.turn, v.w // c, v.h // c, v.side, v.value)
        ci, cj = np.nonzero(static_fits(coarse, cv, n_coarse))
        strip = v.aisle(n_aisle)
        cost = v.w * v.h + (strip[2] * strip[3] if strip else 0)
        parts.append((ci.astype(np.int64) * c, cj.astype(np.int64) * c, np.full(len(ci), -v.value),
                      np.full(len(ci), cost), np.full(len(ci), k)))
    ii = np.concatenate([p[0] for p in parts]) if parts else np.zeros(0, dtype=np.int64)
    jj = np.concatenate([p[1] for p in parts]) if parts else np.zeros(0, dtype=np.int64)
    val = np.concatenate([p[2] for p in parts]) if parts else np.zeros(0)
    cost = np.concatenate([p[3] for p in parts]) if parts else np.zeros(0)
    kk = np.concatenate([p[4] for p in parts]) if parts else np.zeros(0, dtype=np.int64)
    # Bottom to top, left to right (rows) or left to right, bottom to top (cols); at each position the most
    # valuable variant using the least area first (a short-side aisle before a long one), so rows pack tightly.
    major, minor = (jj, ii) if scan.startswith("rows") else (ii, jj)
    if scan.endswith("-back"):  # from the far side: top to bottom, or right to left
        major, minor = -major, -minor
    order = np.lexsort((kk, cost, val, minor, major))
    plan = list(zip(kk[order].tolist(), ii[order].tolist(), jj[order].tolist()))
    greedy(lay, plan, deadline)
    return lay, len(plan)


#: Positions a greedy pass tries per second (the camp at 0.05 m: 5.5 million in 38 s).
TRIES_PER_SECOND = 1_000_000


def start(zone_of: np.ndarray, vs: list[Variant], n_aisle: int, *, seconds: float,
          limits: dict[int, int] | None = None) -> tuple[Layout, dict[str, Any]]:
    """A first layout: greedy passes from the coarsest exact grid to the finest the time allows, the best kept
    (the camp, 0.05 m grid: 2,158 beds at 0.5 m, 2,220 at 0.25 m, 2,316 at 0.1 m, 2,386 at 0.05 m)."""
    began = time.monotonic()
    nx, ny = zone_of.shape
    sizes = [x for v in vs for x in (v.w, v.h)]
    factors = sorted((c for c in range(1, min(sizes) + 1) if all(x % c == 0 for x in sizes)), reverse=True)
    # From about 0.5 m-equivalent cells (a few tens of thousands of positions) to the grid itself.
    # From the coarsest (fast, a sure first answer) to the grid itself, as long as the time allows.
    best, record = None, []
    for c in factors:
        left = seconds - (time.monotonic() - began)
        estimate = (nx // c) * (ny // c) * len(vs) * 0.35 / TRIES_PER_SECOND
        if best is not None and estimate > left:
            record.append({"factor": c, "skipped": f"about {estimate:.0f} s, {left:.0f} s left"})
            continue
        lay, tried = _greedy_at(zone_of, vs, n_aisle, c, time.monotonic() + max(left, 1.0), limits)
        record.append({"factor": c, "placed": len(lay.items), "tried": tried})
        if best is None or lay.value() > best.value():
            best = lay
    # The finest grid passed, scanned in the other directions too: rows pack differently against each area's
    # walls, and the best is kept.
    done = [r for r in record if "placed" in r]
    if done:
        c = done[-1]["factor"]
        for scan in ("cols",):
            left = seconds - (time.monotonic() - began)
            estimate = (nx // c) * (ny // c) * len(vs) * 0.35 / TRIES_PER_SECOND * 1.5
            if estimate > left:
                break
            lay, tried = _greedy_at(zone_of, vs, n_aisle, c, time.monotonic() + left, limits, scan)
            record.append({"factor": c, "scan": scan, "placed": len(lay.items)})
            if lay.value() > best.value():
                best = lay
    return best, {"passes": record, "seconds": round(time.monotonic() - began, 3)}


def _rectangles(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """A cover of the True cells by rectangles (i, j, w, h): runs along y merged across equal neighbours."""
    nx, ny = mask.shape
    out = []
    open_runs: dict[tuple[int, int], list[int]] = {}
    for i in range(nx + 1):
        runs = set()
        if i < nx:
            col = mask[i]
            j = 0
            while j < ny:
                if col[j]:
                    k = j
                    while k < ny and col[k]:
                        k += 1
                    runs.add((j, k))
                    j = k
                else:
                    j += 1
        for run in list(open_runs):
            if run not in runs:
                i0 = open_runs.pop(run)[0]
                out.append((i0, run[0], i - i0, run[1] - run[0]))
        for run in runs:
            if run not in open_runs:
                open_runs[run] = [i]
    return out


def improve_window(lay: Layout, wi: int, wj: int, size_i: int, size_j: int, *, seconds: float, workers: int,
                   extra: int = 3, seed: int = 0) -> int:
    """Solve one window exactly; apply it when it places more value. Returns the value gained (0 if none)."""
    from ortools.sat.python import cp_model

    nx, ny = lay.zone_of.shape
    i0, j0 = max(0, wi), max(0, wj)
    i1, j1 = min(nx, wi + size_i), min(ny, wj + size_j)
    if i1 - i0 < 2 or j1 - j0 < 2:
        return 0
    n = lay.n_aisle

    def inside(v, i, j):
        var = lay.vs[v]
        lo_i, lo_j, hi_i, hi_j = i, j, i + var.w, j + var.h
        strip = var.aisle(n)
        if strip is not None:
            lo_i, lo_j = min(lo_i, i + strip[0]), min(lo_j, j + strip[1])
            hi_i, hi_j = max(hi_i, i + strip[0] + strip[2]), max(hi_j, j + strip[1] + strip[3])
        return lo_i >= i0 and lo_j >= j0 and hi_i <= i1 and hi_j <= j1

    movable = [ident for ident, (v, i, j) in lay.items.items() if inside(v, i, j)]
    before = sum(lay.vs[lay.items[x][0]].value for x in movable)
    old = {x: lay.items[x] for x in movable}
    for x in movable:
        lay.remove(x)
    W, H = i1 - i0, j1 - j0
    free = lay.free[i0:i1, j0:j1]
    zone = lay.zone_of[i0:i1, j0:j1]
    taken = lay.owner[i0:i1, j0:j1] >= 0
    aisled = lay.aisles[i0:i1, j0:j1] > 0
    bed_blocked = _rectangles(~free | taken | aisled)
    aisle_blocked = _rectangles(~free | taken)

    m = cp_model.CpModel()
    slots = len(movable) + extra
    zones_here = sorted({int(z) for z in np.unique(zone) if z >= 0})
    beds: list[list[tuple[Any, Any, Any, Any]]] = []  # per slot: (presence, x box, y box, variant index)
    aisles_of: list[list[tuple[Any, Any]]] = []
    present = []
    pos = []
    for s in range(slots):
        row, arow, uses = [], [], []
        for k, var in enumerate(lay.vs):
            strip = var.aisle(n)
            lo_i = -strip[0] if strip and strip[0] < 0 else 0
            lo_j = -strip[1] if strip and strip[1] < 0 else 0
            hi_i = W - max(var.w, (strip[0] + strip[2]) if strip else var.w)
            hi_j = H - max(var.h, (strip[1] + strip[3]) if strip else var.h)
            if hi_i < lo_i or hi_j < lo_j:
                continue
            b = m.NewBoolVar("")
            x = m.NewIntVar(lo_i, hi_i, "")
            y = m.NewIntVar(lo_j, hi_j, "")
            xb = m.NewOptionalFixedSizeIntervalVar(x, var.w, b, "")
            yb = m.NewOptionalFixedSizeIntervalVar(y, var.h, b, "")
            row.append((b, xb, yb, k, x, y))
            if strip:
                xa = m.NewOptionalIntervalVar(x + strip[0], strip[2], x + strip[0] + strip[2], b, "")
                ya = m.NewOptionalIntervalVar(y + strip[1], strip[3], y + strip[1] + strip[3], b, "")
                arow.append((xa, ya))
            uses.append(b)
            if len(zones_here) > 1:
                # One zone per item: its two far corners in the same zone (as the candidate form checks).
                pass
        if not uses:
            return _restore(lay, old)
        p = m.NewBoolVar("")
        m.Add(sum(uses) == p)
        present.append(p)
        beds.append(row)
        aisles_of.append(arow)
        pos.append(row)
    fixed_x = [m.NewFixedSizeIntervalVar(i, w, "") for i, j, w, h in bed_blocked]
    fixed_y = [m.NewFixedSizeIntervalVar(j, h, "") for i, j, w, h in bed_blocked]
    all_x = [b[1] for row in beds for b in row]
    all_y = [b[2] for row in beds for b in row]
    m.AddNoOverlap2D(all_x + fixed_x, all_y + fixed_y)
    afx = [m.NewFixedSizeIntervalVar(i, w, "") for i, j, w, h in aisle_blocked]
    afy = [m.NewFixedSizeIntervalVar(j, h, "") for i, j, w, h in aisle_blocked]
    for s in range(slots):
        if not aisles_of[s]:
            continue
        others_x = [b[1] for t, row in enumerate(beds) if t != s for b in row]
        others_y = [b[2] for t, row in enumerate(beds) if t != s for b in row]
        m.AddNoOverlap2D([a[0] for a in aisles_of[s]] + others_x + afx, [a[1] for a in aisles_of[s]] + others_y + afy)
    # Zones: an item lies in one zone. Cells of other zones are free but not to be straddled; a window rarely
    # holds two zones, and then each item's footprint must avoid the boundary: forbid footprints that mix.
    if len(zones_here) > 1:
        for s in range(slots):
            for (b, xb, yb, k, x, y) in beds[s]:
                var = lay.vs[k]
                ok_pos = []
                for zi in zones_here:
                    fits = (zone == zi)
                    integral = np.zeros((W + 1, H + 1), dtype=np.int64)
                    integral[1:, 1:] = fits.astype(np.int64).cumsum(0).cumsum(1)
                    ii, jj = np.meshgrid(np.arange(W), np.arange(H), indexing="ij")
                    on, total = _window_sum(integral, ii, jj, var.w, var.h, W, H)
                    good = on & (total == var.w * var.h)
                    ok_pos.extend((int(a), int(c)) for a, c in zip(*np.nonzero(good)))
                if not ok_pos:
                    m.Add(b == 0)
                else:
                    m.AddAllowedAssignments([x, y], ok_pos).OnlyEnforceIf(b)
    for s in range(slots - 1):
        m.AddImplication(present[s + 1], present[s])
    if lay.limits is not None:
        for kind, most in lay.limits.items():
            m.Add(sum(b for row in beds for (b, _, _, k, _, _) in row if lay.vs[k].kind == kind)
                  <= max(0, most - lay.counts.get(kind, 0)))
    m.Maximize(sum(lay.vs[k].value * b for row in beds for (b, _, _, k, _, _) in row))
    for s, ident in enumerate(movable):
        v, i, j = old[ident]
        for (b, _, _, k, x, y) in beds[s]:
            m.AddHint(b, 1 if k == v else 0)
            if k == v:
                m.AddHint(x, i - i0)
                m.AddHint(y, j - j0)
    for s in range(len(movable), slots):
        for (b, *_rest) in beds[s]:
            m.AddHint(b, 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.2, seconds)
    solver.parameters.num_workers = max(1, workers)
    solver.parameters.random_seed = seed
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE) or solver.ObjectiveValue() <= before + 1e-9:
        return _restore(lay, old)
    new = [(k, i0 + solver.Value(x), j0 + solver.Value(y))
           for row in beds for (b, _, _, k, x, y) in row if solver.Value(b)]
    for v, i, j in new:
        if not lay.can(v, i, j):  # never trust a window blindly: the global state decides
            for x in [x for x, item in lay.items.items() if item in new]:
                lay.remove(x)
            return _restore(lay, old)
        lay.place(v, i, j)
    return int(round(solver.ObjectiveValue() - before))


def _restore(lay: Layout, old: dict[int, tuple[int, int, int]]) -> int:
    for v, i, j in old.values():
        lay.place(v, i, j)
    return 0


#: Windows in a row that found nothing better, after which improving stops.
IDLE_WINDOWS = 25


def improve(lay: Layout, *, seconds: float, workers: int, window: int, seed: int = 0,
            should_stop: Callable[[], bool] = lambda: False, per_window: float = 1.5) -> dict[str, Any]:
    """Windows over the free area, in random order, until the time is up; each one solved exactly."""
    rng = random.Random(seed)
    began = time.monotonic()
    nx, ny = lay.zone_of.shape
    free_i, free_j = np.nonzero(lay.free)
    tried = gained = improved = idle = 0
    # Windows until the time is up, or until many in a row found nothing better (then the answer is final).
    while time.monotonic() - began < seconds and not should_stop() and len(free_i) and idle < IDLE_WINDOWS:
        k = rng.randrange(len(free_i))
        wi, wj = int(free_i[k]) - window // 2, int(free_j[k]) - window // 2
        left = seconds - (time.monotonic() - began)
        g = improve_window(lay, wi, wj, window, window, seconds=min(per_window, max(0.2, left)), workers=workers,
                           seed=rng.randrange(1 << 30))
        tried += 1
        if g > 0:
            gained += g
            improved += 1
            idle = 0
        else:
            idle += 1
    return {"windows": tried, "improved": improved, "gained": gained, "seconds": round(time.monotonic() - began, 2),
            "stopped": "time" if time.monotonic() - began >= seconds else "no better window" if idle >= IDLE_WINDOWS
            else "asked"}


#: The scan orders a refill may use; each packs differently against walls and neighbours.
SCANS = ("rows", "cols", "rows-back", "cols-back")


def _region_plan(lay: Layout, fits: list[np.ndarray], i0: int, j0: int, i1: int, j1: int, scan: str,
                 priority: list[int]) -> list[tuple[int, int, int]]:
    """The positions (lower-left corner in the region) of every variant that fits the free area, in scan order,
    the variants at one position in the given priority."""
    parts = []
    # Positions whose footprint (and aisle) is free of items right now: most of a region is still full after the
    # ruin, so this leaves the cleared part (each is checked again as the fill goes on).
    W, H = i1 - i0, j1 - j0
    pad = max(max(v.w, v.h) for v in lay.vs) + lay.n_aisle + 1
    a0, b0 = max(0, i0 - pad), max(0, j0 - pad)
    a1, b1 = min(lay.owner.shape[0], i1 + pad), min(lay.owner.shape[1], j1 + pad)
    taken = lay.owner[a0:a1, b0:b1] >= 0
    blocked = taken | (lay.aisles[a0:a1, b0:b1] > 0)
    ia = np.zeros((a1 - a0 + 1, b1 - b0 + 1), dtype=np.int32)
    ia[1:, 1:] = blocked.astype(np.int32).cumsum(0).cumsum(1)
    it = np.zeros_like(ia)
    it[1:, 1:] = taken.astype(np.int32).cumsum(0).cumsum(1)
    for rank, k in enumerate(priority):
        ci, cj = np.nonzero(fits[k][i0:i1, j0:j1])
        if not len(ci):
            continue
        var = lay.vs[k]
        li, lj = ci + (i0 - a0), cj + (j0 - b0)
        on, total = _window_sum(ia, li, lj, var.w, var.h, a1 - a0, b1 - b0)
        keep = on & (total == 0)
        strip = var.aisle(lay.n_aisle)
        if strip is not None:
            on2, total2 = _window_sum(it, li + strip[0], lj + strip[1], strip[2], strip[3], a1 - a0, b1 - b0)
            keep &= on2 & (total2 == 0)
        ci, cj = ci[keep], cj[keep]
        if len(ci):
            parts.append((ci + i0, cj + j0, np.full(len(ci), rank), np.full(len(ci), k)))
    if not parts:
        return []
    ii = np.concatenate([p[0] for p in parts])
    jj = np.concatenate([p[1] for p in parts])
    rank = np.concatenate([p[2] for p in parts])
    kk = np.concatenate([p[3] for p in parts])
    major, minor = (jj, ii) if scan.startswith("rows") else (ii, jj)
    if scan.endswith("-back"):
        major, minor = -major, -minor
    order = np.lexsort((rank, minor, major))
    return list(zip(kk[order].tolist(), ii[order].tolist(), jj[order].tolist()))


def _fill(lay: Layout, plan: list[tuple[int, int, int]]) -> list[int]:
    """Place greedily along the plan; the items placed. Unlike `greedy`, the corner check looks at the whole
    footprint's first cell only when the scan runs forwards (a backward scan meets items by their far side)."""
    placed = []
    owner, aisles = lay.owner, lay.aisles
    dims = [(v.w - 1, v.h - 1) for v in lay.vs]
    for v, i, j in plan:
        dw, dh = dims[v]
        # The four corners first (a few lookups); the full footprint and aisle only when they are clear.
        if (owner[i, j] >= 0 or aisles[i, j] or owner[i + dw, j] >= 0 or owner[i, j + dh] >= 0
                or owner[i + dw, j + dh] >= 0 or aisles[i + dw, j + dh]):
            continue
        if lay.can(v, i, j):
            placed.append(lay.place(v, i, j))
    return placed


def ruin_recreate(lay: Layout, fits: list[np.ndarray], *, seconds: float, seed: int = 0,
                  should_stop: Callable[[], bool] = lambda: False,
                  valid: Callable[[Layout, set[int]], bool] | None = None) -> dict[str, Any]:
    """Improve by ruin and recreate: clear a region (a square of a few item lengths, or a band across the whole
    area), then refill it greedily in a random scan order and variant priority. A refill that places more is
    kept; one that places as much is kept half the time (to move on from a plateau); one that places less, or
    breaks `valid` (access to an entrance), is undone. The best layout seen is the one returned. General: it
    knows nothing of beds or camps, only items, the free area and the aisle rule."""
    rng = random.Random(seed)
    began = time.monotonic()
    nx, ny = lay.zone_of.shape
    big = max(max(v.w, v.h) + 2 * lay.n_aisle for v in lay.vs)
    free_i, free_j = np.nonzero(lay.free)
    best_items, best_value = dict(lay.items), lay.value()
    moves = kept = better = 0
    values = sorted({v.value for v in lay.vs}, reverse=True)
    while time.monotonic() - began < seconds and not should_stop() and len(free_i):
        moves += 1
        k = rng.randrange(len(free_i))
        ci, cj = int(free_i[k]), int(free_j[k])
        shape = rng.random()
        if shape < 0.6:  # a square of 1.5 to 4 item lengths
            half = int(big * rng.choice((0.75, 1.0, 1.5, 2.0)))
            i0, i1, j0, j1 = ci - half, ci + half, cj - half, cj + half
        elif shape < 0.8:  # a band across the area, one to three item lengths high
            band, length = int(big * rng.choice((1.0, 1.5, 2.0, 3.0))), int(big * rng.choice((4, 8, 16)))
            i0, i1, j0, j1 = ci - length // 2, ci + length // 2, cj - band // 2, cj + band // 2
        else:  # the same, upright (a band of 4 to 16 item lengths)
            band, length = int(big * rng.choice((1.0, 1.5, 2.0, 3.0))), int(big * rng.choice((4, 8, 16)))
            i0, i1, j0, j1 = ci - band // 2, ci + band // 2, cj - length // 2, cj + length // 2
        i0, j0, i1, j1 = max(0, i0), max(0, j0), min(nx, i1), min(ny, j1)
        hit = np.unique(lay.owner[i0:i1, j0:j1])
        removed = {int(x): lay.items[int(x)] for x in hit if x >= 0}
        before = sum(lay.vs[v].value for v, _, _ in removed.values())
        for ident in removed:
            lay.remove(ident)
        # The region grows to the removed items' extent, so each can come back where it was.
        for v, i, j in removed.values():
            var = lay.vs[v]
            i0, j0 = min(i0, max(0, i - lay.n_aisle)), min(j0, max(0, j - lay.n_aisle))
            i1, j1 = max(i1, min(nx, i + var.w + lay.n_aisle)), max(j1, min(ny, j + var.h + lay.n_aisle))
        priority = []
        for value in values:  # the more valuable first; among equals, a random order
            same = [k for k, v in enumerate(lay.vs) if v.value == value]
            rng.shuffle(same)
            priority += same
        placed = _fill(lay, _region_plan(lay, fits, i0, j0, i1, j1, rng.choice(SCANS), priority))
        after = sum(lay.vs[lay.items[x][0]].value for x in placed)
        ok = after > before or (after == before and rng.random() < 0.5)
        if ok and valid is not None:
            touched = {int(z) for z in np.unique(lay.zone_of[i0:i1, j0:j1]) if z >= 0}
            ok = valid(lay, touched)
        if not ok:
            for ident in placed:
                lay.remove(ident)
            for v, i, j in removed.values():
                lay.place(v, i, j)
            continue
        kept += 1
        if lay.value() > best_value + 1e-9:
            better += 1
            best_items, best_value = dict(lay.items), lay.value()
    if lay.value() < best_value - 1e-9:
        for ident in list(lay.items):
            lay.remove(ident)
        for v, i, j in best_items.values():
            lay.place(v, i, j)
    return {"moves": moves, "kept": kept, "better": better, "seconds": round(time.monotonic() - began, 2)}


def area_bound(free_cells: int, vs: list[Variant], n_aisle: int, aisle_side: str) -> int:
    """No layout places more: the free cells over the smallest item's cells plus half its aisle."""
    smallest = min(vs, key=lambda v: v.w * v.h)
    side = 0
    if aisle_side != "none" and n_aisle:
        long_ = max(smallest.w, smallest.h)
        short = min(smallest.w, smallest.h)
        side = {"long": long_, "short": short, "any": short}[aisle_side]
    return int(free_cells // (smallest.w * smallest.h + side * n_aisle / 2))


def solve(compiled: Any, *, time_limit: float, workers: int, should_stop: Callable[[], bool] | None = None,
          seed: int | None = None, gap_rel: float = 0.0, on_progress: Any = None) -> Any:
    """The `layout` backend: a model whose rules are one place rule and whose goal rewards chosen slots."""
    from app.solve.compile import Unsupported
    from app.solve.place_rule import SIDE_NAMES
    from app.solve.result import Solution

    began = time.monotonic()
    stop = should_stop or (lambda: False)
    if len(compiled.placements) != 1 or any(c.schedule is None or c.schedule.kind != "place"
                                            for c in compiled.constraints):
        raise Unsupported("the placement solver takes one place rule and no other rule")
    place = compiled.placements[0]
    if compiled.sense != "maximize" or compiled.objective_quadratic or compiled.objective_mode == "lex":
        raise Unsupported("the placement solver maximizes a sum over the chosen slots")
    chosen_keys = {s.chosen for s in place.slots}
    if any(k not in chosen_keys for k in compiled.objective.coeffs):
        raise Unsupported("the placement solver's goal reads only whether each slot is chosen")
    # Kinds: slots of the same size, turning and value are interchangeable.
    kinds: dict[tuple, list] = {}
    for s in place.slots:
        value = float(compiled.objective.coeffs.get(s.chosen, 0))
        kinds.setdefault((s.length, s.width, s.can_turn, value), []).append(s)
    kind_list = list(kinds)
    vs = variants_cells([(length, width, [0, 90] if turn else [0], value)
                         for (length, width, turn, value) in kind_list], place.aisle_sides, place.aisle)
    vs = [v for v in vs if v.value > 0]
    limits = {k: len(kinds[key]) for k, key in enumerate(kind_list)}
    zone = place.zone_grid
    free_cells = int((zone >= 0).sum())
    lay, started = start(zone, vs, place.aisle, seconds=0.5 * time_limit, limits=limits) if vs else (
        Layout(zone, vs, place.aisle, limits=limits), {"passes": []})
    if place.entrance is not None:
        # Access: the greedy start packs without it; every item no way reaches is taken away, and ruin and
        # recreate refills only with layouts where every item is still reached.
        lay.entrance = place.entrance
        started["unreachable_removed"] = make_reachable(lay)
    if on_progress is not None:
        try:
            on_progress("incumbent", {"t": time.monotonic() - began, "objective": lay.value(), "bound": None})
        except Exception:  # noqa: BLE001 -- progress is a courtesy
            pass
    left = time_limit - (time.monotonic() - began)
    improved: dict[str, Any] = {}
    if vs and left > 2 and not stop():
        # Ruin and recreate for most of the time left, then small windows solved exactly by CP-SAT.
        fits = [static_fits(zone, v, place.aisle) for v in vs]
        valid = ((lambda candidate, zones: not unreachable_items(candidate, zones=zones))
                 if place.entrance is not None else None)
        improved["ruin_recreate"] = ruin_recreate(lay, fits, seconds=(1.0 if valid else 0.8) * (left - 1),
                                                  seed=seed or 0, should_stop=stop, valid=valid)
        left = time_limit - (time.monotonic() - began)
        if left > 2 and not stop() and valid is None:  # the exact windows hold no access rule
            window = 4 * max(max(v.w, v.h) + place.aisle for v in vs)
            improved["windows"] = improve(lay, seconds=left - 1, workers=workers, window=window, seed=seed or 0,
                                          should_stop=stop)
    problems = lay.check()
    if problems:  # pragma: no cover -- the layout is built under the same rules; never report a broken one
        raise Unsupported("the placement broke its own rules: " + "; ".join(problems[:3]))
    assignments: dict = {}
    free_slots = {k: list(kinds[key]) for k, key in enumerate(kind_list)}
    for ident, (v, i, j) in sorted(lay.items.items(), key=lambda kv: (kv[1][2], kv[1][1])):
        var = vs[v]
        slot = free_slots[var.kind].pop(0)
        assignments[slot.chosen] = 1
        assignments[slot.x], assignments[slot.y] = int(i), int(j)
        if slot.turn is not None:
            assignments[slot.turn] = 1 if var.turn == 90 else 0
        if slot.side is not None:
            assignments[slot.side] = SIDE_NAMES.index(var.side) if var.side else 0
    for rest in free_slots.values():
        for slot in rest:
            for k in (slot.chosen, slot.x, slot.y, slot.turn, slot.side):
                if k is not None:
                    assignments[k] = 0
    for key in compiled.variables:
        assignments.setdefault(key, 0)
    smallest = min(vs, key=lambda v: v.w * v.h) if vs else None
    count_bound = area_bound(free_cells, vs, place.aisle, place.aisle_sides) if vs else 0
    total_slots = len(place.slots)
    best_value = max((v.value for v in vs), default=0.0)
    # No layout places more than the area allows, nor more than there are slots of each kind.
    bound = min(count_bound * best_value, sum(len(kinds[key]) * key[3] for key in kind_list))
    objective = lay.value() + float(compiled.objective.const)
    bound += float(compiled.objective.const)
    proven = objective >= bound - 1e-9
    solution = Solution("optimal" if proven else "feasible", proven, int(objective) if objective == int(objective)
                        else objective, assignments, round(time.monotonic() - began, 3), "layout",
                        best_bound=bound)
    solution.execution = {"placement": {"start": started, "improve": improved, "placed": len(lay.items),
                                    "slots": total_slots, "free_cells": free_cells, "area_bound": count_bound,
                                    "smallest": [smallest.w, smallest.h] if smallest else None}}
    return solution


def check_assignments(place: Any, assignments: dict) -> list[str]:
    """Every rule of a place rule, at an answer, from scratch: what is wrong, or nothing (`app.solve.verify`)."""
    from app.solve.place_rule import SIDE_NAMES

    vs: list[Variant] = []
    placed: list[tuple[int, int, int]] = []
    problems = []
    for slot in place.slots:
        if not round(float(assignments.get(slot.chosen, 0) or 0)):
            continue
        turned = bool(round(float(assignments.get(slot.turn, 0) or 0))) if slot.turn is not None else False
        if turned and not slot.can_turn:
            problems.append(f"slot {slot.id} is turned but may not turn")
        w, h = (slot.width, slot.length) if turned else (slot.length, slot.width)
        side = None
        if place.aisle:
            k = int(round(float(assignments.get(slot.side, 0) or 0))) if slot.side is not None else -1
            if not 0 <= k < len(SIDE_NAMES):
                problems.append(f"slot {slot.id} has no aisle side")
                continue
            side = SIDE_NAMES[k]
            horizontal = w >= h
            allowed = {"long": ("bottom", "top") if horizontal else ("left", "right"),
                       "short": ("left", "right") if horizontal else ("bottom", "top"),
                       "any": SIDE_NAMES}[place.aisle_sides]
            if side not in allowed:
                problems.append(f"slot {slot.id}'s aisle is on a side not allowed ({side})")
        vs.append(Variant(0, 90 if turned else 0, w, h, side, 1.0))
        placed.append((len(vs) - 1, int(round(float(assignments.get(slot.x, 0) or 0))),
                       int(round(float(assignments.get(slot.y, 0) or 0)))))
    lay = Layout(place.zone_grid, vs, place.aisle, entrance=getattr(place, "entrance", None))
    for v, i, j in placed:
        lay.items[lay._next] = (v, i, j)
        lay._next += 1
    return problems + lay.check()
