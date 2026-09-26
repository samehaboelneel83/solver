"""Cairo University lecture timetable template (OAAS Phase 6 use case)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.lectures import CAIRO_UNIVERSITY_LECTURES, build_ir, build_seed
from app.main import app
from app.seed import seed_admin
from app.showcase import ensure_showcase_templates
from app.solve.service import claim_next, enqueue_run, execute_run
from tests.test_v1_problem_run import db  # noqa: F401


def test_lecture_ir_assigns_each_section_once():
    ir = build_ir()
    assert ir["variables"]["assign"]["index"] == ["section", "day", "period", "room"]
    assert {c["id"] for c in ir["constraints"]} >= {
        "c_once",
        "c_room",
        "c_instructor",
        "c_capacity",
    }
    seed = build_seed()
    sections = [e for e in seed["entities"] if e["type"] == "section"]
    assert len(sections) == 4
    assert any(e["attrs"]["enrollment"] == 70 for e in sections)


def test_cairo_university_lectures_applies_and_solves_all_morning(db):
    """Phase 6 acceptance: apply → solve → four morning placements, objective 0."""
    seed_admin(db)
    db.commit()
    settings = get_settings()
    client = TestClient(app)
    token = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ids = ensure_showcase_templates(db)
    template_id = ids[CAIRO_UNIVERSITY_LECTURES]
    response = client.post(
        f"/api/v1/templates/{template_id}/apply",
        json={"domain_name": "cu_fcai_demo", "name": "lectures"},
        headers=headers,
    )
    try:
        assert response.status_code == 201, response.text
        body = response.json()
        run_id = enqueue_run(db, body["scenario_id"], time_limit=30.0, reuse=False)
        assert claim_next(db) == run_id
        outcome = execute_run(db, run_id)
        assert outcome.status == "optimal", (outcome.status, getattr(outcome, "error", None))
        assert outcome.objective == 0
        placed = outcome.assignments["assign"]
        assert len(placed) == 4
        # Each placement is [section, day, period, room]; period must be morning.
        for key in placed:
            assert key[2] == "morning", key
        big = [k for k in placed if k[0] == "cs101_a"]
        assert len(big) == 1 and big[0][3] == "hall_a"
    finally:
        if response.status_code == 201:
            body = response.json()
            db.execute(text("DELETE FROM run WHERE scenario_id = :s"), {"s": body["scenario_id"]})
            db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": body["domain_id"]})
        db.execute(text("DELETE FROM template WHERE name = :n"), {"n": CAIRO_UNIVERSITY_LECTURES})
        db.commit()
