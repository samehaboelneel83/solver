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
    assert out["upper_bound"]["items"] == int(8.0 // (0.5 + 0.5 * 0.5 / 4))  # a quarter aisle: four may share


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


def test_layout_refuses_links_over_the_assistant_file_limit_before_writing(tmp_path):
    with pytest.raises(layout.LayoutRefused, match="without truncation"):
        layout.make(_room(tmp_path, w=10, h=10), str(tmp_path), area_layers=["ROOMS"],
                    items=[{"name": "desk", "length": 1.0, "width": 1.0, "rotations": [0]}],
                    max_file_rows=9)
    assert not (tmp_path / "layout_items.csv").exists()


def test_the_camp_drawing_in_well_under_a_second(tmp_path):
    f = agent_files.parse_spatial("camp_layout_layers.dxf", DRAWING.read_bytes())
    out = layout.make([f], str(tmp_path), area_layers=["BOUNDARY"], blocked_layers=["OBSTACLES", "DOORS_OBSTACLE"],
                      label_layer="LABELS", items=[{"name": "bed", "length": 1.5, "width": 0.5, "rotations": [0, 90]}],
                      aisle=0.35, aisle_side="short")
    assert out["zones"] == [f"C{n:02d}" for n in range(1, 12)]
    assert out["grid_step_m"] == 0.5 and out["free_area_m2"] == pytest.approx(2071.7, abs=1)
    assert 20_000 < out["candidates"] < 40_000 and out["upper_bound"]["items"] == 2609
    with pytest.raises(layout.LayoutRefused, match="Coarser exact steps"):
        layout.make([f], str(tmp_path), area_layers=["BOUNDARY"], items=[{"name": "bed", "length": 1.5, "width": 0.5}],
                    aisle=0.35, aisle_side="any", step=0.25)


def test_layout_can_generate_one_polygon_from_a_layer(tmp_path):
    f = agent_files.parse_spatial("camp_layout_layers.dxf", DRAWING.read_bytes())
    one = layout.make([f], str(tmp_path), area_layers=["BOUNDARY"], area_indices=[0],
                      blocked_layers=["OBSTACLES", "DOORS_OBSTACLE"], label_layer="LABELS",
                      items=[{"name": "bed", "length": 1.5, "width": 0.5, "rotations": [0, 90]}],
                      aisle=0.35, aisle_side="short")
    assert one["areas"] == 1
    assert one["candidates"] > 0


def test_a_grid_too_fine_for_the_aisle_falls_back_to_the_coarser_exact_grid(tmp_path):
    """1.75 m beds with a 0.35 m aisle: the aisle-exact grid is 0.05 m (259,280 positions in this room), refused
    as too many; the platform lays it out on the exact 0.25 m grid itself and says the aisle it modelled."""
    out = layout.make(_room(tmp_path, w=20, h=10), str(tmp_path), area_layers=["ROOMS"],
                      items=[{"name": "bed", "length": 1.75, "width": 0.5, "rotations": [0, 90]}],
                      aisle=0.35, aisle_side="short")
    assert out["grid_step_m"] == 0.25 and out["aisle_m"]["modelled"] == 0.5
    assert 0 < out["candidates"] <= layout.MAX_CANDIDATES
    assert "coarser exact 0.25 m grid" in out["grid_note"] and "0.05 m grid" in out["grid_note"]
    # A step the caller chose is kept, and refused as before.
    with pytest.raises(layout.LayoutRefused, match="Coarser exact steps: 0.25 m"):
        layout.make(_room(tmp_path, w=20, h=10), str(tmp_path), area_layers=["ROOMS"],
                    items=[{"name": "bed", "length": 1.75, "width": 0.5, "rotations": [0, 90]}],
                    aisle=0.35, aisle_side="short", step=0.05)


def test_candidate_limit_lists_only_coarser_steps_that_divide_item_sizes(tmp_path):
    f = agent_files.parse_spatial("camp_layout_layers.dxf", DRAWING.read_bytes())
    with pytest.raises(layout.LayoutRefused) as error:
        layout.make([f], str(tmp_path), area_layers=["BOUNDARY"],
                    items=[{"name": "bed", "length": 1.75, "width": 0.5}],
                    aisle=0.35, aisle_side="any", step=0.25)
    assert "Coarser exact steps: none" in str(error.value)
    assert "0.5 m" not in str(error.value) and "1 m" not in str(error.value)


def test_the_assistant_tool_attaches_the_files_and_returns_the_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SANDBOX_ROOT", str(tmp_path))
    from app.main import app

    f = agent_files.parse_spatial("camp_layout_layers.dxf", DRAWING.read_bytes())
    agent = core.Agent(core.Settings(enabled=False), core.ApiIndex(app.openapi()), lambda *a, **k: {},
                       core.Context("x", mode="model", files=[f], user_id="u", conversation_id="c"))
    text = agent.run_tool("make_layout", {"area_layers": ["BOUNDARY"], "blocked_layers": ["OBSTACLES"],
                                          "items": [{"name": "bed", "length": 1.5, "width": 0.5, "rotations": [0, 90]}],
                                          "aisle": 0.35, "aisle_side": "short", "form": "candidates"})
    assert text.startswith("LAYOUT made") and '"entities_from_file"' in text
    assert {"layout_items.csv", "layout_occupies.csv", "layout_keeps_free.csv"} <= {x["name"] for x in agent.ctx.files}
    assert "make_layout" in {t["function"]["name"] for t in core.MODEL_TOOLS}


def test_by_default_the_tool_gives_the_placement_form_on_the_exact_grid(tmp_path, monkeypatch):
    """No list of positions (plan phase 1C): the areas and slots, a place rule, and the aisle exactly as asked."""
    monkeypatch.setenv("AGENT_SANDBOX_ROOT", str(tmp_path))
    from app.main import app

    f = agent_files.parse_spatial("camp_layout_layers.dxf", DRAWING.read_bytes())
    agent = core.Agent(core.Settings(enabled=False), core.ApiIndex(app.openapi()), lambda *a, **k: {},
                       core.Context("x", mode="model", files=[f], user_id="u", conversation_id="c"))
    text = agent.run_tool("make_layout", {"area_layers": ["BOUNDARY"], "blocked_layers": ["OBSTACLES"],
                                          "items": [{"name": "bed", "length": 1.5, "width": 0.5, "rotations": [0, 90]}],
                                          "aisle": 0.35, "aisle_side": "short"})
    assert text.startswith("LAYOUT made, placement form") and '"place"' in text
    assert '"grid_step_m": 0.05' in text and '"modelled": 0.35' in text
    assert {"layout_areas.csv", "layout_slots.csv"} <= {x["name"] for x in agent.ctx.files}


def test_access_layers_root_every_aisle_at_an_entrance(tmp_path):
    """The camp field test: items must reach a door through free cells. The plan carries a sourced connected rule;
    an area with no access feature is named, not assumed to have one."""
    files = _room(tmp_path, w=6, h=4)
    files[0]["sheets"].append({"name": "plan__DOORS", "columns": ["feature", "kind", "shape_m"],
                               "rows": [["DOORS_1", "line", "LINESTRING (0 1, 0 2)"]], "total_rows": 1})
    out = layout.make(files, str(tmp_path), area_layers=["ROOMS"], access_layers=["DOORS"],
                      items=[{"name": "desk", "length": 2, "width": 1}], aisle=1, aisle_side="any", step=1)
    assert out["access"]["entrance_cells"] >= 1 and out["access"]["areas_without_access"] == []
    rule = next(c for c in out["spec"]["ir"]["constraints"] if c["id"] == "c_access")
    assert rule["connected"]["sources"] == "entrance" and "groups" not in rule["connected"]
    assert "layout_next_to.csv" in out["files"] and out["not_modelled"].startswith("Nothing")
