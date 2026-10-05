"""Distances and travel times along a lines layer the person imported (improvement plan 2.9).

`app.spatial.roads` reads the road network from map tiles. A site has its own
network as often: a site's corridors, a plant's internal roads, a city's
drainage-truck routes, pipes. Any lines layer of an imported map dataset is
read as one here: each line's vertices are nodes (a vertex two lines share,
to within `JOIN_M`, is one node -- that is what makes a junction), each
segment an edge with its geodesic length and, when a speed field is named,
the time it takes at that line's speed (else `default_kmh`).

A place joins the network at its nearest node, and the walk from the place to
that node counts at the same speed. A place further than `SNAP_M` from any
line is unreachable, as is a place on a piece of network the others cannot
reach: those pairs come back as NaN and are reported, never guessed.
Shortest paths are SciPy's Dijkstra, origins at once.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

JOIN_M = 2.0
SNAP_M = 500.0
#: Long straight segments get a node every this many metres, so a place beside the middle of a
#: road joins it there rather than at a far corner.
DENSIFY_M = 25.0
MAX_SEGMENTS = 400_000


class NetworkError(ValueError):
    """A layer that cannot be read as a network, in words for the person."""


@dataclass
class Network:
    xy: np.ndarray        # node positions in local metres
    lonlat: np.ndarray    # node positions in degrees
    graph: Any            # scipy sparse matrix of metres
    minutes: Any          # scipy sparse matrix of minutes
    origin: tuple[float, float]
    lines: int
    speed_field: str | None
    default_kmh: float


def _local(lon: np.ndarray, lat: np.ndarray, origin: tuple[float, float]) -> np.ndarray:
    k = np.cos(np.radians(origin[1]))
    return np.column_stack(((lon - origin[0]) * 111_320.0 * k, (lat - origin[1]) * 110_574.0))


def _densified(coords: list[list[float]]) -> list[list[float]]:
    """The line with extra vertices so no segment is longer than about DENSIFY_M."""
    out = [list(coords[0][:2])]
    for a, b in zip(coords, coords[1:]):
        k = np.cos(np.radians((a[1] + b[1]) / 2))
        length = float(np.hypot((b[0] - a[0]) * 111_320.0 * k, (b[1] - a[1]) * 110_574.0))
        steps = max(1, int(np.ceil(length / DENSIFY_M)))
        for i in range(1, steps + 1):
            t = i / steps
            out.append([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
    return out


def _noded(lines: list[tuple[list[list[float]], dict[str, Any]]]) -> list[tuple[list[list[float]], dict[str, Any]]]:
    """Each line with a vertex added wherever another line crosses it, so crossing roads join.

    A road plan drawn in CAD, or two roads digitised separately, often cross without a shared
    vertex; joining only vertices within JOIN_M would leave every road an island (user retest: an
    Alexandria grid of 20 crossing roads had no junction). Each line keeps its own properties
    (its speed), which a union of all lines would lose."""
    from shapely.geometry import LineString, MultiPoint, Point
    from shapely.strtree import STRtree

    shapes = [LineString([p[:2] for p in coords]) for coords, _ in lines]
    tree = STRtree(shapes)
    out = []
    for i, (coords, props) in enumerate(lines):
        line = shapes[i]
        cuts: list[tuple[float, float]] = []
        for j in tree.query(line):
            j = int(j)
            if j == i:
                continue
            hit = line.intersection(shapes[j])
            if hit.is_empty:
                continue
            points = [hit] if isinstance(hit, Point) else list(getattr(hit, "geoms", [])) if isinstance(hit, MultiPoint) else []
            for point in points:
                cuts.append((float(point.x), float(point.y)))
        if not cuts:
            out.append((coords, props))
            continue
        placed = [(line.project(Point(p[0], p[1])), [p[0], p[1]]) for p in [c[:2] for c in coords]]
        placed += [(line.project(Point(x, y)), [x, y]) for x, y in cuts]
        placed.sort(key=lambda item: item[0])
        merged = [placed[0][1]]
        for _, point in placed[1:]:
            if point != merged[-1]:
                merged.append(point)
        out.append((merged, props))
    return out


_CLOSED = {"1", "true", "yes", "y", "closed", "blocked", "x"}


def closed(value: Any) -> bool:
    """A line's closure property read as yes or no: true, 1, "yes", "closed" close it."""
    return value is True or (not isinstance(value, bool) and str(value).strip().lower() in _CLOSED)


