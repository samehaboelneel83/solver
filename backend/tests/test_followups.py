"""Gate override and scenario list filters (R30 / R29 follow-ups)."""

from __future__ import annotations

from sqlalchemy import text

from app.seed import seed_admin
from app.solve import suite
from tests.test_api_problems import auth_headers, client, crossed, domain_id, problems  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_list_scenarios_hides_checks_by_default(db, client, auth_headers, crossed):
    seed_admin(db)
    a, a1 = crossed["a"], crossed["a1"]
    db.execute(
        text(
            "INSERT INTO scenario (problem_id, model_version_id, name, patch)"
            " VALUES (:p, :v, 'checks: version 1', '{}'::jsonb),"
            "        (:p, :v, 'live plan', '{}'::jsonb)"
        ),
        {"p": a, "v": a1},
    )
    db.commit()
    hidden = client.get(f"/api/v1/scenarios?problem_id={a}", headers=auth_headers)
    assert hidden.status_code == 200, hidden.text
    names = [s["name"] for s in hidden.json()["items"]]
    assert "live plan" in names
    assert "checks: version 1" not in names
    shown = client.get(f"/api/v1/scenarios?problem_id={a}&include_checks=true", headers=auth_headers)
    assert any(s["name"] == "checks: version 1" for s in shown.json()["items"])


def test_gate_override_clears_gate(db, client, auth_headers, crossed, monkeypatch):
    seed_admin(db)
    version_id = crossed["a2"]
    problem_id = crossed["a"]

    def fake_checks(_db, model_version_id):
        return {
            "model_version_id": model_version_id,
            "state": "failed",
            "cases": [{"case_id": 1, "name": "x", "run_id": None, "state": "failed", "reasons": ["bad"]}],
        }

    monkeypatch.setattr(suite, "version_checks", fake_checks)
    # Ensure the version is not already in use by a non-checks scenario
    db.execute(
        text("DELETE FROM scenario WHERE model_version_id = :v AND name NOT LIKE 'checks: version %'"),
        {"v": version_id},
    )
    db.commit()
    assert suite.gate(db, problem_id, version_id) is not None

    response = client.post(
        f"/api/v1/model-versions/{version_id}/gate-override",
        headers=auth_headers,
        json={"reason": "pilot customer accepted this cost"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["overridden"] is True
    assert suite.gate(db, problem_id, version_id) is None
    actions = db.execute(
        text("SELECT action FROM iam.audit_event WHERE action = 'suite.gate_override'")
    ).scalars().all()
    assert len(actions) >= 1
