"""Generated sets (plan of 8 October 2026, 1B): a candidate set stored as its recipe and built by the worker --
the same members, links and answer as the stored list, with nothing of it in the database."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent import layout
from app.ir.validate import _DomainChecker, check_shape, with_generated
from app.solve import generate
from app.solve.backends import choose
from app.solve.classify import classify
from app.solve.compile import Unsupported, compile_model
from app.solve.service import solve_compiled, variable_count
from tests.test_layout import _room as _plain_room
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _room(tmp_path, door=False):
    files = _plain_room(tmp_path)
    if door:
        files[0]["sheets"].append({"name": "plan__DOORS", "columns": ["feature", "kind", "shape_m"],
                                   "rows": [["D1", "line", "LINESTRING (0 0.5, 0 1)"]], "total_rows": 1,
                                   "truncated": False})
    return files

ROOM = "POLYGON ((0 0, 4 0, 4 2, 0 2, 0 0))"


def _data(sets=None, relationships=None):
    return {"sets": sets or {}, "parameters": {}, "relationships": relationships or {}, "parameter_defaults": {}}


def test_a_range_and_a_product_with_its_links_filtered():
    data = _data({"nurse": [{"id": "n1", "ward": "A"}, {"id": "n2", "ward": "B"}],
                  "shift": [{"id": "s1", "ward": "A"}, {"id": "s2", "ward": "A"}, {"id": "s3", "ward": "B"}]},
                 {"can_work": [{"from": "n1", "to": "s1"}, {"from": "n1", "to": "s3"}, {"from": "n2", "to": "s3"}]})
    ir = {"generate": [{"kind": "range", "set": "hour", "from": 0, "to": 6, "step": 3},
                       {"kind": "product", "set": "assign", "of": ["nurse", "shift"], "linked": "can_work",
                        "same": [["ward", "ward"]]}]}
    built = generate.apply(ir, data)
    assert built["sets"]["hour"] == [{"id": "0", "value": 0}, {"id": "3", "value": 3}, {"id": "6", "value": 6}]
    # n1-s3 is linked but in another ward; n1-s2 is in the ward but not linked.
    assert built["sets"]["assign"] == [{"id": "n1|s1", "nurse": "n1", "shift": "s1"},
                                       {"id": "n2|s3", "nurse": "n2", "shift": "s3"}]
    assert built["relationships"]["assign_shift"] == [{"from": "n1|s1", "to": "s1"}, {"from": "n2|s3", "to": "s3"}]
    assert "assign" not in data["sets"]  # the frozen data is not touched
    assert generate.apply(ir, built) is built  # built once


def test_pairs_of_one_set_without_repeats_once_each():
    data = _data({"cell": [{"id": "a"}, {"id": "b"}, {"id": "c"}]})
    built = generate.apply({"generate": [{"kind": "product", "set": "pair", "of": ["cell", "cell"], "distinct": True,
                                          "unordered": True}]}, data)
    assert [r["id"] for r in built["sets"]["pair"]] == ["a|b", "a|c", "b|c"]
    assert built["sets"]["pair"][0] == {"id": "a|b", "cell": "a", "cell_2": "b"}
    assert set(built["relationships"]) == {"pair_cell", "pair_cell_2"}


def _positions_recipe(aisle=1, sides="long", access=False):
    recipe = {"kind": "positions", "areas": "area", "shape": "shape", "kinds": "item_kind",
              "length": "length_cells", "width": "width_cells", "can_turn": "can_turn", "value": "value",
              "step": 0.5, "origin": [0, 0], "items": "item", "cells": "cell", "occupies": "occupies"}
    if aisle:
        recipe.update(aisle=aisle, aisle_sides=sides, keeps_free="keeps_free")
    if access:
        recipe.update(access="door", access_shape="shape", next_to="next_to")
    return recipe


def _room_data(door=False):
    sets = {"area": [{"id": "R1", "shape": ROOM}],
            "item_kind": [{"id": "bed", "length_cells": 2, "width_cells": 1, "can_turn": 1, "value": 1}]}
    if door:
        sets["door"] = [{"id": "d1", "shape": "LINESTRING (0 0.5, 0 1)"}]
    return _data(sets)


def test_positions_are_the_stored_candidate_lists_own(tmp_path):
    stored = layout.make(_room(tmp_path), str(tmp_path), area_layers=["ROOMS"],
                         items=[{"name": "bed", "length": 1.0, "width": 0.5, "rotations": [0, 90]}], aisle=0.5,
                         aisle_side="long", step=0.5)
    built = generate.apply({"generate": [_positions_recipe()]}, _room_data())
    assert len(built["sets"]["item"]) == stored["candidates"]
    assert len(built["relationships"]["occupies"]) == stored["links"]["occupies"]
    assert len(built["relationships"]["keeps_free"]) == stored["links"]["keeps_free"]
    assert len(built["sets"]["cell"]) == stored["cells"]
    first = built["sets"]["item"][0]
    assert first["kind"] == "bed" and first["zone"] == "R1" and first["width_m"] == 1.0 and first["height_m"] == 0.5


def _recipe_model(access=False):
    """The candidate form's own model (layout._spec), its item and cell sets and links made by a recipe."""
    spec = layout._spec([{"name": "bed", "value": 1}], {"items": "", "cells": "", "occupies": "", "keeps_free": "",
                                                         "next_to": ""}, True, "layout", access)
    ir = dict(spec["ir"])
    ir["sets"] = ["area", "item_kind"] + (["door"] if access else [])
    ir.pop("relationships")
    ir["generate"] = [_positions_recipe(access=access)]
    return ir