def build(lines: list[tuple[list[list[float]], dict[str, Any]]], speed_field: str | None, default_kmh: float,
          *, closed_field: str | None = None, delay_field: str | None = None, avoid: list[Any] | None = None) -> Network:
    """The network of `lines` -- (coordinates, properties) pairs in WGS 84.

    Benchmark, October 2026 (flooded roads, closures): `closed_field` names a property that takes a
    line out; `delay_field` a property of minutes added to travel along the whole line (spread over
    its length); `avoid` shapely areas no segment may enter -- a flood zone, a no-go area."""
    from scipy.sparse import coo_matrix
    from scipy.spatial import cKDTree

    if not lines:
        raise NetworkError("the layer has no lines to travel along")
    if default_kmh <= 0:
        raise NetworkError("a speed is more than 0 km/h")
    if closed_field:
        lines = [(c, p) for c, p in lines if not closed((p or {}).get(closed_field))]
        if not lines:
            raise NetworkError(f"every line is closed by {closed_field!r}")
    if delay_field:
        # The delay of a line spread over it by length, kept per line through noding and densifying.
        from shapely.geometry import LineString

        lines = [(c, {**p, "__delay_per_deg": _delay(p.get(delay_field)) / max(LineString([q[:2] for q in c]).length, 1e-12)})
                 if len(c) >= 2 else (c, p) for c, p in lines]
    lines = [(_densified(coords), props) for coords, props in _noded([(c, p) for c, p in lines if len(c) >= 2])]
    barrier = None
    if avoid:
        from shapely.ops import unary_union
        from shapely.prepared import prep

        barrier = prep(unary_union(avoid))
    allpts = np.array([p[:2] for coords, _ in lines for p in coords], dtype=float)
    origin = (float(allpts[:, 0].mean()), float(allpts[:, 1].mean()))
    xy_all = _local(allpts[:, 0], allpts[:, 1], origin)
    # Vertices within JOIN_M of each other are one node.
    tree = cKDTree(xy_all)
    groups = tree.query_ball_point(xy_all, JOIN_M)
    node_of = np.full(len(xy_all), -1, dtype=np.int64)
    nodes: list[int] = []
    for i, near in enumerate(groups):
        if node_of[i] >= 0:
            continue
        idx = len(nodes)
        nodes.append(i)
        for j in near:
            if node_of[j] < 0:
                node_of[j] = idx
    xy = xy_all[nodes]
    lonlat = allpts[nodes]
    rows, cols, dist, mins = [], [], [], []
    at = 0
    for coords, props in lines:
        speed = default_kmh
        if speed_field:
            try:
                value = float(props.get(speed_field))
                if value > 0:
                    speed = value
            except (TypeError, ValueError):
                pass
        per_deg = float(props.get("__delay_per_deg") or 0.0)
        for k in range(len(coords) - 1):
            a, b = node_of[at], node_of[at + 1]
            at += 1
            if a == b:
                continue
            if barrier is not None:
                from shapely.geometry import LineString

                if barrier.intersects(LineString([coords[k][:2], coords[k + 1][:2]])):
                    continue
            d = float(np.hypot(*(xy[a] - xy[b])))
            extra = per_deg * float(np.hypot(coords[k + 1][0] - coords[k][0], coords[k + 1][1] - coords[k][1])) if per_deg else 0.0
            rows += [a, b]
            cols += [b, a]
            dist += [d, d]
            mins += [d / 1000.0 / speed * 60.0 + extra] * 2
        at += 1
        if len(rows) > 2 * MAX_SEGMENTS:
            raise NetworkError(f"the layer has more than {MAX_SEGMENTS:,} segments; use a smaller one")
    n = len(xy)
    graph = coo_matrix((dist, (rows, cols)), shape=(n, n)).tocsr()
    minutes = coo_matrix((mins, (rows, cols)), shape=(n, n)).tocsr()
    return Network(xy, lonlat, graph, minutes, origin, len(lines), speed_field, default_kmh)


def _delay(value: Any) -> float:
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        return 0.0
    return minutes if minutes > 0 and minutes == minutes else 0.0


