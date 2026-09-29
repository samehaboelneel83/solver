"""Epic engine, E-4: the learned selector allowed to act (setting `solve.selector_acts`).

The selector's vote is replaced here by a fixed one, so the test is about the
policy -- when a pick acts, what it may pick, and what the run records -- not
about the stored evidence.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.solve import selector
from app.solve.service import claim_next, enqueue_run, execute_run
from tests.test_alternatives import _knapsack
from tests.test_functions import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401


@pytest.fixture
def scenario(db):  # noqa: F811
    domain = make_domain(db, "selector-acts")
    problem = make_problem(db, domain)
    version = make_model_version(db, problem, _knapsack())
    scenario_id = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 's') RETURNING id"),
                             {"p": problem, "v": version}).scalar_one()
    db.commit()
    yield problem, scenario_id
    db.execute(text("DELETE FROM run"))
    db.execute(text("DELETE FROM setting WHERE scope = 'problem' AND scope_id = :p"), {"p": problem})
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
    db.commit()


def _vote(confidence: float, seen: list):
    def predict(fingerprint, admissible, **_):
        seen.append(list(admissible))
        # Anything the rules admit other than their own first choice for a yes-or-no model.
        pick = "scip" if "scip" in admissible else [a for a in admissible if a != "cp-sat"][0]
        return {"pick": pick, "confidence": confidence, "confident": confidence >= selector.CONFIDENT,
                "like": ["rota", "knapsack"]}

    return predict


def _run(db, scenario_id, acts: bool | None, problem):  # noqa: F811
    if acts is not None:
        db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.selector_acts',"
                        " CAST(:v AS jsonb))"), {"p": problem, "v": "true" if acts else "false"})
        db.commit()
    run_id = enqueue_run(db, scenario_id, time_limit=10.0, reuse=False)
    claim_next(db)
    outcome = execute_run(db, run_id)
    return outcome, db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()


def test_a_confident_pick_solves_the_run_when_allowed_and_says_so(db, empty_queue, scenario, monkeypatch):  # noqa: F811
    problem, scenario_id = scenario
    seen: list = []
    monkeypatch.setattr(selector, "predict", _vote(1.0, seen))
    outcome, params = _run(db, scenario_id, True, problem)
    assert outcome.status == "optimal"
    record = params["selector"]
    assert params["chosen_solver"] == record["pick"] != record["rules_chose"]
    assert record["acted"] is True and record["agree"] is True
    assert params["why_solver"].startswith(f"the learned selector picked {record['pick']}: 100% of the")
    assert f"the rules would have chosen {record['rules_chose']}" in params["why_solver"]
    assert params["selector_acts"] is True
    # Only ever among what the rules admit.
    assert record["pick"] in seen[0]


def test_a_pick_short_of_confident_is_only_recorded(db, empty_queue, scenario, monkeypatch):  # noqa: F811
    problem, scenario_id = scenario
    monkeypatch.setattr(selector, "predict", _vote(0.6, []))
    _, params = _run(db, scenario_id, True, problem)
    assert params["selector"]["acted"] is False
    assert params["chosen_solver"] == "cp-sat" != params["selector"]["pick"]


def test_by_default_it_acts_on_nothing(db, empty_queue, scenario, monkeypatch):  # noqa: F811
    problem, scenario_id = scenario
    monkeypatch.setattr(selector, "predict", _vote(1.0, []))
    _, params = _run(db, scenario_id, None, problem)
    assert params["selector_acts"] is False
    assert params["selector"]["acted"] is False and params["chosen_solver"] == "cp-sat"


def test_an_explicit_choice_outranks_it(db, empty_queue, scenario, monkeypatch):  # noqa: F811
    problem, scenario_id = scenario
    monkeypatch.setattr(selector, "predict", _vote(1.0, []))
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.selector_acts',"
                    " CAST('true' AS jsonb))"), {"p": problem})
    db.commit()
    run_id = enqueue_run(db, scenario_id, time_limit=10.0, reuse=False, solver="highs")
    claim_next(db)
    execute_run(db, run_id)
    params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
    assert params["chosen_solver"] == "highs" and params["selector"]["acted"] is False
