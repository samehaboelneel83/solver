"""The local nonlinear lane (app.solve.ipopt, queue R6): the best answer nearby, never called the best."""

from __future__ import annotations

import math

import pytest
from sqlalchemy import text

from app.solve import compile_model
from app.solve.backends import IPOPT, by_name, choose, optimality_of
from app.solve.classify import classify
from app.solve.lp import NotContinuous
from app.solve.service import claim_next, enqueue_run, execute_run, solve_compiled
from tests.test_functions import BUDGET, NO_DATA, X, _ir, empty_queue, fn, plus, times  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401

pytestmark = pytest.mark.skipif(not IPOPT.is_available(), reason="casadi (IPOPT) is not installed in this image")


def _ipopt(ir, time_limit=10):
    compiled = compile_model(ir, NO_DATA)
    return solve_compiled(by_name("ipopt"), compiled, time_limit=time_limit, seed=1)[0]


def test_a_convex_model_reaches_the_optimum_worked_by_hand():
    # exp(x) - 2x falls until e^x = 2: x = ln 2, worth 2 - 2 ln 2.
    result = _ipopt(_ir(plus(fn("exp", X), times(-2, X))))
    assert result.status == "optimal" and result.best_bound is None
    assert result.objective == pytest.approx(2 - 2 * math.log(2), abs=1e-5)
    assert result.assignments[("x", ())] == pytest.approx(math.log(2), abs=1e-4)


def test_the_budget_split_between_log_and_sqrt():
    s = math.sqrt(12) - 1
    result = _ipopt(_ir(plus(fn("log", plus({"const": 1}, X)), fn("sqrt", {"var": "y", "index": []})), "maximize",
                        x=(0, 10), constraints=[BUDGET]))
    assert result.status == "optimal"
    assert result.objective == pytest.approx(math.log(11 - s * s) + s, abs=1e-4)


def test_its_optimum_is_local_and_it_is_never_chosen_over_a_global_solver():
    assert optimality_of(IPOPT, "optimal") == "local"
    ir = _ir(fn("sin", X), "maximize", x=(0, 10))
    backend, _ = choose(classify(ir, NO_DATA))
    assert backend.name == "scip"


def test_a_nonconvex_model_gets_the_peak_nearest_where_it_starts():
    # sin on [0, 10], started at 5: the peak at 5 pi / 2 is the nearby one -- a local optimum, worth 1.
    result = _ipopt(_ir(fn("sin", X), "maximize", x=(0, 10)))
    assert result.status == "optimal" and result.objective == pytest.approx(1.0, abs=1e-6)
    assert result.assignments[("x", ())] == pytest.approx(5 * math.pi / 2, abs=1e-3)


def test_whole_numbers_are_refused_by_name():
    compiled = compile_model(_ir(fn("exp", X), domain="integer"), NO_DATA)
    with pytest.raises(NotContinuous, match="ipopt solves continuous models"):
        solve_compiled(by_name("ipopt"), compiled, time_limit=5, seed=1)


def test_its_finding_of_no_answer_is_never_a_proof_of_none():
    impossible = {"id": "c", "left": X, "relation": ">=", "right": {"const": 20}, "severity": "hard"}
    result = _ipopt(_ir(fn("exp", X), constraints=[impossible]))
    assert result.status == "unknown" and result.objective is None and not result.assignments


def test_a_run_that_asks_for_ipopt_is_recorded_local(db, empty_queue):  # noqa: F811
    ir = _ir(plus(fn("exp", X), times(-2, X)))
    problem = make_problem(db, make_domain(db, "ipopt"))
    version = make_model_version(db, problem, ir)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=10.0, reuse=False, solver="ipopt")
    claim_next(db)
    outcome = execute_run(db, run_id)
    row = db.execute(text("SELECT status, optimality, solver FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
    assert outcome.status == "optimal" and row["optimality"] == "local" and row["solver"].startswith("ipopt")


# -- after SCIP (setting `solve.local_fallback`) -------------------------------------------------------


def _fallback(ir, result):
    from app.solve.backends import SCIP
    from app.solve.service import _local_fallback

    compiled = compile_model(ir, NO_DATA)
    return _local_fallback(compiled, classify(ir, NO_DATA), SCIP, result, time_limit=8, seed=1, workers=2,
                           should_stop=lambda: False)


def _S(status, objective=None, assignments=None, bound=None):
    from app.solve.result import Solution

    return Solution(status=status, optimal=False, objective=objective, assignments=assignments or {},
                    wall_seconds=1.0, solver="scip", best_bound=bound)


def test_with_nothing_from_scip_ipopts_answer_is_the_runs_and_claims_local():
    ir = _ir(plus(fn("exp", X), times(-2, X)))
    result, backend, record = _fallback(ir, _S("unknown"))
    assert backend is IPOPT and optimality_of(backend, result.status) == "local"
    assert result.objective == pytest.approx(2 - 2 * math.log(2), abs=1e-5)
    assert record["kept"] and record["from"] == "the middle of each range"


def test_scips_answer_is_polished_under_its_own_bound_and_proven_only_when_they_meet():
    ir = _ir(plus(fn("exp", X), times(-2, X)))
    best = 2 - 2 * math.log(2)
    rough = _S("feasible", 1.0, {("x", ()): 0.0, ("__fn", ("0",)): 1.0}, bound=best - 0.1)
    result, backend, record = _fallback(ir, rough)
    assert backend.name == "scip" and record["kept"] and record["from"] == "scip's answer"
    assert result.objective == pytest.approx(best, abs=1e-5)
    assert result.status == "feasible" and result.best_bound == best - 0.1  # SCIP's bound stands; no proof yet
    closed = _S("feasible", 1.0, {("x", ()): 0.0, ("__fn", ("0",)): 1.0}, bound=best)
    result, _, _ = _fallback(ir, closed)
    assert result.status == "optimal"  # the global bound says so, not IPOPT


def test_an_integer_model_is_left_to_scip():
    ir = _ir(fn("exp", X), domain="integer")
    result, backend, record = _fallback(ir, _S("unknown"))
    assert backend.name == "scip" and record["used"] is False and result.status == "unknown"
