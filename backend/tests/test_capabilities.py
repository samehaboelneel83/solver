"""Task 4: generic-CRUD registry narrowing, capability flags, bigint keys.

Covers the three things `build_crud_router`/`register_table` gained when the
generic factory was narrowed to schema v1's flat tables (`domain`,
`template`, `problem`) alongside the four untouched `iam` tables:

- the registry's exact membership (no stray table, none of IMMUTABLE_TABLES),
- the `creatable`/`updatable`/`deletable` flags, both as reported by
  `/api/meta/schema` and as route suppression on the router itself, and
- the per-model path-param type (bigint tables take an int `item_id`,
  `iam` tables keep their UUID one).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.crud.factory import build_crud_router
from app.crud.registry import TABLE_REGISTRY
from app.main import app
from app.models import IMMUTABLE_TABLES
from app.models.v1_domain import Domain
from app.schemas.generate import make_crud_schemas
from app.seed import seed_admin


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    db = SessionLocal()
    seed_admin(db)
    db.close()


@pytest.fixture
def auth_headers():
    settings = get_settings()
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_registry_is_exactly_the_seven_flat_and_iam_tables():
    """The generic CRUD registry must contain exactly the four `iam` tables
    plus the three flat v1 tables -- no stray registration, and (see next
    test) none of the four immutable tables."""
    assert {(m.schema, m.table) for m in TABLE_REGISTRY} == {
        ("iam", "organization"),
        ("iam", "user_account"),
        ("iam", "role"),
        ("iam", "user_role"),
        ("public", "domain"),
        ("public", "template"),
        ("public", "problem"),
    }


def test_immutable_tables_never_appear_in_the_registry():
    """model_version, dataset, solution and constraint_result are frozen by
    the `forbid_update()` trigger. `model_version` gets Task 9's
    purpose-built router and the other three get none at all -- none of the
    four is ever driven through the generic factory."""
    registered = {m.table for m in TABLE_REGISTRY}
    assert registered.isdisjoint(IMMUTABLE_TABLES)


def test_meta_schema_reports_capability_flags_defaulting_true(auth_headers):
    client = TestClient(app)
    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200

    for table in response.json():
        assert table["creatable"] is True
        assert table["updatable"] is True
        assert table["deletable"] is True


def test_capability_flags_suppress_write_routes():
    """A router built with updatable=False, deletable=False exposes GET and
    POST but no PUT or DELETE. Asserted against the router's own route
    table, not a live request -- no currently registered table is
    read-only, so a request-level test would have nothing to exercise."""
    create_schema, update_schema, read_schema = make_crud_schemas(
        Domain, name="DomainCapabilityTest", readonly={"id"}, server_default={"created_at"}
    )

    r = build_crud_router(
        model=Domain,
        create_schema=create_schema,
        update_schema=update_schema,
        read_schema=read_schema,
        schema_name="public",
        table_name="domain",
        updatable=False,
        deletable=False,
    )

    methods = {m for route in r.routes for m in route.methods}
    assert methods == {"GET", "POST"}


def test_capability_flags_default_to_creatable_updatable_deletable():
    """With no flags passed, all four routes (list, get, create, update,
    delete) are present -- GET/POST/PUT/DELETE."""
    create_schema, update_schema, read_schema = make_crud_schemas(
        Domain, name="DomainCapabilityDefaultTest", readonly={"id"}, server_default={"created_at"}
    )

    r = build_crud_router(
        model=Domain,
        create_schema=create_schema,
        update_schema=update_schema,
        read_schema=read_schema,
        schema_name="public",
        table_name="domain",
    )

    methods = {m for route in r.routes for m in route.methods}
    assert methods == {"GET", "POST", "PUT", "DELETE"}


def test_get_domain_by_int_id_succeeds_and_non_int_returns_422(auth_headers):
    """`domain` is a schema v1 flat table with a bigint surrogate key, so
    its generic single-item route must accept an int id (unlike the
    UUID-keyed `iam` tables) and reject a non-integer one with 422 rather
    than a 404 (which would mean it was silently coerced to a string)."""
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    create_response = client.post(
        "/api/domain/",
        json={"name": f"cap-test-domain-{suffix}"},
        headers=auth_headers,
    )
    assert create_response.status_code == 201, create_response.text
    domain_id = create_response.json()["id"]
    assert isinstance(domain_id, int)

    try:
        get_response = client.get(f"/api/domain/{domain_id}", headers=auth_headers)
        assert get_response.status_code == 200
        assert get_response.json()["id"] == domain_id

        bad_response = client.get("/api/domain/not-an-int", headers=auth_headers)
        assert bad_response.status_code == 422
    finally:
        # The row was created through a real HTTP POST (a separate,
        # already-committed session), so a local db.rollback() can't undo
        # it -- delete it through the API instead, or it accumulates in
        # the shared solver_test database across runs.
        client.delete(f"/api/domain/{domain_id}", headers=auth_headers)


def test_options_route_sits_at_the_collapsed_public_prefix_and_resolves_bigint_ids(auth_headers):
    """`options.py` mints one FK-dropdown route per TABLE_REGISTRY entry.
    For a `schema_name="public"` table that must land at the same
    collapsed prefix as its CRUD sibling (`/api/domain/options`, not
    `/api/public/domain/options`), and `ids=` must parse as the table's
    real id type (bigint here) rather than assuming UUID for every table."""
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    create_response = client.post(
        "/api/domain/",
        json={"name": f"cap-test-options-domain-{suffix}"},
        headers=auth_headers,
    )
    assert create_response.status_code == 201, create_response.text
    domain_id = create_response.json()["id"]

    try:
        options_response = client.get(
            f"/api/domain/options?ids={domain_id}", headers=auth_headers
        )
        assert options_response.status_code == 200
        items = options_response.json()
        assert len(items) == 1
        assert items[0]["id"] == str(domain_id)

        bad_id_response = client.get(
            "/api/domain/options?ids=not-an-int", headers=auth_headers
        )
        assert bad_id_response.status_code == 422
    finally:
        client.delete(f"/api/domain/{domain_id}", headers=auth_headers)


def test_options_route_for_iam_table_still_resolves_uuid_ids(auth_headers):
    """Regression guard for the fix above: deriving `ids=`'s cast from each
    table's own primary-key type must not break the untouched, UUID-keyed
    `iam` tables -- a blanket int cast here would be exactly as wrong as a
    blanket UUID cast was."""
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    create_response = client.post(
        "/api/iam/role/",
        json={"code": f"opt-cap-{suffix}", "name": "Options Capability Test"},
        headers=auth_headers,
    )
    assert create_response.status_code == 201, create_response.text
    role_id = create_response.json()["id"]

    try:
        options_response = client.get(
            f"/api/iam/role/options?ids={role_id}", headers=auth_headers
        )
        assert options_response.status_code == 200
        items = options_response.json()
        assert len(items) == 1
        assert items[0]["id"] == role_id

        bad_id_response = client.get("/api/iam/role/options?ids=not-a-uuid", headers=auth_headers)
        assert bad_id_response.status_code == 422
    finally:
        # Same shape as the domain test above: created via a real HTTP
        # POST (a separate, already-committed session), so it must be
        # deleted through the API rather than relied on to roll back.
        client.delete(f"/api/iam/role/{role_id}", headers=auth_headers)
