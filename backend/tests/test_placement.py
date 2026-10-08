"""Placing items without a candidate list (app.solve.placement, the `place` rule; plan of 8 October 2026, 1C/1D)."""
from __future__ import annotations

import csv
import os
import time
from pathlib import Path

import numpy as np
import pytest

from app.agent import files as agent_files
from app.agent import layout
from app.ir.validate import check_shape
from app.solve import placement as pl
from app.solve.backends import choose
from app.solve.classify import classify
from app.solve.compile import compile_model
from app.solve.service import solve_compiled
from app.solve import verify
from tests.test_layout import DRAWING, _room
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _data(folder, spec):
    sets = {}
    for ent in spec["seed"]["entities_from_file"]:
        with open(os.path.join(folder, ent["file"])) as f:
            rows = list(csv.DictReader(f))
        sets[ent["type"]] = [{"id": r[ent["key"]], **{a: r[c] for a, c in ent["attrs"].items()}} for r in rows]
    for r in sets.get("slot", []):
        for k in ("length_cells", "width_cells", "can_turn"):
            r[k] = int(r[k])
        r["value"] = float(r["value"])
    return {"sets": sets, "parameters": {}, "relationships": {}, "parameter_defaults": {}}


def _solve(folder, out, seconds=5):
    spec = out["spec"]
    data = _data(folder, spec)
    model = compile_model(spec["ir"], data)
    backend, _ = choose(classify(spec["ir"], data))
    result, _ = solve_compiled(backend, model, time_limit=seconds, seed=1, should_stop=lambda: False, workers=1,
                              gap_rel=0.0)
    return backend, model, result


def test_a_room_is_filled_exactly_and_proven_when_it_meets_the_bound(tmp_path):
    # 4 x 2 m, 1 x 0.5 m desks, no aisle: 16 fit, and the area says no more can.
    out = layout.place(_room(tmp_path), str(tmp_path), area_layers=["ROOMS"],
                       items=[{"name": "desk", "length": 1.0, "width": 0.5, "rotations": [0, 90]}])
    assert out["form"] == "place" and out["upper_bound"]["items"] == 16
    backend, model, result = _solve(tmp_path, out)
    assert backend.name == "layout"
    assert result.status == "optimal" and result.objective == 16 and result.best_bound == 16
    assert verify.accept(model, result)["accepted"]


def test_aisles_are_kept_free_and_may_be_shared(tmp_path):
    # 4 x 2 m, 1 x 0.5 m beds with a 0.5 m aisle on a long side: two rows back to back need their own aisles;
    # rows facing each other share one.
    out = layout.place(_room(tmp_path), str(tmp_path), area_layers=["ROOMS"],
                       items=[{"name": "bed", "length": 1.0, "width": 0.5, "rotations": [0]}], aisle=0.5,
                       aisle_side="long")
    backend, model, result = _solve(tmp_path, out)
    assert result.objective == 8  # rows at y 0 and 1.5 m, facing the shared aisle in between
    assert verify.accept(model, result)["accepted"]


def test_the_check_refuses_an_overlap_an_item_on_an_aisle_and_one_off_the_area(tmp_path):
    out = layout.place(_room(tmp_path), str(tmp_path), area_layers=["ROOMS"],
                       items=[{"name": "bed", "length": 1.0, "width": 0.5, "rotations": [0]}], aisle=0.5,
                       aisle_side="long")
    _, model, result = _solve(tmp_path, out)
    place = model.placements[0]
    chosen = [s for s in place.slots if result.assignments[s.chosen]]
    a, b = chosen[0], chosen[1]
    broken = dict(result.assignments)
    broken[b.x], broken[b.y] = broken[a.x], broken[a.y]
    assert any("covered twice" in p for p in pl.check_assignments(place, broken))
    off = dict(result.assignments)
    off[a.x] = 7  # 1 m long from 3.5 m: past the 4 m wall
    assert pl.check_assignments(place, off)
    report = verify.accept(model, type(result)(**{**result.__dict__, "assignments": broken}))
    assert not report["accepted"] and report["failures"][0]["kind"] == "placement"


