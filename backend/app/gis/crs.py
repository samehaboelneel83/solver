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


#: Roughly where a site is: a country's box (west, south, east, north). The CRSs whose area of use
#: meets it -- national grids, UTM zones on the local datums -- are tried, and those that put the
#: drawing inside the country are offered. A position given instead is a box 1.5° around it.
REGIONS: dict[str, tuple[float, float, float, float]] = {
    "Bahrain": (50.3, 25.8, 50.7, 26.3),
    "Cyprus": (32.2, 34.5, 34.6, 35.7),
    "Egypt": (24.7, 22.0, 36.9, 31.7),
    "Iran": (44.0, 25.0, 63.4, 39.8),
    "Iraq": (38.8, 29.0, 48.6, 37.4),
    "Israel": (34.2, 29.4, 35.9, 33.4),
    "Jordan": (34.9, 29.2, 39.3, 33.4),
    "Kuwait": (46.5, 28.5, 48.5, 30.1),
    "Lebanon": (35.1, 33.0, 36.7, 34.7),
    "Libya": (9.3, 19.5, 25.2, 33.2),
    "Oman": (52.0, 16.6, 59.9, 26.4),
    "Palestine": (34.2, 31.2, 35.6, 32.6),
    "Qatar": (50.7, 24.5, 51.7, 26.2),
    "Saudi Arabia": (34.5, 16.3, 55.7, 32.2),
    "Sudan": (21.8, 8.6, 38.6, 22.3),
    "Syria": (35.7, 32.3, 42.4, 37.3),
    "Turkey": (25.6, 35.8, 44.8, 42.1),
    "United Arab Emirates": (51.5, 22.6, 56.4, 26.1),
    "Yemen": (42.5, 12.1, 54.0, 19.0),
}


def region_box(region: str | None = None, point: tuple[float, float] | None = None):
    """The box to search: a named country's, or 1.5° around a position (lon, lat)."""
    if point is not None:
        lon, lat = point
        return (lon - 1.5, lat - 1.5, lon + 1.5, lat + 1.5)
    return REGIONS.get(region or "")


def regional(extent, unit_metres: float | None, box, point: tuple[float, float] | None = None,
             label: str = "there", limit: int = 15, point_label: str = "the position given") -> list[dict[str, Any]]:
    """Every projected CRS whose area of use meets `box` that puts the drawing inside it, best first.

    Best: nearest the given position (when there is one), then not on a superseded datum (WGS 72),
    then the most local (smallest area of use)."""
    if extent is None or box is None:
        return []
    from pyproj.aoi import AreaOfInterest
    from pyproj.database import query_crs_info
    from pyproj.enums import PJType

    cx, cy = (extent[0] + extent[2]) / 2, (extent[1] + extent[3]) / 2
    units = unit_metres or 1.0
    w, s, e, n = box
    found = []
    for info in query_crs_info(auth_name="EPSG", pj_types=[PJType.PROJECTED_CRS],
                               area_of_interest=AreaOfInterest(w, s, e, n), contains=False):
        area = info.area_of_use
        if info.deprecated or area is None:
            continue
        # Regional systems only: a continent-wide one fits anything (an area across the antimeridian is wide).
        width = area.east - area.west + (360 if area.west > area.east else 0)
        if width > 40:
            continue
        code = int(info.code)
        at = where(code, cx, cy, units)
        if at is None or not _inside(at[0], at[1], box, margin=0.3) or \
                not _inside(at[0], at[1], (area.west, area.south, area.east, area.north), margin=0.1):
            continue
        # Modern WGS 84 first, a superseded datum (WGS 72) last.
        datum = 0 if "WGS 84" in info.name else 3 if "WGS 72" in info.name else 1
        far = _km(at, point) if point else 0.0
        found.append(((round(far / 25), datum, width), code, info.name, area.name, at, far))
    found.sort(key=lambda f: f[0])
    # One entry per place: systems that put the drawing within 3 km of each other differ by datum,
    # not by where the site is; the best is offered, the others named beside it.
    groups: list[dict[str, Any]] = []
    for _, code, name, area, at, far in found:
        home = next((g for g in groups if _km(g["at"], at) < 3), None)
        if home is not None:
            home["also"].append(f"{name} (EPSG:{code})")
            continue
        short = area if len(area) <= 70 else area[:67] + "..."
        groups.append({"at": at, "also": [], "offer": {
            "placement": {"kind": "epsg", "code": code}, "name": name, "area": area,
            "reason": (f"lands {far:.0f} km from {point_label}" if point else f"lands in {label}")
                      + f", inside its area of use ({short})",
            "centre": [round(at[0], 6), round(at[1], 6)], "fits": True, "score": 7 - len(groups) * 0.01}})
    # Sure, so a form may choose it unasked: the only place in the region, or the nearest to a position when
    # that is close (50 km) and the next is not.
    if groups:
        first = groups[0]["offer"]
        lone = len(groups) == 1
        near_one = point is not None and _km(groups[0]["at"], point) < 50 and \
            (len(groups) == 1 or _km(groups[1]["at"], point) >= 50)
        first["sure"] = lone or near_one
    out = []
    for g in groups[:limit]:
        offer = g["offer"]
        if g["also"]:
            offer["also"] = g["also"]
            offer["reason"] += f"; {len(g['also'])} other datum{'s' if len(g['also']) > 1 else ''} put it within 3 km"
        out.append(offer)
    return out


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, h)))


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


@lru_cache(maxsize=2048)
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
               usual: int | None = None, near: tuple[float, float] | None = None,
               region: str | None = None, point: tuple[float, float] | None = None) -> list[dict[str, Any]]:
    """The likely placements of a drawing, best first, each with where it would land.
    `region` (a country of REGIONS) or `point` (lon, lat) says roughly where the site is."""
    if extent is None:
        return []
    box = region_box(region, point)
    if box is not None:
        # A position given wins; else the domain's other maps break a tie between places in the country.
        if near is not None and not _inside(near[0], near[1], box, margin=0.5):
            near = None  # the domain's other maps are elsewhere: no help here
        hint, hint_label = (point, "the position given") if point else (near, "this domain's other maps")
        local = regional(extent, unit_metres, box, hint, label=region or "the place given", point_label=hint_label)
        seen_codes = {c["placement"]["code"] for c in local}
        # Beside them: the drawing's own GEODATA and the domain's usual system, and others only if they
        # too put the drawing in the place given.
        rest = [c for c in candidates(extent, unit_metres, geodata=geodata, usual=usual, near=near)
                if c["placement"]["code"] not in seen_codes
                and (c["score"] >= 8 or _inside(c["centre"][0], c["centre"][1], box, margin=0.3))]
        return sorted(rest + local, key=lambda c: -c["score"])
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
                    "centre": [round(at[0], 6), round(at[1], 6)], "fits": fits, "score": score + (1 if fits else -2),
                    "sure": fits and score >= 6})

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
