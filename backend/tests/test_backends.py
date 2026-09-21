"""Two solvers, one answer — and a policy that says which ran and why.

The test that gives this phase its meaning is `both_backends_agree`: the
same model, two genuinely different searches (constraint programming and
branch-and-cut), the same optimum. A second backend that quietly disagreed
would mean one of them is wrong, and with a single backend nothing could
ever have told us.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.solve import compile_model, classify
from app.solve.backends import CP_SAT, HIGHS, MILP, NoBackend, available_names, by_name, choose
from app.solve import cpsat, highs, milp
from app.solve.classify import Classification
from app.solve.service import enqueue_run, execute_run
from app.worker import work_once
from tests.test_solve import _feasible, _ir_and_data  # noqa: F401  (fixtures reused)
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


# -- the two backends, on the same model ------------------------------------


def test_both_backends_agree_on_the_optimum(db):
    """Constraint programming and branch-and-cut are different searches. If
    they disagreed about the best answer, one of them would be wrong -- and a
    platform with a single backend could never find that out."""
    version, _ = _feasible(db, demand_value=1)
    ir, data = _ir_and_data(db, version)
    compiled = compile_model(ir, data)

    from_cpsat = cpsat.solve(compiled, time_limit=10.0)
    from_milp = milp.solve(compiled, time_limit=10.0)

    assert from_cpsat.status == "optimal"
    assert from_milp.status == "optimal"
    assert from_cpsat.objective == from_milp.objective == 2
    # The rosters may differ -- several assignments can be optimal -- but
    # both must staff every day, which is the constraint, not the objective.
    for result in (from_cpsat, from_milp):
        assert {entry[1] for entry in result.chosen("assign")} == {"mon", "tue"}


def test_both_backends_call_an_impossible_model_infeasible(db):
    version, _ = _feasible(db, demand_value=1, hours=8)
    db.execute(text("DELETE FROM entity WHERE key = 'sara'"))
    ir, data = _ir_and_data(db, version)
    compiled = compile_model(ir, data)

    assert cpsat.solve(compiled, time_limit=10.0).status == "infeasible"
    assert milp.solve(compiled, time_limit=10.0).status == "infeasible"


def test_the_milp_backend_rounds_rather_than_truncates(db):
    """Its variable values come back as floats. A 1 that took a
    floating-point detour arrives as 0.9999999, and `int()` reads that as 0 --
    a roster that silently loses a shift."""
    version, _ = _feasible(db, demand_value=2)
    ir, data = _ir_and_data(db, version)

    result = milp.solve(compile_model(ir, data), time_limit=10.0)

    assert result.objective == 4
    assert all(value in (0, 1) for value in result.assignments.values())
    assert len(result.chosen("assign")) == 4


# -- the policy -------------------------------------------------------------


def test_an_integer_model_goes_to_the_highest_ranked_solver_that_fits():
    found = Classification("IP", ["every variable is binary"], {"linear", "integral"})

    backend, why = choose(found)

    assert backend is CP_SAT
    assert "highest-ranked" in why
    # And the reason names the alternative, because "why this one" is the
    # first question when two runs of the same model disagree.
    assert "milp" in why


def test_choose_has_a_planner_sentence_the_editor_can_show():
    """The Model editor must not grow a solver picker. It still has to say
    what a run would pick, and in words that are not the backend's name."""
    found = Classification("IP", [], {"linear", "integral"})

    backend, _why = choose(found)

    assert backend.planner_choice
    assert "combinatorial" in backend.planner_choice.lower()
    assert backend.name not in backend.planner_choice.lower()


def test_an_explicit_choice_wins_and_says_so():
    found = Classification("IP", [], {"linear", "integral"})

    backend, why = choose(found, "milp")

    assert backend is MILP
    assert why == "asked for milp"


def test_a_solver_that_cannot_take_the_model_is_refused_not_substituted():
    """Falling back silently would make the run's record a lie: it would say
    one solver ran when the caller asked for another."""
    found = Classification("MINLP", [], {"nonlinear"})

    with pytest.raises(NoBackend) as excinfo:
        choose(found, "cp-sat")

    assert "cannot take a MINLP model" in str(excinfo.value)


def test_an_unknown_solver_name_is_refused():
    with pytest.raises(NoBackend) as excinfo:
        choose(Classification("IP", [], {"linear"}), "gurobi")

    assert "no solver called 'gurobi'" in str(excinfo.value)


def test_a_model_no_backend_takes_fails_with_the_reason():
    found = Classification("MINLP", [], {"nonlinear"})

    with pytest.raises(NoBackend) as excinfo:
        choose(found)

    assert "no available solver takes a MINLP model" in str(excinfo.value)


def test_the_registry_reports_what_this_build_actually_has():
    # Checked, not assumed: a registry that offered a backend this build
    # cannot create would fail at solve time instead of selection time.
    names = available_names()
    assert names[0] == "cp-sat"
    assert "glop" in names
    assert "milp" in names
    if HIGHS.is_available():
        assert "highs" in names
        assert names.index("highs") < names.index("milp")
    else:
        assert "highs" not in names
    assert by_name("milp") is MILP
    assert by_name("highs") is HIGHS
    assert by_name("nope") is None


def test_highs_stays_available_after_ortools_has_loaded():
    """highspy and ortools both ship libHighs. A same-process import of
    highspy after milp would raise undefined symbol; the child process is
    what makes a fourth backend real rather than a row that is never ready."""
    assert milp.available() is not None
    from importlib.util import find_spec

    if find_spec("highspy") is None:
        pytest.skip("highspy is not in this build")
    assert highs.available()


@pytest.mark.skipif(not HIGHS.is_available(), reason="highspy is not in this build")
def test_highs_agrees_with_milp_on_the_optimum(db):
    version, _ = _feasible(db, demand_value=1)
    ir, data = _ir_and_data(db, version)
    compiled = compile_model(ir, data)

    from_highs = highs.solve(compiled, time_limit=10.0)
    from_milp = milp.solve(compiled, time_limit=10.0)

    assert from_highs.status == "optimal"
    assert from_milp.status == "optimal"
    assert from_highs.objective == from_milp.objective == 2


# -- through a run ----------------------------------------------------------


def test_a_run_records_which_solver_ran_and_why(db):
    seeded = _feasible(db)[0]
    problem = db.execute(
        text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": seeded}
    ).scalar_one()
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name)"
            " VALUES (:p, :v, 'base') RETURNING id"
        ),
        {"p": problem, "v": seeded},
    ).scalar_one()
    db.commit()

    run_id = enqueue_run(db, scenario, time_limit=10.0)
    work_once(db)

    row = db.execute(
        text("SELECT solver, params, status FROM run WHERE id = :r"), {"r": run_id}
    ).mappings().one()
    assert row["status"] == "optimal"
    assert row["solver"] == "cp-sat"
    assert row["params"]["chosen_solver"] == "cp-sat"
    assert "highest-ranked" in row["params"]["why_solver"]


def test_a_run_can_ask_for_the_other_solver(db):
    version = _feasible(db)[0]
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

    run_id = enqueue_run(db, scenario, time_limit=10.0, solver="milp")
    work_once(db)

    row = db.execute(
        text("SELECT solver, solver_version, objective, params FROM run WHERE id = :r"),
        {"r": run_id},
    ).mappings().one()
    assert row["solver"] == "milp"
    assert row["solver_version"].startswith(("scip", "cbc"))
    # Same model, same answer as cp-sat gives above.
    assert row["objective"] == 2
    assert row["params"]["why_solver"] == "asked for milp"