def test_the_kinds_slots_cap_how_many(tmp_path):
    out = layout.place(_room(tmp_path), str(tmp_path), area_layers=["ROOMS"],
                       items=[{"name": "desk", "length": 1.0, "width": 0.5, "rotations": [0], "count": 5}])
    assert out["slots_by_kind"] == {"desk": 5}
    _, _, result = _solve(tmp_path, out)
    assert result.objective == 5 and result.status == "optimal"


def test_the_camp_on_its_exact_grid_beats_the_candidate_form(tmp_path):
    """The camp: 1.5 x 0.5 m beds, a 0.35 m aisle on any side. The candidate form needs a 0.5 m grid (the aisle
    taken as 0.5 m) and 54,468 positions; the place form lays it out on the exact 0.05 m grid."""
    f = agent_files.parse_spatial("camp_layout_layers.dxf", DRAWING.read_bytes())
    out = layout.place([f], str(tmp_path), area_layers=["BOUNDARY"], blocked_layers=["OBSTACLES", "DOORS_OBSTACLE"],
                       label_layer="LABELS", items=[{"name": "bed", "length": 1.5, "width": 0.5, "rotations": [0, 90]}],
                       aisle=0.35, aisle_side="any")
    assert out["grid_step_m"] == 0.05 and out["aisle_m"]["modelled"] == 0.35
    _, model, result = _solve(tmp_path, out, seconds=30)
    assert result.objective >= 2300 and result.best_bound == out["upper_bound"]["items"]
    assert verify.accept(model, result)["accepted"]


def test_a_place_rule_is_validated(tmp_path):
    out = layout.place(_room(tmp_path), str(tmp_path), area_layers=["ROOMS"],
                       items=[{"name": "desk", "length": 1.0, "width": 0.5, "rotations": [0, 90]}])
    ir = out["spec"]["ir"]
    assert check_shape(ir) is None
    bad = {**ir, "constraints": [{**ir["constraints"][0], "place": {**ir["constraints"][0]["place"], "step": 0}}]}
    assert check_shape(bad).code == "place_malformed"
    soft = {**ir, "constraints": [{**ir["constraints"][0], "severity": "soft", "weight": 1}]}
    assert check_shape(soft).code == "place_on_soft"
    wrong = {**ir, "variables": {**ir["variables"], "placed": {"index": ["slot"], "domain": "integer"}}}
    assert check_shape(wrong).code == "place_domain"
    half = {**ir, "sets": ir["sets"] + ["access_point"], "constraints": [{**ir["constraints"][0], "place": {
        **ir["constraints"][0]["place"], "access": {"index": "e", "set": "access_point"}}}]}
    assert check_shape(half).code == "place_malformed"
    whole = {**half, "constraints": [{**half["constraints"][0], "place": {**half["constraints"][0]["place"],
                                                                          "access_shape": "shape"}}]}
    assert check_shape(whole) is None


def test_rectangles_cover_a_mask_exactly():
    mask = np.zeros((6, 5), dtype=bool)
    mask[1:4, 1:3] = True
    mask[5, 4] = True
    covered = np.zeros_like(mask)
    for i, j, w, h in pl._rectangles(mask):
        assert not covered[i:i + w, j:j + h].any()
        covered[i:i + w, j:j + h] = True
    assert (covered == mask).all()


