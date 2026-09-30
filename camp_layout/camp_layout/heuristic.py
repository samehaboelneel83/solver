"""Stage 0: a constructive layout, used as the solvers' starting point.

A grid model this size (tens of thousands of binaries, a network flow with
big-M capacities) is hard to *start*: a solver may spend minutes before its
first good layout. People lay camps out in rows -- a corridor, beds along both
sides of it, the next corridor -- and connect the rows to the doors. This does
the same, then hands the solver a complete, feasible assignment of every
model variable to improve on:

1. for each orientation (corridors along x or along y) and each offset,
   corridor lines one bed-row apart on each side;
2. join every piece of corridor to the network, nearest first, growing it
   from the door zones (a greedy Steiner tree over the tile graph);
3. pack beds greedily -- the mandatory types first -- wherever a slot is free
   and a corridor tile stands at the middle of its long side;
4. give each bed the nearest door that still has capacity (door capacity and
   zone area), dropping beds no door can take;
5. prune corridor tiles no bed's path uses, pack again into what they freed;
6. route each bed's unit of flow along its shortest path.

The best of all orientations and offsets (most beds, then least corridor)
is returned. It is a heuristic: the model, not this, decides optimality.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from .discretize import Grid


@dataclass
class Layout:
    beds: list[int] = field(default_factory=list)  # placement indices
    tiles: set[int] = field(default_factory=set)
    level: dict[str, int] = field(default_factory=dict)
    door_of: dict[int, str] = field(default_factory=dict)
    entry: dict[int, int] = field(default_factory=dict)  # placement -> access tile used
    paths: dict[int, list[int]] = field(default_factory=dict)  # placement -> tiles from source to entry
    label: str = ""


class Constructor:
    def __init__(self, grid: Grid):
        self.g = grid
        self.adj: dict[int, list[int]] = defaultdict(list)
        for k, n in grid.neighbours:
            self.adj[k].append(n)
        self.sources: dict[str, list[int]] = defaultdict(list)
        for t in grid.tiles:
            if t.zone is not None:
                self.sources[t.zone].append(t.index)
        self.cells_of = {t.index: grid.tile_cells(t) for t in grid.tiles}
        self.band_cells = set(grid.band)

    # -- public ------------------------------------------------------------------
    def best(self) -> Layout:
        g = self.g
        across = min(p.span[1] if not p.rotated else p.span[0] for p in g.placements)
        period = 2 * across + g.s
        best: Layout | None = None
        for along_x in (True, False):
            for offset in range(period):
                lay = self.build(along_x, offset, period)
                key = (len(lay.beds), -len(lay.tiles))
                if best is None or key > (len(best.beds), -len(best.tiles)):
                    best = lay
        assert best is not None
        return best

    def build(self, along_x: bool, offset: int, period: int) -> Layout:
        g = self.g
        lines = {t.index for t in g.tiles if ((t.anchor[1] if along_x else t.anchor[0]) - offset) % period == 0}
        network = self._connect(lines)
        lay = self._fill(network)
        lay.label = f"corridors along {'x' if along_x else 'y'}, offset {offset}"
        return lay

    # -- steps -------------------------------------------------------------------
    def _connect(self, wanted: set[int]) -> set[int]:
        """The door zones plus every piece of `wanted`, each joined to the
        network by its shortest link, nearest pieces first."""
        network = {k for ks in self.sources.values() for k in ks}
        pieces = self._components(wanted)
        dist = self._bfs(network)[0]
        pieces.sort(key=lambda piece: min((dist.get(k, 1 << 30) for k in piece), default=1 << 30))
        for piece in pieces:
            if not any(k in dist for k in piece):
                continue  # unreachable from any door
            d, parent = self._bfs(network)
            target = min((k for k in piece if k in d), key=lambda k: d[k], default=None)
            if target is None:
                continue
            k = target
            while k not in network:
                network.add(k)
                k = parent[k]
            network |= piece
        return network

    def _fill(self, network: set[int]) -> Layout:
        g = self.g
        lay = Layout()
        chosen = self._pack(network, [])
        lay.level = {door: len(levels) - 1 for door, levels in g.levels.items()}
        self._assign(lay, chosen, network)
        used = self._used_tiles(lay)
        # Second pass: corridor nobody walks is floor again.
        chosen = self._pack(used, list(lay.beds))
        self._assign(lay, chosen, used)
        lay.tiles = self._used_tiles(lay)
        # The shallowest zone that still holds the beds its door serves.
        for door, levels in g.levels.items():
            zone = next(z for z in g.problem.zones if z.door == door)
            load = sum(1 for d in lay.door_of.values() if d == door)
            lay.level[door] = next((lvl for lvl in range(len(levels))
                                    if not zone.area_per_bed or zone.area_per_bed * load <= g.level_area[door][lvl] + 1e-9),
                                   len(levels) - 1)
        return lay

    def _pack(self, network: set[int], keep: list[int]) -> list[int]:
        g = self.g
        taken: set[tuple[int, int]] = set()
        for k in network:
            taken.update(self.cells_of[k])
        taken |= self.band_cells  # zones are at their deepest while packing
        chosen = []
        for p in keep:
            chosen.append(p)
            taken.update(g.placements[p].cells())
        counts: dict[str, int] = defaultdict(int)
        for p in chosen:
            counts[g.placements[p].bed_type] += 1
        types = sorted(g.problem.bed_types, key=lambda b: (-b.min_count, -b.priority))
        order = []
        for bed in types:
            ps = [p for p in g.placements if p.bed_type == bed.id]
            # Smaller slots first (more beds), then row by row so beds pack end to end.
            ps.sort(key=lambda p: (p.span[0] * p.span[1], p.anchor[1], p.anchor[0]))
            order.append((bed, ps))
        for bed, ps in order:
            for p in ps:
                if bed.max_count is not None and counts[bed.id] >= bed.max_count:
                    break
                cells = p.cells()
                if any(c in taken for c in cells):
                    continue
                if not any(k in network for k in g.access[p.index]):
                    continue
                chosen.append(p.index)
                taken.update(cells)
                counts[bed.id] += 1
        return chosen

    def _assign(self, lay: Layout, chosen: list[int], network: set[int]) -> None:
        g = self.g
        trees = {door: self._bfs(set(srcs), within=network) for door, srcs in self.sources.items()}
        room = {}
        for door in g.levels:
            zone = next(z for z in g.problem.zones if z.door == door)
            cap = g.problem.door(door).capacity
            by_area = int(g.level_area[door][lay.level[door]] / zone.area_per_bed + 1e-9) if zone.area_per_bed else 1 << 30
            room[door] = min(cap if cap is not None else 1 << 30, by_area)
        options = []
        for p in chosen:
            best = []
            for door, (dist, _) in trees.items():
                for k in g.access[p]:
                    if k in network and k in dist:
                        best.append((dist[k], door, k))
            best.sort()
            options.append((best[0][0] if best else 1 << 30, p, best))
        options.sort()
        lay.beds, lay.door_of, lay.entry, lay.paths = [], {}, {}, {}
        for _, p, best in options:
            for _, door, k in best:
                if room[door] > 0:
                    room[door] -= 1
                    lay.beds.append(p)
                    lay.door_of[p], lay.entry[p] = door, k
                    parent = trees[door][1]
                    path, x = [k], k
                    while parent.get(x) is not None:
                        x = parent[x]
                        path.append(x)
                    lay.paths[p] = path[::-1]
                    break

    def _used_tiles(self, lay: Layout) -> set[int]:
        used = {k for ks in self.sources.values() for k in ks}
        for path in lay.paths.values():
            used.update(path)
        return used

    # -- graph helpers -----------------------------------------------------------
    def _bfs(self, starts: set[int], within: set[int] | None = None):
        dist = {k: 0 for k in starts}
        parent: dict[int, int | None] = {k: None for k in starts}
        queue = deque(starts)
        while queue:
            k = queue.popleft()
            for n in self.adj[k]:
                if n in dist or (within is not None and n not in within):
                    continue
                dist[n] = dist[k] + 1
                parent[n] = k
                queue.append(n)
        return dist, parent

    def _components(self, tiles: set[int]) -> list[set[int]]:
        seen, out = set(), []
        for t in tiles:
            if t in seen:
                continue
            comp, queue = {t}, deque([t])
            seen.add(t)
            while queue:
                k = queue.popleft()
                for n in self.adj[k]:
                    if n in tiles and n not in seen:
                        seen.add(n)
                        comp.add(n)
                        queue.append(n)
            out.append(comp)
        return out


def hint_values(builder, lay: Layout) -> list[float]:
    """Every model variable's value for this layout: a complete, feasible start."""
    g = builder.grid
    values = [0.0] * len(builder.m.vars)

    def put(var, value):
        values[var.index] = float(value)

    for p in lay.beds:
        put(builder.y[p], 1)
    for k in lay.tiles:
        put(builder.t[k], 1)
        for c in g.tile_cells(g.tiles[k]):
            put(builder.u[c], 1)
    for (door, level), var in builder.e.items():
        put(var, 1 if lay.level[door] == level else 0)
    flow: dict[tuple[int, int], int] = defaultdict(int)
    src: dict[int, int] = defaultdict(int)
    load: dict[str, int] = defaultdict(int)
    for p in lay.beds:
        path = lay.paths[p]
        src[path[0]] += 1
        for a, b in zip(path, path[1:]):
            flow[(a, b)] += 1
        put(builder.a[(p, lay.entry[p])], 1)
        load[lay.door_of[p]] += 1
    for arc, v in flow.items():
        put(builder.f[arc], v)
    for k, v in src.items():
        put(builder.src[k], v)
    for door, var in builder.load.items():
        put(var, load[door])
    return values
