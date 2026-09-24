"""Per-problem memory (app.solve.memory): the recall rule, then through a run."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.solve.memory import MIN_RUNS, RECENT, recall
from app.solve.service import claim_next, enqueue_run, execute_run
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401


def test_the_fastest_median_among_admissible_solvers_wins():
    history = [("highs", 0.8), ("cp-sat", 2.0), ("highs", 1.2), ("cp-sat", 2.4), ("scip", 0.1), ("scip", 0.1)]
    got = recall(history, admissible={"highs", "cp-sat"})
    assert got.solver == "highs"
    assert got.evidence == ("remembered: highs proved 2 of this problem's recent runs in a median 1 s; "
                            "cp-sat 2 in 2.2 s")


def test_one_lucky_run_decides_nothing():
    assert MIN_RUNS == 2
    assert recall([("highs", 0.1), ("cp-sat", 3.0), ("cp-sat", 3.1)], {"highs", "cp-sat"}).solver == "cp-sat"
    assert recall([("highs", 0.1)], {"highs"}) is None


def test_only_the_recent_runs_count():
    old = [("cp-sat", 0.1)] * 10
    recent = [("highs", 1.0)] * RECENT
    assert recall(recent + old, {"highs", "cp-sat"}).solver == "highs"


@pytest.mark.parametrize("history", [[], [("glop", 1.0), ("glop", 1.0)]])
def test_nothing_to_remember(history):
    assert recall(history, {"cp-sat"}) is None


# -- through a run -------------------------------------------------------------------------------

IR = {
    "version": 2, "sets": [], "parameters": {},
    "variables": {"x": {"index": [], "domain": "integer", "lower": 0, "upper": 9}},
    "constraints": [{"id": "c", "left": {"var": "x", "index": []}, "relation": "<=", "right": {"const": 7}, "severity": "hard"}],
    "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": []}}]},
}


def _scenario(db) -> tuple[int, int]:
    problem = make_problem(db, make_domain(db, "memory"))
    version = make_model_version(db, problem, IR)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.memory', CAST('true' AS jsonb))"),
               {"p": problem})
    db.commit()
    return problem, scenario


def _solve(db, scenario, **kw) -> dict:
    run_id = enqueue_run(db, scenario, time_limit=10.0, reuse=False, **kw)
    assert claim_next(db) == run_id
    execute_run(db, run_id)
    return db.execute(text("SELECT solver, status, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()


def test_a_problem_remembers_the_solver_that_proved_it(db, empty_queue):  # noqa: F811
    _, scenario = _scenario(db)
    first = _solve(db, scenario)
    assert first["solver"] == "cp-sat" and "remembered" not in first["params"]["why_solver"]
    # Two proven runs on HiGHS, asked for by name, recorded as fast.
    for _ in range(2):
        _solve(db, scenario, solver="highs")
    db.execute(text("UPDATE run SET wall_time_s = CASE solver WHEN 'highs' THEN 0.01 ELSE 5 END WHERE status = 'optimal'"))
    db.commit()
    remembered = _solve(db, scenario)
    assert remembered["solver"] == "highs" and remembered["status"] == "optimal"
    assert remembered["params"]["why_solver"].startswith("remembered: highs proved 2")
    # A solver named on the run still wins.
    assert _solve(db, scenario, solver="cp-sat")["solver"] == "cp-sat"


def test_memory_is_off_unless_the_setting_says_so(db, empty_queue):  # noqa: F811
    problem, scenario = _scenario(db)
    db.execute(text("UPDATE setting SET value = CAST('false' AS jsonb) WHERE scope_id = :p AND key = 'solve.memory'"), {"p": problem})
    db.commit()
    for _ in range(2):
        _solve(db, scenario, solver="highs")
    db.execute(text("UPDATE run SET wall_time_s = 0.01 WHERE solver = 'highs'"))
    db.commit()
    assert _solve(db, scenario)["solver"] == "cp-sat"


# -- the bench replay's verdict --------------------------------------------------------------------


def _row(family, rule_s, memory_s, wrong=False):
    return {"family": family, "size": "S", "instance": f"{family}-S-0", "rule": "cp-sat", "memory": "highs",
            "rule_s": rule_s, "memory_s": memory_s, "wrong": wrong}


def test_the_replay_enables_memory_only_by_the_harness_s_rule():
    from bench.memory import report

    _, enable = report([_row("a", 1.0, 0.5), _row("b", 2.0, 1.0)])
    assert enable is True
    # One family faster is not enough.
    assert report([_row("a", 1.0, 0.5), _row("b", 1.0, 1.0)])[1] is False
    # An instance twice as slow vetoes it.
    assert report([_row("a", 1.0, 0.5), _row("b", 2.0, 1.0), _row("b", 0.2, 0.5)])[1] is False
    # So does a wrong answer.
    assert report([_row("a", 1.0, 0.5), _row("b", 2.0, 1.0, wrong=True)])[1] is False
