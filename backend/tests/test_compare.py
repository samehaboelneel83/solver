"""Two runs, side by side -- and what the platform may honestly claim.

The comparison people actually want is causal: *I relaxed this rule, and this
is what it bought me.* That claim is only true when the patch is the one thing
that differed. These tests are mostly about the cases where it is not:

- two runs over **different data** may differ for reasons that have nothing to
  do with the rules, and the comparison must say so rather than let a planner
  read an added employee as the effect of a relaxation;
- two runs of **different problems** are refused outright, because `assign`
  in one domain is not `assign` in another and lining them up would invent a
  relationship that does not exist.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.solve.compare import NotComparable, compare
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


def _scenario(db, version: int, name: str, patch: str = "{}") -> int:
    problem = db.execute(
        text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}
    ).scalar_one()
    scenario = db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name, patch)"
            " VALUES (:p, :v, :n, CAST(:patch AS jsonb)) RETURNING id"
        ),
        {"p": problem, "v": version, "n": name, "patch": patch},
    ).scalar_one()
    db.commit()
    return scenario


def _solved(db, scenario: int) -> int:
    run_id = enqueue_run(db, scenario, time_limit=20.0)
    work_once(db)
    return run_id


# -- the comparison itself --------------------------------------------------


def test_relaxing_a_rule_shows_what_it_bought_and_what_it_cost(db):
    """The comparison the whole feature exists for: one scenario insists on
    coverage, the other pays a penalty to break it. The objective moves, the
    roster moves, and the rule's outcome moves -- and because the patch is the
    only difference, all three can honestly be laid at its door."""
    version, _ = _feasible(db, demand_value=2, hours=8)
    strict = _scenario(db, version, "strict")
    relaxed = _scenario(db, version, "relaxed", '{"soften": {"c_cover": 100}}')

    left = _solved(db, strict)
    right = _solved(db, relaxed)

    result = compare(db, left, right)

    assert result.left["status"] == "infeasible"
    assert result.right["status"] in ("optimal", "feasible")
    assert result.differs_by == ["patch"]
    assert result.patch_is_the_only_difference is True
    assert "down to it" in result.note
    # The relaxed run has a roster; the strict one has none, so everything in
    # it is an addition.
    assert result.moved["assign"].added
    assert result.moved["assign"].removed == []


def test_a_rule_whose_outcome_changed_is_reported_with_both_sides(db):
    version, _ = _feasible(db, demand_value=2, hours=8)
    soft_cheap = _scenario(db, version, "cheap", '{"soften": {"c_cover": 1}}')
    soft_dear = _scenario(db, version, "dear", '{"soften": {"c_cover": 500}}')

    result = compare(db, _solved(db, soft_cheap), _solved(db, soft_dear))

    cover = next(r for r in result.rules if r.constraint_id == "c_cover")
    # Same breach, a different price for it: the penalty differs even where
    # the violation does not, which is exactly what changing the weight buys.
    assert cover.left_penalty != cover.right_penalty
    assert result.objective_delta is not None


def test_a_rule_that_held_in_both_runs_is_not_reported(db):
    """A diff that listed everything would bury the two lines that changed."""
    version, _ = _feasible(db, demand_value=1)
    a = _scenario(db, version, "a")
    b = _scenario(db, version, "b")

    result = compare(db, _solved(db, a), _solved(db, b))

    assert result.rules == []
    assert result.objective_delta == 0


# -- what it refuses to claim -----------------------------------------------


def test_runs_over_different_data_are_compared_but_not_attributed_to_the_patch(db):
    """The honesty rule. An employee added between the two runs can change the
    roster on its own; calling that the effect of a rule would be a wrong
    answer dressed as an insight."""
    version, _ = _feasible(db, demand_value=1)
    scenario = _scenario(db, version, "same")
    left = _solved(db, scenario)

    employee = db.execute(
        text(
            "SELECT et.id FROM entity_type et JOIN model_version mv ON TRUE"
            "  JOIN problem p ON p.id = mv.problem_id"
            " WHERE mv.id = :v AND et.domain_id = p.domain_id AND et.name = 'employee'"
        ),
        {"v": version},
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO entity (entity_type_id, key, label, attrs)"
            " VALUES (:t, 'zara', 'Zara', CAST('{\"hours_per_week\": 40}' AS jsonb))"
        ),
        {"t": employee},
    )
    db.commit()
    right = _solved(db, scenario)

    result = compare(db, left, right)

    assert "data" in result.differs_by
    assert result.patch_is_the_only_difference is False
    if len(result.differs_by) == 1:
        # One difference is the cause (operator trial F28).
        assert result.note == "these runs differ only by data, so the change in the answer is down to it"
    else:
        assert "cannot be attributed" in result.note


def test_two_runs_of_different_problems_are_refused(db):
    """Their variables are not the same vocabulary."""
    one, _ = _feasible(db, demand_value=1)
    two, _ = _feasible(db, demand_value=1)
    left = _solved(db, _scenario(db, one, "one"))
    right = _solved(db, _scenario(db, two, "two"))

    with pytest.raises(NotComparable) as excinfo:
        compare(db, left, right)

    assert "not the same vocabulary" in str(excinfo.value)


def test_a_run_compared_with_itself_is_refused(db):
    version, _ = _feasible(db, demand_value=1)
    run_id = _solved(db, _scenario(db, version, "only"))

    with pytest.raises(NotComparable):
        compare(db, run_id, run_id)


def test_an_unknown_run_is_refused_by_id(db):
    version, _ = _feasible(db, demand_value=1)
    run_id = _solved(db, _scenario(db, version, "only"))

    with pytest.raises(NotComparable) as excinfo:
        compare(db, run_id, 10**9)

    assert "no run" in str(excinfo.value)


def test_identical_runs_say_the_difference_is_the_solvers_freedom(db):
    """Two runs of the same scenario over the same data. Any difference in the
    roster is the solver choosing between equally good answers, and saying
    that is better than implying the model changed."""
    version, _ = _feasible(db, demand_value=1)
    scenario = _scenario(db, version, "twice")

    result = compare(db, _solved(db, scenario), _solved(db, scenario))

    assert result.differs_by == []
    assert result.patch_is_the_only_difference is False
    assert "equally good answers" in result.note


def test_one_difference_is_named_as_the_cause_and_several_are_not():
    from app.solve.compare import _note
    assert _note(["solver"]) == "these runs differ only by solver, so the change in the answer is down to it"
    assert "cannot be attributed" in _note(["data", "solver"])


def test_runs_before_and_after_a_scenario_moved_differ_by_its_model_version(db):
    """Benchmark, October 2026: a run read its model through its scenario, so once the scenario was
    moved to version 2 its version-1 runs were compared (and exported) as version 2."""
    first, _ = _feasible(db, demand_value=1)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": first}).scalar_one()
    ir = db.execute(text("SELECT ir FROM model_version WHERE id = :v"), {"v": first}).scalar_one()
    second = db.execute(text("INSERT INTO model_version (problem_id, ir, note) VALUES (:p, CAST(:ir AS jsonb), 'v2')"
                             " RETURNING id"), {"p": problem, "ir": __import__("json").dumps(ir)}).scalar_one()
    db.commit()
    scenario = _scenario(db, first, "moved")
    before = _solved(db, scenario)
    db.execute(text("UPDATE scenario SET model_version_id = :v WHERE id = :s"), {"v": second, "s": scenario})
    db.commit()
    after = _solved(db, scenario)

    assert db.execute(text("SELECT model_version_id FROM run WHERE id = :r"), {"r": before}).scalar_one() == first
    assert db.execute(text("SELECT model_version_id FROM run WHERE id = :r"), {"r": after}).scalar_one() == second
    assert compare(db, before, after).differs_by[0] == "model version"
