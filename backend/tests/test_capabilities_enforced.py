"""What a role actually stops you doing.

Before migration 0013 every authenticated user could do everything, so these
tests are the first that can fail for the right reason. The one that carries
the feature is `a_planner_may_solve_but_not_change_the_model`: a planner
asking "what if Thursday needed one more?" must be able to run a scenario
without being able to edit the model everyone else's answers depend on. If
that split does not hold, roles are decoration.

The refusals are **403, not 404**. The resource exists and the caller is who
they say they are; what is missing is permission, and saying so is what lets
them ask for it -- a 404 would also lie to the UI, which needs to tell "not
there" from "not yours".
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.seed import seed_admin, seed_workforce_demo
from tests.test_v1_problem_run import db  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    session = SessionLocal()
    seed_admin(session)
    session.close()


def _account(db, role: str | None) -> dict[str, str]:
    """A user holding one role, or none at all."""
    username = f"{role or 'roleless'}-{uuid.uuid4().hex[:8]}"
    password = "correct horse battery staple"
    org = db.execute(text("SELECT id FROM iam.organization LIMIT 1")).scalar_one()
    user_id = db.execute(
        text(
            "INSERT INTO iam.user_account (id, organization_id, username, display_name,"
            "                              email, hashed_password, is_active)"
            " VALUES (gen_random_uuid(), :o, :u, :u, :e, :p, true) RETURNING id"
        ),
        {"o": org, "u": username, "e": f"{username}@example.test", "p": hash_password(password)},
    ).scalar_one()
    if role is not None:
        db.execute(
            text(
                "INSERT INTO iam.user_role (id, user_id, role_id)"
                " SELECT gen_random_uuid(), :u, id FROM iam.role WHERE code = :r"
            ),
            {"u": str(user_id), "r": role},
        )
    db.commit()

    client = TestClient(app)
    token = client.post(
        "/api/auth/login", data={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seeded(db):
    created = seed_workforce_demo(db)
    db.commit()
    yield created
    db.execute(text("DELETE FROM domain WHERE id = :d"), {"d": created["domain_id"]})
    db.commit()


# -- the split the feature exists for ---------------------------------------


def test_a_planner_may_solve_but_not_change_the_model(db, seeded):
    client = TestClient(app)
    planner = _account(db, "planner")

    solving = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        headers=planner,
        json={"time_limit_s": 5},
    )
    editing = client.post(
        "/api/v1/entity-types",
        headers=planner,
        json={"domain_id": seeded["domain_id"], "name": "sneaky", "role": "agent"},
    )

    assert solving.status_code == 201
    assert editing.status_code == 403
    assert "domain.edit" in editing.json()["detail"]


def test_a_modeller_may_change_the_model(db, seeded):
    client = TestClient(app)
    modeller = _account(db, "modeller")

    response = client.post(
        "/api/v1/entity-types",
        headers=modeller,
        json={"domain_id": seeded["domain_id"], "name": "vehicle", "role": "resource"},
    )

    assert response.status_code == 201


def test_a_modeller_may_not_grant_roles(db, seeded):
    """iam.manage is the capability that creates users and assigns roles.
    domain.edit is not a back door onto that — a modeller shapes the model,
    they do not decide who else may."""
    client = TestClient(app)
    modeller = _account(db, "modeller")
    username = f"granted-{uuid.uuid4().hex[:8]}"

    created = client.post(
        "/api/iam/user_account/",
        headers=modeller,
        json={"username": username, "password": "change-me-planner"},
    )
    assert created.status_code == 403, created.text
    assert "iam.manage" in created.json()["detail"]

    role = client.get("/api/iam/role/?q=planner", headers=modeller).json()["items"][0]
    granted = client.post(
        "/api/iam/user_role/",
        headers=modeller,
        json={"user_id": role["id"], "role_id": role["id"]},
    )
    assert granted.status_code == 403, granted.text
    assert "iam.manage" in granted.json()["detail"]


def test_a_viewer_may_read_but_neither_solve_nor_edit(db, seeded):
    """Reading stays behind authentication alone: a result nobody can look at
    is not worth producing, and the platform's value is in being read."""
    client = TestClient(app)
    viewer = _account(db, "viewer")

    assert client.get("/api/v1/entity-types", headers=viewer).status_code == 200
    assert (
        client.post(
            f"/api/v1/scenarios/{seeded['scenario_id']}/runs", headers=viewer, json={}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/entity-types",
            headers=viewer,
            json={"domain_id": seeded["domain_id"], "name": "nope", "role": "agent"},
        ).status_code
        == 403
    )


