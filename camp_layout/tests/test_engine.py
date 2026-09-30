"""The engine end to end, and the validator catching what it must."""
from __future__ import annotations

import dataclasses
import json

import pytest
from shapely.geometry import box

from camp_layout import export
from camp_layout.adapters import adapter
from camp_layout.builder import ModelBuilder
from camp_layout.discretize import discretize
from camp_layout.examples import complex_camp, small_camp
from camp_layout.heuristic import Constructor, hint_values
from camp_layout.model import violations
from camp_layout.optimize import lexicographic, weighted
from camp_layout.pipeline import solve
from camp_layout.problem import BedType, Door, ObjectiveSpec
from camp_layout.result import PlacedBed
from camp_layout.validate import validate


def test_a_bad_definition_is_refused_before_modelling():
    bad = small_camp(bed_types=(BedType("cot", 2.0, 0.9, sizes=((1.5, 0.9),)),))
    assert "bed type cot: size 1.5x0.9 outside its range" in bad.check()
    with pytest.raises(ValueError, match="not consistent"):
        solve(bad, "heuristic", log=lambda *a: None)
    diagonal = small_camp(doors=(Door("D1", (0, 0), (1, 1)),))
    assert "door D1 is not on an axis-aligned edge" in diagonal.check()


def test_candidates_respect_the_fixed_geometry():
    grid = discretize(small_camp())
    pillar = box(9, 5, 10, 6)
    for p in grid.placements:
        slot = grid.block_box(p.anchor, p.span)
        assert grid.geometry.camp.buffer(1e-6).contains(slot)
        assert slot.intersection(pillar).area == 0
        assert grid.access[p.index]
    for t in grid.tiles:
        assert all(c in grid.walk_ok for c in grid.tile_cells(t))


@pytest.mark.parametrize("make", [small_camp, complex_camp])
def test_stage_zero_is_a_complete_feasible_start(make):
    grid = discretize(make())
    builder = ModelBuilder(grid)
    model = builder.build()
    lay = Constructor(grid).best()
    assert lay.beds
    assert violations(model, hint_values(builder, lay)) == []


def test_cpsat_from_stage_zero_reaches_the_bound_on_the_small_room_and_validates():
    run = solve(small_camp(), "cpsat", time_limit=20, stage_limits={"beds": 30}, log=lambda *a: None)
    beds = run.outcome.stages[0]
    assert beds.value >= 30
    assert run.validation.ok, [c for c in run.validation.checks if not c.ok]
    # Later stages never give beds back.
    assert len(run.layout.beds) == beds.value


def test_the_same_model_solves_on_a_milp_solver():
    run = solve(small_camp(), "scip", time_limit=20, log=lambda *a: None)
    assert run.outcome.ok
    assert run.validation.ok, [c for c in run.validation.checks if not c.ok]
    assert len(run.layout.beds) >= 30


def test_weighted_mode_normalises_and_solves():
    problem = small_camp(objectives=ObjectiveSpec(mode="weighted"))
    run = solve(problem, "cpsat", time_limit=15, log=lambda *a: None)
    assert run.outcome.ok and run.validation.ok
    assert run.outcome.stages[0].objective == "weighted"


def test_lexicographic_keeps_each_stage():
    grid = discretize(small_camp())
    b = ModelBuilder(grid)
    m = b.build()
    start = hint_values(b, Constructor(grid).best())
    out = lexicographic(m, adapter("cpsat"), ("beds", "corridor"), time_limit=10, start=start, log=lambda *a: None)
    beds = m.objectives["beds"].expr.value(out.values)
    assert beds >= out.stages[0].value - 1e-6
    assert "beds ≥" in out.stages[0].kept


# -- the validator catches what it must ---------------------------------------------------

@pytest.fixture(scope="module")
def good():
    return solve(small_camp(), "heuristic", log=lambda *a: None)


def _with_beds(run, beds):
    return dataclasses.replace(run.layout, beds=beds)


def _failed(v):
    return {c.name for c in v.checks if not c.ok}


def test_a_valid_layout_passes_every_check(good):
    assert good.validation.ok
    assert set(good.validation.walk) == {b.id for b in good.layout.beds}


def test_overlapping_beds_are_caught(good):
    first = good.layout.beds[0]
    twin = dataclasses.replace(first, id="TWIN")
    v = validate(good.problem, _with_beds(good, good.layout.beds + [twin]))
    assert "no two beds overlap" in _failed(v)


def test_a_bed_on_an_obstacle_is_caught(good):
    on_pillar = PlacedBed("BAD", "cot", 2.0, 0.9, False, box(8.8, 5.0, 10.8, 5.9), box(8.8, 5, 10.8, 6))
    assert "no bed on an obstacle" in _failed(validate(good.problem, _with_beds(good, good.layout.beds + [on_pillar])))


def test_a_bed_no_corridor_reaches_is_caught(good):
    # Take away every corridor: the specified door zone remains, most beds are cut off.
    cut = dataclasses.replace(good.layout, corridor_squares=[])
    assert "every bed reaches a door through the corridors" in _failed(validate(good.problem, cut))


def test_door_capacity_is_checked_independently(good):
    tight = small_camp(doors=(Door("D1", (6, 0), (7.5, 0), capacity=10),))
    assert "door capacities hold (max-flow assignment)" in _failed(validate(tight, good.layout))


def test_gis_export_writes_both_crs_and_the_viewer(good, tmp_path):
    files = export.write(good, tmp_path)
    local = json.loads(files["output_local"].read_text())
    layers = {f["properties"]["layer"] for f in local["features"]}
    assert {"boundary", "bed", "corridor", "door", "door_zone", "path", "obstacle"} <= layers
    wgs = json.loads(files["output_wgs84"].read_text())
    lon, lat = wgs["features"][0]["geometry"]["coordinates"][0][0]
    assert abs(lon - 31.60) < 0.01 and abs(lat - 30.10) < 0.01
    html = files["viewer"].read_text()
    assert "/*__DATA__*/null" not in html and '"beds":30' in html