def test_a_place_plan_builds_runs_and_reports_through_the_platform(tmp_path, tenants, db, empty_queue):  # noqa: F811
    from uuid import uuid4

    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.main import app
    from app.solve.service import claim_next, enqueue_run, execute_run

    out = layout.place(_room(tmp_path), str(tmp_path), area_layers=["ROOMS"],
                       items=[{"name": "bed", "length": 1.0, "width": 0.5, "rotations": [0, 90]}], aisle=0.5,
                       aisle_side="long")
    seed = dict(out["spec"]["seed"])
    data = _data(tmp_path, out["spec"])
    seed["entities"] = [{"type": t, "key": r["id"], "attrs": {k: v for k, v in r.items() if k != "id"}}
                        for t, rows in data["sets"].items() for r in rows]
    del seed["entities_from_file"]
    spec = {"domain_name": f"place {uuid4().hex[:6]}", "problem_name": "beds", "seed": seed, "ir": out["spec"]["ir"],
            "dry_run": False, "trial": False}
    built = TestClient(app).post("/api/v1/problems/from-spec", json=spec, headers=tenants["a"])
    assert built.status_code == 200, built.text
    run_id = enqueue_run(db, built.json()["scenario_id"], time_limit=5.0, reuse=False)
    outcome = None
    while (claimed := claim_next(db)) is not None:  # the build may have queued a first run of its own
        done = execute_run(db, claimed)
        outcome = done if claimed == run_id else outcome
    row = db.execute(text("SELECT status, solver, objective, best_bound, error, wall_time_s,"
                          "       extract(epoch FROM finished_at - started_at) AS took FROM run WHERE id = :r"),
                     {"r": run_id}).mappings().one()
    assert row["solver"] == "layout" and row["status"] in ("optimal", "feasible"), dict(row)
    # The run's clock is the wall clock: a run that solved for seconds did not finish the moment it started
    # (live camp test, October 2026: a 118 s run was stored as finishing 1.2 s after it started).
    assert float(row["took"]) >= 0.9 * float(row["wall_time_s"]), dict(row)
    # 32 free cells / (2 cells + a quarter of a 2-cell aisle) = 12: proven best only when the answer reaches it.
    assert outcome.objective >= 9 and out["upper_bound"]["items"] == 12
    assert (row["status"] == "optimal") == (outcome.objective == 12)
    result = TestClient(app).get(f"/api/v1/agent/result/{run_id}", headers=tenants["a"]).json()
    assert "LAYOUT" in result["text"] and result["facts"]["goal"] == outcome.objective
    for fmt in ("dxf", "csv", "xlsx"):
        got = TestClient(app).get(f"/api/v1/runs/{run_id}/export?format={fmt}", headers=tenants["a"])
        assert got.status_code == 200, (fmt, got.text[:300])
    drawing = TestClient(app).get(f"/api/v1/runs/{run_id}/export?format=dxf", headers=tenants["a"]).content
    assert b"PLACED" in drawing.upper()  # the chosen slots drawn as rectangles in metres


def test_the_plan_from_the_tool_checks_with_a_trial_on_the_camp(tmp_path, tenants):  # noqa: F811
    """The tool's files, read as the Assistant reads them, through check_spec's dry run and trial."""
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.main import app

    f = agent_files.parse_spatial("camp_layout_layers.dxf", DRAWING.read_bytes())
    out = layout.place([f], str(tmp_path), area_layers=["BOUNDARY"], blocked_layers=["OBSTACLES", "DOORS_OBSTACLE"],
                       label_layer="LABELS", items=[{"name": "bed", "length": 1.5, "width": 0.5, "rotations": [0, 90]}],
                       aisle=0.35, aisle_side="any")
    files = [agent_files.parse(name, (tmp_path / name).read_bytes(), max_rows=agent_files.MAX_GENERATED_ROWS)
             for name in out["files"]]
    seed = agent_files.expand(out["spec"]["seed"], files)
    spec = {"domain_name": f"camp {uuid4().hex[:6]}", "problem_name": "beds", "seed": seed, "ir": out["spec"]["ir"],
            "dry_run": True, "trial": True}
    checked = TestClient(app).post("/api/v1/problems/from-spec", json=spec, headers=tenants["a"])
    assert checked.status_code == 200, checked.text[:500]
    trial = checked.json()["trial"]
    assert trial["status"] in ("feasible", "optimal") and trial["objective"] >= 2300, trial


