"""Epic UX, U-5: before a run -- is it ready, which solvers fit and why the others do not, is a worker there."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.solve.backends import choose, fit
from app.solve.classify import classify
from app.solve.compare import _claims
from app.worker import beat
from tests.test_alternatives import _knapsack
from tests.test_api_runs import auth_headers, ensure_admin_seeded  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401


def test_fit_says_why_each_solver_is_kept_out_and_agrees_with_choose():
    found = classify(_knapsack(), {})
    rows = {r["name"]: r for r in fit(found)}
    chosen = [r["name"] for r in rows.values() if r["chosen"]]
    assert chosen == [choose(found)[0].name]
    assert rows["glop"]["fits"] is False and "not a IP model" in rows["glop"]["why"]
    assert rows["benders"]["fits"] is False  # a pure yes-or-no model has no continuous part
    assert rows["ga"]["fits"] and not rows["ga"]["automatic"] and "asked for by name" in rows["ga"]["why"]
    assert all(r["why"] for r in rows.values())


def test_fit_names_a_solver_the_settings_keep_out():
    found = classify(_knapsack(), {})
    rows = {r["name"]: r for r in fit(found, denied={"cp-sat"})}
    assert rows["cp-sat"]["fits"] is False and "denied here" in rows["cp-sat"]["why"]
    assert any(r["chosen"] for r in rows.values())


@pytest.fixture
def scenario(db):  # noqa: F811
    domain = make_domain(db, "preflight")
    problem = make_problem(db, domain)

    def make(ir):
        version = make_model_version(db, problem, ir)
        sid = db.execute(text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, :n) RETURNING id"),
                         {"p": problem, "v": version, "n": f"s{version}"}).scalar_one()
        db.commit()
        return sid

    yield make
    db.execute(text("DELETE FROM run WHERE scenario_id IN (SELECT id FROM scenario WHERE problem_id = :p)"), {"p": problem})
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
    db.execute(text("DELETE FROM worker_heartbeat"))
    db.commit()


def test_a_ready_scenario_says_so_with_its_solvers_and_workers(scenario, auth_headers):  # noqa: F811
    sid = scenario(_knapsack())
    body = TestClient(app).get(f"/api/v1/scenarios/{sid}/preflight", headers=auth_headers).json()
    assert body["ready"] is True and body["findings"] == []
    assert body["model_class"] == "IP"
    assert [s["name"] for s in body["solvers"] if s["chosen"]] == ["cp-sat"]
    assert body["workers"]["state"] in ("offline", "ready", "busy")


def test_a_rule_with_no_arithmetic_blocks_the_run_and_says_what_to_do(scenario, auth_headers):  # noqa: F811
    ir = _knapsack()
    ir["constraints"].append({"id": "c_policy", "severity": "hard", "note": "nobody works two nights"})
    sid = scenario(ir)
    body = TestClient(app).get(f"/api/v1/scenarios/{sid}/preflight", headers=auth_headers).json()
    assert body["ready"] is False
    (finding,) = [f for f in body["findings"] if f["code"] == "rule_not_expressed"]
    assert finding["kind"] == "blocker" and finding["rules"] == ["c_policy"] and "Model editor" in finding["says"]


def test_a_set_with_no_records_is_a_warning_not_a_blocker(scenario, auth_headers):  # noqa: F811
    ir = {"version": 2, "sets": ["nobody_here"], "parameters": {},
          "variables": {"x": {"index": ["nobody_here"], "domain": "binary"}},
          "constraints": [], "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression":
              {"sum": {"var": "x", "index": ["n"]}, "over": [{"index": "n", "set": "nobody_here"}]}}]}}
    sid = scenario(ir)
    body = TestClient(app).get(f"/api/v1/scenarios/{sid}/preflight", headers=auth_headers).json()
    assert any(f["code"] == "set_empty" and f["kind"] == "warning" for f in body["findings"])


def test_workers_are_online_when_one_beat_recently(db, scenario, auth_headers):  # noqa: F811
    client = TestClient(app)
    db.execute(text("DELETE FROM worker_heartbeat"))
    db.commit()
    assert client.get("/api/v1/workers", headers=auth_headers).json()["state"] in ("offline", "busy")
    beat(db, "test-worker")
    status = client.get("/api/v1/workers", headers=auth_headers).json()
    assert status["state"] == "ready" and status["online"] == 1 and "online" in status["says"]
    db.execute(text("UPDATE worker_heartbeat SET last_seen = now() - interval '5 minutes'"))
    db.commit()
    assert client.get("/api/v1/workers", headers=auth_headers).json()["online"] == 0


def test_two_answers_that_claim_different_things_say_so():
    assert _claims({"id": 1, "optimality": "global"}, {"id": 2, "optimality": "global"}) is None
    said = _claims({"id": 1, "optimality": "global"}, {"id": 2, "optimality": "local"})
    assert "run 1's answer is proven the best possible; run 2's is the best nearby" in said
