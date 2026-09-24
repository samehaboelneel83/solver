"""From the domain's CRS to metres and back (spatial spec §2): the UTM zone of
the boundary's centroid, so "a 500 m cell" is 500 m on the ground."""

from __future__ import annotations

from pyproj import CRS, Transformer
from shapely.ops import transform

#: One UTM zone is six degrees of longitude wide.
MAX_WIDTH_DEG = 6.0


class OutOfRange(ValueError):
    """A boundary one UTM zone cannot hold."""


def utm_epsg(lon: float, lat: float) -> int:
    zone = min(60, int((lon + 180) // 6) + 1)
    return (32600 if lat >= 0 else 32700) + zone


class Projection:
    """Forward into the metres of the UTM zone around `around` (given in
    `crs`), and back into `crs`."""

    def __init__(self, crs: int, around: tuple[float, float]):
        source = CRS.from_epsg(crs)
        lon, lat = Transformer.from_crs(source, CRS.from_epsg(4326), always_xy=True).transform(*around)
        self.epsg_metres = utm_epsg(lon, lat)
        metres = CRS.from_epsg(self.epsg_metres)
        self._forward = Transformer.from_crs(source, metres, always_xy=True)
        self._back = Transformer.from_crs(metres, source, always_xy=True)

    def forward(self, geom):
        return transform(self._forward.transform, geom)

    def back(self, geom):
        return transform(self._back.transform, geom)

    def forward_point(self, point: tuple[float, float]) -> tuple[float, float]:
        return self._forward.transform(*point)


def lonlat_bounds(geom, crs: int) -> tuple[float, float, float, float]:
    """A geometry's bounds in degrees, whatever CRS it is written in."""
    to = Transformer.from_crs(CRS.from_epsg(crs), CRS.from_epsg(4326), always_xy=True)
    minx, miny, maxx, maxy = geom.bounds
    corners = [to.transform(x, y) for x in (minx, maxx) for y in (miny, maxy)]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    return min(xs), min(ys), max(xs), max(ys)


def check_extent(bounds: tuple[float, float, float, float]) -> None:
    """Refuse a boundary crossing longitude 180 or wider than one UTM zone
    (spatial plan, Review Focus 1): one projection could not hold it true."""
    min_lon, _, max_lon, _ = bounds
    if max_lon - min_lon > 180:
        raise OutOfRange("the boundary crosses longitude 180; split it at the antimeridian")
    if max_lon - min_lon > MAX_WIDTH_DEG:
        raise OutOfRange(
            f"the boundary is {max_lon - min_lon:.1f} degrees of longitude wide; one grid covers at most "
            f"{MAX_WIDTH_DEG:.0f} (one UTM zone) -- split it into parts"
        )
