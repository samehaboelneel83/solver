"""Drawing -> workbook -> problem: the converter on a clean drawing and on a
realistic one (millimetres, surveyed coordinates, blocks, circles, hatches)."""
from __future__ import annotations

import ezdxf
import pytest
from shapely.geometry import Polygon

from camp_layout.__main__ import main
from camp_layout.dxf import DrawingError, read_dxf, write_dxf
from camp_layout.examples import complex_camp
from camp_layout.pipeline import solve
from camp_layout.workbook import dxf_to_workbook, read_workbook, write_workbook


def test_a_problem_survives_drawing_and_workbook(tmp_path):
    p = complex_camp()
    write_dxf(p, str(tmp_path / "camp.dxf"))
    d = read_dxf(str(tmp_path / "camp.dxf"))
    assert round(d.boundary.area, 2) == round(Polygon(p.boundary).area, 2)
    assert [(x.a, x.b) for x in d.doors] == [(tuple(map(float, q.a)), tuple(map(float, q.b))) for q in p.doors]
    assert [o.id for o in d.obstacles] == [o.id for o in p.obstacles]
    assert [z.id for z in d.zones] == ["medical-area"]
    write_workbook(p, tmp_path / "camp.xlsx")
    q = read_workbook(tmp_path / "camp.xlsx")
    assert q.check() == []
    assert q.bed_types == p.bed_types and q.zones == p.zones and q.doors == p.doors


def _surveyed_drawing(path):
    """A camp as a surveyor would send it: millimetres at UTM coordinates."""
    E, N = 330_000_000, 3_330_000_000  # mm
    mm = lambda x, y: (E + x * 1000, N + y * 1000)
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([mm(0, 0), mm(20, 0), mm(20, 10), mm(12, 15), mm(0, 15)], close=True, dxfattribs={"layer": "Site"})
    gate = doc.blocks.new("GATE")
    gate.add_line((0, 0), (1800, 0))
    gate.add_arc((0, 0), 1800, 0, 90)
    msp.add_blockref("GATE", mm(4, 0), dxfattribs={"layer": "Gates"})
    msp.add_line(mm(20, 4), mm(20, 5.5), dxfattribs={"layer": "DOORS"})
    msp.add_circle(mm(10, 7), 1200, dxfattribs={"layer": "Obstacles"})
    msp.add_text("Water tank", dxfattribs={"layer": "Obstacles", "height": 300}).set_placement(mm(10, 7))
    h = msp.add_hatch(dxfattribs={"layer": "NO_BEDS"})
    h.paths.add_polyline_path([mm(15, 11), mm(17, 11), mm(17, 9.5), mm(15, 9.5)], is_closed=True)
    msp.add_lwpolyline([mm(1, 1), mm(2, 1), mm(2, 2)], dxfattribs={"layer": "Furniture"})
    doc.saveas(path)


def test_a_surveyed_drawing_in_millimetres_reads_in_local_metres(tmp_path):
    _surveyed_drawing(tmp_path / "survey.dxf")
    d = read_dxf(str(tmp_path / "survey.dxf"), crs="EPSG:32636")
    assert round(d.boundary.area, 3) == 20 * 10 + 12 * 5 + 0.5 * 8 * 5
    assert d.offset == (330_000, 3_330_000)
    assert d.origin_lonlat is not None and 30 < d.origin_lonlat[0] < 34 and 29 < d.origin_lonlat[1] < 31
    doors = {x.id: (x.a, x.b) for x in d.doors}
    assert doors["D1"] == ((4.0, 0.0), (5.8, 0.0))  # the block's opening, on the south wall
    assert doors["D2"] == ((20.0, 4.0), (20.0, 5.5))
    assert [o.id for o in d.obstacles] == ["Water-tank"] and abs(d.obstacles[0].polygon.area - 3.1416 * 1.44) < 0.05
    assert len(d.prohibited) == 1 and abs(d.prohibited[0].polygon.area - 3.0) < 1e-6
    assert any("Furniture" in n for n in d.notes)


def test_the_command_line_takes_a_drawing_to_a_validated_layout(tmp_path, capsys):
    _surveyed_drawing(tmp_path / "survey.dxf")
    main(["dxf2xlsx", str(tmp_path / "survey.dxf"), str(tmp_path / "camp.xlsx"), "--crs", "EPSG:32636"])
    q = read_workbook(tmp_path / "camp.xlsx")
    assert q.check() == [] and len(q.doors) == 2
    run = solve(q, "heuristic", log=lambda *a: None)
    assert run.layout.beds and run.validation.ok, [c for c in run.validation.checks if not c.ok]


def test_a_drawing_without_a_camp_or_doors_says_what_is_missing(tmp_path):
    doc = ezdxf.new()
    doc.modelspace().add_lwpolyline([(0, 0), (5, 0), (5, 5)], close=True, dxfattribs={"layer": "OBSTACLES"})
    doc.saveas(tmp_path / "x.dxf")
    with pytest.raises(DrawingError, match="no closed shape on a boundary layer"):
        read_dxf(str(tmp_path / "x.dxf"))
    doc.modelspace().add_lwpolyline([(0, 0), (9, 0), (9, 9), (0, 9)], close=True, dxfattribs={"layer": "CAMP"})
    doc.saveas(tmp_path / "x.dxf")
    with pytest.raises(DrawingError, match="no door found"):
        read_dxf(str(tmp_path / "x.dxf"))