def _solve(ir, data):
    model = compile_model(ir, data)
    backend, _ = choose(classify(ir, data))
    result, _ = solve_compiled(backend, model, time_limit=30, seed=1, should_stop=lambda: False, workers=1,
                               gap_rel=0.0)
    assert result.status == "optimal"
    return result.objective


def _stored(tmp_path, access):
    """The same room as a stored candidate list (layout.make's files), read as a snapshot would freeze them."""
    import csv
    import os

    files = _room(tmp_path, door=access)
    out = layout.make(files, str(tmp_path), area_layers=["ROOMS"], items=[{"name": "bed", "length": 1.0,
                      "width": 0.5, "rotations": [0, 90]}], aisle=0.5, aisle_side="long", step=0.5,
                      access_layers=["DOORS"] if access else None)
    seed = out["spec"]["seed"]

    def rows(name):
        with open(os.path.join(tmp_path, name)) as f:
            return list(csv.DictReader(f))
    sets = {e["type"]: [{"id": r[e["key"]], **{a: r[c] for a, c in e["attrs"].items()}} for r in rows(e["file"])]
            for e in seed["entities_from_file"]}
    for r in sets["cell"]:
        r["entrance"] = int(r.get("entrance") or 0)
    rels = {e["type"]: [{"from": r[e["from"][1]], "to": r[e["to"][1]]} for r in rows(e["file"])]
            for e in seed["relationships_from_file"]}
    return out["spec"]["ir"], _data(sets, rels)


@pytest.mark.parametrize("access", [False, True])
def test_a_model_of_generated_positions_is_checked_compiled_and_solved_as_the_stored_one(tmp_path, access):
    ir = _recipe_model(access)
    assert check_shape(ir) is None
    data = _room_data(door=access)
    assert _solve(ir, data) == _solve(*_stored(tmp_path, access))
    assert variable_count(ir, data) == len(generate.apply(ir, data)["sets"]["item"]) + (
        len(generate.apply(ir, data)["sets"]["cell"]) if access else 0)


def test_a_recipe_too_large_refuses_at_the_compile(monkeypatch):
    monkeypatch.setattr(generate.limits, "GENERATED_MEMBERS", 10)
    with pytest.raises(Unsupported, match="more than the 10"):
        compile_model(_recipe_model(), _room_data())


FIXTURES = __import__("json").loads((__import__("pathlib").Path(__file__).parent / "generate_fixtures.json").read_text())


def test_the_shared_base_model_is_valid():
    assert check_shape(FIXTURES["base"]) is None


@pytest.mark.parametrize("case", FIXTURES["invalid"], ids=lambda c: c["why"])
def test_a_recipe_is_refused_by_its_shape(case):
    """The same cases, codes and places as frontend/src/ir/generate.test.ts."""
    problem = check_shape({**FIXTURES["base"], **case["change"]})
    assert problem is not None and (problem.code, problem.loc) == (case["code"], case["loc"]), problem


def test_rules_over_generated_sets_are_checked_against_the_domain():
    ir = _recipe_model()

    def world(attributes):
        return SimpleNamespace(
            entity_type_ids={"area": 1, "item_kind": 2}, ancestors={"area": [], "item_kind": []},
            attributes=attributes, relationship_ends={}, parameter_index={}, parameter_value_type={},
            predictor_inputs={}, edge_attributes={}, is_a=lambda s, a: s == a)

    checked = world({})
    with_generated(checked, ir)
    assert checked.relationship_ends["occupies"] == ("item", "cell")
    assert _DomainChecker(ir, checked).check() is None
    # A rule reading an attribute the recipe does not make is refused like any.
    bad = {**ir, "constraints": [*ir["constraints"], {
        "id": "c_colour", "forall": [{"index": "i", "set": "item"}], "left": {"attr": {"of": "i", "name": "colour"}},
        "relation": "<=", "right": {"const": 1}, "severity": "hard"}]}
    assert check_shape(bad) is None
    checked = world({})
    with_generated(checked, bad)
    assert _DomainChecker(bad, checked).check() is not None


def _from_files(folder, seed):
    import csv
    import os

    sets = {}
    for e in seed["entities_from_file"]:
        with open(os.path.join(folder, e["file"])) as f:
            sets[e["type"]] = [{"id": r[e["key"]], **{a: r[c] for a, c in e["attrs"].items()}} for r in csv.DictReader(f)]
    for r in sets.get("item_kind", []):
        for k in ("length_cells", "width_cells", "can_turn"):
            r[k] = int(r[k])
        r["value"] = float(r["value"])
    return _data(sets)


