"""The probe race (app.solve.race): who wins and why, then through a run."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.solve import race
from app.solve.race import probe_seconds, run_portfolio, run_race, should_portfolio, should_race
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


# -- the portfolio (queue R2) ---------------------------------------------------------------------


def _portfolio(results: dict, sense="minimize", workers=8, rule="cp-sat"):
    calls = []

    def run_one(name, seconds, share, should_stop):
        calls.append((name, seconds, share))
        return results[name]

    return run_portfolio(list(results), run_one, workers=workers, time_limit=30, sense=sense, rule=rule), calls


def test_the_portfolio_runs_every_solver_for_the_whole_time_on_a_share_of_the_threads():
    raced, calls = _portfolio({"cp-sat": S("feasible", 10, 8), "highs": S("optimal", 9, 9, seconds=4.0)})
    assert sorted(calls) == [("cp-sat", 30, 4), ("highs", 30, 4)]
    assert raced.winner == "highs" and raced.answer.status == "optimal" and raced.probe_s == 30
    assert raced.evidence == "portfolio (2 solvers at once, up to 30 s): highs proved it in 4 s; cp-sat gap 20%"


def test_without_a_proof_the_best_answer_at_the_deadline_is_the_answer_not_solved_again():
    raced, _ = _portfolio({"cp-sat": S("feasible", 10, 8), "highs": S("feasible", 10, 9.5), "scip": S("unknown")})
    assert raced.winner == "highs" and raced.answer.objective == 10 and raced.answer.status == "feasible"


def test_a_proof_that_there_is_no_answer_settles_it():
    raced, _ = _portfolio({"cp-sat": S("unknown"), "highs": S("infeasible", seconds=0.2)})
    assert raced.winner == "highs" and raced.answer.status == "infeasible"
    assert "highs proved it infeasible in 0.2 s" in raced.evidence


def test_no_answer_anywhere_keeps_the_rules_choice_and_its_verdict():
    raced, _ = _portfolio({"highs": S("unknown"), "cp-sat": S("unknown")})
    assert raced.winner == "cp-sat" and raced.answer.status == "unknown"
    assert raced.evidence.endswith("no solver found an answer; cp-sat, the rules' choice, stands")


def test_an_infeasibility_proof_stops_the_others():
    import time as clock

    seen: dict[str, bool] = {}

    def run_one(name, seconds, share, should_stop):
        if name == "fast":
            return S("infeasible", seconds=0.05)
        deadline = clock.monotonic() + 5
        while clock.monotonic() < deadline and not should_stop():
            clock.sleep(0.01)
        seen[name] = should_stop()
        return S("unknown", seconds=0.1)

    started = clock.monotonic()
    raced = run_portfolio(["slow", "fast"], run_one, workers=4, time_limit=30, sense="minimize", rule="slow")
    assert raced.winner == "fast" and seen == {"slow": True} and clock.monotonic() - started < 2


@pytest.mark.parametrize(
    "model_class, fingerprint, candidates, why",
    [
        ("LP", {"variables": 5000, "rows": 900}, ["glop", "highs"], "a portfolio races integer models only"),
        ("IP", {"variables": 5000, "rows": 900}, ["cp-sat"], "only one solver that proves its answer takes this model"),
        ("MILP", {"variables": 20, "rows": 10}, ["highs", "scip"], "the model is small enough for the rules' choice to settle it at once"),
        ("MILP", {"variables": 5000, "rows": 900}, ["highs", "scip"], None),
    ],
)
def test_when_a_portfolio_is_skipped(model_class, fingerprint, candidates, why):
    assert should_portfolio(model_class, fingerprint, candidates) == why


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


def test_a_run_by_portfolio_keeps_the_winners_answer_and_records_every_entrant(db, empty_queue, monkeypatch):  # noqa: F811
    monkeypatch.setattr(race, "FLOOR_DECISIONS", 0)
    monkeypatch.setattr(race, "FLOOR_ROWS", 0)
    problem = make_problem(db, make_domain(db, "portfolio"))
    version = make_model_version(db, problem, IR)
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                          {"p": problem, "v": version}).scalar_one()
    # Both on: the portfolio takes the probe race's place.
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.portfolio', CAST('true' AS jsonb)),"
                    " ('problem', :p, 'solve.probe', CAST('true' AS jsonb)), ('problem', :p, 'solve.memory', CAST('false' AS jsonb))"),
               {"p": problem})
    db.commit()
    run_id = enqueue_run(db, scenario, time_limit=10.0, reuse=False)
    assert claim_next(db) == run_id
    outcome = execute_run(db, run_id)
    row = db.execute(text("SELECT solver, optimality, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
    assert outcome.status == "optimal" and outcome.objective == 7 and row["optimality"] == "global"
    entrants = row["params"]["portfolio"]
    assert {e["solver"] for e in entrants} >= {"cp-sat", "highs"}
    assert row["params"]["why_solver"].startswith("portfolio (")
    assert "probes" not in row["params"]
    assert row["params"]["chosen_solver"] in {e["solver"] for e in entrants if e["status"] == "optimal"}
