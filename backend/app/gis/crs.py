"""Where a drawing is on the Earth (DXF -> GIS, step 2: the coordinate reference system).

A DXF rarely says which CRS its numbers are in. `X = 523450, Y = 3341250`
is a point in Egypt in UTM zone 36N, in the Pacific in zone 1N, and nowhere
at all as degrees. So the CRS is chosen, not assumed, and it is chosen with
the drawing's place shown on a map before anything is stored.

A placement (`Placement`) is one of:

- `{"kind": "epsg", "code": 32636}` -- any CRS in the EPSG registry (UTM
  zones, the Egyptian belts, national grids, WGS 84 degrees...);
- `{"kind": "local", "anchor": [x, y], "lonlat": [lon, lat], "rotation": deg,
  "scale": 1}` -- local engineering coordinates: the drawing point `anchor`
  is at `lonlat`, the drawing's +Y axis is turned `rotation` degrees
  clockwise from north, and lengths are multiplied by `scale`.

In both, `units` says what one drawing unit is in metres (millimetre
drawings of UTM coordinates are common); degrees are never scaled.

`candidates` ranks the likely CRSs for a drawing: the CRS its GEODATA
names, the domain's usual drawing CRS, degrees when the numbers look like
longitude and latitude, the CRSs whose area of use the drawing would fall
in (the Egyptian belts, Web Mercator...), and the UTM zone around a hint.
Each comes with where the drawing would land, so a person can choose by
place, not by code.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

import numpy as np

#: CRSs worth trying on any drawing: their area of use decides whether they are offered.
CURATED = [
    22992, 22993, 22994, 22991,          # Egypt 1907 belts: Red, Purple, Extended Purple, Blue
    3857,                                # Web Mercator
    2039, 28191, 28193,                  # Israel TM Grid, Palestine 1923 grids
    20136, 20137, 20138,                 # Adindan / UTM 36N-38N (Sudan, Ethiopia)
    3395,                                # World Mercator
    27700, 2154, 25832, 25833, 31467,    # British National Grid, Lambert-93, ETRS89 UTM, Gauss-Krueger
]


class PlacementError(ValueError):
    """The placement is not one we can use; the message says why."""


@dataclass(frozen=True)
class Placement:
    kind: str
    code: int | None = None
    anchor: tuple[float, float] = (0.0, 0.0)
    lonlat: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0
    scale: float = 1.0
    units: float = 1.0

    @classmethod
    def parse(cls, data: dict[str, Any], units: float | None) -> "Placement":
        kind = data.get("kind")
        u = float(units) if units else 1.0
        if not (0 < u < 1e6):
            raise PlacementError("units must be a positive number of metres per drawing unit")
        if kind == "epsg":
            try:
                code = int(data["code"])
                info = crs_info(code)
            except Exception as exc:  # noqa: BLE001 -- pyproj's CRSError, a missing or bad code
                raise PlacementError(f"EPSG:{data.get('code')} is not a coordinate system we know") from exc
            if info["geographic"]:
                u = 1.0
            return cls("epsg", code=code, units=u)
        if kind == "local":
            try:
                anchor = (float(data["anchor"][0]), float(data["anchor"][1]))
                lonlat = (float(data["lonlat"][0]), float(data["lonlat"][1]))
                rotation = float(data.get("rotation", 0.0))
                scale = float(data.get("scale", 1.0))
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                raise PlacementError("a local placement needs anchor [x, y], lonlat [lon, lat], rotation and scale") from exc
            if not (-180 <= lonlat[0] <= 180 and -90 <= lonlat[1] <= 90):
                raise PlacementError("the anchor's longitude and latitude are out of range")
            if not (0 < scale < 1e6):
                raise PlacementError("scale must be positive")
            return cls("local", anchor=anchor, lonlat=lonlat, rotation=rotation, scale=scale, units=u)
        raise PlacementError("a placement is {kind: 'epsg', code} or {kind: 'local', anchor, lonlat, rotation, scale}")

    def to_json(self) -> dict[str, Any]:
        if self.kind == "epsg":
            return {"kind": "epsg", "code": self.code, "units": self.units, "name": crs_info(self.code)["name"]}
        return {"kind": "local", "anchor": list(self.anchor), "lonlat": list(self.lonlat), "rotation": self.rotation,
                "scale": self.scale, "units": self.units}

    def transformer(self) -> Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
        """Drawing coordinates (arrays) to longitude and latitude (arrays)."""
        from pyproj import Transformer

        if self.kind == "epsg":
            t = _to_wgs84(self.code)
            u = self.units
            return lambda x, y: t.transform(np.asarray(x) * u, np.asarray(y) * u)
        lon0, lat0 = self.lonlat
        t = Transformer.from_crs(f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +x_0=0 +y_0=0 +units=m +ellps=WGS84",
                                 "EPSG:4326", always_xy=True)
        k = self.units * self.scale
        theta = math.radians(self.rotation)
        c, s = math.cos(theta), math.sin(theta)
        ax, ay = self.anchor

        def run(x, y):
            dx, dy = (np.asarray(x) - ax) * k, (np.asarray(y) - ay) * k
            # Clockwise by `rotation`: the drawing's +Y turns from north towards east.
            return t.transform(dx * c + dy * s, -dx * s + dy * c)

        return run


@lru_cache(maxsize=256)
def _to_wgs84(code: int):
    from pyproj import Transformer

    return Transformer.from_crs(f"EPSG:{code}", "EPSG:4326", always_xy=True)


@lru_cache(maxsize=2048)
def crs_info(code: int) -> dict[str, Any]:
    from pyproj import CRS

    crs = CRS.from_epsg(code)
    area = crs.area_of_use
    unit = crs.axis_info[0].unit_name if crs.axis_info else ""
    return {"code": code, "name": crs.name, "geographic": crs.is_geographic, "unit": unit,
            "area": area.name if area else None, "bounds": list(area.bounds) if area else None}


def search(query: str, limit: int = 30) -> list[dict[str, Any]]:
    """CRSs in the EPSG registry whose code or name matches `query`."""
    q = query.strip().lower().removeprefix("epsg:")
    if not q:
        return []
    out = []
    for info in _registry():
        if q == info.code or q in info.name.lower() or (info.area_of_use and q in info.area_of_use.name.lower()):
            out.append({"code": int(info.code), "name": info.name,
                        "area": info.area_of_use.name if info.area_of_use else None,
                        "type": info.type.name.lower().replace("_crs", "")})
            if len(out) >= limit:
                break
    out.sort(key=lambda r: (str(r["code"]) != q, r["code"]))
    return out


@lru_cache(maxsize=1)
def _registry():
    from pyproj.database import query_crs_info
    from pyproj.enums import PJType

    return [i for i in query_crs_info(auth_name="EPSG", pj_types=[PJType.PROJECTED_CRS, PJType.GEOGRAPHIC_2D_CRS])
            if not i.deprecated]


def utm_epsg(lon: float, lat: float) -> int:
    zone = min(60, int((lon + 180) // 6) + 1)
    return (32600 if lat >= 0 else 32700) + zone


def _inside(lon: float, lat: float, bounds, margin: float = 0.5) -> bool:
    if bounds is None or not (math.isfinite(lon) and math.isfinite(lat)):
        return False
    w, s, e, n = bounds
    if w > e:  # crosses the antimeridian
        return (lon >= w - margin or lon <= e + margin) and s - margin <= lat <= n + margin
    return w - margin <= lon <= e + margin and s - margin <= lat <= n + margin


def where(code: int, x: float, y: float, units: float = 1.0) -> tuple[float, float] | None:
    try:
        u = 1.0 if crs_info(code)["geographic"] else units
        lon, lat = _to_wgs84(code).transform(x * u, y * u)
    except Exception:  # noqa: BLE001
        return None
    if not (math.isfinite(lon) and math.isfinite(lat)) or abs(lat) > 90:
        return None
    return float(lon), float(lat)


def candidates(extent, unit_metres: float | None, *, geodata: dict[str, Any] | None = None,
               usual: int | None = None, near: tuple[float, float] | None = None) -> list[dict[str, Any]]:
    """The likely placements of a drawing, best first, each with where it would land."""
    if extent is None:
        return []
    cx, cy = (extent[0] + extent[2]) / 2, (extent[1] + extent[3]) / 2
    units = unit_metres or 1.0
    out: list[dict[str, Any]] = []
    seen: set[int] = set()

    def offer(code: int, reason: str, score: float) -> None:
        if code in seen:
            return
        try:
            info = crs_info(code)
        except Exception:  # noqa: BLE001
            return
        at = where(code, cx, cy, units)
        if at is None:
            return
        seen.add(code)
        fits = _inside(at[0], at[1], info["bounds"])
        out.append({"placement": {"kind": "epsg", "code": code}, "name": info["name"], "area": info["area"],
                    "reason": reason if fits else f"{reason}; but the drawing would fall outside its area of use",
                    "centre": [round(at[0], 6), round(at[1], 6)], "fits": fits, "score": score + (1 if fits else -2)})

    if geodata and geodata.get("epsg"):
        offer(int(geodata["epsg"]), "the drawing's own geographic location (GEODATA) names it", 10)
    if usual:
        offer(int(usual), "the coordinate system this domain's drawings are usually in", 8)
    degrees = all(abs(v) <= 180 for v in (extent[0], extent[2])) and all(abs(v) <= 90 for v in (extent[1], extent[3]))
    if degrees and (extent[2] - extent[0]) < 30:
        offer(4326, "the numbers look like longitude and latitude in degrees", 7 if unit_metres is None else 3)
    big = max(abs(cx), abs(cy)) * units > 1000
    if big:
        for code in CURATED:
            try:
                info = crs_info(code)
            except Exception:  # noqa: BLE001
                continue
            at = where(code, cx, cy, units)
            if at and _inside(at[0], at[1], info["bounds"], margin=0.0):
                bounds = info["bounds"] or [0, 0, 0, 0]
                if bounds[2] - bounds[0] > 300:
                    # A world-wide system fits any numbers: offered last, and said so.
                    offer(code, "a world-wide system: the numbers fit it, which says little -- check the place", 0)
                else:
                    offer(code, f"the drawing falls inside its area of use ({info['area']})", 4)
        e, n = cx * units, cy * units
        if 100_000 <= e <= 900_000 and 0 <= n <= 9_400_000:
            if near:
                offer(utm_epsg(*near), "the UTM zone around this domain's other maps", 6)
    out.sort(key=lambda c: -c["score"])
    return out


def utm_zones(extent, unit_metres: float | None) -> list[dict[str, Any]]:
    """Every UTM zone, north and south, with where the drawing would land in each:
    the numbers alone cannot tell the zone, the place can."""
    if extent is None:
        return []
    cx, cy = (extent[0] + extent[2]) / 2, (extent[1] + extent[3]) / 2
    units = unit_metres or 1.0
    e, n = cx * units, cy * units
    if not (100_000 <= e <= 900_000 and 0 <= n <= 10_000_000):
        return []
    zones = []
    for hemi, base in (("N", 32600), ("S", 32700)):
        for zone in range(1, 61):
            at = where(base + zone, cx, cy, units)
            if at:
                zones.append({"code": base + zone, "zone": f"{zone}{hemi}", "centre": [round(at[0], 5), round(at[1], 5)]})
    return zones