def matrix(net: Network, origins: list[tuple[float, float]], targets: list[tuple[float, float]],
           *, minutes: bool, snap_m: float = SNAP_M) -> tuple[np.ndarray, dict[str, Any]]:
    """Metres or minutes from each origin to each target along the network; NaN where unreachable.
    `snap_m`: how far off the lines a place may be and still join them (the person can widen it).
    `info["off_origins"]` / `["off_targets"]`: the places further than that, by position, with how
    far each is -- so a place left out is named, not a silent row of blanks."""
    from scipy.sparse.csgraph import dijkstra
    from scipy.spatial import cKDTree

    tree = cKDTree(net.xy)

    def snap(points):
        if not points:
            return np.zeros(0), np.zeros(0, dtype=int)
        arr = np.array(points, dtype=float)
        d, i = tree.query(_local(arr[:, 0], arr[:, 1], net.origin))
        return d, i

    od, oi = snap(origins)
    td, ti = snap(targets)
    weights = net.minutes if minutes else net.graph
    unique = np.unique(oi) if len(oi) else oi
    paths = dijkstra(weights, directed=False, indices=unique) if len(unique) else np.zeros((0, len(net.xy)))
    row_of = {int(n): r for r, n in enumerate(unique)}
    out = np.full((len(origins), len(targets)), np.nan)
    walk = (lambda m: m / 1000.0 / net.default_kmh * 60.0) if minutes else (lambda m: m)
    for r in range(len(origins)):
        if od[r] > snap_m:
            continue
        along = paths[row_of[int(oi[r])]][ti]
        total = along + walk(od[r]) + np.array([walk(x) for x in td])
        total[(td > snap_m) | ~np.isfinite(along)] = np.nan
        out[r] = total
    unreachable = int(np.isnan(out).sum())
    off_o = [(i, round(float(d))) for i, d in enumerate(od) if d > snap_m]
    off_t = [(i, round(float(d))) for i, d in enumerate(td) if d > snap_m]
    info = {"nodes": int(len(net.xy)), "lines": net.lines, "snap_limit_m": snap_m,
            **({"off_origins": off_o} if off_o else {}), **({"off_targets": off_t} if off_t else {}),
            **({"speed_field": net.speed_field} if net.speed_field else {}), "default_kmh": net.default_kmh,
            **({"unreachable_pairs": unreachable} if unreachable else {})}
    return out, info


def from_layer(db, dataset_id: int, layer: str) -> list[tuple[list[list[float]], dict[str, Any]]]:
    """The lines of one layer of an imported dataset, as (coordinates, properties)."""
    from sqlalchemy import text

    rows = db.execute(
        text("SELECT f.geometry, f.properties FROM gis_feature f JOIN gis_layer l ON l.id = f.layer_id"
             " WHERE f.dataset_id = :d AND l.name = :n AND f.kind = 'line'"),
        {"d": dataset_id, "n": layer},
    ).all()
    out = []
    for geometry, props in rows:
        if geometry.get("type") == "LineString":
            out.append((geometry["coordinates"], props or {}))
        elif geometry.get("type") == "MultiLineString":
            out += [(part, props or {}) for part in geometry["coordinates"]]
    return out


def paths(net: Network, pairs: list[tuple[tuple[float, float], tuple[float, float]]], *, snap_m: float = SNAP_M,
          minutes: bool = False) -> list[list[list[float]] | None]:
    """For each (from, to) the way along the network as [lon, lat] points, the places themselves
    at each end; None where either is off the network or the other cannot be reached. To draw a
    flow along the roads it takes rather than as a straight line (benchmark, October 2026)."""
    from scipy.sparse.csgraph import dijkstra
    from scipy.spatial import cKDTree

    if not pairs:
        return []
    tree = cKDTree(net.xy)
    ends = np.array([p for pair in pairs for p in pair], dtype=float)
    d, i = tree.query(_local(ends[:, 0], ends[:, 1], net.origin))
    starts = sorted({int(i[2 * k]) for k in range(len(pairs))})
    _, before = dijkstra(net.minutes if minutes else net.graph, directed=False, indices=starts, return_predecessors=True)
    row = {n: r for r, n in enumerate(starts)}
    out: list[list[list[float]] | None] = []
    for k, (a, b) in enumerate(pairs):
        if d[2 * k] > snap_m or d[2 * k + 1] > snap_m:
            out.append(None)
            continue
        s, t = int(i[2 * k]), int(i[2 * k + 1])
        way, at = [t], t
        while at != s:
            at = int(before[row[s], at])
            if at < 0:
                break
            way.append(at)
        if at != s:
            out.append(None)
            continue
        points = [list(a), *[[float(x), float(y)] for x, y in net.lonlat[way[::-1]]], list(b)]
        out.append(_simplified(points))
    return out


def _simplified(points: list[list[float]], tolerance_deg: float = 0.0001) -> list[list[float]]:
    """A drawn way without the vertices `build` added every DENSIFY_M (about 11 m of tolerance): a
    flow along 200 km of road was 10,000 points, and the map took seconds to answer."""
    from shapely.geometry import LineString

    if len(points) < 3:
        return points
    return [[float(x), float(y)] for x, y in LineString(points).simplify(tolerance_deg, preserve_topology=False).coords]
