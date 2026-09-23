"""Why there is no answer.

The fixture is a conflict that can be reasoned about by hand. Two employees,
two days, one shift; each day needs **two** people, and an 8-hour weekly cap
means nobody can work more than one shift all week. Four shift-slots have to
be filled and only two can be. It is infeasible, and the reason is a
particular pair of rules -- coverage and the hours cap -- while the third
rule, "nobody works two shifts in a day", has nothing to do with it.

That third rule is what makes these tests worth writing. Reporting every hard
constraint would be true ("these cannot all hold") and worthless; the
question is which ones are *needed*, and the test asserts irreducibility
directly, by removing each reported member and checking the model becomes
solvable.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import text

from decimal import Decimal

from app.solve import compile_model, cpsat, highs
from app.solve.compile import Compiled, Constraint, Variable
from app.solve.compile import Linear
from app.solve.diagnose import explain
from app.solve.result import Solution
from app.solve.service import enqueue_run
from app.worker import work_once
from tests.test_solve import _feasible, _ir_and_data  # noqa: F401
from tests.test_v1_problem_run import (  # noqa: F401
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


@pytest.fixture(autouse=True)
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.commit()


def _impossible(db):
    """Demand 2 a day, but an 8-hour cap allows one shift a week each."""
    version, _ = _feasible(db, demand_value=2, hours=8)
    ir, data = _ir_and_data(db, version)
    return version, compile_model(ir, data)


def _solves(compiled, constraints) -> bool:
    """Is the model solvable with just these constraints?"""
    trial = replace(compiled, constraints=list(constraints), objective=Linear())
    return cpsat.solve(trial, time_limit=10.0).status in ("optimal", "feasible")


def _matches(constraint, items) -> bool:
    instance = [str(v) for v in constraint.index.values()]
    return any(
        item["constraint_id"] == constraint.id and item["instance"] == instance for item in items
    )


def _scenario_for(db, version: int) -> int:
    problem = db.execute(
        text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}
    ).scalar_one()
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name)"
            " VALUES (:p, :v, 'base') RETURNING id"
        ),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    return scenario


# -- the property the whole module exists for -------------------------------


def test_every_rule_reported_is_one_that_removing_makes_it_solvable(db):
    """Irreducibility, checked rather than claimed. If a member could be
    dropped and the model stayed infeasible, it was never part of the reason,
    and listing it sends a planner to change the wrong rule."""
    _, compiled = _impossible(db)

    conflict = explain(compiled, cpsat.solve)

    assert conflict.items, "an infeasible model must have a reason"
    assert conflict.minimal
    reported = [c for c in compiled.constraints if _matches(c, conflict.items)]
    assert _solves(compiled, []), "the fixture is only infeasible because of its rules"
    assert not _solves(compiled, reported), "the reported set must itself be infeasible"
    for dropped in reported:
        rest = [c for c in reported if c is not dropped]
        assert _solves(compiled, rest), (
            f"{dropped.id} {list(dropped.index.values())} was reported but is not needed"
        )


def test_a_rule_that_is_not_part_of_the_conflict_is_not_reported(db):
    """`c_one_shift_per_day` is a hard rule that holds here and is implied by
    the hours cap. Naming it would send a planner to edit a rule whose
    removal changes nothing."""
    _, compiled = _impossible(db)

    conflict = explain(compiled, cpsat.solve)

    assert "c_one_shift_per_day" not in conflict.rules
    assert set(conflict.rules) == {"c_cover", "c_max_hours"}


def test_the_conflict_names_instances_not_just_rules(db):
    """Coverage is broken is not actionable; Monday morning is. The schema's
    `run.conflict` is shaped for the second."""
    _, compiled = _impossible(db)

    conflict = explain(compiled, cpsat.solve)

    for item in conflict.items:
        assert set(item) == {"constraint_id", "instance"}
        assert all(isinstance(part, str) for part in item["instance"])
    cover = [i["instance"] for i in conflict.items if i["constraint_id"] == "c_cover"]
    assert cover
    assert all(part in (["mon", "morning"], ["tue", "morning"]) for part in cover)


# -- honesty when the search is cut short -----------------------------------


def test_a_search_that_runs_out_of_budget_says_it_is_not_minimal(db):
    """A truncated deletion filter still returns a set that conflicts, but not
    an irreducible one. Reporting it as minimal would tell a planner that
    every listed rule matters when some may not."""
    _, compiled = _impossible(db)

    conflict = explain(compiled, cpsat.solve, budget=1)

    assert conflict.minimal is False
    assert "may be larger than it needs to be" in conflict.note
    # Still true, and still a conflict: it just has not been narrowed.
    reported = [c for c in compiled.constraints if _matches(c, conflict.items)]
    assert not _solves(compiled, reported)


def test_a_probe_that_cannot_decide_stops_the_search_rather_than_guessing(db):
    """A timeout is not a verdict. Treating `unknown` as still-infeasible
    would drop a constraint that was in fact needed, and the answer would name
    the wrong rules."""
    _, compiled = _impossible(db)

    def never_decides(compiled, *, time_limit, workers=8):
        return Solution(
            status="unknown",
            optimal=False,
            objective=None,
            assignments={},
            wall_seconds=0.0,
            solver="stub",
        )

    conflict = explain(compiled, never_decides)

    assert conflict.minimal is False
    assert "without deciding" in conflict.note
    # Nothing was narrowed away on an undecided probe.
    assert len(conflict.items) == len(compiled.constraints)


# -- through a run ----------------------------------------------------------


def test_an_infeasible_run_records_its_conflict(db):
    version, compiled = _impossible(db)
    run_id = enqueue_run(db, _scenario_for(db, version), time_limit=20.0)

    work_once(db)

    row = db.execute(
        text("SELECT status, conflict, conflict_minimal, params FROM run WHERE id = :r"),
        {"r": run_id},
    ).mappings().one()
    assert row["status"] == "infeasible"
    assert row["conflict_minimal"] is True
    assert {item["constraint_id"] for item in row["conflict"]} == {"c_cover", "c_max_hours"}
    assert "removing any one" in row["params"]["conflict_note"]
    # The relaxation is infeasible too, so HiGHS named the core.
    assert row["params"]["conflict_method"] == "iis"
    assert row["params"]["conflict_probes"] >= 1


def test_a_solved_run_carries_no_conflict(db):
    """There is nothing to explain when there is an answer, and an empty list
    would read as a conflict with no members."""
    version, _ = _feasible(db, demand_value=1)
    run_id = enqueue_run(db, _scenario_for(db, version), time_limit=20.0)

    work_once(db)

    row = db.execute(
        text("SELECT status, conflict, conflict_minimal FROM run WHERE id = :r"), {"r": run_id}
    ).mappings().one()
    assert row["status"] == "optimal"
    assert row["conflict"] is None
    assert row["conflict_minimal"] is None


# -- a core from HiGHS's IIS (Phase 11) ---------------------------------------


def test_a_highs_core_gives_the_same_conflict_in_fewer_probes(db):
    """The fixture's relaxation is infeasible too (four slots, room for two
    even fractionally), so HiGHS names a core; CP-SAT confirms and shrinks
    it. Same rules, still irreducible, a fraction of the solves."""
    _, compiled = _impossible(db)

    whole = explain(compiled, cpsat.solve)
    cored = explain(compiled, cpsat.solve, core=highs.iis)

    assert whole.method == "deletion" and cored.method == "iis"
    assert cored.minimal and set(cored.rules) == set(whole.rules) == {"c_cover", "c_max_hours"}
    assert cored.probes < whole.probes, (cored.probes, whole.probes)
    reported = [c for c in compiled.constraints if _matches(c, cored.items)]
    assert not _solves(compiled, reported)
    for dropped in reported:
        assert _solves(compiled, [c for c in reported if c is not dropped])


def _whole_only() -> Compiled:
    """2x = 1 over whole x: infeasible, but x = 0.5 satisfies the relaxation."""
    x = ("x", ())
    return Compiled(
        variables={x: Variable(x, "integer", Decimal(0), Decimal(10))},
        constraints=[
            Constraint("c_cap", {}, Linear(coeffs={x: Decimal(1)}), "<=", Linear(const=Decimal(10))),
            Constraint("c_half", {}, Linear(coeffs={x: Decimal(2)}), "=", Linear(const=Decimal(1))),
        ],
        objective=Linear(),
        sense="minimize",
        var_index_sets={"x": []},
    )


def test_no_core_when_only_the_whole_numbers_conflict():
    compiled = _whole_only()
    assert highs.iis(compiled) is None

    conflict = explain(compiled, cpsat.solve, core=highs.iis)

    assert conflict.method == "deletion" and conflict.minimal
    assert conflict.rules == ["c_half"]


def test_a_core_the_backend_does_not_confirm_is_not_trusted():
    """A core is a candidate, not a verdict: offered one that holds (the cap
    alone), the search confirms, finds it solvable, and filters the model."""
    compiled = _whole_only()

    conflict = explain(compiled, cpsat.solve, core=lambda model: [0])

    assert conflict.method == "deletion"
    assert conflict.rules == ["c_half"] and conflict.minimal


def test_highs_names_the_rows_of_an_irreducible_subset():
    """x, y in 0..10: x + y >= 12, x <= 3, y <= 4, x - y <= 100. The first
    three cannot hold together; the fourth has nothing to do with it."""
    x, y = ("x", ()), ("y", ())
    box = {k: Variable(k, "continuous", Decimal(0), Decimal(10)) for k in (x, y)}
    rows = [
        Constraint("c_enough", {}, Linear(coeffs={x: Decimal(1), y: Decimal(1)}), ">=", Linear(const=Decimal(12))),
        Constraint("c_x", {}, Linear(coeffs={x: Decimal(1)}), "<=", Linear(const=Decimal(3))),
        Constraint("c_y", {}, Linear(coeffs={y: Decimal(1)}), "<=", Linear(const=Decimal(4))),
        Constraint("c_spread", {}, Linear(coeffs={x: Decimal(1), y: Decimal(-1)}), "<=", Linear(const=Decimal(100))),
    ]
    compiled = Compiled(variables=box, constraints=rows, objective=Linear(), sense="minimize", var_index_sets={})
    assert highs.iis(compiled) == [0, 1, 2]
    # Feasible once c_enough asks for 7: nothing to name.
    rows[0] = Constraint("c_enough", {}, rows[0].left, ">=", Linear(const=Decimal(7)))
    assert highs.iis(compiled) is None


def test_highs_is_not_asked_about_what_it_cannot_hold():
    compiled = _whole_only()
    switched = Constraint("c_half", {}, compiled.constraints[1].left, "=", Linear(const=Decimal(1)),
                          when=(("x", ()), 1))
    assert highs.iis(replace(compiled, constraints=[switched])) is None


def test_a_highs_core_that_cannot_finish_is_no_core(monkeypatch):
    """HiGHS's IIS search does not stop at its time limit, so its child can
    be killed at the deadline; the diagnosis must not die with it."""
    def killed(*args, **kwargs):
        raise RuntimeError("highs worker timed out")

    monkeypatch.setattr(highs, "_in_child", killed)
    compiled = _whole_only()
    assert highs.iis(compiled) is None
    conflict = explain(compiled, cpsat.solve, core=highs.iis)
    assert conflict.method == "deletion" and conflict.rules == ["c_half"]
