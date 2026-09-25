"""Road distances and travel times from the tile server's roads (queue R16b).

No OpenStreetMap extract is on this machine; the tile server's vector tiles
are (OpenMapTiles, `transportation` layer, motorways to minor roads at zoom
12). So the road network is read from them: the tiles covering the places
(and a margin), each road line decoded (`app.spatial.mvt`), its vertices
placed on one global grid -- a vertex shared by two tiles lands on the same
point exactly, which is what stitches the tiles -- and each segment an edge
with its geodesic length and, at its class's speed, a travel time. Shortest
paths are SciPy's Dijkstra, a few origins at a time.

What this is and is not, recorded in the source of every value it writes:
roads as the zoom-12 tiles draw them (simplified; small streets left out),
every road both ways (the tiles' one-way flag marks nearly every line, so it
is not trusted), speeds by class, no traffic. A place further than
`SNAP_M` from any road, or on a piece of road the others cannot reach, is
unreachable: its pairs are reported, never guessed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

import numpy as np

from app.spatial import mvt
from app.spatial.distance import Place
from app.spatial.terrain import LOCAL_HOSTS, _with_host, candidates, fetch_bytes

ZOOM = 12
LAYER = "transportation"
#: km/h by OpenMapTiles class; a class not listed carries no traffic here (rail, ferry, construction, paths).
SPEED_KMH = {"motorway": 90, "trunk": 80, "primary": 60, "secondary": 50, "tertiary": 40, "minor": 30,
             "service": 20, "track": 15}
#: A place further than this from any road is off the network.
SNAP_M = 2000.0
#: The margin round the places' box, as a share of its size (roads leave and come back).
MARGIN = 0.15
#: The most tiles one request reads: zoom-12 tiles are about 10 km a side at the equator, and noding
#: nine of central Cairo's takes about 20 s (queue R16b), so 36 is about 60 km square in a minute or so.
MAX_TILES = 36


class RoadsError(ValueError):
    """The roads cannot be read: named, so the form can say why."""


@dataclass
class Network:
    lon: np.ndarray
    lat: np.ndarray
    metres: Any  # scipy.sparse csr, symmetric
    minutes: Any
    tiles: int
    template: str


def vector_source(index_url: str, fetch: Callable[[str], bytes | None] = fetch_bytes) -> str:
    """The tile address template of the index's vector tileset with roads."""
    if not index_url.lower().startswith(("http://", "https://")):
        raise RoadsError("road distances need the tile index address (setting spatial.tiles_index) -- it is not set")
    last: Exception | None = None
    for url in candidates(index_url):
        try:
            body = fetch(url)
        except (OSError, ValueError) as exc:
            last = exc
            continue
        if body is None:
            continue
        for tileset in json.loads(body):
            layers = {str(v.get("id")) for v in tileset.get("vector_layers") or []}
            if (LAYER in layers or str(tileset.get("format", "")).lower() == "pbf") and tileset.get("tiles"):
                template = str(tileset["tiles"][0])
                reached = urlsplit(url).hostname or ""
                if (urlsplit(template).hostname or "") in LOCAL_HOSTS and reached not in LOCAL_HOSTS:
                    template = _with_host(template, reached)
                return template
        raise RoadsError(f"the tile index at {index_url} lists no vector tileset with roads")
    raise RoadsError(f"the tile index at {index_url} could not be reached from the server ({last})")


