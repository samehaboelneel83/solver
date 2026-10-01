"""G. Independent validation: the layout against the rules, with exact geometry.

"The solver said optimal" proves nothing about the camp (spec §12). This
module never looks at the model, the grid or the variables: it reads the
problem definition and the layout's shapes and checks every hard rule again.

Accessibility is checked the way a person moves. A walker is a disc of
diameter w (the minimum corridor width, less a millimetre of tolerance). The
places its centre can reach are the walkable region eroded by w/2; a bed is
accessible when the point w/2 off the middle of its long side and some door's
point w/2 inside its opening lie in the same piece of that eroded region.
That both proves a path exists and that it is at least w wide all the way.
It is checked twice: through all free floor, and through the corridor
network alone (corridors, door zones and door frames) -- the second is the
hard rule. Walking distances are shortest paths on a 0.1 m raster of the
corridor network, reported per bed; door capacities are checked by a max-flow
assignment of beds to the doors they can reach.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra, maximum_flow
from shapely import STRtree, contains_xy
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from .geometry import Geometry
from .problem import CampProblem
from .result import LayoutResult

TOL = 1e-3  # a millimetre: coordinates are exact to far better than this
CLEARANCE_TOL = 0.01  # a walker may be 1 cm narrower than the minimum corridor width
REACH = 0.2  # how far beyond w/2 from a bed's side its user may stand
AREA = 1e-6


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    count: int = 0


@dataclass
class Validation:
    checks: list[Check] = field(default_factory=list)
    walk: dict[str, float] = field(default_factory=dict)  # bed -> metres to its door
    door_of: dict[str, str] = field(default_factory=dict)
    paths: dict[str, LineString] = field(default_factory=dict)
    loads: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, bad: list[str], detail_ok: str, count: int = 0) -> None:
        self.checks.append(Check(name, not bad, detail_ok if not bad else "; ".join(bad[:5]) +
                                 (f" (+{len(bad) - 5} more)" if len(bad) > 5 else ""), count))

    def summary(self) -> dict:
        walks = list(self.walk.values())
        return {"valid": self.ok, "checks": [c.__dict__ for c in self.checks],
                "walk_total_m": round(sum(walks), 1), "walk_max_m": round(max(walks), 1) if walks else 0.0,
                "walk_mean_m": round(sum(walks) / len(walks), 1) if walks else 0.0, "door_loads": self.loads}


def _pieces(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def _access_reach(bed, w: float, reach: float = REACH) -> list:
    """Where a walker's centre may stand to use the bed: beside the middle half
    of each long side, from touching the bed out to w/2 + `reach` (the side
    gap a bed keeps is within reach). A person steps in anywhere along the
    middle of the bed, not only at its exact centre."""
    minx, miny, maxx, maxy = bed.polygon.bounds
    far = w / 2 + reach
    if (maxx - minx) >= (maxy - miny):
        q = (maxx - minx) / 4
        cx = (minx + maxx) / 2
        return [box(cx - q, miny - far, cx + q, miny), box(cx - q, maxy, cx + q, maxy + far)]
    q = (maxy - miny) / 4
    cy = (miny + maxy) / 2
    return [box(minx - far, cy - q, minx, cy + q), box(maxx, cy - q, maxx + far, cy + q)]


def _stand_point(bed, side, w: float) -> Point:
    """The point w/2 off the middle of a long side: where distances are measured from."""
    minx, miny, maxx, maxy = side.bounds
    bminx, bminy, bmaxx, bmaxy = bed.polygon.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    if (bmaxx - bminx) >= (bmaxy - bminy):
        return Point(cx, bminy - w / 2 if maxy <= bminy + 1e-9 else bmaxy + w / 2)
    return Point(bminx - w / 2 if maxx <= bminx + 1e-9 else bmaxx + w / 2, cy)


def validate(problem: CampProblem, layout: LayoutResult, raster: float = 0.1) -> Validation:
    geo = Geometry(problem)
    v = Validation()
    w = problem.corridor.min_width
    beds = layout.beds
    polys = [b.polygon for b in beds]
    camp = geo.camp

    v.add("beds inside the camp", [b.id for b in beds if not geo.inside(b.polygon)], f"all {len(beds)} inside", len(beds))

    tree = STRtree(polys)
    overlaps = []
    for i, p in enumerate(polys):
        for j in tree.query(p):
            if j > i and p.intersection(polys[j]).area > AREA:
                overlaps.append(f"{beds[i].id}/{beds[j].id}")
    v.add("no two beds overlap", overlaps, "none overlap")

    def against(shapes: dict, label: str):
        bad = []
        for sid, shape in shapes.items():
            for i in tree.query(shape):
                if polys[i].intersection(shape).area > AREA:
                    bad.append(f"{beds[i].id} on {sid}")
        v.add(f"no bed on {label}", bad, f"none on {label}")

    against(geo.obstacles, "an obstacle")
    against(geo.prohibited, "a prohibited area")
    against(geo.door_frames, "a door")
    zones_now = {}
    bad_depth = []
    for zone in problem.zones:
        depth = layout.zone_depth.get(zone.door, zone.depth)
        if depth < zone.depth - TOL or depth > zone.max_depth + TOL:
            bad_depth.append(f"{zone.door} at {depth} m outside [{zone.depth}, {zone.max_depth}]")
        zones_now[zone.door] = geo.zone_polygon(zone, depth)
    against(zones_now, "a door zone")
    v.add("door zones within their allowed depth", bad_depth, "every zone within its bounds")
    v.add("door zones clear of obstacles",
          [d for d, z in zones_now.items() if z.intersection(geo.blocked).area > AREA], "all clear")

    types = {t.id: t for t in problem.bed_types}
    bad_dims, counts = [], {}
    for b in beds:
        t = types.get(b.bed_type)
        counts[b.bed_type] = counts.get(b.bed_type, 0) + 1
        minx, miny, maxx, maxy = b.polygon.bounds
        along, across = (maxy - miny, maxx - minx) if b.rotated else (maxx - minx, maxy - miny)
        if t is None or not t.within(round(along, 6), round(across, 6)):
            bad_dims.append(f"{b.id} {along:.2f}x{across:.2f}")
        if t is not None and not t.rotation and b.rotated:
            bad_dims.append(f"{b.id} rotated")
        if t is not None and t.zone and not geo.placement_zones[t.zone].buffer(TOL).contains(b.polygon):
            bad_dims.append(f"{b.id} outside {t.zone}")
    v.add("bed sizes, orientation and zones as allowed", bad_dims, "all within their type's rules")
    bad_counts = []
    for t in problem.bed_types:
        n = counts.get(t.id, 0)
        if n < t.min_count or (t.max_count is not None and n > t.max_count):
            bad_counts.append(f"{t.id}: {n} not in [{t.min_count}, {t.max_count}]")
    v.add("bed counts per type", bad_counts, ", ".join(f"{k}: {n}" for k, n in sorted(counts.items())) or "none")

    unchanged = [d.id for d in problem.doors if not geo.door_frames[d.id].equals(Geometry(problem).door_frames[d.id])]
    v.add("doors unchanged", unchanged, f"{len(problem.doors)} doors as defined")

    corridor = layout.corridor
    v.add("corridors inside the camp", [] if geo.inside(corridor) else ["corridor leaves the camp"], "inside")
    v.add("corridors clear of obstacles", [] if corridor.intersection(geo.blocked).area <= AREA else
          [f"{corridor.intersection(geo.blocked).area:.2f} m² on obstacles"], "clear")
    on_beds = [beds[i].id for sq in layout.corridor_squares for i in tree.query(sq) if polys[i].intersection(sq).area > AREA]
    v.add("corridors clear of beds", sorted(set(on_beds)), "clear")
    narrow = [f"square {k}" for k, sq in enumerate(layout.corridor_squares)
              if min(sq.bounds[2] - sq.bounds[0], sq.bounds[3] - sq.bounds[1]) < w - TOL]
    v.add(f"corridor pieces at least {w} m wide", narrow, f"{len(layout.corridor_squares)} pieces, each {w} m or wider")

    # -- accessibility, as a walker of width w ------------------------------------
    blocked = unary_union([geo.blocked, *polys])
    free = camp.difference(blocked)
    network = unary_union([corridor, *zones_now.values(), *geo.door_frames.values()]).intersection(camp).difference(blocked)
    door_pts = {}
    for d in problem.doors:
        (ax, ay), (bx, by) = d.a, d.b
        nx, ny = geo.normals[d.id]
        door_pts[d.id] = Point((ax + bx) / 2 + nx * w / 2, (ay + by) / 2 + ny * w / 2)

    def reach(region, label):
        pieces = _pieces(region.buffer(-(w / 2 - CLEARANCE_TOL)))
        door_piece = {d: next((k for k, piece in enumerate(pieces) if piece.buffer(CLEARANCE_TOL).contains(pt)), None)
                      for d, pt in door_pts.items()}
        reachable = {k for k in door_piece.values() if k is not None}
        bad = []
        for b in beds:
            if not any(pieces[k].intersects(side) for side in _access_reach(b, w) for k in reachable):
                bad.append(b.id)
        v.add(label, bad, f"all {len(beds)} beds reach a door with {w} m clearance (±{CLEARANCE_TOL * 100:.0f} cm)",
              len(beds))

    reach(free, "every bed reaches a door (any free floor)")
    reach(network, "every bed reaches a door through the corridors")
    _distances(v, problem, geo, beds, network, door_pts, zones_now, raster)
    return v


def _distances(v: Validation, problem, geo, beds, network, door_pts, zones, raster: float) -> None:
    """Shortest walks on a raster of the corridor network (centre-line region),
    and a capacity-respecting assignment of beds to doors."""
    w = problem.corridor.min_width
    region = network.buffer(-(w / 2 - raster))
    if region.is_empty:
        v.add("walking distances", ["no walkable corridor"], "")
        return
    minx, miny, maxx, maxy = region.bounds
    xs = np.arange(minx + raster / 2, maxx, raster)
    ys = np.arange(miny + raster / 2, maxy, raster)
    gx, gy = np.meshgrid(xs, ys)
    inside = contains_xy(region, gx.ravel(), gy.ravel()).reshape(gx.shape)
    ids = -np.ones(gx.shape, dtype=np.int64)
    ids[inside] = np.arange(int(inside.sum()))
    rows, cols, data = [], [], []
    ny_, nx_ = gx.shape
    for dy, dx, cost in ((0, 1, raster), (1, 0, raster), (1, 1, raster * 2 ** 0.5), (1, -1, raster * 2 ** 0.5)):
        c0, c1 = (0, nx_ - dx) if dx >= 0 else (-dx, nx_)
        a = ids[0:ny_ - dy, c0:c1]
        b = ids[dy:ny_, c0 + dx:c1 + dx]
        m = (a >= 0) & (b >= 0)
        rows += list(a[m])
        cols += list(b[m])
        data += [cost] * int(m.sum())
    n = int(inside.sum())
    graph = csr_matrix((data + data, (rows + cols, cols + rows)), shape=(n, n))
    coords = np.column_stack([gx[inside], gy[inside]])

    def nearest(pt: Point) -> int:
        d = (coords[:, 0] - pt.x) ** 2 + (coords[:, 1] - pt.y) ** 2
        return int(np.argmin(d))

    doors = [d.id for d in problem.doors]
    door_nodes = [nearest(door_pts[d]) for d in doors]
    dist, pred = dijkstra(graph, indices=door_nodes, return_predecessors=True)
    # Every side a bed may be used from, for every door: a bed between two
    # corridors may be served from either.
    def stand(b, side):
        # The nearest corridor centre point beside the middle half of this side.
        inside = np.flatnonzero(contains_xy(side.buffer(w / 2), coords[:, 0], coords[:, 1]))
        if inside.size:
            p = _stand_point(b, side, w)
            return int(inside[np.argmin((coords[inside, 0] - p.x) ** 2 + (coords[inside, 1] - p.y) ** 2)])
        return nearest(_stand_point(b, side, w))

    sides = {b.id: [stand(b, side) for side in _access_reach(b, w)] for b in beds}
    best = {b.id: [min(sides[b.id], key=lambda k: dist[j, k]) for j in range(len(doors))] for b in beds}

    # Capacity: beds -> doors they can reach, max flow must place every bed.
    cap = []
    for d in doors:
        zone = next((z for z in problem.zones if z.door == d), None)
        c = problem.door(d).capacity
        area = zones[d].area if d in zones else 0.0
        by_area = int(area / zone.area_per_bed + 1e-9) if zone and zone.area_per_bed else 10 ** 6
        cap.append(min(c if c is not None else 10 ** 6, by_area))
    nb, nd = len(beds), len(doors)
    src, sink = nb + nd, nb + nd + 1
    r, c_, cap_ = [], [], []
    for i, b in enumerate(beds):
        r.append(src); c_.append(i); cap_.append(1)
        for j in range(nd):
            if np.isfinite(dist[j, best[b.id][j]]):
                r.append(i); c_.append(nb + j); cap_.append(1)
    for j in range(nd):
        r.append(nb + j); c_.append(sink); cap_.append(int(cap[j]))
    flow_graph = csr_matrix((np.array(cap_, dtype=np.int32), (r, c_)), shape=(nb + nd + 2, nb + nd + 2))
    flow = maximum_flow(flow_graph, src, sink)
    assigned = flow.flow.tocsr()
    for i, b in enumerate(beds):
        row = assigned[i]
        for k, val in zip(row.indices, row.data):
            if val > 0 and nb <= k < nb + nd:
                v.door_of[b.id] = doors[k - nb]
    v.add("door capacities hold (max-flow assignment)",
          [] if flow.flow_value == nb else [f"only {flow.flow_value} of {nb} beds fit the doors' capacities"],
          f"all {nb} beds assigned within capacity")
    v.loads = {d: sum(1 for x in v.door_of.values() if x == d) for d in doors}
    for b in beds:
        d = v.door_of.get(b.id)
        if d is None:
            continue
        j = doors.index(d)
        node = best[b.id][j]
        v.walk[b.id] = round(float(dist[j, node]) + w / 2, 2)
        pts, k = [], node
        while k >= 0 and k != door_nodes[j]:
            pts.append(tuple(coords[k]))
            k = pred[j, k]
        pts.append(tuple(coords[door_nodes[j]]))
        if len(pts) >= 2:
            v.paths[b.id] = LineString(pts).simplify(raster)
