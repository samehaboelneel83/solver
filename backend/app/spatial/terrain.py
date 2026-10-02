"""Elevation and slope per grid cell, from terrain-RGB tiles (GIS 10).

The tile server's TileJSON index (the setting `spatial.tiles_index`) names a
tileset with an `encoding`: each pixel's colour is a height.

- `mapbox`:    height = -10000 + (R*65536 + G*256 + B) * 0.1 m
- `terrarium`: height = R*256 + G + B/256 - 32768 m

A cell's elevation is the mean of heights sampled on a regular grid of points
inside it; its slope, the mean of the gradient magnitudes between neighbouring
samples, in percent. The zoom is chosen so a pixel is about an eighth of the
cell, within what the tileset has. A point on a tile the server does not have
(outside its coverage) gives no height; a cell with none gets no value, and is
counted, rather than a made-up zero.

**Reaching the server.** The setting holds an address for the viewer's
browser, which runs on the host; this runs in a container, where `localhost`
is the container itself. So an address on `localhost` / `127.0.0.1` is tried
as written and then on `host.docker.internal` -- Docker's name for the host --
and the tile addresses are rewritten to whichever answered.
"""

from __future__ import annotations

import gzip
import io
import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from shapely.geometry import Point, Polygon

#: bytes of the resource, or None when the server has no such resource (404).
Fetch = Callable[[str], bytes | None]

TILE = 256
SAMPLES_PER_SIDE = 7
#: A pixel about this fraction of a cell: enough samples to see its slope.
PIXEL_OF_CELL = 1 / 8
LOCAL_HOSTS = {"localhost", "127.0.0.1"}


class TerrainError(ValueError):
    """The terrain cannot be read: named, so the grid form can say why."""


def fetch_bytes(url: str, timeout: float = 10.0) -> bytes | None:
    """GET `url`; None for a 404; gzip undone whether or not it was declared."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 -- an http(s) address, checked by the caller
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def _with_host(url: str, host: str) -> str:
    parts = urlsplit(url)
    netloc = host + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def candidates(url: str) -> list[str]:
    """The address as written, and -- for the host's own name -- as a container reaches the host."""
    host = urlsplit(url).hostname or ""
    return [url, _with_host(url, "host.docker.internal")] if host in LOCAL_HOSTS else [url]


@dataclass
class TerrainSource:
    template: str
    encoding: str
    minzoom: int
    maxzoom: int


def terrain_source(index_url: str, fetch: Fetch = fetch_bytes) -> TerrainSource:
    """The terrain tileset of the index at `index_url`, its tile addresses reachable from here."""
    if not index_url.lower().startswith(("http://", "https://")):
        raise TerrainError(
            "This installation has no terrain map set up, so ground height cannot be read. Ask an administrator to "
            "set it (setting spatial.tiles_index), or import heights as a field of the records.")
    last: Exception | None = None
    for url in candidates(index_url):
        try:
            body = fetch(url)
        except (OSError, ValueError) as exc:
            last = exc
            continue
        if body is None:
            continue
        index = json.loads(body)
        for tileset in index if isinstance(index, list) else []:
            encoding = str(tileset.get("encoding") or "").lower()
            if encoding in ("mapbox", "terrarium") and tileset.get("tiles"):
                template = str(tileset["tiles"][0])
                reached = urlsplit(url).hostname or ""
                if (urlsplit(template).hostname or "") in LOCAL_HOSTS and reached not in LOCAL_HOSTS:
                    template = _with_host(template, reached)
                return TerrainSource(template, encoding, int(tileset.get("minzoom", 0)), int(tileset.get("maxzoom", 12)))
        raise TerrainError(f"the tile index at {index_url} lists no terrain tileset (one with an encoding)")
    raise TerrainError(f"the tile index at {index_url} could not be reached from the server ({last})")


def height_of(rgb: tuple[int, int, int], encoding: str) -> float:
    r, g, b = rgb
    if encoding == "terrarium":
        return r * 256 + g + b / 256 - 32768
    return -10000 + (r * 65536 + g * 256 + b) * 0.1


def zoom_for(size_m: float, latitude: float, source: TerrainSource) -> int:
    """The shallowest zoom whose pixel is at most PIXEL_OF_CELL of the cell, within the tileset's range."""
    ground = 156543.03392 * math.cos(math.radians(latitude))
    for z in range(source.minzoom, source.maxzoom + 1):
        if ground / 2**z <= size_m * PIXEL_OF_CELL:
            return z
    return source.maxzoom


@dataclass
class Sampler:
    """Heights at points, reading each tile once."""

    source: TerrainSource
    zoom: int
    fetch: Fetch = fetch_bytes
    _tiles: dict[tuple[int, int], object] = field(default_factory=dict)

    def _tile(self, x: int, y: int):
        if (x, y) not in self._tiles:
            from PIL import Image

            url = self.source.template.replace("{z}", str(self.zoom)).replace("{x}", str(x)).replace("{y}", str(y))
            body = self.fetch(url)
            self._tiles[(x, y)] = Image.open(io.BytesIO(body)).convert("RGB").load() if body else None
        return self._tiles[(x, y)]

    def height(self, lon: float, lat: float) -> float | None:
        size = TILE * 2**self.zoom
        s = math.sin(math.radians(max(-85.05112878, min(85.05112878, lat))))
        px = (lon + 180) / 360 * size
        py = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * size
        tile = self._tile(int(px // TILE), int(py // TILE))
        if tile is None:
            return None
        return height_of(tile[int(px % TILE), int(py % TILE)], self.source.encoding)


def cell_terrain(cell: Polygon, sampler: Sampler) -> tuple[float, float] | None:
    """(mean elevation m, mean slope %) of a cell given in lon/lat, or None where there is no terrain."""
    minx, miny, maxx, maxy = cell.bounds
    n = SAMPLES_PER_SIDE
    xs = [minx + (maxx - minx) * (i + 0.5) / n for i in range(n)]
    ys = [miny + (maxy - miny) * (j + 0.5) / n for j in range(n)]
    grid: dict[tuple[int, int], float] = {}
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            if cell.contains(Point(x, y)):
                h = sampler.height(x, y)
                if h is not None:
                    grid[(i, j)] = h
    if not grid:
        return None
    lat = (miny + maxy) / 2
    dx = (maxx - minx) / n * 111_320 * math.cos(math.radians(lat))
    dy = (maxy - miny) / n * 110_540
    slopes = []
    for (i, j), h in grid.items():
        east, north = grid.get((i + 1, j)), grid.get((i, j + 1))
        if east is not None and north is not None and dx > 0 and dy > 0:
            slopes.append(math.hypot((east - h) / dx, (north - h) / dy) * 100)
    return sum(grid.values()) / len(grid), (sum(slopes) / len(slopes) if slopes else 0.0)
