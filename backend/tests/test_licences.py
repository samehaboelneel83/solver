"""An organization's own solver licences (queue R42): encrypted, write-only, given to its own solves
only, never in a log, a run's record or an error; and the solvers an organization allows."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.db import engine
from app.solve import adapters, licences, sandbox
from app.solve.backends import BUILT_IN, NoBackend, choose
from app.solve.classify import classify
from app.solve.convexity import refine
from app.solve.service import claim_next, enqueue_run, execute_run, SettingUnusable
from app.solve import compile_model
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_diagnose import _scenario_for
from tests.test_golden import GOLDEN, NO_DATA
from tests.test_solve import _feasible
from tests.test_v1_problem_run import db  # noqa: F401

REFERENCE = Path(__file__).resolve().parent.parent / "adapters" / "reference"
KEY = "DEMO-5e3cf1a9-not-a-real-key"
GOOD = {"env": {"DEMO_LICENCE_KEY": KEY}, "file": "demo licence\nissued to the tests\n"}


@pytest.fixture
def registry(monkeypatch):
    """The reference adapters in the registry, as the api and the worker have them live; solves
    inline (the sandbox's forkserver was started without them in this test process)."""
    monkeypatch.setenv("SOLVER_ADAPTERS_DIR", str(REFERENCE))
    monkeypatch.setenv("SOLVE_SANDBOX", "0")
    loaded = BUILT_IN + adapters.load(BUILT_IN)
    monkeypatch.setattr("app.solve.backends.REGISTRY", loaded)
    monkeypatch.setattr("app.api.solver_licences.REGISTRY", loaded)
    return {b.name: b for b in loaded}


def test_a_sealed_licence_opens_only_with_its_key(monkeypatch):
    sealed, fingerprint = licences.seal(GOOD)
    assert KEY.encode() not in sealed and len(fingerprint) == 12
    assert licences.unseal(sealed) == GOOD
    monkeypatch.setenv("SOLVER_SECRETS_KEY", "q" * 43 + "=")
    assert licences.unseal(sealed) is None


def test_a_licence_is_given_to_the_solve_and_taken_back_after():
    licence = {"env": {"DEMO_LICENCE_KEY": KEY}, "file": {"name": "demo.lic", "text": "demo licence\n",
                                                            "env": "DEMO_LICENCE_FILE"}}
    assert "DEMO_LICENCE_KEY" not in os.environ
    with sandbox._applied(licence):
        assert os.environ["DEMO_LICENCE_KEY"] == KEY
        path = os.environ["DEMO_LICENCE_FILE"]
        assert Path(path).read_text() == "demo licence\n" and oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert "DEMO_LICENCE_KEY" not in os.environ and "DEMO_LICENCE_FILE" not in os.environ
    assert not Path(path).exists()


def test_an_error_quoting_the_licence_loses_it():
    licence = {"env": {"DEMO_LICENCE_KEY": KEY}}
    clean = sandbox.scrubbed(RuntimeError(f"licence rejected: key {KEY!r}"), licence)
    assert KEY not in str(clean) and "[licence]" in str(clean)


# -- the API ------------------------------------------------------------------------------


def test_the_api_takes_a_licence_and_never_gives_it_back(registry, client, auth_headers):
    listed = client.get("/api/v1/solver-licences", headers=auth_headers).json()["items"]
    demo = next(i for i in listed if i["adapter"] == "licensed-demo")
    assert demo["required"] and not demo["set"] and demo["env"] == ["DEMO_LICENCE_KEY"] and demo["file"]
    try:
        put = client.put("/api/v1/solver-licences/licensed-demo", json=GOOD, headers=auth_headers)
        assert put.status_code == 200 and set(put.json()) == {"adapter", "set", "fingerprint"}
        for response in (client.get("/api/v1/solver-licences", headers=auth_headers),
                         client.get("/api/v1/solvers", headers=auth_headers)):
            assert KEY not in response.text and "demo licence" not in response.text
        solvers = client.get("/api/v1/solvers", headers=auth_headers).json()["items"]
        assert next(s for s in solvers if s["name"] == "licensed-demo")["licence"] == "set"
        stored = engine.connect().execute(text("SELECT payload FROM iam.solver_licence WHERE adapter = 'licensed-demo'"))
        assert KEY.encode() not in bytes(stored.scalar_one())
    finally:
        assert client.delete("/api/v1/solver-licences/licensed-demo", headers=auth_headers).status_code == 204
    solvers = client.get("/api/v1/solvers", headers=auth_headers).json()["items"]
    assert next(s for s in solvers if s["name"] == "licensed-demo")["licence"] == "missing"


@pytest.mark.parametrize("body, code", [
    ({"env": {"PATH": "/tmp"}}, "licence_unknown_name"),
    ({}, "licence_empty"),
    ({"env": {"DEMO_LICENCE_KEY": ""}}, "licence_value"),
])
def test_the_api_takes_only_what_the_manifest_declares(registry, client, auth_headers, body, code):
    response = client.put("/api/v1/solver-licences/licensed-demo", json=body, headers=auth_headers)
    assert response.status_code == 422 and response.json()["detail"][0]["type"] == code


def test_a_licence_for_a_built_in_or_unknown_solver_is_refused(registry, client, auth_headers):
    assert client.put("/api/v1/solver-licences/highs", json=GOOD, headers=auth_headers).status_code == 404
    assert client.put("/api/v1/solver-licences/cbc", json=GOOD, headers=auth_headers).status_code == 422


def test_another_organization_sees_no_licence():
    sealed, fingerprint = licences.seal(GOOD)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            owner = connection.execute(text("SELECT id FROM iam.organization LIMIT 1")).scalar_one()
            connection.execute(text("INSERT INTO iam.solver_licence (organization_id, adapter, payload, fingerprint)"
                                    " VALUES (:o, 'licensed-demo', :p, :f)"), {"o": owner, "p": sealed, "f": fingerprint})
            connection.execute(text("SET ROLE solver_app"))
            connection.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": str(uuid.uuid4())})
            assert connection.execute(text("SELECT count(*) FROM iam.solver_licence")).scalar_one() == 0
        finally:
            transaction.rollback()


# -- through a run -------------------------------------------------------------------------


@pytest.fixture
def empty_queue(db):
    db.execute(text("DELETE FROM run"))
    db.execute(text("DELETE FROM iam.solver_licence"))
    db.commit()
    yield
    db.execute(text("DELETE FROM run"))
    db.execute(text("DELETE FROM iam.solver_licence"))
    db.commit()


def _solve(db, scenario, solver):
    run = enqueue_run(db, scenario, time_limit=10.0, reuse=False, solver=solver)
    assert claim_next(db) == run
    execute_run(db, run)
    return db.execute(text("SELECT status, error, params, solver_version FROM run WHERE id = :r"),
                      {"r": run}).mappings().one()


def _set(db, scenario, licence):
    sealed, fingerprint = licences.seal(licence)
    db.execute(text("INSERT INTO iam.solver_licence (organization_id, adapter, payload, fingerprint)"
                    " SELECT organization_id, 'licensed-demo', :p, :f FROM scenario WHERE id = :s"),
               {"p": sealed, "f": fingerprint, "s": scenario})
    db.commit()


def test_a_licensed_solver_runs_only_with_this_organizations_licence(registry, db, empty_queue):
    version, _ = _feasible(db)
    scenario = _scenario_for(db, version)
    refused = _solve(db, scenario, "licensed-demo")
    assert refused["status"] == "error" and "needs a licence, and this organization has not set one" in refused["error"]
    _set(db, scenario, GOOD)
    solved = _solve(db, scenario, "licensed-demo")
    assert solved["status"] == "optimal" and "licensed-demo" in solved["solver_version"]
    assert KEY not in str(dict(solved)) and "DEMO_LICENCE_KEY" not in os.environ


def test_a_rejected_licence_is_named_in_the_error_but_never_quoted(registry, db, empty_queue):
    version, _ = _feasible(db)
    scenario = _scenario_for(db, version)
    wrong = {"env": {"DEMO_LICENCE_KEY": "EXPIRED-7f00c2d4-key"}, "file": "demo licence\n"}
    _set(db, scenario, wrong)
    run = _solve(db, scenario, "licensed-demo")
    assert run["status"] == "error" and "licensed-demo" in (run["error"] or "")
    assert "EXPIRED-7f00c2d4-key" not in str(dict(run))


# -- which solvers an organization allows ----------------------------------------------------


def test_allowed_and_denied_solvers_are_obeyed_by_the_rules_and_by_name(registry):
    ir = GOLDEN[0][1]
    found = refine(classify(ir, NO_DATA), compile_model(ir, NO_DATA))
    first, _ = choose(found)
    second, _ = choose(found, denied={first.name})
    assert second.name != first.name
    with pytest.raises(NoBackend, match="denied here"):
        choose(found, first.name, denied={first.name})
    with pytest.raises(NoBackend, match="not among the solvers allowed"):
        choose(found, "highs", allowed={"cp-sat"})
    assert choose(found, allowed={"highs"})[0].name == "highs"


def test_a_denied_solver_is_refused_when_the_run_is_asked_for(registry, db, empty_queue):
    version, _ = _feasible(db)
    scenario = _scenario_for(db, version)
    problem = db.execute(text("SELECT problem_id FROM scenario WHERE id = :s"), {"s": scenario}).scalar_one()
    db.execute(text("INSERT INTO setting (scope, scope_id, key, value)"
                    " VALUES ('problem', :p, 'solve.denied_solvers', CAST('\"cbc, highs\"' AS jsonb))"), {"p": problem})
    db.commit()
    with pytest.raises(SettingUnusable, match="cbc is denied here"):
        enqueue_run(db, scenario, time_limit=10.0, reuse=False, solver="cbc")
