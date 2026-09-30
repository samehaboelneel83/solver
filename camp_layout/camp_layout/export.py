"""GIS output: the input and the layout as GeoJSON, and a map to look at them.

Two coordinate systems are written:

- local metres (x east, y north), the model's own -- `*_local.geojson`;
- WGS84 longitude/latitude, the camp placed at `problem.origin_lonlat` with an
  azimuthal equidistant projection -- `*_wgs84.geojson`, for QGIS,
  geojson.io, kepler.gl or any web map over imagery.

Every feature carries a `layer` property (boundary, door, door_zone, obstacle,
prohibited, placement_zone, bed, corridor, path) and what a reader needs to
know about it. `viewer.html` is a self-contained map of both.
"""
from __future__ import annotations

import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, mapping
from shapely.ops import transform, unary_union

from .geometry import Geometry
from .pipeline import Run


def _feature(geom, layer: str, **props):
    return {"type": "Feature", "geometry": mapping(geom), "properties": {"layer": layer, **props}}


def input_features(run: Run) -> list[dict]:
    p = run.problem
    geo = Geometry(p)
    feats = [_feature(geo.camp, "boundary", name=p.name, area_m2=round(geo.camp.area, 1))]
    for z in p.zones:
        feats.append(_feature(geo.zone_polygon(z, z.max_depth), "door_zone_max", door=z.door,
                              depth_m=z.max_depth, note="the most this zone may grow"))
        feats.append(_feature(geo.zone_polygon(z, z.depth), "door_zone", door=z.door, depth_m=z.depth,
                              area_m2=round(geo.zone_polygon(z, z.depth).area, 1), area_per_bed_m2=z.area_per_bed))
    for d in p.doors:
        (ax, ay), (bx, by) = d.a, d.b
        feats.append(_feature(geo.door_frames[d.id], "door", id=d.id, width_m=round(abs(bx - ax) + abs(by - ay), 2),
                              capacity=d.capacity))
    for pz in p.placement_zones:
        allowed = [t.id for t in p.bed_types if t.zone == pz.id]
        feats.append(_feature(geo.placement_zones[pz.id], "placement_zone", id=pz.id, bed_types=", ".join(allowed)))
    for pr in p.prohibited:
        feats.append(_feature(geo.prohibited[pr.id], "prohibited", id=pr.id, note="no beds; people may walk"))
    for o in p.obstacles:
        feats.append(_feature(geo.obstacles[o.id], "obstacle", id=o.id, kind=o.kind,
                              area_m2=round(geo.obstacles[o.id].area, 1)))
    return feats


def output_features(run: Run) -> list[dict]:
    p, lay, v = run.problem, run.layout, run.validation
    geo = Geometry(p)
    feats = [_feature(geo.camp, "boundary", name=p.name)]
    for z in p.zones:
        depth = lay.zone_depth.get(z.door, z.depth)
        poly = geo.zone_polygon(z, depth)
        feats.append(_feature(poly, "door_zone", door=z.door, depth_m=depth, grown_m=round(depth - z.depth, 2),
                              area_m2=round(poly.area, 1), beds_served=v.loads.get(z.door, 0)))
    corridor = unary_union([lay.corridor]).difference(unary_union([geo.zone_polygon(z, lay.zone_depth.get(z.door, z.depth))
                                                                    for z in p.zones]))
    if not corridor.is_empty:
        feats.append(_feature(corridor, "corridor", area_m2=round(corridor.area, 1),
                              min_width_m=p.corridor.min_width))
    for d in p.doors:
        feats.append(_feature(geo.door_frames[d.id], "door", id=d.id, capacity=d.capacity,
                              beds_served=v.loads.get(d.id, 0)))
    for pr in p.prohibited:
        feats.append(_feature(geo.prohibited[pr.id], "prohibited", id=pr.id))
    for o in p.obstacles:
        feats.append(_feature(geo.obstacles[o.id], "obstacle", id=o.id, kind=o.kind))
    for bid, line in v.paths.items():
        feats.append(_feature(line, "path", bed=bid, door=v.door_of.get(bid), walk_m=v.walk.get(bid)))
    types = {t.id: t for t in p.bed_types}
    for b in lay.beds:
        t = types[b.bed_type]
        feats.append(_feature(b.polygon, "bed", id=b.id, bed_type=b.bed_type,
                              size=f"{b.length:g} x {b.width:g} m", resized=(b.length, b.width) != (t.length, t.width),
                              rotated=b.rotated, door=v.door_of.get(b.id), walk_m=v.walk.get(b.id)))
    return feats


def report(run: Run) -> dict:
    lay, v = run.layout, run.validation
    counts: dict[str, int] = {}
    for b in lay.beds:
        counts[b.bed_type] = counts.get(b.bed_type, 0) + 1
    return {
        "camp": run.problem.name,
        "solver": lay.solver,
        "beds": len(lay.beds),
        "beds_by_type": counts,
        "resized_beds": sum(1 for b in lay.beds
                            if (b.length, b.width) != (run.problem.bed_type(b.bed_type).length, run.problem.bed_type(b.bed_type).width)),
        "stage0_beds": int(sum(run.start[i] for i in range(len(run.start)) if run.model.vars[i].name.startswith("y["))),
        "objectives": lay.objectives,
        "stages": lay.stages,
        "zone_depth_m": lay.zone_depth,
        "validation": v.summary(),
        "grid": run.grid.stats(),
        "model": {k: lay.model_size[k] for k in ("variables", "constraints", "nonzeros")},
        "seconds": {k: round(s, 1) for k, s in run.seconds.items()},
    }


def to_wgs84(features: list[dict], origin_lonlat) -> list[dict]:
    lon0, lat0 = origin_lonlat
    t = Transformer.from_crs(f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +x_0=0 +y_0=0 +units=m +ellps=WGS84",
                             "EPSG:4326", always_xy=True)
    from shapely.geometry import shape
    out = []
    for f in features:
        g = transform(lambda x, y, z=None: t.transform(x, y), shape(f["geometry"]))
        out.append({**f, "geometry": mapping(g)})
    return out


def _collection(features, crs_note):
    return {"type": "FeatureCollection", "name": crs_note, "features": features}


def write(run: Run, folder: str | Path) -> dict[str, Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    inp, out = input_features(run), output_features(run)
    files = {
        "input_local": folder / "input_local.geojson",
        "output_local": folder / "output_local.geojson",
        "input_wgs84": folder / "input_wgs84.geojson",
        "output_wgs84": folder / "output_wgs84.geojson",
        "report": folder / "report.json",
        "viewer": folder / "viewer.html",
    }
    files["input_local"].write_text(json.dumps(_collection(inp, "camp input, local metres")))
    files["output_local"].write_text(json.dumps(_collection(out, "camp layout, local metres")))
    files["input_wgs84"].write_text(json.dumps(_collection(to_wgs84(inp, run.problem.origin_lonlat), "camp input, WGS84")))
    files["output_wgs84"].write_text(json.dumps(_collection(to_wgs84(out, run.problem.origin_lonlat), "camp layout, WGS84")))
    rep = report(run)
    files["report"].write_text(json.dumps(rep, indent=2, default=str))
    template = (Path(__file__).parent / "viewer_template.html").read_text()
    data = {"input": _collection(inp, "input"), "output": _collection(out, "output"), "report": rep,
            "origin": list(run.problem.origin_lonlat)}
    files["viewer"].write_text(template.replace("/*__DATA__*/null", json.dumps(data, default=str, separators=(",", ":"))))
    return files