def test_a_user_with_no_role_at_all_can_do_nothing_but_read(db, seeded):
    """The default has to be closed. An account nobody has granted anything
    must not inherit the run of the place."""
    client = TestClient(app)
    nobody = _account(db, None)

    assert client.get("/api/v1/entity-types", headers=nobody).status_code == 200
    assert (
        client.post(
            f"/api/v1/scenarios/{seeded['scenario_id']}/runs", headers=nobody, json={}
        ).status_code
        == 403
    )


# -- choosing the solver is its own capability ------------------------------


def test_a_planner_may_solve_but_not_pick_the_solver(db, seeded):
    """Asking the question and choosing the technique it is answered with are
    different decisions. A run's solver is part of what makes its answer
    defensible, so it is not a planner's to change by default."""
    client = TestClient(app)
    planner = _account(db, "planner")

    chosen = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        headers=planner,
        json={"time_limit_s": 5, "solver": "milp"},
    )
    left_to_the_platform = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        headers=planner,
        json={"time_limit_s": 5},
    )

    assert chosen.status_code == 403
    assert "not choose the solver" in chosen.json()["detail"]
    assert left_to_the_platform.status_code == 201


def test_a_modeller_may_pick_the_solver(db, seeded):
    client = TestClient(app)
    modeller = _account(db, "modeller")

    response = client.post(
        f"/api/v1/scenarios/{seeded['scenario_id']}/runs",
        headers=modeller,
        json={"time_limit_s": 5, "solver": "milp"},
    )

    assert response.status_code == 201


# -- what the caller may do -------------------------------------------------


def test_me_reports_the_capabilities_the_api_actually_enforces(db, seeded):
    """A UI that guessed would offer buttons whose only outcome is a 403, or
    hide actions the user has. This is computed where it is enforced."""
    client = TestClient(app)

    planner = client.get("/api/v1/me", headers=_account(db, "planner")).json()
    modeller = client.get("/api/v1/me", headers=_account(db, "modeller")).json()

    assert planner["capabilities"] == ["run.submit"]
    assert set(modeller["capabilities"]) == {
        "domain.edit",
        "model.publish",
        "run.submit",
        "solver.configure",
        # Migration 0014: a modeller may also change what governs a solve.
        "settings.edit",
    }


def test_the_seeded_admin_can_still_do_everything(db):
    """Enforcement must not lock the only account out of its own platform."""
    from app.core.config import get_settings

    settings = get_settings()
    client = TestClient(app)
    token = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    ).json()["access_token"]

    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json()

    assert "domain.edit" in me["capabilities"]
    assert "iam.manage" in me["capabilities"]


def test_two_roles_grant_the_union_of_their_capabilities(db, seeded):
    """Roles add up. Holding planner and modeller must not somehow be less
    than holding modeller."""
    client = TestClient(app)
    headers = _account(db, "planner")
    me = client.get("/api/v1/me", headers=headers).json()
    assert me["capabilities"] == ["run.submit"]

    db.execute(
        text(
            "INSERT INTO iam.user_role (id, user_id, role_id)"
            " SELECT gen_random_uuid(), u.id, r.id"
            "   FROM iam.user_account u, iam.role r"
            "  WHERE u.username = :u AND r.code = 'modeller'"
        ),
        {"u": me["username"]},
    )
    db.commit()

    after = client.get("/api/v1/me", headers=headers).json()

    assert "run.submit" in after["capabilities"]
    assert "domain.edit" in after["capabilities"]