def _tile_of(lon: float, lat: float) -> tuple[int, int]:
    n = 2 ** ZOOM
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def network(places: list[Place], template: str, fetch: Callable[[str], bytes | None] = fetch_bytes) -> Network:
    """The roads round the places, as a graph: lines read, dead ends joined to the road they stop short
    of, and every at-grade crossing made a junction (bridges and tunnels are not: a flyover is not a
    crossroads)."""
    import shapely
    from pyproj import Geod
    from scipy.sparse import coo_matrix
    from shapely.geometry import LineString, MultiLineString, Point

    lons = [p.lon for p in places]
    lats = [p.lat for p in places]
    pad_x = max(0.01, (max(lons) - min(lons)) * MARGIN)
    pad_y = max(0.01, (max(lats) - min(lats)) * MARGIN)
    x0, y1 = _tile_of(min(lons) - pad_x, min(lats) - pad_y)
    x1, y0 = _tile_of(max(lons) + pad_x, max(lats) + pad_y)
    count = (x1 - x0 + 1) * (y1 - y0 + 1)
    if count > MAX_TILES:
        raise RoadsError(f"the places spread over {count} road tiles, more than {MAX_TILES}; measure fewer or closer places")
    ground: list[LineString] = []
    ground_kmh: list[float] = []
    raised: list[LineString] = []
    raised_kmh: list[float] = []
    extent_seen = 4096
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            body = fetch(template.format(z=ZOOM, x=tx, y=ty))
            if not body:
                continue
            for props, lines, extent in mvt.lines(body, LAYER):
                kmh = SPEED_KMH.get(str(props.get("class")))
                if kmh is None:
                    continue
                extent_seen = extent
                for line in lines:
                    # One global grid: a vertex two tiles share is one point.
                    coords = [(tx * extent + px, ty * extent + py) for px, py in line]
                    if len(set(coords)) < 2:
                        continue
                    geometry = LineString(coords)
                    if props.get("brunnel") in ("bridge", "tunnel"):
                        raised.append(geometry)
                        raised_kmh.append(kmh)
                    else:
                        ground.append(geometry)
                        ground_kmh.append(kmh)
    if not ground and not raised:
        raise RoadsError("the tiles round these places carry no roads")
    everything = ground + raised
    tree = shapely.STRtree(everything)
    # A dead end a few metres short of another road meets it there (simplification drops the junction).
    connectors: list[LineString] = []
    ends = [Point(g.coords[k]) for g in everything for k in (0, -1)]
    owner = [i for i in range(len(everything)) for _ in (0, 1)]
    near = tree.query(ends, predicate="dwithin", distance=DANGLE_UNITS)
    best: dict[int, tuple[float, int]] = {}
    for e, g in zip(*near):
        if g == owner[e]:
            continue
        d = ends[e].distance(everything[g])
        if d > 1e-9 and (e not in best or d < best[e][0]):
            best[e] = (d, g)
    for e, (_, g) in best.items():
        connectors.append(shapely.shortest_line(ends[e], everything[g]))
    # Every crossing of ground-level roads (and each connector's foot) becomes a vertex of both.
    noded = shapely.unary_union(MultiLineString(ground + connectors)) if ground or connectors else None
    pieces = list(noded.geoms) if noded is not None and noded.geom_type == "MultiLineString" else ([noded] if noded else [])
    # A noded piece keeps the speed of the road it lies on; a connector is a minor road.
    ground_tree = shapely.STRtree(ground) if ground else None
    speeds: list[float] = []
    if pieces and ground_tree is not None:
        middles = [p.interpolate(0.5, normalized=True) for p in pieces]
        found = ground_tree.query_nearest(middles, max_distance=0.5, all_matches=False)
        speed_of = {int(i): ground_kmh[int(j)] for i, j in zip(*found)}
        speeds = [speed_of.get(k, SPEED_KMH["minor"]) for k in range(len(pieces))]
    else:
        speeds = [SPEED_KMH["minor"]] * len(pieces)
    lines_ = pieces + raised
    kmh_ = speeds + raised_kmh
    node_of: dict[tuple[float, float], int] = {}
    gx: list[float] = []
    gy: list[float] = []
    a: list[int] = []
    b: list[int] = []
    speed: list[float] = []
    for line, kmh in zip(lines_, kmh_):
        previous = None
        for x, y in line.coords:
            key = (round(x * 2) / 2, round(y * 2) / 2)
            node = node_of.get(key)
            if node is None:
                node = node_of[key] = len(gx)
                gx.append(key[0])
                gy.append(key[1])
            if previous is not None and previous != node:
                a.append(previous)
                b.append(node)
                speed.append(kmh)
            previous = node
    world = 2 ** ZOOM * extent_seen
    lon = np.array(gx) / world * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * np.array(gy) / world))))
    ia, ib = np.array(a), np.array(b)
    _, _, metres = Geod(ellps="WGS84").inv(lon[ia], lat[ia], lon[ib], lat[ib])
    metres = np.maximum(np.asarray(metres), 0.01)  # a zero weight would read as no edge
    minutes = metres / (np.array(speed) * 1000.0 / 60.0)
    n = len(gx)
    both = (np.concatenate([ia, ib]), np.concatenate([ib, ia]))

    def graph(weights):
        # Two lines over one segment keep the shorter: min, not sum, where duplicates meet.
        doubled = np.concatenate([weights, weights])
        order = np.lexsort((doubled, both[1], both[0]))
        rows, cols, w = both[0][order], both[1][order], doubled[order]
        first = np.ones(len(rows), dtype=bool)
        first[1:] = (rows[1:] != rows[:-1]) | (cols[1:] != cols[:-1])
        return coo_matrix((w[first], (rows[first], cols[first])), shape=(n, n)).tocsr()

    return Network(lon, lat, graph(metres), graph(minutes), count, template)


