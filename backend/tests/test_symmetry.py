"""Symmetry breaking: which entities are interchangeable, and that ordering them never changes the optimum.

Interchangeable means nothing in the model can tell two members apart: the
same attributes, the same parameter cells, the same neighbours, and no edge
between them. The ordering rows keep one arrangement of each class, so the
proven optimum must be the one found without them -- checked against CP-SAT,
which is given no rows, on seeded random rosters.
"""

from __future__ import annotations

import random

import pytest
from sqlalchemy import text

from app.solve import compile_model
from app.solve.backends import by_name
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from app.solve.symmetry import classes, order_rows
from tests.test_diagnose import _scenario_for
from tests.test_solve import _feasible  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

IR = {
    "version": 1,
    "sets": ["person", "day"],
    "relationships": ["mentors"],
    "parameters": {"demand": {"index": ["day"]}, "skill": {"index": ["person"]}},
    "variables": {"assign": {"index": ["person", "day"], "domain": "binary"}},
    "constraints": [],
}


def _data(people, skills=None, edges=()):
    return {
        "sets": {"person": people, "day": [{"id": "mon"}, {"id": "tue"}]},
        "parameters": {
            "demand": [{"day": "mon", "value": 1}, {"day": "tue", "value": 2}],
            "skill": [{"person": p, "value": v} for p, v in (skills or {}).items()],
        },
        "relationships": {"mentors": [{"from": a, "to": b} for a, b in edges]},
        "parameter_defaults": {},
    }


def test_members_alike_in_everything_are_one_class():
    people = [{"id": p, "grade": "mid"} for p in ("a", "b", "c")]
    assert classes(IR, _data(people)) == [("person", ("a", "b", "c"))]


def test_an_attribute_a_parameter_cell_or_a_neighbour_tells_members_apart():
    people = [{"id": "a", "grade": "mid"}, {"id": "b", "grade": "mid"}, {"id": "c", "grade": "senior"}]
    assert classes(IR, _data(people)) == [("person", ("a", "b"))]
    alike = [{"id": p} for p in ("a", "b", "c")]
    assert classes(IR, _data(alike, skills={"a": 1, "b": 1, "c": 2})) == [("person", ("a", "b"))]
    # c mentors a new starter z the others do not: c is set apart.
    found = classes(IR, _data(alike + [{"id": "z"}], edges=[("c", "z")]))
    assert ("person", ("a", "b")) in found
    assert not any("c" in members for _, members in found)


def test_members_joined_by_an_edge_are_never_interchangeable():
    """a mentors b and b mentors a: alike in every signature, but a class
    would let an ordering swap the two ends of the relationship."""
    alike = [{"id": "a"}, {"id": "b"}]
    assert classes(IR, _data(alike, edges=[("a", "b"), ("b", "a")])) == []


def test_the_rows_order_each_members_total_on_one_variable():
    ir = {**IR, "relationships": [], "parameters": {}}
    compiled = compile_model(ir, _data([{"id": p} for p in ("a", "b", "c")]))
    ordered, record = order_rows(compiled)
    added = ordered.constraints[len(compiled.constraints):]
    assert record == [
        {"set": "person", "members": 3, "variable": "assign", "rows": 2},
        {"set": "day", "members": 2, "variable": "assign", "rows": 1},
    ]
    first = added[0]
    assert (first.id, first.relation) == ("__symmetry", ">=")
    assert sorted(k[1] for k in first.left.coeffs) == [("a", "mon"), ("a", "tue")]
    assert sorted(k[1] for k in first.right.coeffs) == [("b", "mon"), ("b", "tue")]


# -- the optimum is never cut ---------------------------------------------------------------


def _roster(seed: int):
    """Six people on two contracts, three days: cover each day's demand,
    within each person's cap, at least cost."""
    rnd = random.Random(seed)
    contracts = [(rnd.randint(1, 3), rnd.randint(1, 9)) for _ in range(2)]
    people = [{"id": f"p{i}", "cap": contracts[i % 2][0], "cost": contracts[i % 2][1]} for i in range(6)]
    days = [{"id": f"d{d}"} for d in range(3)]
    ir = {
        "version": 1,
        "sets": ["person", "day"],
        "parameters": {"demand": {"index": ["day"]}},
        "variables": {"assign": {"index": ["person", "day"], "domain": "binary"}},
        "constraints": [
            {"id": "c_cover", "forall": [{"index": "d", "set": "day"}],
             "left": {"sum": {"var": "assign", "index": ["p", "d"]}, "over": [{"index": "p", "set": "person"}]},
             "relation": ">=", "right": {"par": "demand", "index": ["d"]}, "severity": "hard"},
            {"id": "c_cap", "forall": [{"index": "p", "set": "person"}],
             "left": {"sum": {"var": "assign", "index": ["p", "d"]}, "over": [{"index": "d", "set": "day"}]},
             "relation": "<=", "right": {"attr": {"of": "p", "name": "cap"}}, "severity": "hard"},
        ],
        "objective": {"sense": "minimize", "terms": [{"id": "o", "weight": 1, "expression": {"sum": {
            "mul": [{"attr": {"of": "p", "name": "cost"}}, {"var": "assign", "index": ["p", "d"]}]},
            "over": [{"index": "p", "set": "person"}, {"index": "d", "set": "day"}]}}]},
    }
    data = {"sets": {"person": people, "day": days},
            "parameters": {"demand": [{"day": d["id"], "value": rnd.randint(1, 5)} for d in days]},
            "parameter_defaults": {}, "relationships": {}}
    return ir, data


