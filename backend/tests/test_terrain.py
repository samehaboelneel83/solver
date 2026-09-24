"""Elevation and slope per cell from terrain-RGB tiles, on surfaces whose answers are known (GIS 10)."""

from __future__ import annotations

import io
import json
import math

import pytest
from PIL import Image
from shapely.geometry import box

from app.spatial.terrain import (
    Sampler,
    TerrainError,
    TerrainSource,
    candidates,
    cell_terrain,
    height_of,
    terrain_source,
    zoom_for,
)

TEMPLATE = "http://localhost:8080/data/egypt_terrain/{z}/{x}/{y}.png"


def _encode_mapbox(h: float) -> tuple[int, int, int]:
    v = round((h + 10000) * 10)
    return (v >> 16) & 255, (v >> 8) & 255, v & 255


def _server(surface, covered=lambda x, y: True, index_hosts=("localhost",)):
    """A fake tile server: `surface(lon, lat)` in metres, as mapbox terrain-RGB PNGs; the index as JSON."""
    calls: list[str] = []

    def fetch(url: str) -> bytes | None:
        calls.append(url)
        if url.endswith("/index.json"):
            host = url.split("/")[2].split(":")[0]
            if host not in index_hosts:
                raise OSError("connection refused")
            return json.dumps([
                {"id": "egypt_satellite", "tiles": ["http://localhost:8080/data/egypt_satellite/{z}/{x}/{y}.jpg"], "format": "jpg"},
                {"id": "egypt_terrain", "tiles": [TEMPLATE], "encoding": "mapbox", "minzoom": 0, "maxzoom": 12},
            ]).encode()
        parts = url.split("/")
        z, x, y = int(parts[-3]), int(parts[-2]), int(parts[-1].split(".")[0])
        if not covered(x, y):
            return None
        size = 256 * 2**z
        image = Image.new("RGB", (256, 256))
        pixels = image.load()
        for i in range(256):
            lon = (x * 256 + i + 0.5) / size * 360 - 180
            for j in range(256):
                n = math.pi - 2 * math.pi * (y * 256 + j + 0.5) / size
                lat = math.degrees(math.atan(math.sinh(n)))
                pixels[i, j] = _encode_mapbox(surface(lon, lat))
        out = io.BytesIO()
        image.save(out, "PNG")
        return out.getvalue()

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


SOURCE = TerrainSource(TEMPLATE, "mapbox", 0, 12)
#: 1 km square near Giza, in lon/lat.
CELL = box(31.25, 30.05, 31.25 + 1000 / (111_320 * math.cos(math.radians(30.0545))), 30.05 + 1000 / 110_540)


def test_the_two_encodings_read_by_hand():
    assert height_of((1, 134, 160), "mapbox") == pytest.approx(0.0)
    assert height_of((1, 134, 170), "mapbox") == pytest.approx(1.0)
    assert height_of((128, 0, 0), "terrarium") == pytest.approx(0.0)
    assert height_of((128, 100, 128), "terrarium") == pytest.approx(100.5)


def test_a_container_reaches_the_host_under_its_own_name():
    assert candidates("http://localhost:8080/index.json") == [
        "http://localhost:8080/index.json", "http://host.docker.internal:8080/index.json"]
    assert candidates("https://tiles.example.org/index.json") == ["https://tiles.example.org/index.json"]


def test_the_terrain_tileset_is_found_and_its_tiles_rewritten_to_the_host_that_answered():
    fetch = _server(lambda lon, lat: 0, index_hosts=("host.docker.internal",))
    source = terrain_source("http://localhost:8080/index.json", fetch)
    assert source.encoding == "mapbox" and (source.minzoom, source.maxzoom) == (0, 12)
    assert source.template == "http://host.docker.internal:8080/data/egypt_terrain/{z}/{x}/{y}.png"


def test_what_cannot_be_read_is_named():
    with pytest.raises(TerrainError, match="not set"):
        terrain_source("", _server(lambda lon, lat: 0))
    with pytest.raises(TerrainError, match="could not be reached"):
        terrain_source("http://localhost:8080/index.json", _server(lambda lon, lat: 0, index_hosts=()))
    no_terrain = lambda url: json.dumps([{"id": "topo", "tiles": ["http://x/{z}/{x}/{y}.jpg"]}]).encode()  # noqa: E731
    with pytest.raises(TerrainError, match="no terrain tileset"):
        terrain_source("http://tiles.example.org/index.json", no_terrain)


def test_the_zoom_puts_about_eight_pixels_across_a_cell():
    # Ground resolution at 30 N: 156543.03 * cos(30) = 135,570 m per pixel at z0.
    # A 1 km cell wants pixels of at most 125 m: 2^z >= 1084.6, so z = 11 (66 m).
    assert zoom_for(1000, 30.0, SOURCE) == 11
    assert zoom_for(20, 30.0, SOURCE) == 12  # deeper than the tileset has: its deepest


def test_a_plane_rising_eastward_has_its_height_at_the_centre_and_its_slope():
    # 1000 m per degree of longitude: at 30.05 N a degree is 111,320 * cos(30.05) = 96,368 m,
    # so the slope is 1000 / 96,368 = 1.038 %.
    surface = lambda lon, lat: 50 + 1000 * (lon - 31.2)  # noqa: E731
    sampler = Sampler(SOURCE, zoom_for(1000, 30.05, SOURCE), _server(surface))
    elevation, slope = cell_terrain(CELL, sampler)
    assert elevation == pytest.approx(surface(CELL.centroid.x, CELL.centroid.y), abs=1.0)
    assert slope == pytest.approx(1000 / (111_320 * math.cos(math.radians(30.05))) * 100, abs=0.15)


def test_flat_ground_has_no_slope_and_each_tile_is_read_once():
    fetch = _server(lambda lon, lat: 120.0)
    sampler = Sampler(SOURCE, 11, fetch)
    elevation, slope = cell_terrain(CELL, sampler)
    assert elevation == pytest.approx(120.0, abs=0.1) and slope == pytest.approx(0.0, abs=0.01)
    tiles = [url for url in fetch.calls if url.endswith(".png")]
    assert len(tiles) == len(set(tiles))


def test_a_cell_outside_the_coverage_gets_no_value_rather_than_zero():
    sampler = Sampler(SOURCE, 11, _server(lambda lon, lat: 10.0, covered=lambda x, y: False))
    assert cell_terrain(CELL, sampler) is None
