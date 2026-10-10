"""Point the test run at an isolated `<db>_test` database, **drop and
recreate it from scratch**, and migrate it to head -- all *before* any test
(or fixture) touches `app`.

Why this runs at import time rather than in a (even session-scoped,
autouse) fixture: `app.core.config.get_settings()` is `@lru_cache`d, and
`app.core.db` calls it at *module import* time (`settings =
get_settings()`, then `engine = create_engine(settings.database_url)`).
The first import of anything under `app` anywhere in the process freezes
which database every later `get_settings()`/`SessionLocal`/`engine` call
uses for the rest of that process -- a fixture runs too late to change
that, because by the time fixtures execute, the test modules that
reference them (and therefore `app...`) have already been imported.

pytest imports every `conftest.py` before it imports any test module, so
as long as this file rewrites `os.environ["DATABASE_URL"]` to the test
database *before* it (directly or via `alembic.command.upgrade`, which
runs `alembic/env.py` and that in turn imports `app.core.config` /
`app.core.db` / `app.models`) causes the first `app` import, every test
module's own `from app... import ...` picks up the test database.

This also means the app's own database is never touched by the test
suite: `domain.entity` row counts (and everything else) in the database
the running stack's admin UI and `/graph` demo page read stay exactly as
they were before `pytest` ran.

Why drop-and-recreate, not just migrate-to-head against whatever is
already there: several tests commit real rows through HTTP POSTs (the app
commits inside the request, so a test-side `db.rollback()` can't undo it),
and at least one test's correctness silently depends on the table being
small (`test_list_order_by` filters/orders a table with a default
`limit=50` -- once enough leftover rows from *other* runs accumulated, the
current run's own rows got paged off the end and the test failed for a
reason with nothing to do with whatever change was actually being tested).
Per-test teardown narrows this but doesn't close it (a crashed run, a
`Ctrl-C`, or simply a test someone forgets to clean up still leaks), so
each session instead starts from zero rows on a freshly migrated schema --
accumulation across runs becomes structurally impossible rather than
merely discouraged.

The drop is guarded by an explicit check that the target name actually
ends in `_test` (see `_drop_database_if_exists` below): this is what makes
it safe to point `DROP DATABASE` at a name derived from `DATABASE_URL`/
`TEST_DATABASE_URL` at all. If that check ever fails here, the right
outcome is a crashed test session, not a dropped `solver` database.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg2
from alembic import command
from alembic.config import Config

# Matches .env.example; only used if DATABASE_URL isn't in the environment
# at all (docker-compose always sets it for the backend service).
_DEFAULT_DATABASE_URL = "postgresql+psycopg2://solver:change-me@postgres:5432/solver"


def _database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def _with_database_name(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def _ensure_database_exists(maintenance_url: str, database: str) -> None:
    # psycopg2 doesn't understand SQLAlchemy's "+psycopg2" driver suffix.
    dsn = maintenance_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = True  # CREATE DATABASE cannot run inside a transaction
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{database}"')
    finally:
        conn.close()


def _terminate_other_connections(maintenance_url: str, database: str) -> None:
    """Terminate any other backend connected to `database`, so the DROP
    DATABASE below doesn't fail with "database is being accessed by other
    users" -- e.g. a previous test run that crashed mid-session, or a psql
    session left open against `solver_test` while debugging."""
    dsn = maintenance_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                " WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
    finally:
        conn.close()


def _drop_database_if_exists(maintenance_url: str, database: str) -> None:
    """Drop `database` so this session starts from zero rows on a schema
    migrated to head -- see the module docstring for why per-test teardown
    alone isn't enough.

    The name check below is the entire safety mechanism for this being a
    destructive operation driven by a computed name: it makes it
    impossible for this function to ever drop anything that isn't a
    `..._test` database, regardless of how `DATABASE_URL`/
    `TEST_DATABASE_URL` end up configured. The app's own database (e.g.
    `solver`) can never satisfy it.
    """
    # Deliberately a raise and not an `assert`: assertions are stripped
    # under `python -O`/`PYTHONOPTIMIZE`, and a guard whose entire job is
    # to stand between this line and `DROP DATABASE solver` must not be
    # removable by an interpreter flag. `database` is also checked for
    # emptiness so a URL we failed to parse can't slip through.
    if not database or not database.endswith("_test"):
        raise RuntimeError(
            f"refusing to drop database {database!r}: it does not end in "
            "'_test', which is the only thing standing between this and "
            "dropping the app's own database"
        )
    _terminate_other_connections(maintenance_url, database)
    dsn = maintenance_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = True  # DROP DATABASE cannot run inside a transaction
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{database}"')
    finally:
        conn.close()


_app_database_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
_default_test_url = _with_database_name(
    _app_database_url, f"{_database_name(_app_database_url) or 'solver'}_test"
)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", _default_test_url)
_TEST_DATABASE_NAME = _database_name(TEST_DATABASE_URL)

_maintenance_url = _with_database_name(TEST_DATABASE_URL, "postgres")
_drop_database_if_exists(_maintenance_url, _TEST_DATABASE_NAME)
_ensure_database_exists(_maintenance_url, _TEST_DATABASE_NAME)

# Must happen before the alembic upgrade below, since running migrations
# imports app.core.config/app.core.db/app.models (see module docstring).
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# alembic/env.py prefers MIGRATION_DATABASE_URL, which compose sets to the
# live owner's URL; left in place, the upgrade below would migrate the live
# database and leave the test one empty.
os.environ.pop("MIGRATION_DATABASE_URL", None)
# The machine's own solve limits (compose reads them from .env for the live workers) are not the suite's: with
# SOLVE_SHORT_SHARE=0.25 set there, a run asked for 8 threads was given 2, a portfolio never raced, and the
# host's capacity did not equal the one a test spelled out (10 October 2026). Tests that mean a limit set it.
for _name in ("SOLVE_HOST_WORKERS", "SOLVE_HOST_MEMORY_MB", "SOLVE_WORKER_CPUS", "SOLVE_WORKER_MEMORY", "SOLVE_WORKERS",
              "SOLVE_SHORT_SHARE", "SOLVE_SHORT_SECONDS", "SOLVE_CHECK_SHARE", "SOLVE_LICENSE_SEATS", "SOLVE_MEMORY_MB"):
    os.environ.pop(_name, None)
# ClickHouse too: the suite writes `analytics_test`, never the live
# `analytics` (app.analytics, app.clickhouse_schema).
os.environ["CLICKHOUSE_DB"] = os.environ.get("TEST_CLICKHOUSE_DB", "analytics_test")
try:
    import clickhouse_connect

    _ch = clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
    )
    _ch.command(f"DROP DATABASE IF EXISTS {os.environ['CLICKHOUSE_DB']}")
    _ch.command(f"CREATE DATABASE {os.environ['CLICKHOUSE_DB']}")
except Exception:  # pragma: no cover -- tests that need ClickHouse will say so
    pass

_backend_dir = Path(__file__).resolve().parent.parent
_alembic_ini = _backend_dir / "alembic.ini"
_alembic_cfg = Config(str(_alembic_ini))
# alembic.ini's `script_location = alembic` is relative to the *current
# working directory* at run time (alembic resolves it with os.path.abspath,
# not relative to the ini file) -- fine when pytest is run from
# backend/(inside the container that's /app), but not guaranteed in
# general, so pin it explicitly relative to this conftest's location.
_alembic_cfg.set_main_option("script_location", str(_backend_dir / "alembic"))
command.upgrade(_alembic_cfg, "head")

# The seed organization and admin, as `lifespan` creates them at start-up.
# Since migration 0032 every row belongs to an organization, and a row made
# by system code with none named gets the seed one -- so a test file that
# creates a domain without ever signing in needs it to exist, whether that
# file runs in the whole suite or on its own.
from app.core.db import SessionLocal  # noqa: E402
from app.seed import seed_admin  # noqa: E402

_session = SessionLocal()
try:
    seed_admin(_session)
finally:
    _session.close()


import pytest  # noqa: E402


@pytest.fixture
def steps_first():
    """`solve.probe_first` off by default for the test: a test that checks what a step before the solve did
    needs the step to run, not a quick solve that settles the model first."""
    from sqlalchemy import text

    session = SessionLocal()
    try:
        session.execute(text("UPDATE setting_key SET default_value = CAST('false' AS jsonb) WHERE key = 'solve.probe_first'"))
        session.commit()
        yield
    finally:
        session.execute(text("UPDATE setting_key SET default_value = CAST('true' AS jsonb) WHERE key = 'solve.probe_first'"))
        session.commit()
        session.close()
