"""Placing items on a drawing (app.agent.layout): candidates, cells, links and the plan, made by the platform."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent import core
from app.agent import files as agent_files
from app.agent import layout

DRAWING = Path(__file__).parent / "fixtures" / "camp_layout_layers.dxf"


def _room(tmp_path, w=4.0, h=2.0, blocked=None):
    """A one-room drawing as the file reader gives it: shape_m in metres."""
    rows = [["R1", "polygon", f"POLYGON ((0 0, {w} 0, {w} {h}, 0 {h}, 0 0))"]]
    files = [{"name": "plan.dxf", "spatial": {"local_metres": True}, "sheets": [
        {"name": "plan__ROOMS", "columns": ["feature", "kind", "shape_m"], "rows": rows, "total_rows": 1, "truncated": False},
        {"name": "plan__BLOCK", "columns": ["feature", "kind", "shape_m"], "rows": blocked or [], "total_rows": len(blocked or []),
         "truncated": False}]}]
    return files


def test_a_room_gets_every_position_turn_and_aisle_side(tmp_path):
    out = layout.make(_room(tmp_path), str(tmp_path), area_layers=["ROOMS"],
                      items=[{"name": "bed", "length": 1.0, "width": 0.5, "rotations": [0, 90]}], aisle=0.5,
                      aisle_side="short")
    assert out["grid_step_m"] == 0.5 and out["aisle_m"]["modelled"] == 0.5
    # 4 x 2 m on 0.5 m cells: 8 x 4 cells. Horizontal beds (2 x 1 cells) with a 1-cell aisle left or right.
    rows = (tmp_path / "layout_items.csv").read_text().splitlines()
    assert len(rows) - 1 == out["candidates"] > 0
    assert set(out["spec"]["ir"]["variables"]) == {"place"} and len(out["spec"]["ir"]["constraints"]) == 2
    assert out["upper_bound"]["items"] == int(8.0 // (0.5 + 0.5 * 0.5 / 2))


def test_blocked_areas_are_never_covered(tmp_path):
    files = _room(tmp_path, blocked=[["B1", "polygon", "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"]])
    out = layout.make(files, str(tmp_path), area_layers=["ROOMS"], blocked_layers=["BLOCK"],
                      items=[{"name": "desk", "length": 1.0, "width": 1.0, "rotations": [0]}])
    xs = [float(r.split(",")[6]) for r in (tmp_path / "layout_items.csv").read_text().splitlines()[1:]]
    assert xs and min(xs) >= 2.0 and out["aisle_m"]["side"] == "none"


def test_a_step_that_does_not_divide_the_sizes_is_refused(tmp_path):
    with pytest.raises(layout.LayoutRefused, match="does not divide"):
        layout.make(_room(tmp_path), str(tmp_path), area_layers=["ROOMS"],
                    items=[{"name": "bed", "length": 1.5, "width": 0.5}], step=0.2)


def test_the_camp_drawing_in_well_under_a_second(tmp_path):
    f = agent_files.parse_spatial("camp_layout_layers.dxf", DRAWING.read_bytes())
    out = layout.make([f], str(tmp_path), area_layers=["BOUNDARY"], blocked_layers=["OBSTACLES", "DOORS_OBSTACLE"],
                      label_layer="LABELS", items=[{"name": "bed", "length": 1.5, "width": 0.5, "rotations": [0, 90]}],
                      aisle=0.35, aisle_side="short")
    assert out["zones"] == [f"C{n:02d}" for n in range(1, 12)]
    assert out["grid_step_m"] == 0.5 and out["free_area_m2"] == pytest.approx(2071.7, abs=1)
    assert 20_000 < out["candidates"] < 40_000 and out["upper_bound"]["items"] == 2473
    with pytest.raises(layout.LayoutRefused, match="Ask the user"):
        layout.make([f], str(tmp_path), area_layers=["BOUNDARY"], items=[{"name": "bed", "length": 1.5, "width": 0.5}],
                    aisle=0.35, aisle_side="any", step=0.25)


def test_the_assistant_tool_attaches_the_files_and_returns_the_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SANDBOX_ROOT", str(tmp_path))
    from app.main import app

    f = agent_files.parse_spatial("camp_layout_layers.dxf", DRAWING.read_bytes())
    agent = core.Agent(core.Settings(enabled=False), core.ApiIndex(app.openapi()), lambda *a, **k: {},
                       core.Context("x", mode="model", files=[f], user_id="u", conversation_id="c"))
    text = agent.run_tool("make_layout", {"area_layers": ["BOUNDARY"], "blocked_layers": ["OBSTACLES"],
                                          "items": [{"name": "bed", "length": 1.5, "width": 0.5, "rotations": [0, 90]}],
                                          "aisle": 0.35, "aisle_side": "short"})
    assert text.startswith("LAYOUT made") and '"entities_from_file"' in text
    assert {"layout_items.csv", "layout_occupies.csv", "layout_keeps_free.csv"} <= {x["name"] for x in agent.ctx.files}
    assert "make_layout" in {t["function"]["name"] for t in core.MODEL_TOOLS}
