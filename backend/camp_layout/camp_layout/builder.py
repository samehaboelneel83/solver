"""ConstraintBuilder and ObjectiveBuilder: the grid candidates as a model.

Variables (spec §4)
  y[p]      binary   bed placement p is used (type, size, orientation, position)
  t[k]      binary   corridor tile k is part of the corridor network
  u[c]      binary   cell c is circulation (covered by some used tile)
  e[j,l]    binary   door j's zone takes depth level l (exactly one level)
  f[k,m]    integer  beds' walking flow on tile arc k->m          (relaxable)
  src[k]    integer  flow entering the network at zone tile k      (relaxable)
  a[p,k]    binary   bed p is entered from tile k                  (relaxable)
  load[j]   integer  beds served through door j

Hard constraints (spec §5), by group
  cell      Σ_{p∋c} y[p] + u[c] ≤ 1         beds never overlap each other or a corridor
  tile      t[k] ≤ u[c]  (c in tile k)       a used tile makes its cells circulation
  zone      Σ_{p∋c} y[p] + Σ_{l'≥l} e[j,l'] ≤ 1   a deepened zone holds no bed
  level     Σ_l e[j,l] = 1
  source    t[k] = 1 for tiles in a door's specified zone
  access    Σ_k a[p,k] = y[p];  a[p,k] ≤ t[k] a used bed is entered from a used tile
  flow      Σ_in f + src[k] = Σ_out f + Σ_p a[p,k]   every bed's unit of flow comes from a door
  capacity  f[k,m] ≤ U·t[k],  f[k,m] ≤ U·t[m]  flow only on the corridor network
  door      load[j] = Σ_{k in zone j} src[k];  load[j] ≤ capacity_j
  zonearea  area_per_bed·load[j] ≤ Σ_l area[j,l]·e[j,l]
  count     min_count ≤ Σ_{p of type} y[p] ≤ max_count

Boundary, obstacles, prohibited areas and placement zones need no rows: a
placement or tile that would break them is never generated (discretize).

Objectives (spec §2, §3)
  beds           max  Σ priority·y[p]
  distance       min  Σ g·f[k,m]    total walking distance, beds to doors, along the corridors
  corridor       min  g²·Σ u[c]     circulation area outside the doors' specified zones
  modifications  min  Σ (area[j,l]-area[j,0])·e[j,l] + Σ deviation[p]·y[p]
"""
from __future__ import annotations

from collections import defaultdict

from .discretize import Grid
from .model import Expr, MathematicalModel