def _doors(files, line):
    files[0]["sheets"].append({"name": "plan__DOORS", "columns": ["feature", "kind", "shape_m"],
                               "rows": [["DOORS_1", "line", line]], "total_rows": 1, "truncated": False})
    return files


def test_with_access_every_item_is_reached_from_a_door(tmp_path):
    """A 6 x 4 m room with a door on its left wall: desks with a 1 m aisle; every desk's aisle joins the door
    through uncovered cells (the candidate form's `connected` rule, held here on the grid)."""
    files = _doors(_room(tmp_path, w=6, h=4), "LINESTRING (0 1.5, 0 2.5)")
    out = layout.place(files, str(tmp_path), area_layers=["ROOMS"], access_layers=["DOORS"],
                       items=[{"name": "desk", "length": 2, "width": 1, "rotations": [0, 90]}], aisle=1,
                       aisle_side="any")
    assert out["access"]["features"] == 1 and out["access"]["areas_without_access"] == []
    rule = out["spec"]["ir"]["constraints"][0]["place"]
    assert rule["access"]["set"] == "access_point" and rule["access_shape"] == "shape"
    _, model, result = _solve(tmp_path, out)
    place = model.placements[0]
    assert place.entrance is not None and result.objective >= 6
    assert verify.accept(model, result)["accepted"]
    # An item walled off from the door by a row of others is caught.
    one = [pl.Variant(0, 0, 1, 1, None, 1.0)]
    cut = pl.Layout(place.zone_grid, one, 0, entrance=place.entrance)
    nx, ny = place.zone_grid.shape
    wall = [cut.place(0, 1, j) for j in range(ny)]  # a full column next to the door: still reached from it
    lonely = cut.place(0, nx - 1, ny - 1)  # beyond the wall: no way to the door
    assert pl.unreachable_items(cut) == [lonely] and wall
    assert any("cannot be reached" in p for p in cut.check())


def test_two_kinds_of_different_worth_are_both_laid_out(tmp_path):
    """General: items of several kinds and values, each within its own slots. (With tables worth 5, 96 stools
    are the better answer -- 4 a square metre against 2.5 -- and that is what the solver gives.)"""
    out = layout.place(_room(tmp_path, w=6, h=4), str(tmp_path), area_layers=["ROOMS"],
                       items=[{"name": "table", "length": 2, "width": 1, "rotations": [0, 90], "value": 20,
                               "count": 3},
                              {"name": "stool", "length": 0.5, "width": 0.5, "rotations": [0], "value": 1}])
    assert out["slots_by_kind"]["table"] == 3
    _, model, result = _solve(tmp_path, out)
    kinds = {}
    for slot in model.placements[0].slots:
        if result.assignments[slot.chosen]:
            kinds[slot.length * slot.width] = kinds.get(slot.length * slot.width, 0) + 1
    tables, stools = kinds.get(8, 0), kinds.get(1, 0)  # on the 0.5 m grid: 4 x 2 cells and 1 x 1
    # A table is worth 10 a square metre and a stool 4: all three tables, and stools on the rest (72 cells).
    assert tables == 3 and stools == 72 and result.objective == 3 * 20 + 72
    assert verify.accept(model, result)["accepted"]


def test_the_read_back_says_where_the_aisle_runs_in_plain_words():
    from app.agent.readback import readback

    ir = {"sets": ["slot", "area", "access_point"], "variables": {}, "objective": {}, "constraints": [{"id": "c", "place": {
        "slots": {"set": "slot"}, "areas": {"set": "area"}, "step": 0.05, "aisle": 7, "aisle_sides": "any",
        "access": {"set": "access_point"}}}]}
    text = readback({"ir": ir})
    assert "free on any side" in text and "one access_point" in text and "a any" not in text and "a access" not in text
    ir["constraints"][0]["place"]["aisle_sides"] = "long"
    assert "free along a long side" in readback({"ir": ir})


