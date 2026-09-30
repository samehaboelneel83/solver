"""Applying a template: start a problem from a stored IR.

The template table is seed data, not a second IR. Applying it plants
missing types from `domain_seed`, then publishes `default_ir` as version 1
of a new (or empty) problem. An empty seed is still a 422 from the same
validator a published version uses -- the template must not half-build a
domain.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.ir.contract import IR_VERSION
from app.main import app
from app.seed import ensure_weekly_rota_template, seed_admin, seed_workforce_demo
from tests.test_v1_problem_run import db  # noqa: F401


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    session = SessionLocal()
    seed_admin(session)
    session.close()


@pytest.fixture
def auth_headers():
    settings = get_settings()
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def seeded(db):
    created = seed_workforce_demo(db)
    db.commit()
    yield created
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": created["domain_id"]})
    db.execute(text("DELETE FROM template WHERE name = 'weekly_rota'"))
    db.commit()


def _template_id(db) -> int:
    return db.execute(text("SELECT id FROM template WHERE name = 'weekly_rota'")).scalar_one()


def test_applying_a_template_creates_a_problem_with_the_starting_model(seeded, auth_headers, db):
    client = TestClient(app)
    template_id = _template_id(db)

    response = client.post(
        f"/api/v1/templates/{template_id}/apply",
        json={"domain_id": seeded["domain_id"], "name": "weekly_rota_copy"},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["template_id"] == template_id
    assert body["domain_id"] == seeded["domain_id"]
    version = client.get(
        f"/api/v1/versions/{body['model_version_id']}", headers=auth_headers
    ).json()
    assert version["note"] == "from template weekly_rota"
    # The history says a template made this problem, and who applied it (operator trial F34 F30).
    event = db.execute(text("SELECT object_id FROM iam.audit_event WHERE action = 'template.apply'"
                            " ORDER BY id DESC LIMIT 1")).one()
    assert event.object_id == str(body["problem_id"])
    listed = client.get("/api/v1/audit?action=template.apply", headers=auth_headers).json()["items"][0]
    assert listed["actor"] == "admin"
    assert "c_cover_demand" in [c["id"] for c in version["ir"]["constraints"]]
    scenario = client.get(
        f"/api/v1/scenarios/{body['scenario_id']}", headers=auth_headers
    ).json()
    assert scenario["name"] == "Base"
    assert scenario["patch"] == {}


def test_applying_twice_under_the_same_name_is_refused(seeded, auth_headers, db):
    """The demo problem is already called weekly_rota. A second one with
    that name would collide; the unique constraint is the refusal."""
    client = TestClient(app)
    template_id = _template_id(db)

    response = client.post(
        f"/api/v1/templates/{template_id}/apply",
        json={"domain_id": seeded["domain_id"]},
        headers=auth_headers,
    )

    assert response.status_code == 409, response.text


def test_filling_a_problem_that_already_has_a_model_is_refused(seeded, auth_headers, db):
    client = TestClient(app)
    template_id = _template_id(db)

    response = client.post(
        f"/api/v1/templates/{template_id}/apply",
        json={"problem_id": seeded["problem_id"]},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert "already has a model" in response.json()["detail"]


def test_applying_weekly_rota_to_an_empty_domain_plants_the_types(auth_headers, db):
    """The seed is executable: a domain with no employee type still starts."""
    domain = db.execute(
        text("INSERT INTO domain (name) VALUES ('empty_for_weekly_rota') RETURNING id")
    ).scalar_one()
    template_id = ensure_weekly_rota_template(db)
    db.commit()
    try:
        client = TestClient(app)
        response = client.post(
            f"/api/v1/templates/{template_id}/apply",
            json={"domain_id": domain, "name": "from_template"},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        names = {
            row[0]
            for row in db.execute(
                text("SELECT name FROM entity_type WHERE domain_id = :d"), {"d": domain}
            ).all()
        }
        assert names == {"employee", "unit", "day", "shift"}
        keys = {
            row[0]
            for row in db.execute(
                text(
                    "SELECT e.key FROM entity e"
                    " JOIN entity_type t ON t.id = e.entity_type_id"
                    " WHERE t.domain_id = :d AND t.name = 'employee'"
                ),
                {"d": domain},
            ).all()
        }
        assert "ahmed" in keys
        demand_cells = db.execute(
            text(
                "SELECT count(*) FROM parameter_value pv"
                " JOIN parameter_def p ON p.id = pv.parameter_def_id"
                " WHERE p.domain_id = :d AND p.name = 'demand'"
            ),
            {"d": domain},
        ).scalar_one()
        assert demand_cells > 0
    finally:
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.execute(text("DELETE FROM template WHERE name = 'weekly_rota'"))
        db.commit()


def test_weekly_rota_applied_to_an_empty_domain_solves_to_optimal(auth_headers, db):
    """A new user's first click must lead to an answer, not "no answer exists".

    The seeded people cannot meet the seeded demand -- that is the demo's
    point -- so the template's coverage rule is a target, not a wall.
    Worked by hand, with coverage soft at 100 per missing person:

    * hours caps allow 40/8 + 32/8 + 40/8 + 20/8 + 40/8 = 5+4+5+2+5 = 21
      shifts; every one fills a demanded slot (each costs 1, saves 100);
    * demand is 5 weekdays x (4+3+2) + 2 weekend days x (2+2+2) = 57, so 36
      slots stay short: 3600;
    * North Region's late-shift target (3 a day, weight 4) can only count
      Ahmed and Bilal, at most 2 a day and 5+4 = 9 over the week, so 21-9 =
      12 short: 48 -- their evenings fill demanded slots, so coverage loses
      nothing by it;
    * objective = 21 + 3600 + 48 = 3669.
    """
    from app.solve.service import claim_next, enqueue_run, execute_run

    template_id = ensure_weekly_rota_template(db)
    db.commit()
    client = TestClient(app)
    response = client.post(
        f"/api/v1/templates/{template_id}/apply",
        json={"domain_name": "weekly_rota_first_click", "name": "rota"},
        headers=auth_headers,
    )
    try:
        assert response.status_code == 201, response.text
        run_id = enqueue_run(db, response.json()["scenario_id"], time_limit=30.0)
        assert claim_next(db) == run_id
        outcome = execute_run(db, run_id)

        assert outcome.status == "optimal"
        assert outcome.objective == 3669
        assert len(outcome.assignments["assign"]) == 21
    finally:
        if response.status_code == 201:
            db.execute(
                text("DELETE FROM run WHERE scenario_id = :s"),
                {"s": response.json()["scenario_id"]},
            )
            db.execute(
                text("DELETE FROM domain WHERE id = :d"),
                {"d": response.json()["domain_id"]},
            )
        db.execute(text("DELETE FROM template WHERE name = 'weekly_rota'"))
        db.commit()


def test_start_up_refreshes_the_weekly_rota_template(db):
    """A fix to the template has to reach a live database. Only
    `python -m app.seed` used to refresh it, so a deploy left the old,
    infeasible model in place; start-up now refreshes it like the showcase
    templates."""
    from app.seed import _IR, weekly_rota_template_ir

    db.execute(text("DELETE FROM template WHERE name = 'weekly_rota'"))
    db.execute(
        text(
            "INSERT INTO template (name, ir_version, domain_seed, default_ir)"
            " VALUES ('weekly_rota', '1', '{}', CAST(:ir AS jsonb))"
        ),
        {"ir": json.dumps(_IR)},
    )
    db.commit()
    try:
        with TestClient(app):
            pass
        db.expire_all()
        stored = db.execute(
            text("SELECT default_ir FROM template WHERE name = 'weekly_rota'")
        ).scalar_one()
        assert stored == weekly_rota_template_ir()
    finally:
        db.execute(text("DELETE FROM template WHERE name = 'weekly_rota'"))
        db.commit()


def test_the_template_softens_coverage_and_nothing_else():
    """The template is the demo's model with one change. The demo keeps its
    hard coverage rule: it is the platform's worked example of an
    infeasible model being explained."""
    from app.seed import _IR, weekly_rota_template_ir

    template = weekly_rota_template_ir()
    by_id = {c["id"]: c for c in template["constraints"]}
    assert by_id["c_cover_demand"]["severity"] == "soft"
    assert by_id["c_cover_demand"]["weight"] == 100
    assert {c["id"]: c for c in _IR["constraints"]}["c_cover_demand"]["severity"] == "hard"

    def without_cover(ir):
        return {**ir, "constraints": [c for c in ir["constraints"] if c["id"] != "c_cover_demand"]}

    assert without_cover(template) == without_cover(_IR)
    rest = {k: v for k, v in by_id["c_cover_demand"].items() if k not in ("severity", "weight")}
    original = {c["id"]: c for c in _IR["constraints"]}["c_cover_demand"]
    assert rest == {k: v for k, v in original.items() if k != "severity"}


def test_applying_to_a_domain_that_already_has_people_does_not_duplicate_them(
    seeded, auth_headers, db
):
    before = db.execute(
        text(
            "SELECT count(*) FROM entity e"
            " JOIN entity_type t ON t.id = e.entity_type_id"
            " WHERE t.domain_id = :d"
        ),
        {"d": seeded["domain_id"]},
    ).scalar_one()
    client = TestClient(app)
    response = client.post(
        f"/api/v1/templates/{_template_id(db)}/apply",
        json={"domain_id": seeded["domain_id"], "name": "weekly_rota_copy"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    after = db.execute(
        text(
            "SELECT count(*) FROM entity e"
            " JOIN entity_type t ON t.id = e.entity_type_id"
            " WHERE t.domain_id = :d"
        ),
        {"d": seeded["domain_id"]},
    ).scalar_one()
    assert after == before


def test_applying_with_a_domain_name_creates_the_domain(auth_headers, db):
    template_id = ensure_weekly_rota_template(db)
    db.commit()
    client = TestClient(app)
    response = client.post(
        f"/api/v1/templates/{template_id}/apply",
        json={"domain_name": "from_weekly_rota", "name": "rota"},
        headers=auth_headers,
    )
    try:
        assert response.status_code == 201, response.text
        body = response.json()
        name = db.execute(
            text("SELECT name FROM domain WHERE id = :d"), {"d": body["domain_id"]}
        ).scalar_one()
        assert name == "from_weekly_rota"
        types = db.execute(
            text("SELECT count(*) FROM entity_type WHERE domain_id = :d"),
            {"d": body["domain_id"]},
        ).scalar_one()
        assert types == 4
    finally:
        if response.status_code == 201:
            db.execute(
                text("DELETE FROM domain WHERE id = :d"),
                {"d": response.json()["domain_id"]},
            )
        db.execute(text("DELETE FROM template WHERE name = 'weekly_rota'"))
        db.commit()


def test_ensure_weekly_rota_template_refreshes_a_thin_seed(db):
    db.execute(text("DELETE FROM template WHERE name = 'weekly_rota'"))
    db.execute(
        text(
            "INSERT INTO template (name, ir_version, domain_seed, default_ir)"
            " VALUES ('weekly_rota', '1', '{\"sets\": [\"employee\"]}', '{}')"
        )
    )
    db.commit()
    try:
        ensure_weekly_rota_template(db)
        db.commit()
        seed = db.execute(
            text("SELECT domain_seed FROM template WHERE name = 'weekly_rota'")
        ).scalar_one()
        assert {row["name"] for row in seed["entity_types"]} == {
            "employee",
            "unit",
            "day",
            "shift",
        }
    finally:
        db.execute(text("DELETE FROM template WHERE name = 'weekly_rota'"))
        db.commit()


def test_a_domain_without_the_types_is_named_not_half_built(auth_headers, db):
    """A template whose seed is empty does not invent entity types.
    Missing sets are a 422 from the same validator a published version uses."""
    domain = db.execute(
        text("INSERT INTO domain (name) VALUES ('empty_for_template') RETURNING id")
    ).scalar_one()
    db.commit()
    template_id = db.execute(
        text(
            "INSERT INTO template (name, ir_version, domain_seed, default_ir)"
            " VALUES ('needs_employee', '1', '{}',"
            "         '{\"version\": 1, \"sets\": [\"employee\"], \"parameters\": {},"
            "           \"variables\": {}, \"constraints\": []}')"
            " RETURNING id"
        )
    ).scalar_one()
    db.commit()
    try:
        client = TestClient(app)
        response = client.post(
            f"/api/v1/templates/{template_id}/apply",
            json={"domain_id": domain, "name": "from_template"},
            headers=auth_headers,
        )
        assert response.status_code == 422, response.text
        assert db.execute(
            text("SELECT count(*) FROM problem WHERE domain_id = :d"), {"d": domain}
        ).scalar_one() == 0
        assert db.execute(
            text("SELECT count(*) FROM entity_type WHERE domain_id = :d"), {"d": domain}
        ).scalar_one() == 0
    finally:
        db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": domain})
        db.execute(text("DELETE FROM template WHERE id = :t"), {"t": template_id})
        db.commit()


def test_template_ir_version_defaults_to_the_contract(auth_headers):
    """The platform expresses one IR version. Omitting `ir_version` used
    to 422 as a missing field; the column default is that version."""
    client = TestClient(app)
    name = f"default-ir-version-{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/template/",
        json={"name": name, "default_ir": {}},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    try:
        assert response.json()["ir_version"] == str(IR_VERSION)
    finally:
        client.delete(f"/api/template/{response.json()['id']}", headers=auth_headers)


def test_template_json_columns_must_be_objects(auth_headers):
    """`domain_seed` and `default_ir` are JSONB objects. An array used to
    store and then fail later on apply; name the field at write time."""
    client = TestClient(app)
    name = f"not-an-object-{uuid.uuid4().hex[:8]}"
    cases = (
        ("default_ir", {"name": name, "ir_version": "1", "default_ir": []}),
        (
            "domain_seed",
            {
                "name": f"{name}-seed",
                "ir_version": "1",
                "default_ir": {},
                "domain_seed": ["employee"],
            },
        ),
    )
    for field, payload in cases:
        response = client.post("/api/template/", json=payload, headers=auth_headers)
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert any(list(entry.get("loc", [])) == ["body", field] for entry in detail), detail
        assert any("object" in str(entry.get("msg", "")).lower() for entry in detail)

    created = client.post(
        "/api/template/",
        json={"name": name, "ir_version": "1", "default_ir": {}},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    row_id = created.json()["id"]
    try:
        rewritten = client.put(
            f"/api/template/{row_id}",
            json={"default_ir": "not-an-object"},
            headers=auth_headers,
        )
        assert rewritten.status_code == 422, rewritten.text
        detail = rewritten.json()["detail"]
        assert any(list(entry.get("loc", [])) == ["body", "default_ir"] for entry in detail), detail
    finally:
        client.delete(f"/api/template/{row_id}", headers=auth_headers)
