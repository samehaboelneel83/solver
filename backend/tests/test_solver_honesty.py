"""Phase 6.2: what a run may claim, and what it must carry to be reproduced.

- D2: a solver stopped by a limit before it found anything has no answer.
  HiGHS used to call that `feasible` and hand back whatever its column
  values held -- invented numbers, or an infinite objective that crashed.
- D5 / D9: a goal that improves without limit is `unbounded`, with the
  variables named, never an `optimal` answer resting on a ceiling nobody set.
- D3: the run's seed reaches the solver.
- D6: every answer carries the solver's best bound and the gap to it.
- D8: a continuous lexicographic stage is held at its best with a tolerance,
  not with an exact `=` that float noise can break.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.solve import cpsat, highs
from app.solve.compile import Compiled, Constraint, Linear, Variable
from app.solve.result import Solution
from app.solve.service import _solve_lex, enqueue_run, gap_of
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401


def _run(db, ir: dict, name: str, seed: int = 1) -> dict:
    version = make_model_version(db, make_problem(db, make_domain(db, name)), ir)
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    scenario = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 'base') RETURNING id"),
        {"p": problem, "v": version},
    ).scalar_one()
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=20.0, seed=seed)
    work_once(db)
    row = db.execute(
        text(
            "SELECT id, status, solver, objective, error, best_bound, gap, optimality,"
            "       (SELECT count(*) FROM solution s WHERE s.run_id = run.id) AS solutions"
            "  FROM run WHERE id = :r"
        ),
        {"r": run_id},
    ).mappings().one()
    return dict(row)


def _scalar(domain: str, sense: str, expression: dict, rules: list, **bounds) -> dict:
    return {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {"x": {"index": [], "domain": domain, **bounds}},
        "constraints": rules,
        "objective": {"sense": sense, "terms": [{"id": "o", "weight": 1, "expression": expression}]},
    }


X = {"var": "x", "index": []}


# -- D2 ------------------------------------------------------------------------------


def _parity(n: int = 60) -> Compiled:
    """60 yes/no choices whose count, doubled, must be odd: no answer exists,
    and no solver finds that out within a nanosecond."""
    random.seed(3)
    keys = [("x", (str(i),)) for i in range(n)]
    weights = [random.randint(10, 99) for _ in keys]
    values = [random.randint(10, 99) for _ in keys]
    return Compiled(
        variables={k: Variable(k, "binary", Decimal(0), Decimal(1)) for k in keys},
        constraints=[
            # A capacity row beside the parity row: alone, parity is proven
            # infeasible by presolve before the clock is ever read.
            Constraint(
                "cap",
                {},
                Linear({k: Decimal(w) for k, w in zip(keys, weights)}),
                "<=",
                Linear(const=Decimal(sum(weights) // 3)),
            ),
            Constraint("parity", {}, Linear({k: Decimal(2) for k in keys}), "=", Linear(const=Decimal(n - 1))),
        ],
        objective=Linear({k: Decimal(v) for k, v in zip(keys, values)}),
        sense="maximize",
        var_index_sets={"x": []},
    )


@pytest.mark.skipif(not highs.available(), reason="highs is not installed")
def test_highs_stopped_before_any_answer_returns_no_values():
    result = highs.solve(_parity(), time_limit=1e-9, workers=1)

    assert result.status == "unknown"
    assert result.objective is None
    assert result.assignments == {}


# -- D5 / D9 -------------------------------------------------------------------------


def test_a_goal_that_grows_forever_is_an_unbounded_run_naming_the_variable(db):
    ir = _scalar("continuous", "maximize", X, [{"id": "lo", "left": X, "relation": ">=", "right": {"const": 1}, "severity": "hard"}])

    row = _run(db, ir, "honesty-unbounded")

    assert row["status"] == "unbounded"
    assert row["objective"] is None
    assert row["solutions"] == 0
    assert row["optimality"] is None and row["best_bound"] is None
    assert "x rose to 1,000,000" in row["error"]
    assert "upper bound" in row["error"]


def test_a_decision_its_rules_hold_above_the_guard_is_solved_not_called_unbounded(db):
    """Benchmark round 5: water[P039] needed 1,041,500 m3, a rule said so, and the run was called
    unbounded because the guard ceiling (1,000,000) held it back first."""
    ir = _scalar("continuous", "maximize", X,
                 [{"id": "capacity", "left": X, "relation": "<=", "right": {"const": 1_041_500}, "severity": "hard"}])

    row = _run(db, ir, "honesty-above-guard")

    assert row["status"] == "optimal", row
    assert float(row["objective"]) == pytest.approx(1_041_500)
    assert not row["error"]


def test_an_explicit_upper_bound_is_not_a_ceiling_nobody_set(db):
    ir = _scalar("continuous", "maximize", X, [], upper=1_000_000)

    row = _run(db, ir, "honesty-explicit")

    assert row["status"] == "optimal"
    assert row["objective"] == Decimal("1000000")
    assert row["error"] is None


# -- D3 ------------------------------------------------------------------------------


def test_the_run_seed_reaches_the_solver(db, monkeypatch):
    seen: list = []
    real = cpsat.solve

    def spy(compiled, **kwargs):
        seen.append(kwargs.get("seed"))
        return real(compiled, **kwargs)

    # A fake solver lives in this process; the sandbox's child would not
    # see it (app.solve.sandbox). What is tested here is the run's wiring.
    monkeypatch.setenv("SOLVE_SANDBOX", "0")
    monkeypatch.setattr(cpsat, "solve", spy)
    ir = _scalar("binary", "maximize", X, [])

    row = _run(db, ir, "honesty-seed", seed=7)

    assert row["solver"] == "cp-sat"
    assert seen == [7]


def test_the_same_seed_gives_the_same_answer():
    first = cpsat.solve(_knapsack(), time_limit=10, workers=1, seed=5)
    second = cpsat.solve(_knapsack(), time_limit=10, workers=1, seed=5)
    assert first.assignments == second.assignments


def _knapsack() -> Compiled:
    random.seed(11)
    keys = [("x", (str(i),)) for i in range(30)]
    weights = {k: Decimal(random.randint(1, 20)) for k in keys}
    return Compiled(
        variables={k: Variable(k, "binary", Decimal(0), Decimal(1)) for k in keys},
        constraints=[Constraint("cap", {}, Linear(weights), "<=", Linear(const=Decimal(60)))],
        objective=Linear({k: Decimal(random.randint(1, 20)) for k in keys}),
        sense="maximize",
        var_index_sets={"x": []},
    )


# -- D6 ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "objective, bound, gap",
    [(10, 12, 0.2), (-10, -12, 0.2), (0, 0, 0.0), (21, 21.0000000001, 0.0), (None, 5, None), (5, None, None)],
)
def test_the_gap(objective, bound, gap):
    assert gap_of(objective, bound) == pytest.approx(gap) if gap is not None else gap_of(objective, bound) is None


def test_a_proven_optimum_records_its_bound_and_a_zero_gap(db):
    ir = _scalar("integer", "maximize", X, [{"id": "hi", "left": X, "relation": "<=", "right": {"const": 7}, "severity": "hard"}], upper=10)

    row = _run(db, ir, "honesty-gap")

    assert row["status"] == "optimal"
    assert row["best_bound"] == pytest.approx(7)
    assert row["gap"] == 0


# -- D8 ------------------------------------------------------------------------------


class _Recorder:
    """A backend that records each stage and answers x = 1/3."""

    def __init__(self):
        self.stages: list[Compiled] = []

    def solve(self, compiled, **_):
        self.stages.append(compiled)
        return Solution("optimal", True, 0, {("x", ()): Decimal(1) / Decimal(3)}, 0.0, "recorder")


@pytest.mark.parametrize("sense, relation", [("minimize", "<="), ("maximize", ">=")])
def test_a_continuous_lex_stage_is_held_with_a_tolerance(sense, relation):
    key = ("x", ())
    compiled = Compiled(
        variables={key: Variable(key, "continuous", Decimal(0), Decimal(1))},
        constraints=[],
        objective=Linear(),
        sense=sense,
        var_index_sets={"x": []},
        objective_mode="lex",
        objective_term_ids=["a", "b"],
        objective_terms=[Linear({key: Decimal(1)}), Linear({key: Decimal(2)})],
    )
    recorder = _Recorder()

    _solve_lex(recorder, compiled, time_limit=5, workers=1)

    (freeze,) = recorder.stages[1].constraints
    assert freeze.relation == relation
    third = Decimal(1) / Decimal(3)
    assert abs(freeze.right.const - third) <= max(Decimal("1e-6") * third, Decimal("1e-9"))
    assert freeze.right.const != third


def test_an_integral_lex_stage_is_still_held_exactly():
    key = ("x", ())
    compiled = Compiled(
        variables={key: Variable(key, "integer", Decimal(0), Decimal(5))},
        constraints=[],
        objective=Linear(),
        sense="maximize",
        var_index_sets={"x": []},
        objective_mode="lex",
        objective_term_ids=["a", "b"],
        objective_terms=[Linear({key: Decimal(1)}), Linear({key: Decimal(2)})],
    )

    class Whole(_Recorder):
        def solve(self, compiled, **_):
            self.stages.append(compiled)
            return Solution("optimal", True, 3, {key: 3}, 0.0, "recorder")

    recorder = Whole()
    _solve_lex(recorder, compiled, time_limit=5, workers=1)

    (freeze,) = recorder.stages[1].constraints
    assert freeze.relation == "="
    assert freeze.right.const == 3


# -- gap and threads as settings (migration 0030) ---------------------------------


def test_the_run_passes_its_threads_and_gap_to_the_solver(db, monkeypatch):
    seen: list = []
    real = cpsat.solve

    def spy(compiled, **kwargs):
        seen.append((kwargs.get("workers"), kwargs.get("gap_rel")))
        return real(compiled, **kwargs)

    # A fake solver lives in this process; the sandbox's child would not
    # see it (app.solve.sandbox). What is tested here is the run's wiring.
    monkeypatch.setenv("SOLVE_SANDBOX", "0")
    monkeypatch.setattr(cpsat, "solve", spy)
    db.execute(
        text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('platform', NULL, 'solve.workers', '2')")
    )
    db.commit()
    try:
        _run(db, _scalar("binary", "maximize", X, []), "honesty-knobs")
    finally:
        db.execute(text("DELETE FROM setting WHERE scope = 'platform' AND key = 'solve.workers'"))
        db.commit()

    assert seen == [(2, 0.0)]


class _Loose:
    """A backend that says `optimal` with a bound 10% away, as a solver
    stopped at its own default tolerance would."""

    name = "loose"

    def solve(self, compiled, **_):
        return Solution("optimal", True, 100, {("x", ()): 1}, 0.0, "loose", best_bound=110.0)


def test_optimal_with_an_open_gap_is_recorded_as_feasible():
    from app.solve.service import solve_compiled

    key = ("x", ())
    compiled = Compiled(
        variables={key: Variable(key, "integer", Decimal(0), Decimal(5))},
        constraints=[],
        objective=Linear({key: Decimal(100)}),
        sense="maximize",
        var_index_sets={"x": []},
    )

    result, _ = solve_compiled(_Loose(), compiled, time_limit=5)

    assert result.status == "feasible"
    assert result.optimal is False
    assert gap_of(result.objective, result.best_bound) == pytest.approx(0.1)


# -- D4: a stopped run keeps the answer it had --------------------------------------


def _hard_knapsack(n: int = 200, m: int = 10) -> Compiled:
    """Ten capacity rows over 200 yes/no items: HiGHS finds good answers in
    well under a second and cannot prove the best one for many seconds."""
    rnd = random.Random(4)
    keys = [("x", (str(i),)) for i in range(n)]
    rows = []
    for j in range(m):
        weights = {k: Decimal(rnd.randint(1, 1000)) for k in keys}
        rows.append(Constraint(f"c{j}", {}, Linear(weights), "<=", Linear(const=sum(weights.values()) // 4)))
    return Compiled(
        variables={k: Variable(k, "binary", Decimal(0), Decimal(1)) for k in keys},
        constraints=rows,
        objective=Linear({k: Decimal(rnd.randint(1, 1000)) for k in keys}),
        sense="maximize",
        var_index_sets={"x": []},
    )


@pytest.mark.skipif(not highs.available(), reason="highs is not installed")
def test_stopping_highs_keeps_the_best_answer_it_had():
    import time

    started = time.monotonic()
    result = highs.solve(
        _hard_knapsack(), time_limit=60, workers=1, should_stop=lambda: time.monotonic() - started > 1.5
    )

    assert time.monotonic() - started < 10
    assert result.status == "feasible"
    assert len(result.assignments) == 200
    assert result.objective is not None and result.best_bound is not None
    assert result.best_bound >= result.objective


def _stop_during_solve(monkeypatch, answer: Solution | None):
    """Make CP-SAT's solve mark the run as asked to stop, then return
    `answer` -- or the real result when None."""
    from app.core.db import SessionLocal

    real = cpsat.solve

    def stopped(compiled, **kwargs):
        session = SessionLocal()
        session.execute(text("UPDATE run SET cancel_requested = true WHERE status = 'running'"))
        session.commit()
        session.close()
        return answer if answer is not None else real(compiled, **kwargs)

    # A fake solver lives in this process; the sandbox's child would not
    # see it (app.solve.sandbox). What is tested here is the run's wiring.
    monkeypatch.setenv("SOLVE_SANDBOX", "0")
    monkeypatch.setattr(cpsat, "solve", stopped)


def test_a_run_stopped_with_an_answer_keeps_it_and_says_it_was_stopped(db, monkeypatch):
    _stop_during_solve(monkeypatch, None)

    row = _run(db, _scalar("binary", "maximize", X, []), "honesty-stop-kept")
    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": row["id"]}).scalar_one()

    assert row["status"] == "optimal"
    assert row["objective"] == 1
    assert row["solutions"] == 1
    assert params["stopped_by_request"] is True


def test_a_run_stopped_with_nothing_in_hand_is_cancelled(db, monkeypatch):
    _stop_during_solve(monkeypatch, Solution("unknown", False, None, {}, 0.0, "cp-sat"))
    # No greedy start either (app.solve.greedy would have one in hand for this model).
    monkeypatch.setattr("app.solve.greedy.applies", lambda compiled: "off for this test")

    row = _run(db, _scalar("binary", "maximize", X, []), "honesty-stop-empty")

    assert row["status"] == "cancelled"
    assert row["solutions"] == 0


def test_a_run_stopped_with_only_its_greedy_start_keeps_the_start(db, monkeypatch):
    _stop_during_solve(monkeypatch, Solution("unknown", False, None, {}, 0.0, "cp-sat"))

    row = _run(db, _scalar("binary", "maximize", X, []), "honesty-stop-greedy")

    assert row["status"] == "feasible" and row["objective"] == 1


def test_a_gap_below_the_stored_six_places_is_rounding_even_for_a_small_goal():
    """Evaluation battery: a variance of 0.00146265 is stored as 0.001463; the proven QP was called feasible."""
    assert gap_of(0.001463, 0.0014626534700637153) == 0.0
    assert gap_of(0.0015, 0.0014626534700637153) > 0.02