@pytest.mark.parametrize("access", [False, True])
def test_the_layout_tools_recipe_form_stores_two_small_tables_and_solves_as_the_list(tmp_path, access):
    kw = dict(area_layers=["ROOMS"], items=[{"name": "bed", "length": 1.0, "width": 0.5, "rotations": [0, 90]}],
              aisle=0.5, aisle_side="long", step=0.5, access_layers=["DOORS"] if access else None)
    listed = layout.make(_room(tmp_path / "a", door=access), str(tmp_path / "a"), **kw)
    recipe = layout.generated(_room(tmp_path / "b", door=access), str(tmp_path / "b"), **kw)
    assert recipe["form"] == "generated" and recipe["candidates"] == listed["candidates"]
    assert recipe["links"] == listed["links"] and recipe["stored"]["links"] == 0
    assert recipe["upper_bound"] == listed["upper_bound"]
    spec = recipe["spec"]
    assert check_shape(spec["ir"]) is None
    assert [e["type"] for e in spec["seed"]["entities_from_file"]] == ["area", "item_kind"] + (
        ["access_point"] if access else [])
    data = _from_files(tmp_path / "b", spec["seed"])
    assert len(generate.apply(spec["ir"], data)["sets"]["item"]) == listed["candidates"]
    assert _solve(spec["ir"], data) == _solve(*_stored(tmp_path / "c", access))


def test_a_kind_only_turned_is_stored_turned_and_a_square_once():
    from app.agent.layout import generated

    import tempfile

    folder = tempfile.mkdtemp()
    out = generated(_room(None), folder, area_layers=["ROOMS"], step=0.5, items=[
        {"name": "desk", "length": 1.0, "width": 0.5, "rotations": [90]},
        {"name": "box", "length": 0.5, "width": 0.5, "rotations": [0, 90]}])
    data = _from_files(folder, out["spec"]["seed"])
    assert {r["id"]: (r["length_cells"], r["width_cells"], r["can_turn"]) for r in data["sets"]["item_kind"]} == {
        "desk": (1, 2, 0), "box": (1, 1, 0)}
    # 4 x 2 m: an upright desk at each of 8 x 3 places; a box at each of 8 x 4.
    assert out["candidates_by_kind"] == {"desk": 24, "box": 32}
    assert len(generate.apply(out["spec"]["ir"], data)["sets"]["item"]) == 56


def test_a_generated_plan_builds_runs_and_reports_through_the_platform(tmp_path, tenants, db, empty_queue):  # noqa: F811
    """Built with only its areas and kinds stored; the worker builds the positions; the answer reads back with
    them (the Assistant's result, the exports) -- and no position, cell or link is a row anywhere."""
    from uuid import uuid4

    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.main import app
    from app.solve.service import claim_next, enqueue_run, execute_run

    out = layout.generated(_room(tmp_path), str(tmp_path), area_layers=["ROOMS"], aisle=0.5, aisle_side="long",
                           step=0.5, items=[{"name": "bed", "length": 1.0, "width": 0.5, "rotations": [0, 90]}])
    seed = dict(out["spec"]["seed"])
    data = _from_files(tmp_path, seed)
    seed["entities"] = [{"type": t, "key": r["id"], "attrs": {k: v for k, v in r.items() if k != "id"}}
                        for t, rows in data["sets"].items() for r in rows]
    del seed["entities_from_file"]
    spec = {"domain_name": f"generated {uuid4().hex[:6]}", "problem_name": "beds", "seed": seed,
            "ir": out["spec"]["ir"], "dry_run": False, "trial": False}
    client = TestClient(app)
    built = client.post("/api/v1/problems/from-spec", json=spec, headers=tenants["a"])
    assert built.status_code == 200, built.text
    run_id = enqueue_run(db, built.json()["scenario_id"], time_limit=20.0, reuse=False)
    outcome = None
    while (claimed := claim_next(db)) is not None:
        done = execute_run(db, claimed)
        outcome = done if claimed == run_id else outcome
    row = db.execute(text("SELECT r.status, r.error, d.data FROM run r JOIN dataset d ON d.id = r.dataset_id"
                          " WHERE r.id = :r"), {"r": run_id}).mappings().one()
    assert row["status"] == "optimal", row["error"]
    assert set(row["data"]["sets"]) == {"area", "item_kind"} and not row["data"].get("relationships")
    assert outcome.objective == _solve(*_stored(tmp_path / "stored", False))
    domain = db.execute(text("SELECT p.domain_id FROM run r JOIN scenario s ON s.id = r.scenario_id"
                             " JOIN problem p ON p.id = s.problem_id WHERE r.id = :r"), {"r": run_id}).scalar_one()
    assert db.execute(text("SELECT count(*) FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                           " WHERE t.domain_id = :d"), {"d": domain}).scalar_one() == 2
    result = client.get(f"/api/v1/agent/result/{run_id}", headers=tenants["a"]).json()
    assert result["facts"]["goal"] == outcome.objective
    sheet = client.get(f"/api/v1/runs/{run_id}/export?format=csv", headers=tenants["a"])
    assert sheet.status_code == 200 and "bed_" in sheet.text
