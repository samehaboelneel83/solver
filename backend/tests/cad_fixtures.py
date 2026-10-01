"""A drawing with every kind of thing a CAD file holds, for the DXF -> GIS tests.

A site in UTM zone 36N (Egypt), in metres, around E 330 000, N 3 330 000:
layers with colours, lines, polylines (one with an arc segment), circles,
arcs, ellipses, splines, a hatch with a hole, a solid, points, text, multi-
line text, a block with attributes and a nested block inserted twice, and a
dimension.
"""
from __future__ import annotations

E0, N0 = 330_000.0, 3_330_000.0


def site_drawing(path, *, units: int = 6, offset: tuple[float, float] = (E0, N0), scale: float = 1.0) -> None:
    import ezdxf

    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = units
    msp = doc.modelspace()
    at = lambda x, y: (offset[0] * scale + x * scale, offset[1] * scale + y * scale)
    for name, colour in (("Buildings", 1), ("Roads", 8), ("Trees", 3), ("Labels", 5), ("Hatch", 30), ("Dims", 2)):
        doc.layers.add(name, color=colour)
    msp.add_lwpolyline([at(0, 0), at(20, 0), at(20, 10), at(0, 10)], close=True, dxfattribs={"layer": "Buildings"})
    # A building with a rounded end: a bulge on one segment.
    msp.add_lwpolyline([(*at(30, 0), 0, 0, 0), (*at(40, 0), 0, 0, 1), (*at(40, 6), 0, 0, 0), (*at(30, 6), 0, 0, 0)],
                       format="xyseb", close=True, dxfattribs={"layer": "Buildings"})
    msp.add_line(at(-5, -5), at(60, -5), dxfattribs={"layer": "Roads"})
    msp.add_lwpolyline([at(-5, -5), at(-5, 30), at(10, 40)], dxfattribs={"layer": "Roads", "color": 1})
    msp.add_circle(at(25, 20), 2 * scale, dxfattribs={"layer": "Trees"})
    msp.add_arc(at(50, 20), 3 * scale, 0, 180, dxfattribs={"layer": "Roads"})
    msp.add_ellipse(at(10, 25), major_axis=(4 * scale, 0, 0), ratio=0.5, dxfattribs={"layer": "Trees"})
    msp.add_spline([at(0, 50), at(10, 55), at(20, 50), at(30, 55)], dxfattribs={"layer": "Roads"})
    hatch = msp.add_hatch(color=4, dxfattribs={"layer": "Hatch"})
    hatch.paths.add_polyline_path([at(50, 30), at(60, 30), at(60, 40), at(50, 40)], is_closed=True)
    hatch.paths.add_polyline_path([at(53, 33), at(57, 33), at(57, 37), at(53, 37)], is_closed=True)
    msp.add_solid([at(0, 60), at(4, 60), at(0, 63), at(4, 63)], dxfattribs={"layer": "Buildings"})
    msp.add_point(at(70, 70), dxfattribs={"layer": "Trees"})
    msp.add_text("Main gate", height=1.5 * scale, dxfattribs={"layer": "Labels"}).set_placement(at(5, -8))
    msp.add_mtext("Store\\Pblock A", dxfattribs={"layer": "Labels", "char_height": 1 * scale}).set_location(at(2, 5))
    # A tree symbol block (drawn on layer 0, so it takes the insert's layer) with an attribute,
    # nesting a marker block.
    marker = doc.blocks.new("MARK")
    marker.add_circle((0, 0), 0.2 * scale, dxfattribs={"layer": "0"})
    tree = doc.blocks.new("TREE")
    tree.add_circle((0, 0), 1 * scale, dxfattribs={"layer": "0", "color": 0})
    tree.add_blockref("MARK", (0, 0))
    tree.add_attdef("SPECIES", (0, -1.5 * scale), dxfattribs={"height": 0.5 * scale})
    for i, species in enumerate(("palm", "olive")):
        ref = msp.add_blockref("TREE", at(40 + 5 * i, 20), dxfattribs={"layer": "Trees", "color": 3})
        ref.add_auto_attribs({"SPECIES": species})
    dim = msp.add_linear_dim(base=at(0, -2), p1=at(0, 0), p2=at(20, 0), dimstyle="EZDXF", dxfattribs={"layer": "Dims"})
    dim.render()
    doc.saveas(path)
