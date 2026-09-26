"""Tenancy (migration 0032, target roadmap Phase 7, defect D1).

Two organizations: the seed `default` one (A, an operator) and a fresh one
(B, not). B's administrator holds every capability, so any refusal below is
the tenancy's, not a missing permission. What is pinned:

- B sees none of A's rows, in lists or by id, and cannot cancel A's runs --
  D1, which is the reason this phase exists;
- B cannot point its rows at A's by guessing ids: the database refuses a row
  whose parents are not the caller's, as though they did not exist;
- both may use the same names;
- what everyone shares -- roles, platform settings -- only an operator changes;
- the worker, which serves every organization, still solves B's runs, and
  B's answers carry B's organization;
- a connection a request made tenant-specific goes back to the pool as
  system code;
- every table is either a tenant table under row-level security, or on an
  explicit list of shared ones.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.seed import seed_admin
from app.solve.service import enqueue_run
from app.worker import work_once
from tests.test_quadratic import empty_queue  # noqa: F401
from tests.test_v1_problem_run import db, make_domain, make_model_version, make_problem  # noqa: F401

PASSWORD = "tenant-b-password"

IR = {
    "version": 1,
    "sets": [],
    "parameters": {},
    "variables": {"x": {"index": [], "domain": "binary"}},
    "constraints": [],
    "objective": {"sense": "maximize", "terms": [{"id": "o", "weight": 1, "expression": {"var": "x", "index": []}}]},
}


def _login(username: str, password: str) -> dict:
    response = TestClient(app).post("/api/auth/login", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def tenants(db):
    """A (the seed organization) with a queued run; B with an administrator."""
    seed_admin(db)
    suffix = uuid.uuid4().hex[:8]
    org_b = db.execute(
        text(
            "INSERT INTO iam.organization (id, code, name) VALUES (gen_random_uuid(), :c, 'Tenant B') RETURNING id"
        ),
        {"c": f"tenant-b-{suffix}"},
    ).scalar_one()
    user_b = db.execute(
        text(
            "INSERT INTO iam.user_account (id, organization_id, username, hashed_password)"
            " VALUES (gen_random_uuid(), :o, :u, :p) RETURNING id"
        ),
        {"o": org_b, "u": f"admin-b-{suffix}", "p": hash_password(PASSWORD)},
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO iam.user_role (id, user_id, role_id)"
            " SELECT gen_random_uuid(), :u, id FROM iam.role WHERE name = 'Admin'"
        ),
        {"u": user_b},
    )
    db.commit()

    domain_a = make_domain(db, f"shared-name-{suffix}")
    problem_a = make_problem(db, domain_a)
    version_a = make_model_version(db, problem_a, IR)
    scenario_a = db.execute(
        text("INSERT INTO scenario (problem_id, model_version_id, name) VALUES (:p, :v, 'a') RETURNING id"),
        {"p": problem_a, "v": version_a},
    ).scalar_one()
    db.commit()
    run_a = enqueue_run(db, scenario_a, time_limit=5.0)

    settings = get_settings()
    yield {
        "a": _login(settings.admin_username, settings.admin_password),
        "b": _login(f"admin-b-{suffix}", PASSWORD),
        "org_b": org_b,
        "domain_a": domain_a,
        "domain_a_name": f"shared-name-{suffix}",
        "problem_a": problem_a,
        "version_a": version_a,
        "scenario_a": scenario_a,
        "run_a": run_a,
    }

    db.rollback()
    db.execute(text("DELETE FROM run"))
    db.execute(text("DELETE FROM domain WHERE organization_id = :o OR id = :d"), {"o": org_b, "d": domain_a})
    db.execute(text("DELETE FROM iam.user_role WHERE user_id = :u"), {"u": user_b})
    db.execute(text("DELETE FROM iam.user_account WHERE id = :u"), {"u": user_b})
    db.execute(text("DELETE FROM setting WHERE organization_id = :o"), {"o": org_b})
    db.execute(text("DELETE FROM iam.usage_month WHERE organization_id = :o"), {"o": org_b})
    db.execute(text("DELETE FROM iam.quota WHERE organization_id = :o"), {"o": org_b})
    db.execute(text("DELETE FROM iam.rate_bucket"))
    db.execute(text("DELETE FROM iam.organization WHERE id = :o"), {"o": org_b})
    db.commit()


# -- D1: runs --------------------------------------------------------------------


def test_another_organizations_runs_are_not_listed(tenants):
    client = TestClient(app)

    mine = client.get("/api/v1/runs", headers=tenants["a"]).json()
    theirs = client.get("/api/v1/runs", headers=tenants["b"]).json()

    assert tenants["run_a"] in [run["id"] for run in mine["items"]]
    assert theirs == {"items": [], "total": 0}


def test_another_organizations_run_is_not_found_and_cannot_be_cancelled(tenants, db):
    client = TestClient(app)
    run_a = tenants["run_a"]

    assert client.get(f"/api/v1/runs/{run_a}", headers=tenants["b"]).status_code == 404
    assert client.post(f"/api/v1/runs/{run_a}/cancel", headers=tenants["b"]).status_code == 404

    status, asked = db.execute(
        text("SELECT status, cancel_requested FROM run WHERE id = :r"), {"r": run_a}
    ).one()
    assert (status, asked) == ("queued", False)


# -- everything else below a domain --------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/domain/{domain_a}",
        "/api/problem/{problem_a}",
        "/api/v1/versions/{version_a}",
        "/api/v1/scenarios/{scenario_a}",
    ],
)
def test_another_organizations_rows_are_not_found_by_id(tenants, path):
    url = path.format(**tenants)
    assert TestClient(app).get(url, headers=tenants["a"]).status_code == 200
    assert TestClient(app).get(url, headers=tenants["b"]).status_code == 404


def test_another_organizations_domains_are_not_listed(tenants):
    items = TestClient(app).get("/api/domain/", headers=tenants["b"]).json()
    rows = items["items"] if isinstance(items, dict) else items
    assert tenants["domain_a"] not in [row["id"] for row in rows]


def test_two_organizations_may_use_the_same_domain_name(tenants):
    response = TestClient(app).post(
        "/api/domain/", json={"name": tenants["domain_a_name"]}, headers=tenants["b"]
    )
    assert response.status_code == 201, response.text


def test_a_row_cannot_point_at_another_organizations_parent(tenants, db):
    """Postgres checks foreign keys without row-level security, so this is
    the trigger's refusal: B's problem in A's domain is refused exactly as
    one in a domain that does not exist would be."""
    client = TestClient(app)
    domain_b = client.post("/api/domain/", json={"name": "b-domain"}, headers=tenants["b"]).json()["id"]
    problem_b = client.post(
        "/api/problem/", json={"domain_id": domain_b, "name": "b-problem"}, headers=tenants["b"]
    )
    assert problem_b.status_code == 201, problem_b.text

    stolen = client.post(
        "/api/problem/", json={"domain_id": tenants["domain_a"], "name": "in-a"}, headers=tenants["b"]
    )
    assert stolen.status_code == 409, stolen.text
    count = db.execute(
        text("SELECT count(*) FROM problem WHERE domain_id = :d AND name = 'in-a'"), {"d": tenants["domain_a"]}
    ).scalar_one()
    assert count == 0


def test_rows_created_by_a_tenant_belong_to_it(tenants, db):
    client = TestClient(app)
    domain_b = client.post("/api/domain/", json={"name": "owned"}, headers=tenants["b"]).json()["id"]
    client.post("/api/problem/", json={"domain_id": domain_b, "name": "p"}, headers=tenants["b"])

    orgs = db.execute(
        text(
            "SELECT d.organization_id, p.organization_id FROM domain d JOIN problem p ON p.domain_id = d.id"
            " WHERE d.id = :d"
        ),
        {"d": domain_b},
    ).one()
    assert orgs == (tenants["org_b"], tenants["org_b"])


# -- what everyone shares ------------------------------------------------------------


def test_only_an_operator_changes_platform_settings(tenants):
    client = TestClient(app)
    body = {"scope": "platform", "scope_id": None, "key": "solve.time_limit_s", "value": 12}

    refused = client.put("/api/v1/settings", json=body, headers=tenants["b"])
    unset = client.put("/api/v1/settings", json={**body, "value": None}, headers=tenants["b"])

    assert refused.status_code == 403, refused.text
    assert "operator" in refused.json()["detail"]
    assert unset.status_code == 403


def test_a_tenant_sets_its_own_domain_settings(tenants):
    client = TestClient(app)
    domain_b = client.post("/api/domain/", json={"name": "configured"}, headers=tenants["b"]).json()["id"]
    response = client.put(
        "/api/v1/settings",
        json={"scope": "domain", "scope_id": domain_b, "key": "solve.time_limit_s", "value": 12},
        headers=tenants["b"],
    )
    assert response.status_code == 200, response.text

    other = client.put(
        "/api/v1/settings",
        json={"scope": "domain", "scope_id": tenants["domain_a"], "key": "solve.time_limit_s", "value": 12},
        headers=tenants["b"],
    )
    assert other.status_code == 422, other.text


def test_only_an_operator_changes_roles(tenants):
    code = f"sneaky-{uuid.uuid4().hex[:6]}"
    response = TestClient(app).post("/api/iam/role/", json={"code": code, "name": code}, headers=tenants["b"])
    assert response.status_code == 403, response.text


def test_a_tenant_sees_only_its_own_people(tenants):
    users = TestClient(app).get("/api/iam/user_account/", headers=tenants["b"]).json()
    rows = users["items"] if isinstance(users, dict) else users
    assert {row["organization_id"] for row in rows} == {str(tenants["org_b"])}


# -- the worker serves everyone --------------------------------------------------------


def test_the_worker_solves_a_tenants_run_and_the_answer_is_the_tenants(tenants, db):
    client = TestClient(app)
    headers = tenants["b"]
    domain_b = client.post("/api/domain/", json={"name": "solving"}, headers=headers).json()["id"]
    problem_b = client.post("/api/problem/", json={"domain_id": domain_b, "name": "p"}, headers=headers).json()["id"]
    version_b = client.post(f"/api/v1/problems/{problem_b}/versions", json={"ir": IR}, headers=headers)
    assert version_b.status_code == 201, version_b.text
    scenario_b = client.post(
        "/api/v1/scenarios",
        json={"problem_id": problem_b, "model_version_id": version_b.json()["id"], "name": "s"},
        headers=headers,
    ).json()["id"]
    run_b = client.post(f"/api/v1/scenarios/{scenario_b}/runs", json={}, headers=headers)
    assert run_b.status_code == 201, run_b.text

    # The queue is shared: A's queued run goes first, then B's.
    work_once(db)
    work_once(db)

    body = client.get(f"/api/v1/runs/{run_b.json()['id']}", headers=headers).json()
    assert body["status"] == "optimal"
    orgs = db.execute(
        text("SELECT DISTINCT organization_id FROM solution WHERE run_id = :r"), {"r": run_b.json()["id"]}
    ).scalars().all()
    assert orgs == [tenants["org_b"]]
    assert client.get(f"/api/v1/runs/{run_b.json()['id']}", headers=tenants["a"]).status_code == 404


# -- connection hygiene -------------------------------------------------------------------


def test_a_pooled_connection_forgets_the_tenant(tenants):
    TestClient(app).get("/api/v1/runs", headers=tenants["b"])

    session = SessionLocal()
    try:
        role, org = session.execute(text("SELECT current_user, current_setting('app.org_id', true)")).one()
        assert role != "solver_app"
        assert not org
    finally:
        session.close()


# -- the invariant ---------------------------------------------------------------------

# Shared by every organization, or not the product's at all. Anything else in
# `public` must be a tenant table.
# `solver_conformance` (0072): an added solver is installed for every organization, and only an
# operator runs the kit on it -- a platform fact, like a bench result.
SHARED = {"template", "setting_key", "setting", "alembic_version", "bench_result", "solver_conformance"}


def test_every_table_is_a_tenant_table_or_explicitly_shared(db):
    tables = db.execute(
        text("SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public'")
    ).all()
    tenant = {name: rls for name, rls in tables if name not in SHARED}
    assert tenant, "no tenant tables found"
    for name, rls in tenant.items():
        assert rls, f"{name} has no row-level security"
        column = db.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = :t AND column_name = 'organization_id'"
            ),
            {"t": name},
        ).scalar_one_or_none()
        assert column == "NO", f"{name} has no NOT NULL organization_id"
        policies = db.execute(
            text("SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = :t"), {"t": name}
        ).scalar_one()
        assert policies, f"{name} has no policy"