#: Tile units at zoom 12 are about 2.4 m at the equator (2 m at Cairo). A road that ends this close to
#: another meets it: simplification drops the shared junction vertex, so without this the graph was
#: 56,086 pieces, the largest 12% (queue R16b).
DANGLE_UNITS = 10.0


def snap(net: Network, places: list[Place]) -> tuple[np.ndarray, np.ndarray]:
    """Each place's nearest road point on the network's largest connected piece, and how far it is."""
    from pyproj import Geod
    from scipy.sparse.csgraph import connected_components

    _, label = connected_components(net.metres, directed=False)
    main = np.bincount(label).argmax()
    candidates_ = np.flatnonzero(label == main)
    clon, clat = net.lon[candidates_], net.lat[candidates_]
    nearest = np.empty(len(places), dtype=np.int64)
    gap = np.empty(len(places))
    geod = Geod(ellps="WGS84")
    for k, p in enumerate(places):
        # Nearest by a flat approximation, then measured properly.
        d2 = ((clon - p.lon) * math.cos(math.radians(p.lat))) ** 2 + (clat - p.lat) ** 2
        j = int(d2.argmin())
        nearest[k] = candidates_[j]
        gap[k] = geod.inv(p.lon, p.lat, float(clon[j]), float(clat[j]))[2]
    return nearest, gap


def matrix(net: Network, origins: list[Place], targets: list[Place], *, minutes: bool) -> tuple[np.ndarray, dict[str, Any]]:
    """Road metres (or minutes) from each origin to each target; NaN where no road joins them."""
    from scipy.sparse.csgraph import dijkstra

    o_node, o_gap = snap(net, origins)
    t_node, t_gap = snap(net, targets)
    weights = net.minutes if minutes else net.metres
    out = np.full((len(origins), len(targets)), np.nan)
    for start in range(0, len(origins), 16):
        rows = dijkstra(weights, directed=False, indices=o_node[start:start + 16])
        out[start:start + 16] = rows[:, t_node]
    for k in np.flatnonzero(o_gap > SNAP_M):
        out[k, :] = np.nan
    for k in np.flatnonzero(t_gap > SNAP_M):
        out[:, k] = np.nan
    # The walk from each place to its road point, at walking pace for time, is part of the trip.
    reached = ~np.isnan(out)
    if minutes:
        out = out + (o_gap[:, None] + t_gap[None, :]) / (5000.0 / 60.0)
    else:
        out = out + o_gap[:, None] + t_gap[None, :]
    out[~reached] = np.nan
    same = np.array([[o.entity_id == t.entity_id for t in targets] for o in origins])
    out[same] = 0.0
    off_road = sorted({origins[k].key for k in np.flatnonzero(o_gap > SNAP_M)} | {targets[k].key for k in np.flatnonzero(t_gap > SNAP_M)})
    return out, {"tiles": net.tiles, "nodes": int(len(net.lon)), "off_road": off_road,
                 "unreachable": int(np.isnan(out).sum()), "snap_max_m": round(float(max(o_gap.max(), t_gap.max())), 1)}


def describe(template: str) -> str:
    return ("road (OpenMapTiles zoom-12 roads from the tile server, every road both ways, "
            "free-flow speeds by class, no traffic)")
