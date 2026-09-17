"""Point the test run at an isolated `<db>_test` database and migrate it to
head, *before* any test (or fixture) touches `app`.

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


_app_database_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
_default_test_url = _with_database_name(
    _app_database_url, f"{_database_name(_app_database_url) or 'solver'}_test"
)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", _default_test_url)

_maintenance_url = _with_database_name(TEST_DATABASE_URL, "postgres")
_ensure_database_exists(_maintenance_url, _database_name(TEST_DATABASE_URL))

# Must happen before the alembic upgrade below, since running migrations
# imports app.core.config/app.core.db/app.models (see module docstring).
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

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