@pytest.mark.parametrize("seed", range(30))
def test_ordering_never_cuts_the_optimum(seed):
    ir, data = _roster(seed)
    compiled = compile_model(ir, data)
    assert compiled.symmetry, "the fixture is built to have classes"
    reference, _ = solve_compiled(by_name("cp-sat"), compiled, time_limit=10, seed=1)
    for name in ("highs", "milp"):
        backend = by_name(name)
        if not backend.is_available():
            continue
        result, _ = solve_compiled(backend, compiled, time_limit=10, seed=1, symmetry=True)
        assert result.status == reference.status, (seed, name)
        if reference.status == "optimal":
            assert abs(float(result.objective) - float(reference.objective)) < 1e-6, (seed, name)


def test_the_random_rosters_are_not_all_one_easy_case():
    statuses = set()
    for seed in range(30):
        ir, data = _roster(seed)
        statuses.add(solve_compiled(by_name("cp-sat"), compile_model(ir, data), time_limit=10, seed=1)[0].status)
    assert statuses == {"optimal", "infeasible"}


def test_cp_sat_and_scip_are_never_given_the_rows(monkeypatch):
    import app.solve.symmetry as symmetry

    called = []
    monkeypatch.setattr(symmetry, "order_rows", lambda compiled: called.append(1) or (compiled, []))
    ir, data = _roster(0)
    for name in ("cp-sat", "scip"):
        solve_compiled(by_name(name), compile_model(ir, data), time_limit=10, seed=1, symmetry=True)
    assert called == []


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


@pytest.mark.parametrize("on", [False, True])
def test_a_highs_run_records_the_ordering_only_when_the_setting_says_so(db, empty_queue, on):
    version, _ = _feasible(db)
    scenario = _scenario_for(db, version)
    problem = db.execute(text("SELECT problem_id FROM scenario WHERE id = :s"), {"s": scenario}).scalar_one()
    if on:
        db.execute(
            text("INSERT INTO setting (scope, scope_id, key, value)"
                 " VALUES ('problem', :p, 'solve.symmetry', CAST('true' AS jsonb))"),
            {"p": problem},
        )
        db.commit()
    run_id = enqueue_run(db, scenario, time_limit=10.0, solver="highs")
    assert claim_next(db) == run_id
    outcome = execute_run(db, run_id)
    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    assert outcome.status == "optimal" and params["symmetry"] is on
    if on:
        # The fixture's two employees are alike.
        assert "employee" in {entry["set"] for entry in params["symmetry_rows"]}
    else:
        assert "symmetry_rows" not in params


def _reference_signature(set_name, row, ir, data):
    """The detection as first written: every cell and edge scanned for every member."""
    from app.solve.compile import parameter_index

    key = row["id"]
    attributes = tuple(sorted((k, repr(v)) for k, v in row.items() if k != "id"))
    cells = []
    for name, spec in (ir.get("parameters") or {}).items():
        order = spec.get("index", [])
        if set_name not in order:
            continue
        at = order.index(set_name)
        for cell in data.get("parameters", {}).get(name, []):
            index = parameter_index(cell, order)
            if index[at] == key:
                cells.append((name, index[:at] + index[at + 1:], repr(cell["value"])))
    edges = []
    for rel in ir.get("relationships") or []:
        for edge in data.get("relationships", {}).get(rel, []):
            if edge["from"] == key:
                edges.append((rel, "to", edge["to"]))
            if edge["to"] == key:
                edges.append((rel, "from", edge["from"]))
    return attributes, tuple(sorted(cells)), tuple(sorted(edges))


@pytest.mark.parametrize("family", ["rota_teams", "rota", "facility", "knapsack", "flow_shop"])
def test_the_one_pass_detection_finds_exactly_what_the_member_by_member_one_did(family):
    """Bucketing cells and edges by member (the PDLP bench's compile fix) changes no class."""
    from bench.families import generate
    from app.solve.symmetry import _linked, classes

    instance = generate(family, "S", 0)
    ir, data = instance.ir, instance.data
    expected = []
    for set_name in ir.get("sets") or []:
        if any(spec.get("index", []).count(set_name) > 1 for spec in (ir.get("parameters") or {}).values()):
            continue
        rows = data.get("sets", {}).get(set_name, [])
        groups = {}
        for row in rows:
            groups.setdefault(_reference_signature(set_name, row, ir, data), []).append(row["id"])
        expected += [(set_name, tuple(m)) for m in groups.values() if len(m) > 1 and not _linked(m, ir, data)]
    assert classes(ir, data) == expected
