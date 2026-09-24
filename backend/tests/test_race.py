"""The probe race (app.solve.race): who wins and why, then through a run."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.solve import race
from app.solve.race import probe_seconds, run_race, should_race
from app.solve.result import Solution
from app.solve.service import claim_next, enqueue_run, execute_run
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401


def S(status, objective=None, bound=None, seconds=1.0):
    return Solution(status=status, optimal=status == "optimal", objective=objective, assignments={},
                    wall_seconds=seconds, solver="x", best_bound=bound)


def _race(results: dict, sense="minimize", workers=8):
    calls = []

    def run_one(name, seconds, share, should_stop):
        calls.append((name, seconds, share))
        return results[name]

    return run_race(list(results), run_one, workers=workers, time_limit=30, sense=sense, rule="cp-sat"), calls


def test_the_probe_is_a_tenth_between_one_and_five_seconds():
    assert (probe_seconds(5), probe_seconds(30), probe_seconds(300)) == (1.0, 3.0, 5.0)


def test_a_proof_wins_and_is_the_answer():
    raced, calls = _race({"cp-sat": S("feasible", 10, 8), "highs": S("optimal", 9, 9, seconds=0.4)})
    assert raced.winner == "highs" and raced.answer is not None
    assert raced.evidence == "probe race (3 s each): highs proved it in 0.4 s; cp-sat gap 20%"
    # At once, the threads shared out.
    assert sorted(calls) == [("cp-sat", 3.0, 4), ("highs", 3.0, 4)]


def test_the_first_proof_stops_the_other_probes():
    import time as clock

    seen: dict[str, bool] = {}

    def run_one(name, seconds, share, should_stop):
        if name == "fast":
            return S("optimal", 5, 5, seconds=0.05)
        deadline = clock.monotonic() + 5
        while clock.monotonic() < deadline and not should_stop():
            clock.sleep(0.01)
        seen[name] = should_stop()
        return S("unknown", seconds=0.1)

    started = clock.monotonic()
    raced = run_race(["slow", "fast"], run_one, workers=4, time_limit=30, sense="minimize", rule="slow")
    assert raced.winner == "fast" and raced.answer is not None
    assert seen == {"slow": True} and clock.monotonic() - started < 2


def test_without_a_proof_the_smallest_gap_goes_on():
    raced, _ = _race({"cp-sat": S("feasible", 10, 8), "highs": S("feasible", 10, 9.5), "scip": S("unknown")})
    assert raced.winner == "highs" and raced.answer is None
    assert raced.evidence.endswith("-- highs continues") and "scip found no answer" in raced.evidence


def test_a_better_answer_breaks_a_tie_the_way_the_goal_points():
    raced, _ = _race({"a": S("feasible", 10, None), "b": S("feasible", 12, None)}, sense="maximize")
    assert raced.winner == "b"


def test_no_answer_anywhere_leaves_the_rules_choice():
    raced, _ = _race({"cp-sat": S("unknown"), "highs": S("unknown")})
    assert raced.winner == "cp-sat" and raced.answer is None and "no probe found an answer" in raced.evidence


@pytest.mark.parametrize(
    "fingerprint, candidates, limit, why",
    [
        ({"variables": 5000, "rows": 900}, ["cp-sat"], 30, "only one solver takes this model"),
        ({"variables": 5000, "rows": 900}, ["cp-sat", "highs"], 2, "the time allowed is too short to share with probes"),
        ({"variables": 20, "rows": 10}, ["cp-sat", "highs"], 30, "the model is small enough for the rules' choice to settle it at once"),
        ({"variables": 5000, "rows": 900}, ["cp-sat", "highs"], 30, None),
    ],
)
def test_when_a_race_is_skipped(fingerprint, candidates, limit, why):
    assert should_race(fingerprint, candidates, limit) == why


# -- through a run -------------------------------------------------------------------------------

IR = {
    "version": 2, "sets": [], "parameters": {},
    "variables": {"x": {"index": [], "domain": "integer", "lower": 0, "upper": 9}},
    "constraints": [{"id": "c", "left": {"var": "x", "index": []}, "relation": "<=", "right": {"const": 7}, "severity": "hard"}],
    "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": []}}]},
}


def test_a_run_races_records_the_probes_and_keeps_a_proof(db, empty_queue, monkeypatch):  # noqa: F811
    monkeypatch.setattr(race, "FLOOR_DECISIONS", 0)
    monkeypatch.setattr(race, "FLOOR_ROWS", 0)
    problem = make_problem(db, make_domain(db, "race"))
    version = make_model_version(db, problem, IR)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.probe', CAST('true' AS jsonb)),"
                    " ('problem', :p, 'solve.memory', CAST('false' AS jsonb))"), {"p": problem})
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    assert claim_next(db) == run_id
    outcome = execute_run(db, run_id)
    row = db.execute(text("SELECT solver, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
    assert outcome.status == "optimal" and outcome.objective == 7
    probes = row["params"]["probes"]
    assert {p["solver"] for p in probes} >= {"cp-sat", "highs"}
    assert row["params"]["why_solver"].startswith("probe race (1 s each): ")
    assert row["solver"] in {p["solver"] for p in probes if p["status"] == "optimal"}


def test_a_small_model_says_why_it_did_not_race(db, empty_queue):  # noqa: F811
    problem = make_problem(db, make_domain(db, "race-small"))
    version = make_model_version(db, problem, IR)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.probe', CAST('true' AS jsonb))"),
               {"p": problem})
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    claim_next(db)
    execute_run(db, run_id)
    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    assert params["probe_skipped"] == "the model is small enough for the rules' choice to settle it at once"
    assert "probes" not in params
