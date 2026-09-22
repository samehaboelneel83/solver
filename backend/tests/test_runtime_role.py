"""The role the running app logs in as (migration 0037).

What it may do is asserted by acting as it: `SET ROLE solver_runtime` from
the test's owner connection puts exactly its privileges -- and its
BYPASSRLS, which follows the current role -- in effect. The tests never
give it a password: roles are cluster-wide, and the live database shares
this cluster.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.db import engine

ROLE = "solver_runtime"


@pytest.fixture
def as_runtime():
    """A connection acting as `solver_runtime`, in a transaction that is
    rolled back whatever the test did."""
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text(f"SET ROLE {ROLE}"))
        try:
            yield connection
        finally:
            transaction.rollback()


def _refused(connection, statement: str) -> None:
    """Run `statement` under a savepoint and assert Postgres refused it."""
    savepoint = connection.begin_nested()
    with pytest.raises(ProgrammingError):
        connection.execute(text(statement))
    savepoint.rollback()


def test_the_role_is_not_a_superuser_and_owns_nothing():
    with engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls"
                "  FROM pg_roles WHERE rolname = :r"
            ),
            {"r": ROLE},
        ).mappings().one()
        owned = connection.execute(
            text(
                "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner"
                " WHERE r.rolname = :r"
            ),
            {"r": ROLE},
        ).scalar_one()
    assert not role["rolsuper"]
    assert not role["rolcreaterole"]
    assert not role["rolcreatedb"]
    assert not role["rolreplication"]
    # System code sees every tenant by design (0032); requests switch to
    # solver_app, which does not bypass.
    assert role["rolbypassrls"]
    assert owned == 0


def test_every_product_table_is_readable_and_writable():
    """A table the app cannot write would fail only when that code path
    ran. `alembic_version` is the one exception, on purpose."""
    with engine.connect() as connection:
        missing = connection.execute(
            text(
                "SELECT n.nspname || '.' || c.relname"
                "  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE c.relkind IN ('r', 'p') AND n.nspname IN ('public', 'iam')"
                "   AND c.relname <> 'alembic_version'"
                "   AND NOT (has_table_privilege(:r, c.oid, 'SELECT')"
                "        AND has_table_privilege(:r, c.oid, 'INSERT')"
                "        AND has_table_privilege(:r, c.oid, 'UPDATE')"
                "        AND has_table_privilege(:r, c.oid, 'DELETE'))"
            ),
            {"r": ROLE},
        ).scalars().all()
        version = connection.execute(
            text("SELECT has_table_privilege(:r, 'public.alembic_version', 'SELECT')"),
            {"r": ROLE},
        ).scalar_one()
    assert missing == []
    assert version is False


def test_it_writes_rows_and_draws_ids(as_runtime):
    domain = as_runtime.execute(
        text("INSERT INTO domain (name) VALUES (:n) RETURNING id"),
        {"n": f"runtime-{uuid.uuid4().hex[:8]}"},
    ).scalar_one()
    assert as_runtime.execute(
        text("SELECT count(*) FROM domain WHERE id = :d"), {"d": domain}
    ).scalar_one() == 1


def test_it_cannot_change_the_schema(as_runtime):
    _refused(as_runtime, "CREATE TABLE public.injected (x int)")
    _refused(as_runtime, "CREATE TABLE iam.injected (x int)")
    _refused(as_runtime, "ALTER TABLE run ADD COLUMN injected int")
    _refused(as_runtime, "DROP TABLE run_event")


def test_it_cannot_switch_tenancy_off(as_runtime):
    """What a superuser could do and this role must not: the policies and
    the triggers that enforce tenancy stay on."""
    _refused(as_runtime, "ALTER TABLE domain DISABLE ROW LEVEL SECURITY")
    _refused(as_runtime, "DROP POLICY tenant_isolation ON domain")
    _refused(as_runtime, "ALTER TABLE domain DISABLE TRIGGER ALL")
    _refused(as_runtime, "CREATE ROLE injected SUPERUSER")
    _refused(as_runtime, "SELECT pg_read_file('/etc/passwd')")


def test_a_request_under_it_still_sees_only_its_tenant(as_runtime):
    """Logging in as solver_runtime does not weaken 0032: after `SET ROLE
    solver_app` the policies apply to the current role, and an organization
    with no rows sees none."""
    as_runtime.execute(
        text("INSERT INTO domain (name) VALUES (:n)"),
        {"n": f"runtime-{uuid.uuid4().hex[:8]}"},
    )
    assert as_runtime.execute(text("SELECT count(*) FROM domain")).scalar_one() > 0

    as_runtime.execute(text("SET ROLE solver_app"))
    as_runtime.execute(
        text("SELECT set_config('app.org_id', :o, true)"), {"o": str(uuid.uuid4())}
    )
    assert as_runtime.execute(text("SELECT count(*) FROM domain")).scalar_one() == 0
    assert as_runtime.execute(text("SELECT count(*) FROM run")).scalar_one() == 0


def test_the_runtime_url_keeps_everything_but_who_logs_in():
    from app.runtime_role import runtime_url

    url = runtime_url("postgresql+psycopg2://owner:s3cret@postgres:5432/solver", "Ab-_9x")
    assert url == "postgresql+psycopg2://solver_runtime:Ab-_9x@postgres:5432/solver"