def test_areas_are_combined_from_the_layouts_that_do_best_in_each():
    """General: a layout that packs one area better and another that packs the other better make one that
    packs both; it is checked again under the layout's own rules."""
    zone = np.full((4, 2), -1, dtype=np.int32)
    zone[0:2, :] = 0
    zone[2:4, :] = 1
    one = [pl.Variant(0, 0, 1, 1, None, 1.0)]
    a, b = pl.Layout(zone, one, 0), pl.Layout(zone, one, 0)
    for i, j in ((0, 0), (0, 1), (1, 0), (2, 0)):
        a.place(0, i, j)  # three in area 0, one in area 1
    for i, j in ((0, 0), (2, 0), (2, 1), (3, 1)):
        b.place(0, i, j)  # one in area 0, three in area 1
    combined = pl.best_per_zone([a, b])
    assert combined.value() == 6 and not combined.check()
    assert pl.best_per_zone([a]) is None


def test_a_room_scanned_from_the_far_side_packs_about_as_well_as_from_the_near_side():
    """General: a mirrored scan prefers the mirrored aisle side, so its rows face each other as a forward scan's
    do (before: 70 beds scanned back against 78 forward in this room; the camp: 2,159 against 2,386)."""
    zone = np.zeros((20, 14), dtype=np.int32)
    vs = pl.variants_cells([(3, 1, [0, 90], 1.0)], "any", 1)
    counts = {scan: len(pl._greedy_at(zone, vs, 1, 1, time.monotonic() + 30, None, scan)[0].items)
              for scan in ("rows", "rows-back", "cols", "cols-back")}
    assert counts["rows-back"] >= 0.97 * counts["rows"] and counts["cols-back"] >= 0.97 * counts["cols"], counts


def _exact_most(nx, ny, length, width, aisle, side):
    """The most items a room holds, solved exactly: every fitting position a yes/no, footprints apart, no
    footprint on a chosen item's aisle."""
    from ortools.sat.python import cp_model

    zone = np.zeros((nx, ny), dtype=np.int32)
    vs = pl.variants_cells([(length, width, [0, 90], 1.0)], side, aisle)
    m = cp_model.CpModel()
    cover, strip, xs = {}, {}, []
    for k, v in enumerate(vs):
        for i, j in zip(*np.nonzero(pl.static_fits(zone, v, aisle))):
            x = m.NewBoolVar("")
            xs.append(x)
            for a in range(i, i + v.w):
                for b in range(j, j + v.h):
                    cover.setdefault((a, b), []).append(x)
            s = v.aisle(aisle)
            for a in range(i + s[0], i + s[0] + s[2]):
                for b in range(j + s[1], j + s[1] + s[3]):
                    strip.setdefault((a, b), []).append(x)
    for cell, on in cover.items():
        m.Add(sum(on) <= 1)
        for y in strip.get(cell, []):
            for x in on:
                m.AddImplication(y, x.Not())
    m.Maximize(sum(xs))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20
    assert solver.Solve(m) == cp_model.OPTIMAL
    return int(solver.ObjectiveValue()), vs


@pytest.mark.parametrize("room", [(7, 7, 2, 1, 1, "any"), (9, 9, 2, 1, 1, "short"), (8, 6, 3, 1, 1, "any"),
                                  (7, 6, 3, 1, 2, "long")])
def test_the_bound_is_never_beaten_by_an_exact_solution(room):
    """The area bound is a bound: exact optima stay at or under it (half an aisle per item was not -- a 7 x 7
    room of 2 x 1 items holds 20 and the half-aisle count said 19, so 19 would have been called proven best)."""
    nx, ny, length, width, aisle, side = room
    most, vs = _exact_most(nx, ny, length, width, aisle, side)
    assert pl.area_bound(nx * ny, vs, aisle, side) >= most
