"""The conformance kit (queue R43, app.solve.conformance): the reference adapters pass it; a solver
that claims what it did not find fails it; only a passed current version is chosen unasked."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.solve import adapters, compile_model, conformance
from app.solve.backends import BUILT_IN, NoBackend, choose
from app.solve.classify import classify
from app.solve.convexity import refine
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401

REFERENCE = Path(__file__).resolve().parent.parent / "adapters" / "reference"

LIAR = '''
from dataclasses import replace
from app.solve import cpsat


def solve(compiled, *, time_limit, workers, should_stop=None, seed=None, gap_rel=0.0, on_progress=None, **_):
    """Solves, then claims more than it found: every answer optimal, every optimum one better."""
    result = cpsat.solve(compiled, time_limit=time_limit, workers=workers, seed=seed)
    better = None if result.objective is None else result.objective + (1 if compiled.sense == "maximize" else -1)
    return replace(result, status="optimal", optimal=True, objective=better)
'''


def _liar(tmp_path: Path, version: str = "1") -> Path:
    folder = tmp_path / "liar"
    folder.mkdir()
    (folder / "adapter.py").write_text(LIAR, encoding="utf-8")
    (folder / "adapter.toml").write_text(
        f'name = "liar"\nkind = "python"\nversion = "{version}"\nproves = "global"\n'
        'classes = ["IP", "trivial"]\nprovides = ["linear", "integral"]\n[python]\nmodule = "adapter.py"\n',
        encoding="utf-8")
    return folder


@pytest.fixture
def clean(db, monkeypatch):
    monkeypatch.setenv("SOLVE_SANDBOX", "0")
    db.execute(text("DELETE FROM solver_conformance"))
    db.commit()
    yield
    db.execute(text("DELETE FROM solver_conformance"))
    db.commit()
    adapters.VERIFIED.clear()


def _loaded(monkeypatch, *folders):
    monkeypatch.setenv("SOLVER_ADAPTERS_DIR", ":".join(str(f) for f in folders))
    registry = BUILT_IN + adapters.load(BUILT_IN)
    monkeypatch.setattr("app.solve.backends.REGISTRY", registry)
    return {b.name: b for b in registry}


@pytest.mark.parametrize("name", ["cbc", "highs-cli", "python-cpsat"])
def test_every_reference_adapter_passes(clean, monkeypatch, name):
    backend = _loaded(monkeypatch, REFERENCE)[name]
    report = conformance.run(backend)
    assert report.passed, [c for c in report.checks if c["result"] == "fail"]
    assert {c["check"] for c in report.checks} >= {"answer:knapsack", "answer:infeasible", "bad_hint", "time_limit", "stop"}


def test_a_solver_that_claims_what_it_did_not_find_fails(clean, monkeypatch, tmp_path):
    liar = _loaded(monkeypatch, _liar(tmp_path).parent)["liar"]
    report = conformance.run(liar)
    failed = {c["check"] for c in report.checks if c["result"] == "fail"}
    assert not report.passed and {"answer:knapsack", "answer:infeasible", "bad_hint"} <= failed


def _found():
    ir = conformance.CASES[1][1]  # the knapsack: a whole-number program
    return refine(classify(ir, conformance.NO_DATA), compile_model(ir, conformance.NO_DATA))


def test_only_a_passed_current_version_is_chosen_unasked(clean, db, monkeypatch, tmp_path):
    loaded = _loaded(monkeypatch, REFERENCE)
    with pytest.raises(NoBackend):
        choose(_found(), allowed={"python-cpsat"})  # added, and not yet passed: never unasked
    conformance.store(db, conformance.run(loaded["python-cpsat"]), "tests")
    assert choose(_found(), allowed={"python-cpsat"})[0].name == "python-cpsat"

    db.execute(text("UPDATE solver_conformance SET version = 'an older one'"))
    db.commit()
    adapters.refresh_verified(db)
    with pytest.raises(NoBackend):
        choose(_found(), allowed={"python-cpsat"})  # a pass for another version counts for nothing


def test_a_failed_report_keeps_a_solver_out_of_the_rules(clean, db, monkeypatch, tmp_path):
    liar = _loaded(monkeypatch, _liar(tmp_path).parent)["liar"]
    conformance.store(db, conformance.run(liar), "tests")
    assert "liar" not in adapters.VERIFIED
    with pytest.raises(NoBackend):
        choose(_found(), allowed={"liar"})
    assert choose(_found(), "liar")[0].name == "liar"  # still runs when named


def test_an_operator_runs_the_kit_and_the_list_says_so(clean, monkeypatch, client, auth_headers):
    loaded = _loaded(monkeypatch, REFERENCE)
    monkeypatch.setattr("app.api.solver_licences.REGISTRY", tuple(loaded.values()))
    before = next(s for s in client.get("/api/v1/solvers", headers=auth_headers).json()["items"] if s["name"] == "cbc")
    assert before["automatic"] is False and before["conformance"] is None
    response = client.post("/api/v1/solvers/cbc/conformance", headers=auth_headers)
    assert response.status_code == 200 and response.json()["passed"] is True
    after = next(s for s in client.get("/api/v1/solvers", headers=auth_headers).json()["items"] if s["name"] == "cbc")
    assert after["automatic"] is True and after["conformance"]["passed"] and after["conformance"]["current"]
    assert client.post("/api/v1/solvers/highs/conformance", headers=auth_headers).status_code == 404
