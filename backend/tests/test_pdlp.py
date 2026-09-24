"""PDLP for very large linear programs: optimal to a tolerance, never called proven (queue R1)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.solve import compile_model, lp
from app.solve import pdlp as pdlp_rules
from app.solve.backends import PDLP, choose, optimality_of
from app.solve.classify import classify
from app.worker import work_once
from bench.families import generate
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_tenancy import tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _feed_blend():
    instance = generate("feed_blend", "M", 0)
    return instance.ir, instance.data


def test_pdlp_reaches_the_simplex_optimum_to_its_tolerance_and_claims_no_bound():
    ir, data = _feed_blend()
    compiled = compile_model(ir, data)
    exact = lp.solve(compiled, time_limit=30)
    approximate = lp.solve(compiled, time_limit=30, engine=lp.PDLP)
    assert exact.status == approximate.status == "optimal"
    assert float(approximate.objective) == pytest.approx(float(exact.objective), rel=1e-4)
    assert exact.best_bound is not None and approximate.best_bound is None
    assert approximate.solver.startswith("pdlp (ortools") and "tolerance 1e-06" in approximate.solver


def test_pdlp_refuses_a_discrete_model_by_name():
    instance = generate("knapsack", "S", 0)
    with pytest.raises(lp.NotContinuous, match="pdlp solves linear programs"):
        lp.solve(compile_model(instance.ir, instance.data), time_limit=5, engine=lp.PDLP)


def test_an_ordinary_lp_goes_to_the_simplex_and_a_large_one_to_pdlp():
    ir, data = _feed_blend()
    compiled = compile_model(ir, data)
    found = classify(ir, data)
    assert choose(found)[0].name == "glop"
    # Past the threshold (here set below this model's size) it needs large-scale, which only PDLP provides.
    large = pdlp_rules.admit(found, compiled, threshold=pdlp_rules.nonzeros(compiled) - 1)
    assert pdlp_rules.LARGE_SCALE in large.needs
    backend, why = choose(large)
    assert backend is PDLP and "pdlp" in why
    assert optimality_of(PDLP, "optimal") == "approximate"
    # At or under the threshold nothing changes.
    assert pdlp_rules.admit(found, compiled, threshold=pdlp_rules.nonzeros(compiled)) is found


def test_only_a_linear_program_is_ever_large_scale():
    instance = generate("knapsack", "S", 0)
    compiled = compile_model(instance.ir, instance.data)
    found = classify(instance.ir, instance.data)
    assert pdlp_rules.admit(found, compiled, threshold=0) is found


def test_memory_and_the_race_compare_proofs_only():
    from app.solve.service import _admissible

    ir, data = _feed_blend()
    assert "pdlp" not in _admissible(classify(ir, data))
    large = pdlp_rules.admit(classify(ir, data), compile_model(ir, data), threshold=0)
    assert _admissible(large) == set()  # only PDLP could take it, and it proves nothing
    from app.solve.race import should_race

    assert should_race(None, [], 60) == "no solver that proves its answer takes this model"


def test_a_large_lp_run_is_recorded_approximate_with_its_tolerance(tenants, db, empty_queue, monkeypatch):  # noqa: F811
    """Through the worker: the feed-blend template (a linear program) with `solve.pdlp` on and the
    threshold at zero, so it counts as large -- the run says what its optimum is worth."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.showcase import FEED_BLEND, ensure_showcase_templates

    monkeypatch.setattr(pdlp_rules, "LARGE_SCALE_NNZ", 0)
    client = TestClient(app)
    template = ensure_showcase_templates(db)[FEED_BLEND]
    applied = client.post(f"/api/v1/templates/{template}/apply", json={"domain_name": "pdlp-run"}, headers=tenants["a"]).json()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value) VALUES ('problem', :p, 'solve.pdlp', CAST('true' AS jsonb))"),
               {"p": applied["problem_id"]})
    db.commit()
    run = client.post(f"/api/v1/scenarios/{applied['scenario_id']}/runs", json={"time_limit_s": 30}, headers=tenants["a"])
    assert run.status_code in (200, 201, 202), run.text
    run_id = run.json()["id"]
    for _ in range(5):
        if db.execute(text("SELECT status FROM run WHERE id = :r"), {"r": run_id}).scalar_one() not in ("queued", "running"):
            break
        work_once(db)
    status, optimality, solver, params = db.execute(
        text("SELECT status, optimality, solver, params FROM run WHERE id = :r"), {"r": run_id}).one()
    assert (status, optimality) == ("optimal", "approximate")
    assert solver.startswith("pdlp") and params["tolerance"] == lp.PDLP_TOLERANCE
    assert params["chosen_solver"] == "pdlp" and params["pdlp"] is True
    # And the API reads it back as such: the run page and the list both show it.
    read = client.get(f"/api/v1/runs/{run_id}", headers=tenants["a"])
    assert read.status_code == 200 and read.json()["optimality"] == "approximate"
