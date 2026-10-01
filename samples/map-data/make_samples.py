"""Make the sample drawings in this folder (see README.md).

    cd backend && PYTHONPATH=camp_layout python ../samples/map-data/make_samples.py

mina-camp-utm37n.dxf  the engine's complex example ("Irregular camp, four doors")
                      as a surveyed drawing: metres, UTM zone 37N (EPSG:32637),
                      at Mina, Makkah; camp layers plus roads and notes
small-room-mm.dxf     the small example in millimetres with no coordinate system;
                      its door is a block (a leaf and its swing)
mina-camp.geojson     the Mina camp again as GeoJSON (WGS 84), a `layer` property
                      on each feature naming its layer as in the DXF
"""
from __future__ import annotations

from pathlib import Path

import ezdxf
from camp_layout import examples

HERE = Path(__file__).resolve().parent
# Grid metres of the camp's lower-left corner: Mina, about 21.413 N, 39.893 E.
E0, N0 = 592_540.0, 2_368_100.0


def at(p) -> tuple[float, float]:
    return (E0 + p[0], N0 + p[1])


def mm(p) -> tuple[float, float]:
    return (p[0] * 1000.0, p[1] * 1000.0)


def _label(msp, text: str, at, layer: str, height: float) -> None:
    msp.add_text(text, height=height, dxfattribs={"layer": layer}).set_placement(at)


def mina_camp(path: Path) -> None:
    camp = examples.complex_camp()
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    msp = doc.modelspace()
    for name, colour in (("CAMP_BOUNDARY", 7), ("DOORS", 30), ("OBSTACLES", 8), ("NO_BEDS", 1),
                         ("ZONE_MEDICAL_AREA", 6), ("ROADS", 9), ("NOTES", 5)):
        doc.layers.add(name, color=colour)

    msp.add_lwpolyline([at(p) for p in camp.boundary], close=True, dxfattribs={"layer": "CAMP_BOUNDARY"})
    for d in camp.doors:
        msp.add_line(at(d.a), at(d.b), dxfattribs={"layer": "DOORS"})
        mid = ((d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2)
        _label(msp, d.id, at(mid), "DOORS", 0.4)
    for o in camp.obstacles:
        if o.id == "water-tank":
            # Drawn as a true circle: the reader flattens it.
            xs, ys = [p[0] for p in o.ring], [p[1] for p in o.ring]
            c = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
            msp.add_circle(at(c), (max(xs) - min(xs)) / 2, dxfattribs={"layer": "OBSTACLES"})
        else:
            msp.add_lwpolyline([at(p) for p in o.ring], close=True, dxfattribs={"layer": "OBSTACLES"})
            xs, ys = [p[0] for p in o.ring], [p[1] for p in o.ring]
            c = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
        _label(msp, o.id, at(c), "OBSTACLES", 0.3)
    for p in camp.prohibited:
        msp.add_lwpolyline([at(q) for q in p.ring], close=True, dxfattribs={"layer": "NO_BEDS"})
        xs, ys = [q[0] for q in p.ring], [q[1] for q in p.ring]
        _label(msp, p.id, at(((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)), "NO_BEDS", 0.3)
    for z in camp.placement_zones:
        msp.add_lwpolyline([at(q) for q in z.ring], close=True, dxfattribs={"layer": "ZONE_MEDICAL_AREA"})

    # Context the camp reader leaves alone, and Map data imports as layers of its own.
    msp.add_lwpolyline([at((-8, -6)), at((48, -6)), at((48, 34)), at((-8, 34))], close=True,
                       dxfattribs={"layer": "ROADS"})
    msp.add_line(at((-8, 14)), at((-30, 14)), dxfattribs={"layer": "ROADS"})
    msp.add_mtext("Test camp, Mina\\PUTM 37N (EPSG:32637), metres",
                  dxfattribs={"layer": "NOTES", "char_height": 0.8}).set_location(at((0, 31)))
    doc.saveas(path)


def small_room(path: Path) -> None:
    camp = examples.small_camp()
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    msp = doc.modelspace()
    for name, colour in (("CAMP_BOUNDARY", 7), ("DOORS", 30), ("OBSTACLES", 8)):
        doc.layers.add(name, color=colour)
    msp.add_lwpolyline([mm(p) for p in camp.boundary], close=True, dxfattribs={"layer": "CAMP_BOUNDARY"})

    (door,) = camp.doors
    width = (door.b[0] - door.a[0]) * 1000.0
    block = doc.blocks.new("DOOR_SWING")
    block.add_line((0, 0), (0, width), dxfattribs={"layer": "0"})  # the leaf, open
    block.add_arc((0, 0), width, 0, 90, dxfattribs={"layer": "0"})  # its swing
    msp.add_blockref("DOOR_SWING", mm(door.a), dxfattribs={"layer": "DOORS"})
    _label(msp, door.id, (mm(door.a)[0] + width / 2, -400.0), "DOORS", 250)

    for o in camp.obstacles:
        msp.add_lwpolyline([mm(p) for p in o.ring], close=True, dxfattribs={"layer": "OBSTACLES"})
        xs, ys = [p[0] for p in o.ring], [p[1] for p in o.ring]
        _label(msp, o.id, mm(((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)), "OBSTACLES", 200)
    doc.saveas(path)


def mina_geojson(path: Path) -> None:
    """The Mina drawing's camp layers as GeoJSON in longitude and latitude."""
    import json

    from pyproj import Transformer

    camp = examples.complex_camp()
    t = Transformer.from_crs("EPSG:32637", "EPSG:4326", always_xy=True)

    def lonlat(p) -> list[float]:
        lon, lat = t.transform(*at(p))
        return [round(lon, 8), round(lat, 8)]

    def ring(points) -> list[list[float]]:
        pts = [lonlat(p) for p in points]
        return pts + [pts[0]]

    def feature(layer: str, geometry: dict, **props) -> dict:
        return {"type": "Feature", "properties": {"layer": layer, **props}, "geometry": geometry}

    feats = [feature("CAMP_BOUNDARY", {"type": "Polygon", "coordinates": [ring(camp.boundary)]}, name=camp.name)]
    feats += [feature("DOORS", {"type": "LineString", "coordinates": [lonlat(d.a), lonlat(d.b)]}, name=d.id)
              for d in camp.doors]
    feats += [feature("OBSTACLES", {"type": "Polygon", "coordinates": [ring(o.ring)]}, name=o.id, kind=o.kind)
              for o in camp.obstacles]
    feats += [feature("NO_BEDS", {"type": "Polygon", "coordinates": [ring(p.ring)]}, name=p.id) for p in camp.prohibited]
    feats += [feature("ZONE_MEDICAL_AREA", {"type": "Polygon", "coordinates": [ring(z.ring)]}, name=z.id)
              for z in camp.placement_zones]
    path.write_text(json.dumps({"type": "FeatureCollection", "name": camp.name, "features": feats}, indent=1))


if __name__ == "__main__":
    mina_camp(HERE / "mina-camp-utm37n.dxf")
    small_room(HERE / "small-room-mm.dxf")
    mina_geojson(HERE / "mina-camp.geojson")
    print("wrote", ", ".join(p.name for p in sorted(HERE.glob("*.*")) if p.suffix in (".dxf", ".geojson")))
