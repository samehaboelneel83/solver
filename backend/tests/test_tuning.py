"""A tuning search's options, per domain or problem (queue R10): whitelisted only, applied, recorded."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.seed import seed_workforce_demo
from app.solve import params
from app.solve.service import claim_next, enqueue_run, execute_run
from bench.tune import combinations
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_the_setting_reads_options_per_backend_each_whitelisted():
    assert params.parse_setting("cp-sat.symmetry_level=0, cp-sat.linearization_level=0, highs.presolve=off") == {
        "cp-sat": {"symmetry_level": 0, "linearization_level": 0}, "highs": {"presolve": "off"}}
    assert params.parse_setting("") == {} and params.parse_setting(None) == {}


@pytest.mark.parametrize("text, why", [
    ("cp-sat.symmetry_level=7", "not a whitelisted value"),
    ("cp-sat.threads=4", "not a whitelisted value"),
    ("gurobi.presolve=1", "has no whitelisted options"),
    ("symmetry_level", "is not backend.option=value"),
])
def test_anything_off_the_whitelist_is_refused_by_name(text, why):
    with pytest.raises(ValueError, match=why):
        params.parse_setting(text)


def test_the_search_tries_every_whitelisted_combination_defaults_first():
    found = combinations("cp-sat")
    assert len(found) == 9 and found[0] == {"linearization_level": 1, "symmetry_level": 2}
    assert len(combinations("highs")) == 6 and len(combinations("glop")) == 1


def test_a_run_applies_the_tuned_options_and_records_them(db, empty_queue):  # noqa: F811
    seeded = seed_workforce_demo(db)
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES"
                    " ('problem', :p, 'solve.solver_params', to_jsonb('cp-sat.symmetry_level=0, cp-sat.linearization_level=0'::text)),"
                    " ('problem', :p, 'solve.tuned_from', to_jsonb('2026-09-25 bench/results/2026-09-25-tuning.md'::text)),"
                    " ('problem', :p, 'solve.memory', CAST('false' AS jsonb))"), {"p": seeded["problem_id"]})
    db.commit()
    try:
        run_id = enqueue_run(db, seeded["scenario_id"], time_limit=10.0, reuse=False, solver="cp-sat")
        claim_next(db)
        outcome = execute_run(db, run_id)
        run_params = db.execute(text("SELECT params FROM run WHERE id = :r"), {"r": run_id}).scalar_one()
        assert outcome.status in ("optimal", "feasible")
        assert run_params["solver_params"] == {"symmetry_level": 0, "linearization_level": 0}
        assert run_params["tuned_from"].startswith("2026-09-25")
    finally:
        db.execute(text("DELETE FROM setting WHERE key IN ('solve.solver_params', 'solve.tuned_from', 'solve.memory')"
                        " AND scope = 'problem' AND scope_id = :p"), {"p": seeded["problem_id"]})
        db.commit()


def test_a_setting_off_the_whitelist_refuses_the_run_before_it_is_queued(db, empty_queue):  # noqa: F811
    seeded = seed_workforce_demo(db)
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES"
                    " ('problem', :p, 'solve.solver_params', to_jsonb('cp-sat.threads=64'::text))"), {"p": seeded["problem_id"]})
    db.commit()
    try:
        with pytest.raises(ValueError, match="solve.solver_params cannot be used"):
            enqueue_run(db, seeded["scenario_id"], time_limit=10.0, reuse=False)
    finally:
        db.rollback()
        db.execute(text("DELETE FROM setting WHERE key = 'solve.solver_params' AND scope = 'problem' AND scope_id = :p"),
                   {"p": seeded["problem_id"]})
        db.commit()


def test_the_api_answers_an_unusable_setting_with_a_422_that_names_it(db, empty_queue):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import app

    seeded = seed_workforce_demo(db)
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES"
                    " ('problem', :p, 'solve.solver_params', to_jsonb('cp-sat.threads=64'::text))"), {"p": seeded["problem_id"]})
    db.commit()
    try:
        settings = get_settings()
        client = TestClient(app)
        token = client.post("/api/auth/login", data={"username": settings.admin_username,
                                                     "password": settings.admin_password}).json()["access_token"]
        answer = client.post(f"/api/v1/scenarios/{seeded['scenario_id']}/runs", json={"time_limit_s": 5},
                             headers={"Authorization": f"Bearer {token}"})
        assert answer.status_code == 422, answer.text
        assert answer.json()["detail"][0]["loc"] == ["settings", "solve.solver_params"]
    finally:
        db.execute(text("DELETE FROM setting WHERE key = 'solve.solver_params' AND scope = 'problem' AND scope_id = :p"),
                   {"p": seeded["problem_id"]})
        db.commit()
