"""SCIP: the global solver for the quadratic models stage 2 refused.

Stage 2 refused a continuous quadratic objective that is not proven convex,
and a quadratic objective over mixed decisions, because nothing here could
solve them and PROVE the answer best. SCIP's spatial branch-and-bound can,
so these tests pin that it now takes exactly those -- and only those: a
convex QP still goes to HiGHS and an all-integer one to CP-SAT -- and that
its answers are the ones worked out by hand.

The examples reuse `test_quadratic`'s: share 10 units over items. Maximising
the sum of squares is nonconvex and its best is everything on one item, 100
-- the answer a local solver started in the middle (5 and 5, 50) would miss.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.solve import compile_model, scip
from app.solve.backends import CP_SAT, HIGHS, SCIP, NoBackend, choose
from app.solve.classify import classify, with_convexity
from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.convexity import objective_convexity
from tests.test_quadratic import _ir, _model, _run, empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _found(ir, data):
    convexity = objective_convexity(compile_model(ir, data))
    return with_convexity(classify(ir, data), convexity.convex, convexity.reason)


def _mixed_ir(sense: str = "minimize") -> dict:
    """The 10-unit share over continuous items, plus a yes/no `open` that
    must be 1 for anything to be shared and costs 1 in the objective."""
    ir = _ir("continuous", sense)
    ir["variables"]["open"] = {"index": [], "domain": "binary"}
    ir["constraints"].append(
        {
            "id": "c_open",
            "left": {"sum": {"var": "x", "index": ["i"]}, "over": [{"index": "i", "set": "item"}]},
            "relation": "<=",
            "right": {"mul": [{"const": 10}, {"var": "open", "index": []}]},
            "severity": "hard",
        }
    )
    ir["objective"]["terms"].append(
        {"id": "o_open", "weight": 1, "expression": {"var": "open", "index": []}}
    )
    return ir


def test_this_build_has_scip():
    assert scip.available()


# -- who takes what -----------------------------------------------------------


def test_a_nonconvex_continuous_model_goes_to_scip(db):
    _, ir, data = _model(db, 2, "continuous", sense="maximize")
    backend, why = choose(_found(ir, data))
    assert backend is SCIP
    assert "QP" in why


def test_a_quadratic_goal_over_mixed_decisions_goes_to_scip():
    found = classify(_mixed_ir())
    assert found.model_class == "MIQP"
    backend, _ = choose(found)
    assert backend is SCIP


def test_scip_does_not_take_what_a_faster_solver_proves_as_well(db):
    """Rank 2: the convex QP stays with HiGHS, the integer MIQP with CP-SAT."""
    _, convex, data = _model(db, 2, "continuous")
    assert choose(_found(convex, data))[0] is HIGHS
    _, integer, data = _model(db, 3, "integer", sense="maximize")
    assert choose(_found(integer, data))[0] is CP_SAT


def test_scip_is_offered_no_linear_model():
    assert not SCIP.classes & {"LP", "IP", "MILP", "trivial"}


def test_without_scip_the_refusals_come_back(db, monkeypatch):
    """A build without PySCIPOpt still refuses rather than answering badly."""
    monkeypatch.setattr(scip, "_available", False)
    _, ir, data = _model(db, 2, "continuous", sense="maximize")
    with pytest.raises(NoBackend, match="not proven convex"):
        choose(_found(ir, data))
    with pytest.raises(NoBackend, match="mixed-integer quadratic solver"):
        choose(classify(_mixed_ir()))


# -- the answers --------------------------------------------------------------


def test_scip_finds_the_nonconvex_global_optimum_not_the_middle(db):
    _, ir, data = _model(db, 2, "continuous", sense="maximize")
    solution = scip.solve(compile_model(ir, data), time_limit=20)

    assert solution.status == "optimal"
    assert solution.objective == 100
    assert sorted(solution.assignments.values()) == [0, 10]


def test_scip_finds_the_convex_optimum_too(db):
    """Nothing routes a convex QP here, but the answer must still agree
    with HiGHS's: two solvers disagreeing on one model is a bug in one."""
    _, ir, data = _model(db, 2, "continuous")
    solution = scip.solve(compile_model(ir, data), time_limit=20)

    assert solution.status == "optimal"
    assert abs(Decimal(str(solution.objective)) - 50) < Decimal("0.0001")


def test_a_run_of_a_nonconvex_model_is_solved_by_scip_and_says_global(db):
    version, _, _ = _model(db, 2, "continuous", sense="maximize")

    row = _run(db, version)

    assert row["status"] == "optimal", row["error"]
    assert row["solver"] == "scip"
    assert row["optimality"] == "global"
    assert row["objective"] == Decimal("100")


def test_a_run_of_a_mixed_quadratic_model_is_solved_by_scip(db):
    from tests.test_v1_problem_run import (
        make_domain,
        make_entity,
        make_entity_type,
        make_model_version,
        make_problem,
    )

    dom = make_domain(db, "qp-mixed")
    item = make_entity_type(db, dom, "item", "resource")
    for k in range(2):
        make_entity(db, item, f"i{k}")
    version = make_model_version(db, make_problem(db, dom), _mixed_ir())

    row = _run(db, version)

    assert row["status"] == "optimal", row["error"]
    assert row["solver"] == "scip"
    assert row["optimality"] == "global"
    # 5 and 5 squared, plus opening: 51.
    assert abs(row["objective"] - Decimal("51")) < Decimal("0.0001")


def test_the_editor_promises_the_global_solver_for_a_nonconvex_model(db):
    """`/classify` and a run take the same path: now that a run solves this
    model, the editor must say something will."""
    from app.solve.backends import planner_choice_for

    _, ir, data = _model(db, 2, "continuous", sense="maximize")
    assert planner_choice_for(_found(ir, data)) == SCIP.planner_choice


# -- the adapter's edges --------------------------------------------------------


def _one_var(constraints: list[Constraint]) -> Compiled:
    key = ("x", ())
    return Compiled(
        variables={key: Variable(key, "continuous", Decimal(0), Decimal(5))},
        constraints=constraints,
        objective=Linear({key: Decimal(1)}),
        sense="maximize",
        var_index_sets={"x": []},
    )


def test_a_rule_left_with_nothing_to_decide_that_holds_is_dropped():
    rule = Constraint("c", {}, Linear(const=Decimal(1)), ">=", Linear(const=Decimal(0)))
    solution = scip.solve(_one_var([rule]), time_limit=5)
    assert solution.status == "optimal"
    assert solution.objective == 5


def test_a_rule_left_with_nothing_to_decide_that_fails_makes_it_infeasible():
    rule = Constraint("c", {}, Linear(const=Decimal(0)), ">=", Linear(const=Decimal(1)))
    solution = scip.solve(_one_var([rule]), time_limit=5)
    assert solution.status == "infeasible"
    assert solution.objective is None


def test_a_stop_request_before_the_solve_interrupts_it(db):
    _, ir, data = _model(db, 2, "continuous", sense="maximize")
    solution = scip.solve(compile_model(ir, data), time_limit=20, should_stop=lambda: True)
    assert solution.status == "unknown"
    assert not solution.optimal
    assert solution.assignments == {}
