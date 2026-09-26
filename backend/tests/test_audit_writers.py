"""R34 follow-up: remaining audit writers (keys, publish, scenario, bulk)."""

from __future__ import annotations

from sqlalchemy import text

from app.seed import seed_admin, seed_workforce_demo
from tests.test_api_problems import auth_headers, client  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def test_creating_an_api_key_is_audited(db, client, auth_headers):
    seed_admin(db)
    response = client.post(
        "/api/v1/api-keys",
        headers=auth_headers,
        json={"name": "audit-probe"},
    )
    assert response.status_code == 201, response.text
    actions = db.execute(
        text("SELECT action FROM iam.audit_event WHERE action = 'api_key.create'")
    ).scalars().all()
    assert len(actions) >= 1


def test_publishing_a_model_version_is_audited(db, client, auth_headers):
    seed_admin(db)
    seeded = seed_workforce_demo(db)
    problem = seeded["problem_id"]
    ir = {
        "version": 1,
        "sets": [],
        "parameters": {},
        "variables": {"x": {"index": [], "domain": "binary"}},
        "constraints": [],
        "objective": {
            "sense": "maximize",
            "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": []}}],
        },
    }
    # Workforce demo already has a version; publishing another is fine.
    response = client.post(
        f"/api/v1/problems/{problem}/versions",
        headers=auth_headers,
        json={"ir": ir, "note": "audit"},
    )
    # May 422 if IR doesn't match domain sets — use the problem's existing IR shape.
    if response.status_code != 201:
        existing = client.get(
            f"/api/v1/problems/{problem}/versions", headers=auth_headers
        ).json()["items"][0]
        full = client.get(f"/api/v1/versions/{existing['id']}", headers=auth_headers).json()
        response = client.post(
            f"/api/v1/problems/{problem}/versions",
            headers=auth_headers,
            json={"ir": full["ir"], "note": "audit"},
        )
    assert response.status_code == 201, response.text
    assert db.execute(
        text("SELECT count(*) FROM iam.audit_event WHERE action = 'model.publish'")
    ).scalar_one() >= 1
