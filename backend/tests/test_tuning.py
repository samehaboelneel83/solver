"""A solver's options tuned per problem by Bayesian optimisation over its own runs."""
from __future__ import annotations

from app.solve.tuning import BUDGET, RECHECK, WARMUP, default, space, tune


def run(options, seconds, trial=False, status="optimal"):
    return {"options": options, "trial": trial, "status": status, "seconds": seconds, "gap": None, "limit": 60.0}


def test_the_space_is_the_whitelist_and_the_default_is_what_the_gate_enabled():
    assert len(space("highs")) == 6 and len(space("scip")) == 9
    assert default("scip")["presolving"] == "fast"  # the benchmark's winner
    assert tune("pdlp", []) is None  # nothing whitelisted: nothing to tune


def test_defaults_first_then_a_trial_every_other_run():
    base = default("highs")
    assert not tune("highs", []).trial and tune("highs", []).options == base
    two = [run(base, 5.0)] * WARMUP
    first = tune("highs", two)
    assert first.trial and first.options != base and "Bayesian" in first.evidence
    after = tune("highs", [run(first.options, 9.0, trial=True), *two])
    assert not after.trial and after.options == base  # the trial was slower: the defaults stand


def test_a_faster_configuration_measured_twice_is_kept():
    base = default("highs")
    fast = {**base, "presolve": "off"}
    history = [run(fast, 1.0, trial=True), run(base, 5.0), run(fast, 1.2, trial=True), run(base, 5.0), run(base, 5.0)]
    chosen = tune("highs", history)
    assert not chosen.trial and chosen.options == fast and "best median" in chosen.evidence


def test_the_trial_goes_where_improvement_is_likeliest_and_stops_at_the_budget():
    base = default("scip")
    history = [run(base, 5.0)] * WARMUP
    tried = set()
    for _ in range(BUDGET):
        t = tune("scip", history)
        if t.trial:
            tried.add(tuple(sorted(t.options.items())))
            history = [run(t.options, 6.0, trial=True)] + history
        else:
            history = [run(t.options, 5.0)] + history
    assert len(tried) >= 4  # it explores, not the same one again and again
    spent = [run(base, 5.0, trial=True)] * BUDGET + [run(base, 5.0)] * (RECHECK - 1)
    assert not tune("scip", spent[::-1][: RECHECK - 1] + spent).trial


from tests.test_quadratic import empty_queue  # noqa: E402,F401
from tests.test_v1_problem_run import db  # noqa: E402,F401


def test_a_problem_s_runs_tune_its_solver(db, empty_queue):  # noqa: F811
    from sqlalchemy import text

    from app.solve.service import enqueue_run
    from app.worker import work_once
    from tests.test_benders import _facility
    from tests.test_v1_problem_run import make_domain, make_model_version, make_problem

    version = make_model_version(db, make_problem(db, make_domain(db, "tunes")), _facility(3, 8, 20))
    problem = db.execute(text("SELECT problem_id FROM model_version WHERE id = :v"), {"v": version}).scalar_one()
    scenario = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 'base') "
                               "RETURNING id"), {"p": problem, "v": version}).scalar_one()
    db.commit()
    records, objectives = [], set()
    for _ in range(WARMUP + 2):
        run_id = enqueue_run(db, scenario, time_limit=20.0, reuse=False)
        for _ in range(5):
            if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() != "queued":
                break
            work_once(db)
        row = db.execute(text("SELECT status, objective, params FROM run WHERE id = :r"), {"r": run_id}).mappings().one()
        assert row["status"] == "optimal"
        records.append(row["params"]["tuning"])
        objectives.add(round(float(row["objective"]), 4))
        assert row["params"]["solver_params"] == {**row["params"]["solver_params"], **records[-1]["options"]}
    assert [r["trial"] for r in records] == [False] * WARMUP + [True, False], records
    assert len(objectives) == 1  # options change how fast, never the answer
