"""Solving: IR + frozen dataset -> an answer.

These tests are the first in the project to close the loop the platform was
built for — model a domain, freeze it, and get a roster back.

Two of them are worth reading for what they assert rather than that they pass:

- the **seeded** workforce model is *infeasible*, and should be. Five
  employees cannot cover 57 shift-slots, which is why the seed ships a
  scenario that softens the coverage constraint. A platform that returned a
  roster here would be lying;
- the feasible fixture asserts the three constraints hold **in the returned
  assignment**, not merely that a solver said "succeeded". A compiler that
  dropped a constraint would still report success.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.seed import seed_workforce_demo
from app.solve import Unsupported, classify, compile_model, solve
from app.solve.service import COMPILER_VERSION, patched, run_scenario
from tests.test_v1_problem_run import (  # noqa: F401  (db fixture)
    _data,
    _snapshot,
    db,
    make_attribute_def,
    make_domain,
    make_entity,
    make_entity_type,
    make_model_version,
    make_parameter_def,
    make_parameter_value,
    make_problem,
)


def _ir_and_data(db, version: int) -> tuple[dict, dict]:
    ir = db.execute(
        text("SELECT ir FROM model_version WHERE id = :v"), {"v": version}
    ).scalar_one()
    return ir, _data(db, _snapshot(db, version))


# -- a small model that has an answer ---------------------------------------


def _feasible(db, demand_value: int = 1, hours: int = 40):
    """Two employees, two days, one shift. Deliberately small enough that the
    right answer can be reasoned about by hand: coverage needs
    `demand_value` people on each of two days, so the minimum total is
    `2 * demand_value`."""
    domain = make_domain(db, "rota")
    employee = make_entity_type(db, domain, "employee", "agent")
    day = make_entity_type(db, domain, "day", "time")
    shift = make_entity_type(db, domain, "shift", "time")
    make_attribute_def(db, employee, "hours_per_week", "integer")

    for key in ("ahmed", "sara"):
        make_entity(db, employee, key, attrs={"hours_per_week": hours})
    for key in ("mon", "tue"):
        make_entity(db, day, key)
    make_entity(db, shift, "morning")

    demand = make_parameter_def(db, domain, "demand", [day, shift], default_value=demand_value)

    ir = {
        "version": 1,
        "sets": ["employee", "day", "shift"],
        "parameters": {"demand": {"index": ["day", "shift"]}},
        "variables": {"assign": {"index": ["employee", "day", "shift"], "domain": "binary"}},
        "constraints": [
            {
                "id": "c_cover",
                "note": "each day/shift is staffed to demand",
                "forall": [{"index": "d", "set": "day"}, {"index": "s", "set": "shift"}],
                "left": {
                    "sum": {"var": "assign", "index": ["e", "d", "s"]},
                    "over": [{"index": "e", "set": "employee"}],
                },
                "relation": ">=",
                "right": {"par": "demand", "index": ["d", "s"]},
                "severity": "hard",
            },
            {
                "id": "c_one_shift_per_day",
                "note": "nobody works two shifts in a day",
                "forall": [{"index": "e", "set": "employee"}, {"index": "d", "set": "day"}],
                "left": {
                    "sum": {"var": "assign", "index": ["e", "d", "s"]},
                    "over": [{"index": "s", "set": "shift"}],
                },
                "relation": "<=",
                "right": {"const": 1},
                "severity": "hard",
            },
            {
                "id": "c_max_hours",
                "note": "eight hours a shift, within the weekly limit",
                "forall": [{"index": "e", "set": "employee"}],
                "left": {
                    "mul": [
                        {"const": 8},
                        {
                            "sum": {"var": "assign", "index": ["e", "d", "s"]},
                            "over": [{"index": "d", "set": "day"}, {"index": "s", "set": "shift"}],
                        },
                    ]
                },
                "relation": "<=",
                "right": {"attr": {"of": "e", "name": "hours_per_week"}},
                "severity": "hard",
            },
        ],
        "objective": {
            "sense": "minimize",
            "terms": [
                {
                    "id": "o_shifts",
                    "weight": 1,
                    "expression": {
                        "sum": {"var": "assign", "index": ["e", "d", "s"]},
                        "over": [
                            {"index": "e", "set": "employee"},
                            {"index": "d", "set": "day"},
                            {"index": "s", "set": "shift"},
                        ],
                    },
                }
            ],
        },
    }
    problem = make_problem(db, domain)
    return make_model_version(db, problem, ir), demand


def test_a_feasible_model_returns_a_roster_that_satisfies_every_constraint(db):
    version, _ = _feasible(db)
    ir, data = _ir_and_data(db, version)

    result = solve(compile_model(ir, data))

    assert result.status == "optimal"
    roster = result.chosen("assign")
    # Two days, one person needed on each: the optimum is two shifts, and
    # minimising means it is not three.
    assert result.objective == 2
    assert len(roster) == 2

    # The constraints, re-checked against the answer rather than trusted.
    for day in ("mon", "tue"):
        covered = [r for r in roster if r[1] == day]
        assert len(covered) >= 1, f"{day} is unstaffed"
    for employee in ("ahmed", "sara"):
        for day in ("mon", "tue"):
            same_day = [r for r in roster if r[0] == employee and r[1] == day]
            assert len(same_day) <= 1
        assert 8 * len([r for r in roster if r[0] == employee]) <= 40


def test_an_absent_parameter_cell_falls_back_to_the_default(db):
    """Sparse storage (Ruling 28): no cell is stored for either day, so the
    whole demand comes from `parameter_defaults`. If the compiler read a
    missing cell as zero, this model would need no one at all."""
    version, _ = _feasible(db, demand_value=2)
    ir, data = _ir_and_data(db, version)

    assert data["parameters"]["demand"] == []
    assert data["parameter_defaults"]["demand"] == 2

    result = solve(compile_model(ir, data))

    assert result.objective == 4  # two days, two people each


def test_a_stored_cell_overrides_the_default(db):
    version, demand = _feasible(db, demand_value=1)
    ids = {
        row[0]: row[1]
        for row in db.execute(
            text(
                "SELECT e.key, e.id FROM entity e JOIN entity_type t ON t.id = e.entity_type_id"
                " JOIN parameter_def pd ON pd.domain_id = t.domain_id WHERE pd.id = :p"
            ),
            {"p": demand},
        )
    }
    make_parameter_value(db, demand, [ids["mon"], ids["morning"]], 2)
    ir, data = _ir_and_data(db, version)

    result = solve(compile_model(ir, data))

    # Monday now needs two, Tuesday still one.
    assert result.objective == 3
    assert len([r for r in result.chosen("assign") if r[1] == "mon"]) == 2


def test_an_impossible_model_is_reported_infeasible_not_answered(db):
    """One employee, a weekly limit of eight hours, and two days needing
    cover. There is no roster; saying so is the answer."""
    version, _ = _feasible(db, demand_value=1, hours=8)
    db.execute(text("DELETE FROM entity WHERE key = 'sara'"))
    ir, data = _ir_and_data(db, version)

    result = solve(compile_model(ir, data))

    assert result.status == "infeasible"
    assert result.assignments == {}


# -- the seeded demo --------------------------------------------------------


def test_the_seeded_workforce_model_classifies_as_an_integer_program(db):
    seeded = seed_workforce_demo(db)
    ir, _ = _ir_and_data(db, seeded["model_version_id"])

    found = classify(ir)

    assert found.model_class == "IP"
    assert "every variable is binary" in found.reasons
    assert found.needs == {"linear", "integral"}


def test_the_seeded_workforce_model_is_infeasible_as_shipped(db):
    """Not a failure -- the seed is deliberately over-subscribed, which is why
    it ships a scenario that softens coverage. The platform's job here is to
    say so rather than return a roster that does not cover the demand."""
    seeded = seed_workforce_demo(db)
    ir, data = _ir_and_data(db, seeded["model_version_id"])

    result = solve(compile_model(ir, data), time_limit=30.0)

    assert result.status == "infeasible"


def test_a_soft_constraint_with_a_strict_relation_is_refused(db):
    """`>=` and `<=` have a well-defined "by how much"; `>` and `<` do not,
    so the penalty would be arbitrary. Refused rather than guessed."""
    version, _ = _feasible(db)
    ir, data = _ir_and_data(db, version)
    ir["constraints"][0]["severity"] = "soft"
    ir["constraints"][0]["relation"] = ">"

    with pytest.raises(Unsupported) as excinfo:
        compile_model(ir, data)

    assert "c_cover" in str(excinfo.value)


# -- runs: the tables 0007 created and nothing had written to ---------------


def test_running_the_seeded_scenario_records_a_run_a_solution_and_every_constraint(db):
    """End to end on the shipped demo. Its scenario softens coverage, which
    is what makes the over-subscribed model answerable: the roster breaks the
    rule as little as it can, and the run says by how much and where."""
    seeded = seed_workforce_demo(db)

    outcome = run_scenario(db, seeded["scenario_id"], time_limit=30.0)

    assert outcome.status in ("optimal", "feasible")
    run = db.execute(
        text(
            "SELECT status, solver, solver_version, compiler_version, objective,"
            "       wall_time_s, params, dataset_id FROM run WHERE id = :r"
        ),
        {"r": outcome.run_id},
    ).mappings().one()
    assert run["status"] in ("optimal", "feasible")
    assert run["solver"] == "cp-sat"
    assert "ortools" in run["solver_version"]          # reproducible: which solver
    assert run["compiler_version"] == COMPILER_VERSION  # and which compiler
    assert run["params"]["classified_as"] == "IP"
    assert run["wall_time_s"] >= 0

    rows = db.execute(
        text(
            "SELECT constraint_id, hard, satisfied, total_violation"
            "  FROM constraint_result WHERE run_id = :r ORDER BY constraint_id"
        ),
        {"r": outcome.run_id},
    ).mappings().all()
    by_id = {r["constraint_id"]: r for r in rows}

    # Every constraint is reported, not only the broken ones -- "which rules
    # held" is part of the answer.
    assert set(by_id) == {"c_cover_demand", "c_one_shift_per_day", "c_max_hours"}
    # The softened one is the one that gives.
    assert by_id["c_cover_demand"]["hard"] is False
    assert by_id["c_cover_demand"]["satisfied"] is False
    assert by_id["c_cover_demand"]["total_violation"] > 0
    # The two hard ones are honoured exactly.
    assert by_id["c_one_shift_per_day"]["satisfied"] is True
    assert by_id["c_max_hours"]["satisfied"] is True

    assignments = db.execute(
        text("SELECT assignments FROM solution WHERE run_id = :r"), {"r": outcome.run_id}
    ).scalar_one()
    roster = assignments["assign"]
    assert roster, "a solved run with an empty roster would be a lie"
    # The roster is in the domain's words: [employee, day, shift].
    assert all(len(entry) == 3 for entry in roster)
    # Derived from the frozen dataset rather than hardcoded: a roster naming
    # someone the run was not given would be the bug worth catching here.
    _, data = _ir_and_data(db, seeded["model_version_id"])
    assert {e[0] for e in roster} <= {row["id"] for row in data["sets"]["employee"]}
    assert {e[1] for e in roster} <= {row["id"] for row in data["sets"]["day"]}
    assert {e[2] for e in roster} <= {row["id"] for row in data["sets"]["shift"]}


def test_the_same_scenario_run_twice_shares_its_dataset(db):
    """The snapshot is content-hashed, so a second run of unchanged data
    reuses it rather than minting a near-duplicate -- which is what makes two
    runs comparable."""
    seeded = seed_workforce_demo(db)

    first = run_scenario(db, seeded["scenario_id"], time_limit=15.0)
    second = run_scenario(db, seeded["scenario_id"], time_limit=15.0)

    assert first.dataset_id == second.dataset_id
    assert first.run_id != second.run_id


def test_a_soft_constraint_is_paid_for_rather_than_free(db):
    """With coverage softened, the optimum must still prefer covering. If the
    penalty were dropped, staffing nobody would be optimal and the objective
    would be zero."""
    version, _ = _feasible(db, demand_value=1)
    ir, data = _ir_and_data(db, version)
    softened = patched(ir, {"soften": {"c_cover": 50}})

    result = solve(compile_model(softened, data))

    assert result.status == "optimal"
    # Covering costs 2 (one shift each day); not covering would cost 100.
    assert result.objective == 2


def test_disabling_a_constraint_through_a_patch_removes_it(db):
    version, _ = _feasible(db, demand_value=1, hours=8)
    ir, data = _ir_and_data(db, version)
    db.execute(text("DELETE FROM entity WHERE key = 'sara'"))
    _, data = _ir_and_data(db, version)

    # Hard, it cannot be done: one person, 8 hours, two days to cover.
    assert solve(compile_model(ir, data)).status == "infeasible"

    # Without the hours limit, it can.
    relaxed = patched(ir, {"disable": ["c_max_hours"]})
    assert solve(compile_model(relaxed, data)).status == "optimal"
