"""Checking a draft against the domain without publishing it (Blocks 4)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests.test_tenancy import IR, tenants  # noqa: F401
from tests.test_v1_problem_run import db  # noqa: F401


def _versions(db, problem: int) -> int:  # noqa: F811
    return db.execute(text("SELECT count(*) FROM model_version WHERE problem_id = :p"), {"p": problem}).scalar_one()


def test_a_valid_draft_is_ok_and_nothing_is_written(tenants, db):  # noqa: F811
    problem = tenants["problem_a"]
    before = _versions(db, problem)
    answer = TestClient(app).post(f"/api/v1/problems/{problem}/versions/validate", json={"ir": IR}, headers=tenants["a"])
    assert answer.status_code == 200 and answer.json() == {"ok": True}
    assert _versions(db, problem) == before


def test_a_refused_draft_answers_as_publish_would(tenants, db):  # noqa: F811
    """A refusal only the domain can make -- a set that is not one of its entity types."""
    problem = tenants["problem_a"]
    bad = {**IR, "sets": ["no_such_type"]}
    client = TestClient(app)
    checked = client.post(f"/api/v1/problems/{problem}/versions/validate", json={"ir": bad}, headers=tenants["a"])
    published = client.post(f"/api/v1/problems/{problem}/versions", json={"ir": bad}, headers=tenants["a"])
    assert checked.status_code == published.status_code == 422
    assert checked.json() == published.json()
    assert checked.json()["detail"][0]["loc"][:2] == ["body", "ir"]


def test_another_organization_cannot_validate_against_this_problem(tenants, db):  # noqa: F811
    answer = TestClient(app).post(
        f"/api/v1/problems/{tenants['problem_a']}/versions/validate", json={"ir": IR}, headers=tenants["b"]
    )
    assert answer.status_code == 404