class ModelBuilder:
    def __init__(self, grid: Grid):
        self.grid = grid
        self.m = MathematicalModel()
        self.y: dict[int, object] = {}
        self.t: dict[int, object] = {}
        self.u: dict[tuple[int, int], object] = {}
        self.e: dict[tuple[str, int], object] = {}
        self.f: dict[tuple[int, int], object] = {}
        self.src: dict[int, object] = {}
        self.a: dict[tuple[int, int], object] = {}
        self.load: dict[str, object] = {}

    def build(self) -> MathematicalModel:
        self._variables()
        self._constraints()
        self._objectives()
        return self.m

    # -- variables ---------------------------------------------------------------
    def _variables(self) -> None:
        g, m = self.grid, self.m
        self.U = len(g.placements) and self._bed_upper_bound()
        for p in g.placements:
            self.y[p.index] = m.var(f"y[{p.index}]")
        for tile in g.tiles:
            self.t[tile.index] = m.var(f"t[{tile.index}]")
        for tile in g.tiles:
            for c in g.tile_cells(tile):
                if c not in self.u:
                    self.u[c] = m.var(f"u[{c[0]},{c[1]}]")
        for door, levels in g.levels.items():
            for level in range(len(levels)):
                self.e[(door, level)] = m.var(f"e[{door},{level}]")
            cap = self.grid.problem.door(door).capacity
            self.load[door] = m.var(f"load[{door}]", 0, min(self.U, cap) if cap is not None else self.U, "integer")
        for k, n in g.neighbours:
            self.f[(k, n)] = m.var(f"f[{k},{n}]", 0, self.U, "integer", relaxable=True)
        for tile in g.tiles:
            if tile.zone is not None:
                self.src[tile.index] = m.var(f"src[{tile.index}]", 0, self.U, "integer", relaxable=True)
        for p, tiles in g.access.items():
            for k in tiles:
                self.a[(p, k)] = m.var(f"a[{p},{k}]", 0, 1, "binary", relaxable=True)

    def _bed_upper_bound(self) -> int:
        """No more beds than the bed cells can hold at the smallest slot."""
        smallest = min(p.span[0] * p.span[1] for p in self.grid.placements)
        return max(1, len(self.grid.bed_ok) // smallest)

    # -- constraints -------------------------------------------------------------
    def _constraints(self) -> None:
        g, m = self.grid, self.m
        covering: dict[tuple[int, int], list[int]] = defaultdict(list)
        for p in g.placements:
            for c in p.cells():
                covering[c].append(p.index)

        for c in set(covering) | set(self.u):
            e = Expr.of((self.y[p], 1.0) for p in covering.get(c, []))
            if c in self.u:
                e.add(self.u[c])
            if len(e.terms) > 1:
                m.add(e, "<=", 1, "cell")
        for tile in g.tiles:
            for c in g.tile_cells(tile):
                m.add(Expr.of([(self.t[tile.index], 1.0), (self.u[c], -1.0)]), "<=", 0, "tile")
            if tile.zone is not None:
                m.add(Expr.of([(self.t[tile.index], 1.0)]), "==", 1, "source")

        levels_of: dict[str, int] = {d: len(v) for d, v in g.levels.items()}
        for door, n in levels_of.items():
            m.add(Expr.of((self.e[(door, level)], 1.0) for level in range(n)), "==", 1, "level")
        for c, (door, level) in g.band.items():
            if c not in covering:
                continue
            e = Expr.of((self.y[p], 1.0) for p in covering[c])
            for deeper in range(level, levels_of[door]):
                e.add(self.e[(door, deeper)])
            m.add(e, "<=", 1, "zone")

        into_tile: dict[int, list[int]] = defaultdict(list)
        for p, tiles in g.access.items():
            m.add(Expr.of([(self.a[(p, k)], 1.0) for k in tiles] + [(self.y[p], -1.0)]), "==", 0, "access")
            for k in tiles:
                m.add(Expr.of([(self.a[(p, k)], 1.0), (self.t[k], -1.0)]), "<=", 0, "access")
                into_tile[k].append(p)

        out_arcs: dict[int, list[int]] = defaultdict(list)
        in_arcs: dict[int, list[int]] = defaultdict(list)
        for k, n in g.neighbours:
            out_arcs[k].append(n)
            in_arcs[n].append(k)
            m.add(Expr.of([(self.f[(k, n)], 1.0), (self.t[k], -self.U)]), "<=", 0, "capacity")
            m.add(Expr.of([(self.f[(k, n)], 1.0), (self.t[n], -self.U)]), "<=", 0, "capacity")
        for tile in g.tiles:
            k = tile.index
            e = Expr()
            for n in in_arcs[k]:
                e.add(self.f[(n, k)], 1.0)
            for n in out_arcs[k]:
                e.add(self.f[(k, n)], -1.0)
            if k in self.src:
                e.add(self.src[k], 1.0)
            for p in into_tile[k]:
                e.add(self.a[(p, k)], -1.0)
            if e.terms:
                m.add(e, "==", 0, "flow")

        for door in g.levels:
            e = Expr.of([(self.load[door], 1.0)])
            for tile in g.tiles:
                if tile.zone == door:
                    e.add(self.src[tile.index], -1.0)
            m.add(e, "==", 0, "door")
            zone = next(z for z in g.problem.zones if z.door == door)
            if zone.area_per_bed:
                e = Expr.of([(self.load[door], zone.area_per_bed)])
                for level, area in enumerate(g.level_area[door]):
                    e.add(self.e[(door, level)], -area)
                m.add(e, "<=", 0, "zonearea")

        for bed in g.problem.bed_types:
            e = Expr.of((self.y[p.index], 1.0) for p in g.placements if p.bed_type == bed.id)
            if bed.min_count:
                m.add(e, ">=", bed.min_count, "count")
            if bed.max_count is not None:
                m.add(e, "<=", bed.max_count, "count")

    # -- objectives --------------------------------------------------------------
    def _objectives(self) -> None:
        g, m = self.grid, self.m
        prio = {b.id: b.priority for b in g.problem.bed_types}
        beds = Expr.of((self.y[p.index], prio[p.bed_type]) for p in g.placements)
        distance = Expr.of((v, g.g) for v in self.f.values())
        base_cells = set(g.base_zone)
        corridor = Expr.of((v, g.g * g.g) for c, v in self.u.items() if c not in base_cells)
        mods = Expr.of((self.y[p.index], p.deviation) for p in g.placements if p.deviation)
        for (door, level), v in self.e.items():
            extra = g.level_area[door][level] - g.level_area[door][0]
            if extra > 1e-9:
                mods.add(v, round(extra, 6))
        minx, miny, maxx, maxy = g.geometry.camp.bounds
        span = (maxx - minx) + (maxy - miny)
        m.objectives = {
            "beds": _obj("beds", beds, "max", max(self.U, 1), "beds"),
            "distance": _obj("distance", distance, "min", max(self.U, 1) * span, "m walked"),
            "corridor": _obj("corridor", corridor, "min", len(g.walk_ok) * g.g * g.g, "m²"),
            "modifications": _obj("modifications", mods, "min",
                                  max(1.0, sum(a[-1] - a[0] for a in g.level_area.values()) + self.U * 0.5), "m²"),
        }


def _obj(name, expr, sense, scale, unit):
    from .model import Objective
    return Objective(name, expr, sense, float(scale), unit)
