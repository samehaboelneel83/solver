# Problem-Solver Platform Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a working, dockerized skeleton of the problem-solver platform: PostgreSQL + ClickHouse + FastAPI + React, with generic CRUD over the full domain/problem/iam schema (31 tables) and a metadata-driven admin UI.

**Architecture:** Four Docker services (postgres, clickhouse, backend, frontend) on one internal network. FastAPI owns all database access — the browser only ever talks to FastAPI. Backend uses a generic CRUD router factory driven by SQLAlchemy models and Pydantic schemas derived from those models via a reusable generator, so wiring a table is a few lines, not a bespoke route file. Frontend fetches a `/api/meta/schema` endpoint at runtime and renders navigation, tables, and forms generically from it.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Pydantic v2, Alembic, `clickhouse-connect`, `python-jose`, `passlib[bcrypt]`, pytest + httpx; Node 20+, Vite, TypeScript, Tailwind CSS, shadcn/ui, React Router, TanStack Query, Vitest + React Testing Library; PostgreSQL 16, ClickHouse (`clickhouse/clickhouse-server` latest stable); Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-16-platform-skeleton-design.md`

## Global Constraints

- Postgres tables use UUID primary keys (spec §4).
- Three Postgres schemas: `iam`, `domain`, `problem` (spec §4).
- List endpoints return `{items: [...], total: <int>}`, never a bare array (spec §6.2).
- Auth is JWT with one seeded admin user; no per-endpoint RBAC enforcement this phase (spec §6.4, §8).
- The browser never receives database credentials or talks to Postgres/ClickHouse directly — only to the FastAPI backend (spec §3).
- All four services run via one `docker-compose.yml` on an internal network; `.env` holds secrets, `.env.example` is checked in (spec §3).
- ClickHouse analytics tables are created now but nothing writes real data into them this phase (spec §5, §8).
- No solver, no Solution schema, no enforced RBAC, no audit log, no visual builders this phase (spec §2, §8).

---

## Task 1: Docker Compose infra — Postgres + ClickHouse

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore`

**Interfaces:**
- Produces: a running Postgres reachable at `postgres:5432` (service name `postgres`) inside the `solver_net` network, database name `solver`, and a running ClickHouse reachable at `clickhouse:8123` (HTTP) / `clickhouse:9000` (native), database `analytics`. On the host, Postgres is published at `localhost:5544` (not the default 5432 — this machine already has another Postgres container bound to 5432), and ClickHouse at `localhost:8123`/`localhost:9000`. Later tasks depend on these service names and host ports.

- [ ] **Step 1: Write `.gitignore`**

```gitignore
.env
__pycache__/
*.pyc
.venv/
node_modules/
dist/
.pytest_cache/
```

- [ ] **Step 2: Write `.env.example`**

```dotenv
POSTGRES_USER=solver
POSTGRES_PASSWORD=change-me
POSTGRES_DB=solver
DATABASE_URL=postgresql+psycopg2://solver:change-me@postgres:5432/solver

CLICKHOUSE_DB=analytics
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=

JWT_SECRET=change-me-too
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me-admin
ADMIN_EMAIL=admin@example.com
```

- [ ] **Step 3: Write `docker-compose.yml` with the two database services**

```yaml
name: solver

networks:
  solver_net:
    driver: bridge

volumes:
  postgres_data:
  clickhouse_data:

services:
  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "5544:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - solver_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 10

  clickhouse:
    image: clickhouse/clickhouse-server:24.8
    restart: unless-stopped
    environment:
      CLICKHOUSE_DB: ${CLICKHOUSE_DB}
      CLICKHOUSE_USER: ${CLICKHOUSE_USER}
      CLICKHOUSE_PASSWORD: ${CLICKHOUSE_PASSWORD}
      CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: 1
    ports:
      - "8123:8123"
      - "9000:9000"
    volumes:
      - clickhouse_data:/var/lib/clickhouse
    networks:
      - solver_net
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8123/ping"]
      interval: 5s
      timeout: 5s
      retries: 10
```

- [ ] **Step 4: Verify both services come up healthy**

Run:
```bash
cp .env.example .env
docker compose up -d postgres clickhouse
docker compose ps
```
Expected: both `postgres` and `clickhouse` show `healthy` status within ~30s (`docker compose ps` shows `(healthy)`).

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example .gitignore
git commit -m "infra: add Postgres and ClickHouse to docker-compose"
```

---

## Task 2: Backend skeleton — FastAPI app, config, DB clients, health check

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/Dockerfile`
- Create: `backend/app/__init__.py`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/db.py`
- Create: `backend/app/main.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/health.py`
- Test: `backend/tests/test_health.py`
- Modify: `docker-compose.yml` (add `backend` service)

**Interfaces:**
- Consumes: Postgres/ClickHouse service names from Task 1 (`postgres:5432`, `clickhouse:8123`).
- Produces: `app.core.config.get_settings() -> Settings` (cached), `app.core.db.engine`, `app.core.db.SessionLocal`, `app.core.db.Base` (SQLAlchemy `DeclarativeBase`), `app.core.db.get_db()` (FastAPI dependency yielding a `Session`), `app.core.db.get_clickhouse_client()` (returns a `clickhouse_connect` client). Every later backend task imports these. `GET /api/health` returns `{"postgres": "ok"|"error", "clickhouse": "ok"|"error"}`.

- [ ] **Step 1: Write `backend/requirements.txt`**

```text
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
psycopg2-binary==2.9.9
alembic==1.13.2
pydantic==2.9.2
pydantic-settings==2.5.2
clickhouse-connect==0.8.3
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9
pytest==8.3.3
httpx==0.27.2
```

- [ ] **Step 2: Write `backend/app/core/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    clickhouse_host: str = "clickhouse"
    clickhouse_port: int = 8123
    clickhouse_db: str = "analytics"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    admin_username: str = "admin"
    admin_password: str
    admin_email: str = "admin@example.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 3: Write `backend/app/core/db.py`**

```python
import clickhouse_connect
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_clickhouse_client():
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        database=settings.clickhouse_db,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
    )
```

- [ ] **Step 4: Write `backend/app/api/health.py`**

```python
from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import SessionLocal, get_clickhouse_client

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health() -> dict:
    result = {"postgres": "ok", "clickhouse": "ok"}

    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception:
        result["postgres"] = "error"

    try:
        client = get_clickhouse_client()
        client.command("SELECT 1")
    except Exception:
        result["clickhouse"] = "error"

    return result
```

- [ ] **Step 5: Write `backend/app/main.py`**

```python
from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(title="Problem Solver Platform API")

app.include_router(health_router)
```

- [ ] **Step 6: Write the failing test `backend/tests/test_health.py`**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_status_for_both_databases():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"postgres", "clickhouse"}
    assert body["postgres"] in {"ok", "error"}
    assert body["clickhouse"] in {"ok", "error"}
```

This test only checks shape (it works even before real DBs are reachable, since the endpoint catches connection errors); Step 9 verifies it reports `"ok"` against the real containers.

- [ ] **Step 7: Write `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 8: Add `backend` service to `docker-compose.yml`**

```yaml
  backend:
    build: ./backend
    restart: unless-stopped
    env_file: .env
    environment:
      DATABASE_URL: ${DATABASE_URL}
      CLICKHOUSE_HOST: clickhouse
    ports:
      - "8010:8000"
    depends_on:
      postgres:
        condition: service_healthy
      clickhouse:
        condition: service_healthy
    networks:
      - solver_net
```

- [ ] **Step 9: Run tests locally, then verify against real containers**

Run:
```bash
cd backend && pip install -r requirements.txt && pytest tests/test_health.py -v
```
Expected: PASS (shape check).

Then:
```bash
docker compose up -d --build backend
curl http://localhost:8010/api/health
```
Expected: `{"postgres":"ok","clickhouse":"ok"}`.

- [ ] **Step 10: Commit**

```bash
git add backend docker-compose.yml
git commit -m "feat: FastAPI skeleton with Postgres/ClickHouse health check"
```

---

## Task 3: Alembic setup + `iam` schema migration

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_iam_schema.py`
- Test: `backend/tests/test_migrations_iam.py`

**Interfaces:**
- Consumes: `app.core.db.Base`, `app.core.config.get_settings` (Task 2).
- Produces: Postgres schema `iam` with tables `organization`, `user_account`, `role`, `user_role` (columns as in spec §4.1, with one deliberate deviation: `user_role` gets a synthetic `id UUID PRIMARY KEY` plus `UNIQUE (user_id, role_id)` instead of the composite primary key the spec shows — every other table in the schema has a single-column UUID PK, and the generic CRUD factory built in Task 12 assumes one; a composite-PK join table would need bespoke routing that the platform's whole design is trying to avoid). Later tasks (4, 5, 6, 7, 10) each add one more Alembic revision chained after this one via `down_revision`.

- [ ] **Step 1: Write `backend/alembic.ini`**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 2: Write `backend/alembic/env.py`**

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.db import Base
import app.models  # noqa: F401  (ensures all models are imported before autogenerate)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Write `backend/alembic/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Create `backend/app/models/__init__.py` placeholder (populated by later tasks)**

```python
# Models are imported here as each schema group is implemented, so that
# Alembic's env.py (which imports this package) sees the full metadata.
```

- [ ] **Step 5: Write `backend/alembic/versions/0001_iam_schema.py`**

```python
"""iam schema: organization, user_account, role, user_role

Revision ID: 0001
Revises:
Create Date: 2026-09-16

"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS iam;

        CREATE TABLE iam.organization (
            id              UUID PRIMARY KEY,
            parent_id       UUID REFERENCES iam.organization(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            description     TEXT,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (code)
        );

        CREATE TABLE iam.user_account (
            id              UUID PRIMARY KEY,
            organization_id UUID REFERENCES iam.organization(id),
            username        VARCHAR(150) UNIQUE NOT NULL,
            display_name    VARCHAR(255),
            email           VARCHAR(255),
            hashed_password VARCHAR(255) NOT NULL,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE iam.role (
            id              UUID PRIMARY KEY,
            code            VARCHAR(100) UNIQUE NOT NULL,
            name            VARCHAR(255) NOT NULL
        );

        CREATE TABLE iam.user_role (
            id      UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES iam.user_account(id),
            role_id UUID NOT NULL REFERENCES iam.role(id),
            UNIQUE (user_id, role_id)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS iam.user_role;
        DROP TABLE IF EXISTS iam.role;
        DROP TABLE IF EXISTS iam.user_account;
        DROP TABLE IF EXISTS iam.organization;
        DROP SCHEMA IF EXISTS iam;
        """
    )
```

- [ ] **Step 6: Write the failing test `backend/tests/test_migrations_iam.py`**

```python
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_iam_tables_exist_after_migration():
    engine = create_engine(get_settings().database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="iam"))
    assert tables == {"organization", "user_account", "role", "user_role"}
```

Run: `cd backend && pytest tests/test_migrations_iam.py -v`
Expected: FAIL (schema `iam` does not exist yet — migration not applied).

- [ ] **Step 7: Apply the migration against the running Postgres container**

Run:
```bash
docker compose up -d postgres
cd backend
pip install -r requirements.txt
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver alembic upgrade head
```
(Use the same credentials as `.env`; connecting from the host uses `localhost`, not the service name `postgres`.)

- [ ] **Step 8: Run test again to verify it passes**

Run: `DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver pytest tests/test_migrations_iam.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/alembic.ini backend/alembic backend/app/models/__init__.py backend/tests/test_migrations_iam.py
git commit -m "feat: Alembic setup and iam schema migration"
```

---

## Task 4: `domain` schema migration — Group A (entity core + relationships)

**Files:**
- Create: `backend/alembic/versions/0002_domain_group_a.py`
- Test: `backend/tests/test_migrations_domain_a.py`

**Interfaces:**
- Consumes: `iam.organization` (Task 3, for FK).
- Produces: `domain.entity_type`, `domain.entity`, `domain.attribute_definition`, `domain.entity_attribute`, `domain.relationship_type`, `domain.relationship`. Task 5 chains after this one.

- [ ] **Step 1: Write the failing test `backend/tests/test_migrations_domain_a.py`**

```python
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_domain_group_a_tables_exist_after_migration():
    engine = create_engine(get_settings().database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="domain"))
    assert {
        "entity_type",
        "entity",
        "attribute_definition",
        "entity_attribute",
        "relationship_type",
        "relationship",
    }.issubset(tables)
```

Run: `cd backend && pytest tests/test_migrations_domain_a.py -v`
Expected: FAIL (schema `domain` does not exist yet).

- [ ] **Step 2: Write `backend/alembic/versions/0002_domain_group_a.py`**

```python
"""domain schema group A: entity_type, entity, attribute_definition,
entity_attribute, relationship_type, relationship

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-16

"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS domain;

        CREATE TABLE domain.entity_type (
            id              UUID PRIMARY KEY,
            organization_id UUID REFERENCES iam.organization(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            description     TEXT,
            parent_type_id  UUID REFERENCES domain.entity_type(id),
            is_abstract     BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, code)
        );

        CREATE TABLE domain.entity (
            id              UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES iam.organization(id),
            entity_type_id  UUID NOT NULL REFERENCES domain.entity_type(id),
            code            VARCHAR(150),
            name            VARCHAR(255),
            description     TEXT,
            valid_from      TIMESTAMPTZ,
            valid_to        TIMESTAMPTZ,
            status          VARCHAR(50),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, entity_type_id, code)
        );

        CREATE TABLE domain.attribute_definition (
            id              UUID PRIMARY KEY,
            entity_type_id  UUID NOT NULL REFERENCES domain.entity_type(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            data_type       VARCHAR(50) NOT NULL,
            is_required     BOOLEAN NOT NULL DEFAULT FALSE,
            is_multi_value  BOOLEAN NOT NULL DEFAULT FALSE,
            default_value   JSONB,
            validation_rule JSONB,
            UNIQUE (entity_type_id, code)
        );

        CREATE TABLE domain.entity_attribute (
            id                  UUID PRIMARY KEY,
            entity_id           UUID NOT NULL REFERENCES domain.entity(id),
            attribute_id        UUID NOT NULL REFERENCES domain.attribute_definition(id),
            value_string        TEXT,
            value_number        NUMERIC,
            value_boolean       BOOLEAN,
            value_date          DATE,
            value_datetime      TIMESTAMPTZ,
            value_json          JSONB,
            UNIQUE (entity_id, attribute_id)
        );

        CREATE TABLE domain.relationship_type (
            id                  UUID PRIMARY KEY,
            code                VARCHAR(100) UNIQUE NOT NULL,
            name                VARCHAR(255) NOT NULL,
            source_entity_type  UUID REFERENCES domain.entity_type(id),
            target_entity_type  UUID REFERENCES domain.entity_type(id),
            cardinality         VARCHAR(30),
            is_directed         BOOLEAN NOT NULL DEFAULT TRUE,
            metadata            JSONB
        );

        CREATE TABLE domain.relationship (
            id                   UUID PRIMARY KEY,
            relationship_type_id UUID NOT NULL REFERENCES domain.relationship_type(id),
            source_entity_id     UUID NOT NULL REFERENCES domain.entity(id),
            target_entity_id     UUID NOT NULL REFERENCES domain.entity(id),
            valid_from           TIMESTAMPTZ,
            valid_to             TIMESTAMPTZ,
            attributes           JSONB,
            UNIQUE (relationship_type_id, source_entity_id, target_entity_id)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS domain.relationship;
        DROP TABLE IF EXISTS domain.relationship_type;
        DROP TABLE IF EXISTS domain.entity_attribute;
        DROP TABLE IF EXISTS domain.attribute_definition;
        DROP TABLE IF EXISTS domain.entity;
        DROP TABLE IF EXISTS domain.entity_type;
        """
    )
```

- [ ] **Step 3: Apply migration and verify test passes**

Run:
```bash
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver alembic upgrade head
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver pytest tests/test_migrations_domain_a.py -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0002_domain_group_a.py backend/tests/test_migrations_domain_a.py
git commit -m "feat: domain schema migration group A (entity core + relationships)"
```

---

## Task 5: `domain` schema migration — Group B (hierarchy, roles, states)

**Files:**
- Create: `backend/alembic/versions/0003_domain_group_b.py`
- Test: `backend/tests/test_migrations_domain_b.py`

**Interfaces:**
- Consumes: `domain.entity_type`, `domain.entity` (Task 4).
- Produces: `domain.hierarchy`, `domain.hierarchy_node`, `domain.role_type`, `domain.entity_role`, `domain.state_type`, `domain.entity_state`. Task 6 chains after this one.

- [ ] **Step 1: Write the failing test `backend/tests/test_migrations_domain_b.py`**

```python
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_domain_group_b_tables_exist_after_migration():
    engine = create_engine(get_settings().database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="domain"))
    assert {
        "hierarchy",
        "hierarchy_node",
        "role_type",
        "entity_role",
        "state_type",
        "entity_state",
    }.issubset(tables)
```

Run: `cd backend && pytest tests/test_migrations_domain_b.py -v`
Expected: FAIL

- [ ] **Step 2: Write `backend/alembic/versions/0003_domain_group_b.py`**

```python
"""domain schema group B: hierarchy, hierarchy_node, role_type,
entity_role, state_type, entity_state

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-16

"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE domain.hierarchy (
            id              UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES iam.organization(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            entity_type_id  UUID REFERENCES domain.entity_type(id),
            description     TEXT
        );

        CREATE TABLE domain.hierarchy_node (
            id              UUID PRIMARY KEY,
            hierarchy_id    UUID NOT NULL REFERENCES domain.hierarchy(id),
            entity_id       UUID NOT NULL REFERENCES domain.entity(id),
            parent_node_id  UUID REFERENCES domain.hierarchy_node(id),
            level           INTEGER NOT NULL,
            sort_order      INTEGER,
            UNIQUE (hierarchy_id, entity_id)
        );

        CREATE TABLE domain.role_type (
            id              UUID PRIMARY KEY,
            code            VARCHAR(100) UNIQUE NOT NULL,
            name            VARCHAR(255) NOT NULL,
            description     TEXT
        );

        CREATE TABLE domain.entity_role (
            id              UUID PRIMARY KEY,
            entity_id       UUID NOT NULL REFERENCES domain.entity(id),
            role_type_id    UUID NOT NULL REFERENCES domain.role_type(id),
            valid_from      TIMESTAMPTZ,
            valid_to        TIMESTAMPTZ,
            attributes      JSONB
        );

        CREATE TABLE domain.state_type (
            id              UUID PRIMARY KEY,
            code            VARCHAR(100) UNIQUE NOT NULL,
            name            VARCHAR(255) NOT NULL,
            entity_type_id  UUID REFERENCES domain.entity_type(id)
        );

        CREATE TABLE domain.entity_state (
            id              UUID PRIMARY KEY,
            entity_id       UUID NOT NULL REFERENCES domain.entity(id),
            state_type_id   UUID NOT NULL REFERENCES domain.state_type(id),
            state_value     VARCHAR(100) NOT NULL,
            valid_from      TIMESTAMPTZ NOT NULL,
            valid_to        TIMESTAMPTZ
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS domain.entity_state;
        DROP TABLE IF EXISTS domain.state_type;
        DROP TABLE IF EXISTS domain.entity_role;
        DROP TABLE IF EXISTS domain.role_type;
        DROP TABLE IF EXISTS domain.hierarchy_node;
        DROP TABLE IF EXISTS domain.hierarchy;
        """
    )
```

- [ ] **Step 3: Apply migration and verify test passes**

Run:
```bash
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver alembic upgrade head
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver pytest tests/test_migrations_domain_b.py -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0003_domain_group_b.py backend/tests/test_migrations_domain_b.py
git commit -m "feat: domain schema migration group B (hierarchy, roles, states)"
```

---

## Task 6: `domain` schema migration — Group C (events, resources, time)

**Files:**
- Create: `backend/alembic/versions/0004_domain_group_c.py`
- Test: `backend/tests/test_migrations_domain_c.py`

**Interfaces:**
- Consumes: `domain.entity`, `iam.organization` (Tasks 3, 4).
- Produces: `domain.event_type`, `domain.event`, `domain.resource_type`, `domain.resource`, `domain.time_calendar`, `domain.time_period`. Task 7 chains after this one.

- [ ] **Step 1: Write the failing test `backend/tests/test_migrations_domain_c.py`**

```python
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_domain_group_c_tables_exist_after_migration():
    engine = create_engine(get_settings().database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="domain"))
    assert {
        "event_type",
        "event",
        "resource_type",
        "resource",
        "time_calendar",
        "time_period",
    }.issubset(tables)
```

Run: `cd backend && pytest tests/test_migrations_domain_c.py -v`
Expected: FAIL

- [ ] **Step 2: Write `backend/alembic/versions/0004_domain_group_c.py`**

```python
"""domain schema group C: event_type, event, resource_type, resource,
time_calendar, time_period

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-16

"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE domain.event_type (
            id              UUID PRIMARY KEY,
            code            VARCHAR(100) UNIQUE NOT NULL,
            name            VARCHAR(255) NOT NULL,
            description     TEXT
        );

        CREATE TABLE domain.event (
            id              UUID PRIMARY KEY,
            event_type_id   UUID NOT NULL REFERENCES domain.event_type(id),
            entity_id       UUID REFERENCES domain.entity(id),
            occurred_at     TIMESTAMPTZ NOT NULL,
            data            JSONB
        );

        CREATE TABLE domain.resource_type (
            id              UUID PRIMARY KEY,
            code            VARCHAR(100) UNIQUE NOT NULL,
            name            VARCHAR(255) NOT NULL,
            capacity_type   VARCHAR(50)
        );

        CREATE TABLE domain.resource (
            id                UUID PRIMARY KEY,
            resource_type_id UUID NOT NULL REFERENCES domain.resource_type(id),
            entity_id         UUID REFERENCES domain.entity(id),
            capacity          NUMERIC,
            unit              VARCHAR(50),
            availability_rule JSONB
        );

        CREATE TABLE domain.time_calendar (
            id              UUID PRIMARY KEY,
            organization_id UUID REFERENCES iam.organization(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            timezone        VARCHAR(100)
        );

        CREATE TABLE domain.time_period (
            id              UUID PRIMARY KEY,
            calendar_id     UUID NOT NULL REFERENCES domain.time_calendar(id),
            parent_id       UUID REFERENCES domain.time_period(id),
            name            VARCHAR(255),
            start_time      TIMESTAMPTZ NOT NULL,
            end_time        TIMESTAMPTZ NOT NULL,
            level           INTEGER,
            metadata        JSONB
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS domain.time_period;
        DROP TABLE IF EXISTS domain.time_calendar;
        DROP TABLE IF EXISTS domain.resource;
        DROP TABLE IF EXISTS domain.resource_type;
        DROP TABLE IF EXISTS domain.event;
        DROP TABLE IF EXISTS domain.event_type;
        """
    )
```

- [ ] **Step 3: Apply migration and verify test passes**

Run:
```bash
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver alembic upgrade head
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver pytest tests/test_migrations_domain_c.py -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0004_domain_group_c.py backend/tests/test_migrations_domain_c.py
git commit -m "feat: domain schema migration group C (events, resources, time)"
```

---

## Task 7: `problem` schema migration

**Files:**
- Create: `backend/alembic/versions/0005_problem_schema.py`
- Test: `backend/tests/test_migrations_problem.py`

**Interfaces:**
- Consumes: `iam.organization`, `iam.user_account`, `domain.hierarchy`, `domain.hierarchy_node`, `domain.entity` (Tasks 3-6).
- Produces: `problem.problem`, `problem.scenario`, `problem.variable_definition`, `problem.variable_dimension`, `problem.constraint_definition`, `problem.constraint_scope`, `problem.objective`, `problem.objective_component`, `problem.parameter`. Task 8 (ClickHouse) does not depend on this, but Tasks 16-17 (problem CRUD) do.

- [ ] **Step 1: Write the failing test `backend/tests/test_migrations_problem.py`**

```python
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_problem_tables_exist_after_migration():
    engine = create_engine(get_settings().database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="problem"))
    assert tables == {
        "problem",
        "scenario",
        "variable_definition",
        "variable_dimension",
        "constraint_definition",
        "constraint_scope",
        "objective",
        "objective_component",
        "parameter",
    }
```

Run: `cd backend && pytest tests/test_migrations_problem.py -v`
Expected: FAIL

- [ ] **Step 2: Write `backend/alembic/versions/0005_problem_schema.py`**

```python
"""problem schema: problem, scenario, variable_definition,
variable_dimension, constraint_definition, constraint_scope, objective,
objective_component, parameter

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-16

"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS problem;

        CREATE TABLE problem.problem (
            id              UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES iam.organization(id),
            code            VARCHAR(100) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            description     TEXT,
            problem_type    VARCHAR(100),
            version         INTEGER NOT NULL DEFAULT 1,
            status          VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
            created_by      UUID REFERENCES iam.user_account(id),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, code, version)
        );

        CREATE TABLE problem.scenario (
            id                  UUID PRIMARY KEY,
            problem_id          UUID NOT NULL REFERENCES problem.problem(id),
            code                VARCHAR(100) NOT NULL,
            name                VARCHAR(255) NOT NULL,
            description         TEXT,
            parent_scenario_id  UUID REFERENCES problem.scenario(id),
            parameters          JSONB,
            UNIQUE (problem_id, code)
        );

        CREATE TABLE problem.variable_definition (
            id                UUID PRIMARY KEY,
            problem_id        UUID NOT NULL REFERENCES problem.problem(id),
            code              VARCHAR(150) NOT NULL,
            name              VARCHAR(255) NOT NULL,
            variable_type     VARCHAR(50) NOT NULL,
            description       TEXT,
            domain_definition JSONB,
            UNIQUE (problem_id, code)
        );

        CREATE TABLE problem.variable_dimension (
            id              UUID PRIMARY KEY,
            variable_id     UUID NOT NULL REFERENCES problem.variable_definition(id),
            dimension_order INTEGER NOT NULL,
            dimension_type  VARCHAR(50) NOT NULL,
            domain_source   JSONB
        );

        CREATE TABLE problem.constraint_definition (
            id              UUID PRIMARY KEY,
            problem_id      UUID NOT NULL REFERENCES problem.problem(id),
            code            VARCHAR(150) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            constraint_type VARCHAR(100),
            expression      JSONB,
            severity        VARCHAR(30),
            is_hard         BOOLEAN NOT NULL DEFAULT TRUE,
            weight          NUMERIC,
            priority        INTEGER,
            description     TEXT,
            UNIQUE (problem_id, code)
        );

        CREATE TABLE problem.constraint_scope (
            id                 UUID PRIMARY KEY,
            constraint_id      UUID NOT NULL REFERENCES problem.constraint_definition(id),
            hierarchy_id       UUID REFERENCES domain.hierarchy(id),
            hierarchy_node_id  UUID REFERENCES domain.hierarchy_node(id),
            entity_id          UUID REFERENCES domain.entity(id),
            scope_type         VARCHAR(50),
            parameters         JSONB
        );

        CREATE TABLE problem.objective (
            id              UUID PRIMARY KEY,
            problem_id      UUID NOT NULL REFERENCES problem.problem(id),
            code            VARCHAR(150) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            objective_type  VARCHAR(30) NOT NULL,
            expression      JSONB,
            priority        INTEGER,
            weight          NUMERIC,
            UNIQUE (problem_id, code)
        );

        CREATE TABLE problem.objective_component (
            id              UUID PRIMARY KEY,
            objective_id    UUID NOT NULL REFERENCES problem.objective(id),
            code            VARCHAR(150),
            expression      JSONB,
            weight          NUMERIC,
            priority        INTEGER
        );

        CREATE TABLE problem.parameter (
            id              UUID PRIMARY KEY,
            problem_id      UUID NOT NULL REFERENCES problem.problem(id),
            code            VARCHAR(150) NOT NULL,
            name            VARCHAR(255),
            data_type       VARCHAR(50),
            value           JSONB,
            is_runtime      BOOLEAN DEFAULT FALSE,
            UNIQUE (problem_id, code)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS problem.parameter;
        DROP TABLE IF EXISTS problem.objective_component;
        DROP TABLE IF EXISTS problem.objective;
        DROP TABLE IF EXISTS problem.constraint_scope;
        DROP TABLE IF EXISTS problem.constraint_definition;
        DROP TABLE IF EXISTS problem.variable_dimension;
        DROP TABLE IF EXISTS problem.variable_definition;
        DROP TABLE IF EXISTS problem.scenario;
        DROP TABLE IF EXISTS problem.problem;
        DROP SCHEMA IF EXISTS problem;
        """
    )
```

- [ ] **Step 3: Apply migration and verify test passes**

Run:
```bash
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver alembic upgrade head
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver pytest tests/test_migrations_problem.py -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0005_problem_schema.py backend/tests/test_migrations_problem.py
git commit -m "feat: problem schema migration"
```

---

## Task 8: ClickHouse analytics schema, created at backend startup

**Files:**
- Create: `backend/app/clickhouse_schema.py`
- Modify: `backend/app/main.py` (run schema creation on startup)
- Test: `backend/tests/test_clickhouse_schema.py`

**Interfaces:**
- Consumes: `app.core.db.get_clickhouse_client` (Task 2).
- Produces: `create_analytics_schema(client) -> None`, idempotent (safe to call every startup). Creates ClickHouse tables `analytics.solver_runs`, `analytics.solution_metrics`, `analytics.constraint_violations` per spec §5. No later task writes to these tables this phase — they exist so the container/connection/health-check path is proven end-to-end.

- [ ] **Step 1: Write the failing test `backend/tests/test_clickhouse_schema.py`**

```python
from app.clickhouse_schema import create_analytics_schema
from app.core.db import get_clickhouse_client


def test_analytics_tables_are_created():
    client = get_clickhouse_client()
    create_analytics_schema(client)

    result = client.query(
        "SELECT name FROM system.tables WHERE database = 'analytics'"
    )
    table_names = {row[0] for row in result.result_rows}
    assert {"solver_runs", "solution_metrics", "constraint_violations"}.issubset(table_names)


def test_create_analytics_schema_is_idempotent():
    client = get_clickhouse_client()
    create_analytics_schema(client)
    create_analytics_schema(client)  # must not raise
```

Run: `cd backend && pytest tests/test_clickhouse_schema.py -v`
Expected: FAIL (`ModuleNotFoundError: app.clickhouse_schema`)

- [ ] **Step 2: Write `backend/app/clickhouse_schema.py`**

```python
_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS analytics.solver_runs
    (
        organization_id UUID,
        problem_id UUID,
        scenario_id UUID,
        solver_run_id UUID,
        solver_type LowCardinality(String),
        started_at DateTime64(3),
        finished_at Nullable(DateTime64(3)),
        duration_ms UInt64,
        status LowCardinality(String),
        objective_value Float64,
        best_bound Float64,
        gap Float64,
        variables UInt64,
        constraints UInt64,
        iterations UInt64,
        nodes UInt64
    )
    ENGINE = MergeTree
    ORDER BY (organization_id, problem_id, started_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS analytics.solution_metrics
    (
        organization_id UUID,
        problem_id UUID,
        scenario_id UUID,
        solution_id UUID,
        metric_code LowCardinality(String),
        metric_value Float64,
        measured_at DateTime64(3),
        dimensions Map(String, String)
    )
    ENGINE = MergeTree
    ORDER BY (organization_id, problem_id, metric_code, measured_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS analytics.constraint_violations
    (
        organization_id UUID,
        problem_id UUID,
        solution_id UUID,
        constraint_id UUID,
        entity_id UUID,
        severity LowCardinality(String),
        violation_value Float64,
        penalty Float64,
        occurred_at DateTime64(3)
    )
    ENGINE = MergeTree
    ORDER BY (organization_id, problem_id, constraint_id, occurred_at)
    """,
]


def create_analytics_schema(client) -> None:
    """Create the ClickHouse analytics tables if they don't already exist.

    Safe to call on every backend startup.
    """
    for statement in _STATEMENTS:
        client.command(statement)
```

- [ ] **Step 3: Wire it into startup in `backend/app/main.py`**

```python
from fastapi import FastAPI

from app.api.health import router as health_router
from app.clickhouse_schema import create_analytics_schema
from app.core.db import get_clickhouse_client

app = FastAPI(title="Problem Solver Platform API")

app.include_router(health_router)


@app.on_event("startup")
def on_startup() -> None:
    create_analytics_schema(get_clickhouse_client())
```

- [ ] **Step 4: Run tests against the real ClickHouse container**

Run:
```bash
docker compose up -d clickhouse
cd backend
CLICKHOUSE_HOST=localhost pytest tests/test_clickhouse_schema.py -v
```
Expected: PASS

- [ ] **Step 5: Rebuild backend and confirm startup still works**

Run: `docker compose up -d --build backend && curl http://localhost:8010/api/health`
Expected: `{"postgres":"ok","clickhouse":"ok"}` and no startup errors in `docker compose logs backend`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/clickhouse_schema.py backend/app/main.py backend/tests/test_clickhouse_schema.py
git commit -m "feat: create ClickHouse analytics schema on backend startup"
```

---

## Task 9: Security utilities — password hashing and JWT

**Files:**
- Create: `backend/app/core/security.py`
- Test: `backend/tests/test_security.py`

**Interfaces:**
- Consumes: `app.core.config.get_settings` (Task 2).
- Produces: `hash_password(password: str) -> str`, `verify_password(password: str, hashed: str) -> bool`, `create_access_token(subject: str, expires_minutes: int | None = None) -> str`, `decode_access_token(token: str) -> dict` (raises `jose.JWTError` on invalid/expired tokens). Task 10 (auth endpoints) and `app/api/deps.py` (`get_current_user`) both import these directly — no other module re-implements hashing or token logic.

- [ ] **Step 1: Write the failing test `backend/tests/test_security.py`**

```python
import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_is_not_plaintext_and_verifies():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_access_token_roundtrip():
    token = create_access_token(subject="admin")
    payload = decode_access_token(token)
    assert payload["sub"] == "admin"


def test_decode_rejects_garbage_token():
    with pytest.raises(JWTError):
        decode_access_token("not-a-real-token")
```

Run: `cd backend && pytest tests/test_security.py -v`
Expected: FAIL (`ModuleNotFoundError: app.core.security`)

- [ ] **Step 2: Write `backend/app/core/security.py`**

```python
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd_context.verify(password, hashed)


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd backend && JWT_SECRET=test-secret ADMIN_PASSWORD=test pytest tests/test_security.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/security.py backend/tests/test_security.py
git commit -m "feat: password hashing and JWT utilities"
```

---

## Task 10: `iam` SQLAlchemy models + auth endpoints (login, seed admin, current-user dependency)

**Files:**
- Create: `backend/app/models/base.py`
- Create: `backend/app/models/iam.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/api/deps.py`
- Create: `backend/app/api/auth.py`
- Create: `backend/app/seed.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Consumes: `app.core.db.Base`, `app.core.security.{hash_password,verify_password,create_access_token,decode_access_token}` (Tasks 2, 9), `iam` tables from Task 3.
- Produces: SQLAlchemy models `Organization`, `UserAccount`, `Role`, `UserRole` in `app.models.iam` (all later CRUD tasks reference `UserAccount` for auth and `Organization` as an FK target). `app.models.base.UUIDPKMixin` (every later model task uses this mixin for its primary key). `get_current_user(token: str = Depends(...), db: Session = Depends(get_db)) -> UserAccount` in `app.api.deps` (Task 12's CRUD factory depends on this to guard every route). `seed_admin(db: Session) -> None` in `app.seed`, idempotent. `POST /api/auth/login` (OAuth2 password form) returning `{"access_token": str, "token_type": "bearer"}`.

- [ ] **Step 1: Write `backend/app/models/base.py`**

```python
import uuid

from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPKMixin:
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
```

- [ ] **Step 2: Write `backend/app/models/iam.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class Organization(UUIDPKMixin, Base):
    __tablename__ = "organization"
    __table_args__ = {"schema": "iam"}

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserAccount(UUIDPKMixin, Base):
    __tablename__ = "user_account"
    __table_args__ = {"schema": "iam"}

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=True
    )
    username: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(UUIDPKMixin, Base):
    __tablename__ = "role"
    __table_args__ = {"schema": "iam"}

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class UserRole(UUIDPKMixin, Base):
    __tablename__ = "user_role"
    __table_args__ = {"schema": "iam"}

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.user_account.id"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.role.id"), nullable=False
    )
```

- [ ] **Step 3: Update `backend/app/models/__init__.py`**

```python
# Models are imported here as each schema group is implemented, so that
# Alembic's env.py (which imports this package) sees the full metadata.
from app.models.iam import Organization, Role, UserAccount, UserRole  # noqa: F401
```

- [ ] **Step 4: Write `backend/app/api/deps.py`**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models.iam import UserAccount

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> UserAccount:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(UserAccount).filter(UserAccount.username == username).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user
```

- [ ] **Step 5: Write `backend/app/seed.py`**

```python
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.iam import Organization, UserAccount


def seed_admin(db: Session) -> None:
    """Ensure a default organization and admin user exist. Idempotent."""
    settings = get_settings()

    org = db.query(Organization).filter(Organization.code == "default").first()
    if org is None:
        org = Organization(code="default", name="Default Organization")
        db.add(org)
        db.commit()
        db.refresh(org)

    admin = db.query(UserAccount).filter(UserAccount.username == settings.admin_username).first()
    if admin is None:
        admin = UserAccount(
            organization_id=org.id,
            username=settings.admin_username,
            display_name="Administrator",
            email=settings.admin_email,
            hashed_password=hash_password(settings.admin_password),
        )
        db.add(admin)
        db.commit()
```

- [ ] **Step 6: Write `backend/app/api/auth.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_access_token, verify_password
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> dict:
    user = db.query(UserAccount).filter(UserAccount.username == form_data.username).first()
    if user is None or not user.is_active or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="incorrect username or password")
    token = create_access_token(subject=user.username)
    return {"access_token": token, "token_type": "bearer"}
```

- [ ] **Step 7: Write the failing test `backend/tests/test_auth.py`**

```python
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.main import app
from app.seed import seed_admin


@pytest.fixture(autouse=True)
def ensure_admin_seeded():
    db = SessionLocal()
    seed_admin(db)
    db.close()


def test_login_with_seeded_admin_returns_token():
    settings = get_settings()
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": settings.admin_password},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_with_wrong_password_returns_401():
    settings = get_settings()
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        data={"username": settings.admin_username, "password": "wrong"},
    )
    assert response.status_code == 401


def test_get_current_user_accepts_valid_token():
    settings = get_settings()
    token = create_access_token(subject=settings.admin_username)
    db = SessionLocal()
    user = get_current_user(token=token, db=db)
    db.close()
    assert user.username == settings.admin_username


def test_get_current_user_rejects_invalid_token():
    db = SessionLocal()
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(token="garbage", db=db)
    db.close()
    assert exc_info.value.status_code == 401
```

Run: `cd backend && pytest tests/test_auth.py -v`
Expected: FAIL (`ModuleNotFoundError: app.api.auth` / `app.seed`)

- [ ] **Step 8: Wire seeding and the auth router into `backend/app/main.py`**

```python
from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.clickhouse_schema import create_analytics_schema
from app.core.db import SessionLocal, get_clickhouse_client
from app.seed import seed_admin

app = FastAPI(title="Problem Solver Platform API")

app.include_router(health_router)
app.include_router(auth_router)


@app.on_event("startup")
def on_startup() -> None:
    create_analytics_schema(get_clickhouse_client())
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()
```

- [ ] **Step 9: Run tests against the real Postgres container to verify they pass**

Run:
```bash
docker compose up -d postgres clickhouse
cd backend
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver \
JWT_SECRET=test-secret ADMIN_PASSWORD=change-me-admin \
pytest tests/test_auth.py -v
```
Expected: PASS

- [ ] **Step 10: Rebuild backend and confirm login works end-to-end**

Run:
```bash
docker compose up -d --build backend
curl -X POST http://localhost:8010/api/auth/login -d "username=admin&password=change-me-admin"
```
Expected: JSON body with `access_token` and `"token_type":"bearer"`.

- [ ] **Step 11: Commit**

```bash
git add backend/app/models backend/app/api/deps.py backend/app/api/auth.py backend/app/seed.py backend/app/main.py backend/tests/test_auth.py
git commit -m "feat: iam models, JWT auth, and seeded admin user"
```

---

## Task 11: Generic Pydantic schema generator

**Files:**
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/generate.py`
- Test: `backend/tests/test_schemas_generate.py`

**Interfaces:**
- Consumes: nothing beyond SQLAlchemy/Pydantic — no DB connection required, works purely off model class metadata.
- Produces: `make_crud_schemas(model: Type, *, name: str, readonly: frozenset[str] = frozenset({"id"}), server_default: frozenset[str] = frozenset()) -> tuple[Type[BaseModel], Type[BaseModel], Type[BaseModel]]` returning `(Create, Update, Read)` Pydantic schema classes. Every later model task (12-17) calls this once per table instead of hand-writing Create/Update/Read classes.

- [ ] **Step 1: Write `backend/app/schemas/__init__.py`** (empty)

- [ ] **Step 2: Write the failing test `backend/tests/test_schemas_generate.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.schemas.generate import make_crud_schemas


class _ScratchBase(DeclarativeBase):
    pass


class DummyModel(_ScratchBase):
    __tablename__ = "dummy_model"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _schemas():
    return make_crud_schemas(
        DummyModel, name="Dummy", readonly={"id"}, server_default={"created_at"}
    )


def test_readonly_fields_excluded_from_create_and_update_but_present_in_read():
    Create, Update, Read = _schemas()
    assert "id" not in Create.model_fields
    assert "id" not in Update.model_fields
    assert "id" in Read.model_fields


def test_required_vs_optional_on_create():
    Create, _, _ = _schemas()
    assert Create.model_fields["name"].is_required()
    assert not Create.model_fields["note"].is_required()
    assert not Create.model_fields["created_at"].is_required()


def test_all_non_readonly_fields_optional_on_update():
    _, Update, _ = _schemas()
    assert not Update.model_fields["name"].is_required()
    assert not Update.model_fields["note"].is_required()


def test_read_schema_validates_from_orm_instance():
    _, _, Read = _schemas()
    instance = DummyModel(id=uuid.uuid4(), name="hello", note=None, created_at=None)
    read = Read.model_validate(instance)
    assert read.name == "hello"


class DummyModelWithAliasedColumn(_ScratchBase):
    """Some real tables (relationship_type, time_period) have a column
    literally named "metadata", which collides with SQLAlchemy's reserved
    Base.metadata attribute. The fix is to alias the Python attribute
    (metadata_) while keeping the DB column name (metadata). This model
    reproduces that shape so the generator is proven to key off the
    attribute name, not the column name.
    """

    __tablename__ = "dummy_model_aliased"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    metadata_: Mapped[str | None] = mapped_column("metadata", String(255), nullable=True)


def test_aliased_column_uses_attribute_name_not_db_column_name():
    Create, _, Read = make_crud_schemas(
        DummyModelWithAliasedColumn, name="DummyAliased", readonly={"id"}
    )
    assert "metadata_" in Create.model_fields
    assert "metadata" not in Create.model_fields

    instance = DummyModelWithAliasedColumn(id=uuid.uuid4(), metadata_="tag=1")
    read = Read.model_validate(instance)
    assert read.metadata_ == "tag=1"
```

Run: `cd backend && pytest tests/test_schemas_generate.py -v`
Expected: FAIL (`ModuleNotFoundError: app.schemas.generate`)

- [ ] **Step 3: Write `backend/app/schemas/generate.py`**

```python
import datetime
import uuid
from typing import Any, Optional, Type

from pydantic import BaseModel, ConfigDict, create_model
from sqlalchemy import inspect

_TYPE_MAP: dict[str, type] = {
    "UUID": uuid.UUID,
    "VARCHAR": str,
    "TEXT": str,
    "INTEGER": int,
    "BIGINT": int,
    "NUMERIC": float,
    "BOOLEAN": bool,
    "DATE": datetime.date,
    "TIMESTAMP": datetime.datetime,
    "JSON": Any,
    "JSONB": Any,
}


def _python_type(column) -> type:
    type_name = column.type.__class__.__name__.upper()
    return _TYPE_MAP.get(type_name, str)


def make_crud_schemas(
    model: Type,
    *,
    name: str,
    readonly: frozenset = frozenset({"id"}),
    server_default: frozenset = frozenset(),
) -> tuple[Type[BaseModel], Type[BaseModel], Type[BaseModel]]:
    """Derive (Create, Update, Read) Pydantic schemas from a SQLAlchemy model.

    readonly: fields never accepted on create or update (e.g. primary key).
    server_default: fields optional on create because the database fills
        them in (e.g. created_at via `server_default=func.now()`).
    """
    mapper = inspect(model)
    create_fields: dict[str, tuple] = {}
    update_fields: dict[str, tuple] = {}
    read_fields: dict[str, tuple] = {}

    # Iterate column_attrs (Python attribute names), not mapper.columns (DB
    # column names) — they diverge whenever a column is aliased, which we
    # do for any column named "metadata" (reserved by SQLAlchemy's
    # DeclarativeBase). Keying on the attribute name keeps
    # `model(**payload.model_dump())` and `Read.model_validate(row)`
    # correct in both the common case and the aliased case.
    for attr in mapper.column_attrs:
        col = attr.columns[0]
        field_name = attr.key
        py_type = _python_type(col)
        optional_on_create = col.nullable or field_name in server_default

        if col.nullable:
            read_fields[field_name] = (Optional[py_type], None)
        else:
            read_fields[field_name] = (py_type, ...)

        if field_name in readonly:
            continue

        if optional_on_create:
            create_fields[field_name] = (Optional[py_type], None)
        else:
            create_fields[field_name] = (py_type, ...)

        update_fields[field_name] = (Optional[py_type], None)

    cfg = ConfigDict(from_attributes=True)
    create_schema = create_model(f"{name}Create", __config__=cfg, **create_fields)
    update_schema = create_model(f"{name}Update", __config__=cfg, **update_fields)
    read_schema = create_model(f"{name}Read", __config__=cfg, **read_fields)
    return create_schema, update_schema, read_schema
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_schemas_generate.py -v`
Expected: PASS (no database needed for this test file)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas backend/tests/test_schemas_generate.py
git commit -m "feat: generic Pydantic schema generator from SQLAlchemy models"
```

---

## Task 12: Generic CRUD router factory + `iam` CRUD routes

**Files:**
- Create: `backend/app/crud/__init__.py`
- Create: `backend/app/crud/registry.py`
- Create: `backend/app/crud/factory.py`
- Create: `backend/app/api/routers.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_crud_iam.py`

**Interfaces:**
- Consumes: `app.api.deps.get_current_user`, `app.core.db.get_db` (Tasks 10, 2), `app.schemas.generate.make_crud_schemas` (Task 11), `app.models.iam.{Organization,UserAccount,Role,UserRole}` (Task 10).
- Produces: `build_crud_router(*, model, create_schema, update_schema, read_schema, schema_name: str, table_name: str) -> APIRouter` in `app.crud.factory` — every later CRUD task (13-17) calls this once per table with no other pattern. `register_table(schema, table, model, create_schema, read_schema) -> None` and `TABLE_REGISTRY: list[TableMeta]` in `app.crud.registry` — Task 18's metadata endpoint reads `TABLE_REGISTRY`, using `create_schema` to know which fields are writable and `read_schema` for the full column list (including `id`, which `create_schema` always excludes). List responses are `{"items": [...], "total": int}` per the Global Constraints. `app.api.routers.router` — an `APIRouter` that Tasks 13-17 each add their table's routers to; `main.py` includes it once.

- [ ] **Step 1: Write `backend/app/crud/registry.py`**

```python
from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel


@dataclass
class TableMeta:
    schema: str
    table: str
    model: Type
    create_schema: Type[BaseModel]
    read_schema: Type[BaseModel]


TABLE_REGISTRY: list[TableMeta] = []


def register_table(
    schema: str, table: str, model: Type, create_schema: Type[BaseModel], read_schema: Type[BaseModel]
) -> None:
    TABLE_REGISTRY.append(
        TableMeta(schema=schema, table=table, model=model, create_schema=create_schema, read_schema=read_schema)
    )
```

- [ ] **Step 2: Write `backend/app/crud/factory.py`**

```python
from typing import Type
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.crud.registry import register_table
from app.models.iam import UserAccount


def build_crud_router(
    *,
    model: Type,
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    read_schema: Type[BaseModel],
    schema_name: str,
    table_name: str,
) -> APIRouter:
    """Build a generic list/get/create/update/delete router for one table.

    Registers the table in TABLE_REGISTRY as a side effect, so Task 18's
    /api/meta/schema endpoint picks it up automatically without a second
    bookkeeping step.
    """
    router = APIRouter(prefix=f"/api/{schema_name}/{table_name}", tags=[f"{schema_name}.{table_name}"])
    register_table(schema_name, table_name, model, create_schema, read_schema)

    @router.get("/")
    def list_items(
        limit: int = 50,
        offset: int = 0,
        db: Session = Depends(get_db),
        _: UserAccount = Depends(get_current_user),
    ) -> dict:
        total = db.query(model).count()
        rows = db.query(model).offset(offset).limit(limit).all()
        return {
            "items": [read_schema.model_validate(row).model_dump(mode="json") for row in rows],
            "total": total,
        }

    @router.get("/{item_id}")
    def get_item(
        item_id: UUID, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)
    ) -> read_schema:
        item = db.get(model, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        return item

    @router.post("/", status_code=201)
    def create_item(
        payload: create_schema,
        db: Session = Depends(get_db),
        _: UserAccount = Depends(get_current_user),
    ) -> read_schema:
        item = model(**payload.model_dump())
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    @router.put("/{item_id}")
    def update_item(
        item_id: UUID,
        payload: update_schema,
        db: Session = Depends(get_db),
        _: UserAccount = Depends(get_current_user),
    ) -> read_schema:
        item = db.get(model, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        db.commit()
        db.refresh(item)
        return item

    @router.delete("/{item_id}", status_code=204)
    def delete_item(
        item_id: UUID, db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)
    ) -> None:
        item = db.get(model, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="not found")
        db.delete(item)
        db.commit()

    return router
```

- [ ] **Step 3: Write `backend/app/api/routers.py` with the `iam` tables wired**

```python
from fastapi import APIRouter

from app.crud.factory import build_crud_router
from app.models.iam import Organization, Role, UserAccount, UserRole
from app.schemas.generate import make_crud_schemas

router = APIRouter()

# --- iam ---

OrganizationCreate, OrganizationUpdate, OrganizationRead = make_crud_schemas(
    Organization, name="Organization", readonly={"id"}, server_default={"created_at"}
)
router.include_router(
    build_crud_router(
        model=Organization,
        create_schema=OrganizationCreate,
        update_schema=OrganizationUpdate,
        read_schema=OrganizationRead,
        schema_name="iam",
        table_name="organization",
    )
)

UserAccountCreate, UserAccountUpdate, UserAccountRead = make_crud_schemas(
    UserAccount, name="UserAccount", readonly={"id"}, server_default={"created_at"}
)
router.include_router(
    build_crud_router(
        model=UserAccount,
        create_schema=UserAccountCreate,
        update_schema=UserAccountUpdate,
        read_schema=UserAccountRead,
        schema_name="iam",
        table_name="user_account",
    )
)

RoleCreate, RoleUpdate, RoleRead = make_crud_schemas(Role, name="Role", readonly={"id"})
router.include_router(
    build_crud_router(
        model=Role,
        create_schema=RoleCreate,
        update_schema=RoleUpdate,
        read_schema=RoleRead,
        schema_name="iam",
        table_name="role",
    )
)

UserRoleCreate, UserRoleUpdate, UserRoleRead = make_crud_schemas(UserRole, name="UserRole", readonly={"id"})
router.include_router(
    build_crud_router(
        model=UserRole,
        create_schema=UserRoleCreate,
        update_schema=UserRoleUpdate,
        read_schema=UserRoleRead,
        schema_name="iam",
        table_name="user_role",
    )
)
```

- [ ] **Step 4: Write the failing test `backend/tests/test_crud_iam.py`**

```python
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
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


def test_unauthenticated_request_is_rejected():
    client = TestClient(app)
    response = client.get("/api/iam/organization/")
    assert response.status_code == 401


def test_organization_crud_lifecycle(auth_headers):
    client = TestClient(app)

    create_response = client.post(
        "/api/iam/organization/",
        json={"code": "acme", "name": "Acme Corp", "is_active": True},
        headers=auth_headers,
    )
    assert create_response.status_code == 201
    org = create_response.json()
    org_id = org["id"]
    assert org["code"] == "acme"

    list_response = client.get("/api/iam/organization/", headers=auth_headers)
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] >= 1
    assert any(item["id"] == org_id for item in body["items"])

    get_response = client.get(f"/api/iam/organization/{org_id}", headers=auth_headers)
    assert get_response.status_code == 200
    assert get_response.json()["code"] == "acme"

    update_response = client.put(
        f"/api/iam/organization/{org_id}",
        json={"name": "Acme Corporation"},
        headers=auth_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Acme Corporation"

    delete_response = client.delete(f"/api/iam/organization/{org_id}", headers=auth_headers)
    assert delete_response.status_code == 204

    get_after_delete = client.get(f"/api/iam/organization/{org_id}", headers=auth_headers)
    assert get_after_delete.status_code == 404
```

Run: `cd backend && pytest tests/test_crud_iam.py -v`
Expected: FAIL (`ModuleNotFoundError: app.crud.factory` / `app.api.routers`)

- [ ] **Step 5: Wire the CRUD router into `backend/app/main.py`**

```python
from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.routers import router as crud_router
from app.clickhouse_schema import create_analytics_schema
from app.core.db import SessionLocal, get_clickhouse_client
from app.seed import seed_admin

app = FastAPI(title="Problem Solver Platform API")

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(crud_router)


@app.on_event("startup")
def on_startup() -> None:
    create_analytics_schema(get_clickhouse_client())
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()
```

- [ ] **Step 6: Run tests against the real Postgres/ClickHouse containers to verify they pass**

Run:
```bash
docker compose up -d postgres clickhouse
cd backend
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver \
CLICKHOUSE_HOST=localhost JWT_SECRET=test-secret ADMIN_PASSWORD=change-me-admin \
pytest tests/test_crud_iam.py -v
```
Expected: PASS

- [ ] **Step 7: Rebuild backend and smoke-test through Docker**

Run:
```bash
docker compose up -d --build backend
TOKEN=$(curl -s -X POST http://localhost:8010/api/auth/login -d "username=admin&password=change-me-admin" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -H "Authorization: Bearer $TOKEN" http://localhost:8010/api/iam/organization/
```
Expected: `{"items":[...],"total":...}` including the seeded `"default"` organization.

- [ ] **Step 8: Commit**

```bash
git add backend/app/crud backend/app/api/routers.py backend/app/main.py backend/tests/test_crud_iam.py
git commit -m "feat: generic CRUD router factory, wired for iam tables"
```

---

## Task 13: `domain` schema Group A models + CRUD routes (entity core + relationships)

**Files:**
- Create: `backend/app/models/domain.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/routers.py` (append domain Group A section)
- Test: `backend/tests/test_crud_domain_a.py`

**Interfaces:**
- Consumes: `app.models.base.UUIDPKMixin`, `app.core.db.Base` (Tasks 2, 10), `app.crud.factory.build_crud_router`, `app.schemas.generate.make_crud_schemas` (Tasks 11, 12), `iam.organization` (Task 10) via FK.
- Produces: SQLAlchemy models `EntityType`, `Entity`, `AttributeDefinition`, `EntityAttribute`, `RelationshipType`, `Relationship` in `app.models.domain` (Tasks 14-17 add more classes to this same file). Note: `RelationshipType.metadata_` maps to the DB column `metadata` (aliased — `metadata` is reserved by SQLAlchemy's `DeclarativeBase`); the generic schema/CRUD layer exposes it as `metadata_` end-to-end (JSON body key, Pydantic field, frontend form field), consistent with Task 11's attribute-based generator.

- [ ] **Step 1: Write `backend/app/models/domain.py`**

```python
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class EntityType(UUIDPKMixin, Base):
    __tablename__ = "entity_type"
    __table_args__ = {"schema": "domain"}

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_type_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=True
    )
    is_abstract: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Entity(UUIDPKMixin, Base):
    __tablename__ = "entity"
    __table_args__ = {"schema": "domain"}

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=False
    )
    entity_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=False
    )
    code: Mapped[str | None] = mapped_column(String(150), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AttributeDefinition(UUIDPKMixin, Base):
    __tablename__ = "attribute_definition"
    __table_args__ = {"schema": "domain"}

    entity_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_multi_value: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation_rule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class EntityAttribute(UUIDPKMixin, Base):
    __tablename__ = "entity_attribute"
    __table_args__ = {"schema": "domain"}

    entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=False
    )
    attribute_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.attribute_definition.id"), nullable=False
    )
    value_string: Mapped[str | None] = mapped_column(String, nullable=True)
    value_number: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    value_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    value_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    value_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class RelationshipType(UUIDPKMixin, Base):
    __tablename__ = "relationship_type"
    __table_args__ = {"schema": "domain"}

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_entity_type: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=True
    )
    target_entity_type: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=True
    )
    cardinality: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_directed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)


class Relationship(UUIDPKMixin, Base):
    __tablename__ = "relationship"
    __table_args__ = {"schema": "domain"}

    relationship_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.relationship_type.id"), nullable=False
    )
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=False
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 2: Update `backend/app/models/__init__.py`**

```python
# Models are imported here as each schema group is implemented, so that
# Alembic's env.py (which imports this package) sees the full metadata.
from app.models.iam import Organization, Role, UserAccount, UserRole  # noqa: F401
from app.models.domain import (  # noqa: F401
    AttributeDefinition,
    Entity,
    EntityAttribute,
    EntityType,
    Relationship,
    RelationshipType,
)
```

- [ ] **Step 3: Append the domain Group A section to `backend/app/api/routers.py`** (after the existing `iam` section)

```python
from app.models.domain import (
    AttributeDefinition,
    Entity,
    EntityAttribute,
    EntityType,
    Relationship,
    RelationshipType,
)

# --- domain: group A (entity core + relationships) ---

EntityTypeCreate, EntityTypeUpdate, EntityTypeRead = make_crud_schemas(
    EntityType, name="EntityType", readonly={"id"}, server_default={"created_at"}
)
router.include_router(
    build_crud_router(
        model=EntityType,
        create_schema=EntityTypeCreate,
        update_schema=EntityTypeUpdate,
        read_schema=EntityTypeRead,
        schema_name="domain",
        table_name="entity_type",
    )
)

EntityCreate, EntityUpdate, EntityRead = make_crud_schemas(
    Entity, name="Entity", readonly={"id"}, server_default={"created_at", "updated_at"}
)
router.include_router(
    build_crud_router(
        model=Entity,
        create_schema=EntityCreate,
        update_schema=EntityUpdate,
        read_schema=EntityRead,
        schema_name="domain",
        table_name="entity",
    )
)

AttributeDefinitionCreate, AttributeDefinitionUpdate, AttributeDefinitionRead = make_crud_schemas(
    AttributeDefinition, name="AttributeDefinition", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=AttributeDefinition,
        create_schema=AttributeDefinitionCreate,
        update_schema=AttributeDefinitionUpdate,
        read_schema=AttributeDefinitionRead,
        schema_name="domain",
        table_name="attribute_definition",
    )
)

EntityAttributeCreate, EntityAttributeUpdate, EntityAttributeRead = make_crud_schemas(
    EntityAttribute, name="EntityAttribute", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=EntityAttribute,
        create_schema=EntityAttributeCreate,
        update_schema=EntityAttributeUpdate,
        read_schema=EntityAttributeRead,
        schema_name="domain",
        table_name="entity_attribute",
    )
)

RelationshipTypeCreate, RelationshipTypeUpdate, RelationshipTypeRead = make_crud_schemas(
    RelationshipType, name="RelationshipType", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=RelationshipType,
        create_schema=RelationshipTypeCreate,
        update_schema=RelationshipTypeUpdate,
        read_schema=RelationshipTypeRead,
        schema_name="domain",
        table_name="relationship_type",
    )
)

RelationshipCreate, RelationshipUpdate, RelationshipRead = make_crud_schemas(
    Relationship, name="Relationship", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Relationship,
        create_schema=RelationshipCreate,
        update_schema=RelationshipUpdate,
        read_schema=RelationshipRead,
        schema_name="domain",
        table_name="relationship",
    )
)
```

- [ ] **Step 4: Write the failing test `backend/tests/test_crud_domain_a.py`**

```python
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
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


@pytest.fixture
def organization_id(auth_headers):
    client = TestClient(app)
    response = client.get("/api/iam/organization/", headers=auth_headers)
    items = response.json()["items"]
    default_org = next(item for item in items if item["code"] == "default")
    return default_org["id"]


def test_entity_type_create(auth_headers, organization_id):
    client = TestClient(app)
    response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": "employee-a", "name": "Employee"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["code"] == "employee-a"


def test_entity_attribute_and_relationship_chain(auth_headers, organization_id):
    client = TestClient(app)

    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": "vehicle-a", "name": "Vehicle"},
        headers=auth_headers,
    )
    assert et_response.status_code == 201
    entity_type_id = et_response.json()["id"]

    entity_response = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "code": "veh-1",
            "name": "Truck 1",
        },
        headers=auth_headers,
    )
    assert entity_response.status_code == 201
    entity_id = entity_response.json()["id"]

    attr_def_response = client.post(
        "/api/domain/attribute_definition/",
        json={
            "entity_type_id": entity_type_id,
            "code": "capacity_kg",
            "name": "Capacity (kg)",
            "data_type": "number",
            "is_required": False,
            "is_multi_value": False,
        },
        headers=auth_headers,
    )
    assert attr_def_response.status_code == 201
    attribute_id = attr_def_response.json()["id"]

    entity_attr_response = client.post(
        "/api/domain/entity_attribute/",
        json={"entity_id": entity_id, "attribute_id": attribute_id, "value_number": 1200},
        headers=auth_headers,
    )
    assert entity_attr_response.status_code == 201

    rel_type_response = client.post(
        "/api/domain/relationship_type/",
        json={"code": "assigned_to-a", "name": "Assigned To", "is_directed": True},
        headers=auth_headers,
    )
    assert rel_type_response.status_code == 201
    relationship_type_id = rel_type_response.json()["id"]

    other_entity_response = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "code": "veh-2",
            "name": "Truck 2",
        },
        headers=auth_headers,
    )
    other_entity_id = other_entity_response.json()["id"]

    relationship_response = client.post(
        "/api/domain/relationship/",
        json={
            "relationship_type_id": relationship_type_id,
            "source_entity_id": entity_id,
            "target_entity_id": other_entity_id,
        },
        headers=auth_headers,
    )
    assert relationship_response.status_code == 201
```

Run: `cd backend && pytest tests/test_crud_domain_a.py -v`
Expected: FAIL (`ModuleNotFoundError: app.models.domain` / 404s on `/api/domain/...`)

- [ ] **Step 5: Apply migrations (if not already applied) and run tests against the real containers**

Run:
```bash
docker compose up -d postgres clickhouse
cd backend
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver alembic upgrade head
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver \
CLICKHOUSE_HOST=localhost JWT_SECRET=test-secret ADMIN_PASSWORD=change-me-admin \
pytest tests/test_crud_domain_a.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/domain.py backend/app/models/__init__.py backend/app/api/routers.py backend/tests/test_crud_domain_a.py
git commit -m "feat: domain group A models and CRUD routes (entity core + relationships)"
```

---

## Task 14: `domain` schema Group B models + CRUD routes (hierarchy, roles, states)

**Files:**
- Modify: `backend/app/models/domain.py` (append classes; add `Integer` to the existing `sqlalchemy` import line)
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/routers.py` (append domain Group B section)
- Test: `backend/tests/test_crud_domain_b.py`

**Interfaces:**
- Consumes: `EntityType`, `Entity` from `app.models.domain` (Task 13).
- Produces: SQLAlchemy models `Hierarchy`, `HierarchyNode`, `RoleType`, `EntityRole`, `StateType`, `EntityState` in `app.models.domain`. Task 16 (`problem.constraint_scope`) references `Hierarchy` and `HierarchyNode` via FK.

- [ ] **Step 1: Update the import line at the top of `backend/app/models/domain.py`**

```python
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, func
```

- [ ] **Step 2: Append to `backend/app/models/domain.py`**

```python
class Hierarchy(UUIDPKMixin, Base):
    __tablename__ = "hierarchy"
    __table_args__ = {"schema": "domain"}

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class HierarchyNode(UUIDPKMixin, Base):
    __tablename__ = "hierarchy_node"
    __table_args__ = {"schema": "domain"}

    hierarchy_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.hierarchy.id"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=False
    )
    parent_node_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.hierarchy_node.id"), nullable=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RoleType(UUIDPKMixin, Base):
    __tablename__ = "role_type"
    __table_args__ = {"schema": "domain"}

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class EntityRole(UUIDPKMixin, Base):
    __tablename__ = "entity_role"
    __table_args__ = {"schema": "domain"}

    entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=False
    )
    role_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.role_type.id"), nullable=False
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class StateType(UUIDPKMixin, Base):
    __tablename__ = "state_type"
    __table_args__ = {"schema": "domain"}

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity_type.id"), nullable=True
    )


class EntityState(UUIDPKMixin, Base):
    __tablename__ = "entity_state"
    __table_args__ = {"schema": "domain"}

    entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=False
    )
    state_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.state_type.id"), nullable=False
    )
    state_value: Mapped[str] = mapped_column(String(100), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: Update `backend/app/models/__init__.py`**

```python
from app.models.domain import (  # noqa: F401
    AttributeDefinition,
    Entity,
    EntityAttribute,
    EntityRole,
    EntityState,
    EntityType,
    Hierarchy,
    HierarchyNode,
    Relationship,
    RelationshipType,
    RoleType,
    StateType,
)
```

- [ ] **Step 4: Append the domain Group B section to `backend/app/api/routers.py`**

```python
from app.models.domain import (
    EntityRole,
    EntityState,
    Hierarchy,
    HierarchyNode,
    RoleType,
    StateType,
)

# --- domain: group B (hierarchy, roles, states) ---

HierarchyCreate, HierarchyUpdate, HierarchyRead = make_crud_schemas(
    Hierarchy, name="Hierarchy", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Hierarchy,
        create_schema=HierarchyCreate,
        update_schema=HierarchyUpdate,
        read_schema=HierarchyRead,
        schema_name="domain",
        table_name="hierarchy",
    )
)

HierarchyNodeCreate, HierarchyNodeUpdate, HierarchyNodeRead = make_crud_schemas(
    HierarchyNode, name="HierarchyNode", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=HierarchyNode,
        create_schema=HierarchyNodeCreate,
        update_schema=HierarchyNodeUpdate,
        read_schema=HierarchyNodeRead,
        schema_name="domain",
        table_name="hierarchy_node",
    )
)

RoleTypeCreate, RoleTypeUpdate, RoleTypeRead = make_crud_schemas(
    RoleType, name="RoleType", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=RoleType,
        create_schema=RoleTypeCreate,
        update_schema=RoleTypeUpdate,
        read_schema=RoleTypeRead,
        schema_name="domain",
        table_name="role_type",
    )
)

EntityRoleCreate, EntityRoleUpdate, EntityRoleRead = make_crud_schemas(
    EntityRole, name="EntityRole", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=EntityRole,
        create_schema=EntityRoleCreate,
        update_schema=EntityRoleUpdate,
        read_schema=EntityRoleRead,
        schema_name="domain",
        table_name="entity_role",
    )
)

StateTypeCreate, StateTypeUpdate, StateTypeRead = make_crud_schemas(
    StateType, name="StateType", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=StateType,
        create_schema=StateTypeCreate,
        update_schema=StateTypeUpdate,
        read_schema=StateTypeRead,
        schema_name="domain",
        table_name="state_type",
    )
)

EntityStateCreate, EntityStateUpdate, EntityStateRead = make_crud_schemas(
    EntityState, name="EntityState", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=EntityState,
        create_schema=EntityStateCreate,
        update_schema=EntityStateUpdate,
        read_schema=EntityStateRead,
        schema_name="domain",
        table_name="entity_state",
    )
)
```

- [ ] **Step 5: Write the failing test `backend/tests/test_crud_domain_b.py`**

```python
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
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


@pytest.fixture
def organization_id(auth_headers):
    client = TestClient(app)
    response = client.get("/api/iam/organization/", headers=auth_headers)
    items = response.json()["items"]
    default_org = next(item for item in items if item["code"] == "default")
    return default_org["id"]


@pytest.fixture
def entity_id(auth_headers, organization_id):
    client = TestClient(app)
    et_response = client.post(
        "/api/domain/entity_type/",
        json={"organization_id": organization_id, "code": "unit-b", "name": "Unit"},
        headers=auth_headers,
    )
    entity_type_id = et_response.json()["id"]
    entity_response = client.post(
        "/api/domain/entity/",
        json={
            "organization_id": organization_id,
            "entity_type_id": entity_type_id,
            "code": "unit-1",
            "name": "Unit 1",
        },
        headers=auth_headers,
    )
    return entity_response.json()["id"]


def test_hierarchy_node_chain(auth_headers, organization_id, entity_id):
    client = TestClient(app)

    hierarchy_response = client.post(
        "/api/domain/hierarchy/",
        json={"organization_id": organization_id, "code": "org-chart", "name": "Org Chart"},
        headers=auth_headers,
    )
    assert hierarchy_response.status_code == 201
    hierarchy_id = hierarchy_response.json()["id"]

    node_response = client.post(
        "/api/domain/hierarchy_node/",
        json={"hierarchy_id": hierarchy_id, "entity_id": entity_id, "level": 0},
        headers=auth_headers,
    )
    assert node_response.status_code == 201


def test_entity_role_and_entity_state(auth_headers, entity_id):
    client = TestClient(app)

    role_type_response = client.post(
        "/api/domain/role_type/",
        json={"code": "supervisor-b", "name": "Supervisor"},
        headers=auth_headers,
    )
    assert role_type_response.status_code == 201
    role_type_id = role_type_response.json()["id"]

    entity_role_response = client.post(
        "/api/domain/entity_role/",
        json={"entity_id": entity_id, "role_type_id": role_type_id},
        headers=auth_headers,
    )
    assert entity_role_response.status_code == 201

    state_type_response = client.post(
        "/api/domain/state_type/",
        json={"code": "availability-b", "name": "Availability"},
        headers=auth_headers,
    )
    assert state_type_response.status_code == 201
    state_type_id = state_type_response.json()["id"]

    entity_state_response = client.post(
        "/api/domain/entity_state/",
        json={
            "entity_id": entity_id,
            "state_type_id": state_type_id,
            "state_value": "AVAILABLE",
            "valid_from": "2026-01-01T00:00:00Z",
        },
        headers=auth_headers,
    )
    assert entity_state_response.status_code == 201
```

Run: `cd backend && pytest tests/test_crud_domain_b.py -v`
Expected: FAIL (404s on `/api/domain/hierarchy/...` etc.)

- [ ] **Step 6: Apply migrations and run tests against the real containers**

Run:
```bash
docker compose up -d postgres clickhouse
cd backend
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver alembic upgrade head
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver \
CLICKHOUSE_HOST=localhost JWT_SECRET=test-secret ADMIN_PASSWORD=change-me-admin \
pytest tests/test_crud_domain_b.py -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/domain.py backend/app/models/__init__.py backend/app/api/routers.py backend/tests/test_crud_domain_b.py
git commit -m "feat: domain group B models and CRUD routes (hierarchy, roles, states)"
```

---

## Task 15: `domain` schema Group C models + CRUD routes (events, resources, time)

**Files:**
- Modify: `backend/app/models/domain.py` (append classes)
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/routers.py` (append domain Group C section)
- Test: `backend/tests/test_crud_domain_c.py`

**Interfaces:**
- Consumes: `Entity` (Task 13), `Organization` (Task 10).
- Produces: SQLAlchemy models `EventType`, `Event`, `ResourceType`, `Resource`, `TimeCalendar`, `TimePeriod` in `app.models.domain`. This completes the `domain` schema — 18 tables total across Tasks 13-15. `TimePeriod.metadata_` maps to DB column `metadata` (same aliasing rule as `RelationshipType.metadata_` in Task 13).

- [ ] **Step 1: Append to `backend/app/models/domain.py`**

```python
class EventType(UUIDPKMixin, Base):
    __tablename__ = "event_type"
    __table_args__ = {"schema": "domain"}

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class Event(UUIDPKMixin, Base):
    __tablename__ = "event"
    __table_args__ = {"schema": "domain"}

    event_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.event_type.id"), nullable=False
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ResourceType(UUIDPKMixin, Base):
    __tablename__ = "resource_type"
    __table_args__ = {"schema": "domain"}

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    capacity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)


class Resource(UUIDPKMixin, Base):
    __tablename__ = "resource"
    __table_args__ = {"schema": "domain"}

    resource_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.resource_type.id"), nullable=False
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=True
    )
    capacity: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    availability_rule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class TimeCalendar(UUIDPKMixin, Base):
    __tablename__ = "time_calendar"
    __table_args__ = {"schema": "domain"}

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)


class TimePeriod(UUIDPKMixin, Base):
    __tablename__ = "time_period"
    __table_args__ = {"schema": "domain"}

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.time_calendar.id"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.time_period.id"), nullable=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
```

- [ ] **Step 2: Update `backend/app/models/__init__.py`**

```python
from app.models.domain import (  # noqa: F401
    AttributeDefinition,
    Entity,
    EntityAttribute,
    EntityRole,
    EntityState,
    EntityType,
    Event,
    EventType,
    Hierarchy,
    HierarchyNode,
    Relationship,
    RelationshipType,
    Resource,
    ResourceType,
    RoleType,
    StateType,
    TimeCalendar,
    TimePeriod,
)
```

- [ ] **Step 3: Append the domain Group C section to `backend/app/api/routers.py`**

```python
from app.models.domain import Event, EventType, Resource, ResourceType, TimeCalendar, TimePeriod

# --- domain: group C (events, resources, time) ---

EventTypeCreate, EventTypeUpdate, EventTypeRead = make_crud_schemas(
    EventType, name="EventType", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=EventType,
        create_schema=EventTypeCreate,
        update_schema=EventTypeUpdate,
        read_schema=EventTypeRead,
        schema_name="domain",
        table_name="event_type",
    )
)

EventCreate, EventUpdate, EventRead = make_crud_schemas(Event, name="Event", readonly={"id"})
router.include_router(
    build_crud_router(
        model=Event,
        create_schema=EventCreate,
        update_schema=EventUpdate,
        read_schema=EventRead,
        schema_name="domain",
        table_name="event",
    )
)

ResourceTypeCreate, ResourceTypeUpdate, ResourceTypeRead = make_crud_schemas(
    ResourceType, name="ResourceType", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=ResourceType,
        create_schema=ResourceTypeCreate,
        update_schema=ResourceTypeUpdate,
        read_schema=ResourceTypeRead,
        schema_name="domain",
        table_name="resource_type",
    )
)

ResourceCreate, ResourceUpdate, ResourceRead = make_crud_schemas(
    Resource, name="Resource", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Resource,
        create_schema=ResourceCreate,
        update_schema=ResourceUpdate,
        read_schema=ResourceRead,
        schema_name="domain",
        table_name="resource",
    )
)

TimeCalendarCreate, TimeCalendarUpdate, TimeCalendarRead = make_crud_schemas(
    TimeCalendar, name="TimeCalendar", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=TimeCalendar,
        create_schema=TimeCalendarCreate,
        update_schema=TimeCalendarUpdate,
        read_schema=TimeCalendarRead,
        schema_name="domain",
        table_name="time_calendar",
    )
)

TimePeriodCreate, TimePeriodUpdate, TimePeriodRead = make_crud_schemas(
    TimePeriod, name="TimePeriod", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=TimePeriod,
        create_schema=TimePeriodCreate,
        update_schema=TimePeriodUpdate,
        read_schema=TimePeriodRead,
        schema_name="domain",
        table_name="time_period",
    )
)
```

- [ ] **Step 4: Write the failing test `backend/tests/test_crud_domain_c.py`**

```python
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
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


@pytest.fixture
def organization_id(auth_headers):
    client = TestClient(app)
    response = client.get("/api/iam/organization/", headers=auth_headers)
    items = response.json()["items"]
    default_org = next(item for item in items if item["code"] == "default")
    return default_org["id"]


def test_event_type_and_event(auth_headers):
    client = TestClient(app)

    event_type_response = client.post(
        "/api/domain/event_type/",
        json={"code": "leave-taken-c", "name": "Leave Taken"},
        headers=auth_headers,
    )
    assert event_type_response.status_code == 201
    event_type_id = event_type_response.json()["id"]

    event_response = client.post(
        "/api/domain/event/",
        json={"event_type_id": event_type_id, "occurred_at": "2026-01-05T09:00:00Z"},
        headers=auth_headers,
    )
    assert event_response.status_code == 201


def test_resource_type_and_resource(auth_headers):
    client = TestClient(app)

    resource_type_response = client.post(
        "/api/domain/resource_type/",
        json={"code": "room-c", "name": "Room"},
        headers=auth_headers,
    )
    assert resource_type_response.status_code == 201
    resource_type_id = resource_type_response.json()["id"]

    resource_response = client.post(
        "/api/domain/resource/",
        json={"resource_type_id": resource_type_id, "capacity": 30, "unit": "seats"},
        headers=auth_headers,
    )
    assert resource_response.status_code == 201


def test_time_calendar_and_time_period(auth_headers, organization_id):
    client = TestClient(app)

    calendar_response = client.post(
        "/api/domain/time_calendar/",
        json={"organization_id": organization_id, "code": "main-c", "name": "Main Calendar"},
        headers=auth_headers,
    )
    assert calendar_response.status_code == 201
    calendar_id = calendar_response.json()["id"]

    period_response = client.post(
        "/api/domain/time_period/",
        json={
            "calendar_id": calendar_id,
            "name": "Week 1",
            "start_time": "2026-01-05T00:00:00Z",
            "end_time": "2026-01-11T23:59:59Z",
            "metadata_": {"note": "first week"},
        },
        headers=auth_headers,
    )
    assert period_response.status_code == 201
    assert period_response.json()["metadata_"] == {"note": "first week"}
```

Run: `cd backend && pytest tests/test_crud_domain_c.py -v`
Expected: FAIL (404s on `/api/domain/event_type/...` etc.)

- [ ] **Step 5: Apply migrations and run tests against the real containers**

Run:
```bash
docker compose up -d postgres clickhouse
cd backend
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver alembic upgrade head
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver \
CLICKHOUSE_HOST=localhost JWT_SECRET=test-secret ADMIN_PASSWORD=change-me-admin \
pytest tests/test_crud_domain_c.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/domain.py backend/app/models/__init__.py backend/app/api/routers.py backend/tests/test_crud_domain_c.py
git commit -m "feat: domain group C models and CRUD routes (events, resources, time)"
```

---

## Task 16: `problem` schema Group A models + CRUD routes (problem, scenario, variables)

**Files:**
- Create: `backend/app/models/problem.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/routers.py` (append problem Group A section)
- Test: `backend/tests/test_crud_problem_a.py`

**Interfaces:**
- Consumes: `iam.organization`, `iam.user_account` (Task 10) via FK.
- Produces: SQLAlchemy models `Problem`, `Scenario`, `VariableDefinition`, `VariableDimension` in `app.models.problem` (new file). Task 17 adds more classes to this same file.

- [ ] **Step 1: Write `backend/app/models/problem.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPKMixin


class Problem(UUIDPKMixin, Base):
    __tablename__ = "problem"
    __table_args__ = {"schema": "problem"}

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.organization.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    problem_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="DRAFT")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("iam.user_account.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Scenario(UUIDPKMixin, Base):
    __tablename__ = "scenario"
    __table_args__ = {"schema": "problem"}

    problem_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.problem.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.scenario.id"), nullable=True
    )
    parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class VariableDefinition(UUIDPKMixin, Base):
    __tablename__ = "variable_definition"
    __table_args__ = {"schema": "problem"}

    problem_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.problem.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    variable_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    domain_definition: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class VariableDimension(UUIDPKMixin, Base):
    __tablename__ = "variable_dimension"
    __table_args__ = {"schema": "problem"}

    variable_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.variable_definition.id"), nullable=False
    )
    dimension_order: Mapped[int] = mapped_column(Integer, nullable=False)
    dimension_type: Mapped[str] = mapped_column(String(50), nullable=False)
    domain_source: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 2: Update `backend/app/models/__init__.py`**

```python
from app.models.problem import Problem, Scenario, VariableDefinition, VariableDimension  # noqa: F401
```

- [ ] **Step 3: Append the problem Group A section to `backend/app/api/routers.py`**

```python
from app.models.problem import Problem, Scenario, VariableDefinition, VariableDimension

# --- problem: group A (problem, scenario, variables) ---

ProblemCreate, ProblemUpdate, ProblemRead = make_crud_schemas(
    Problem, name="Problem", readonly={"id"}, server_default={"created_at"}
)
router.include_router(
    build_crud_router(
        model=Problem,
        create_schema=ProblemCreate,
        update_schema=ProblemUpdate,
        read_schema=ProblemRead,
        schema_name="problem",
        table_name="problem",
    )
)

ScenarioCreate, ScenarioUpdate, ScenarioRead = make_crud_schemas(
    Scenario, name="Scenario", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Scenario,
        create_schema=ScenarioCreate,
        update_schema=ScenarioUpdate,
        read_schema=ScenarioRead,
        schema_name="problem",
        table_name="scenario",
    )
)

VariableDefinitionCreate, VariableDefinitionUpdate, VariableDefinitionRead = make_crud_schemas(
    VariableDefinition, name="VariableDefinition", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=VariableDefinition,
        create_schema=VariableDefinitionCreate,
        update_schema=VariableDefinitionUpdate,
        read_schema=VariableDefinitionRead,
        schema_name="problem",
        table_name="variable_definition",
    )
)

VariableDimensionCreate, VariableDimensionUpdate, VariableDimensionRead = make_crud_schemas(
    VariableDimension, name="VariableDimension", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=VariableDimension,
        create_schema=VariableDimensionCreate,
        update_schema=VariableDimensionUpdate,
        read_schema=VariableDimensionRead,
        schema_name="problem",
        table_name="variable_dimension",
    )
)
```

- [ ] **Step 4: Write the failing test `backend/tests/test_crud_problem_a.py`**

```python
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
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


@pytest.fixture
def organization_id(auth_headers):
    client = TestClient(app)
    response = client.get("/api/iam/organization/", headers=auth_headers)
    items = response.json()["items"]
    default_org = next(item for item in items if item["code"] == "default")
    return default_org["id"]


@pytest.fixture
def problem_id(auth_headers, organization_id):
    client = TestClient(app)
    response = client.post(
        "/api/problem/problem/",
        json={
            "organization_id": organization_id,
            "code": "shift-scheduling-a",
            "name": "Shift Scheduling",
            "version": 1,
            "status": "DRAFT",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_scenario_create(auth_headers, problem_id):
    client = TestClient(app)
    response = client.post(
        "/api/problem/scenario/",
        json={"problem_id": problem_id, "code": "baseline-a", "name": "Baseline"},
        headers=auth_headers,
    )
    assert response.status_code == 201


def test_variable_definition_and_dimension(auth_headers, problem_id):
    client = TestClient(app)

    var_response = client.post(
        "/api/problem/variable_definition/",
        json={
            "problem_id": problem_id,
            "code": "employee_shift",
            "name": "Employee Shift Assignment",
            "variable_type": "BOOLEAN",
        },
        headers=auth_headers,
    )
    assert var_response.status_code == 201
    variable_id = var_response.json()["id"]

    dimension_response = client.post(
        "/api/problem/variable_dimension/",
        json={"variable_id": variable_id, "dimension_order": 0, "dimension_type": "ENTITY"},
        headers=auth_headers,
    )
    assert dimension_response.status_code == 201
```

Run: `cd backend && pytest tests/test_crud_problem_a.py -v`
Expected: FAIL (`ModuleNotFoundError: app.models.problem` / 404s)

- [ ] **Step 5: Apply migrations and run tests against the real containers**

Run:
```bash
docker compose up -d postgres clickhouse
cd backend
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver alembic upgrade head
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver \
CLICKHOUSE_HOST=localhost JWT_SECRET=test-secret ADMIN_PASSWORD=change-me-admin \
pytest tests/test_crud_problem_a.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/problem.py backend/app/models/__init__.py backend/app/api/routers.py backend/tests/test_crud_problem_a.py
git commit -m "feat: problem group A models and CRUD routes (problem, scenario, variables)"
```

---

## Task 17: `problem` schema Group B models + CRUD routes (constraints, objectives, parameters)

**Files:**
- Modify: `backend/app/models/problem.py` (append classes; add `Boolean`, `Numeric` to the existing import line)
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/routers.py` (append problem Group B section)
- Test: `backend/tests/test_crud_problem_b.py`

**Interfaces:**
- Consumes: `Problem` (Task 16), `domain.hierarchy`, `domain.hierarchy_node`, `domain.entity` (Tasks 13, 14) via FK.
- Produces: SQLAlchemy models `ConstraintDefinition`, `ConstraintScope`, `Objective`, `ObjectiveComponent`, `Parameter` in `app.models.problem`. This completes the `problem` schema — 9 tables total across Tasks 16-17, and all 31 tables from spec §4 now have CRUD routes.

- [ ] **Step 1: Update the import line at the top of `backend/app/models/problem.py`**

```python
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
```

- [ ] **Step 2: Append to `backend/app/models/problem.py`**

```python
class ConstraintDefinition(UUIDPKMixin, Base):
    __tablename__ = "constraint_definition"
    __table_args__ = {"schema": "problem"}

    problem_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.problem.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    constraint_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expression: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_hard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weight: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class ConstraintScope(UUIDPKMixin, Base):
    __tablename__ = "constraint_scope"
    __table_args__ = {"schema": "problem"}

    constraint_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.constraint_definition.id"), nullable=False
    )
    hierarchy_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.hierarchy.id"), nullable=True
    )
    hierarchy_node_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.hierarchy_node.id"), nullable=True
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("domain.entity.id"), nullable=True
    )
    scope_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Objective(UUIDPKMixin, Base):
    __tablename__ = "objective"
    __table_args__ = {"schema": "problem"}

    problem_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.problem.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    objective_type: Mapped[str] = mapped_column(String(30), nullable=False)
    expression: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class ObjectiveComponent(UUIDPKMixin, Base):
    __tablename__ = "objective_component"
    __table_args__ = {"schema": "problem"}

    objective_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.objective.id"), nullable=False
    )
    code: Mapped[str | None] = mapped_column(String(150), nullable=True)
    expression: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    weight: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Parameter(UUIDPKMixin, Base):
    __tablename__ = "parameter"
    __table_args__ = {"schema": "problem"}

    problem_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("problem.problem.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_runtime: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
```

- [ ] **Step 3: Update `backend/app/models/__init__.py`**

```python
from app.models.problem import (  # noqa: F401
    ConstraintDefinition,
    ConstraintScope,
    Objective,
    ObjectiveComponent,
    Parameter,
    Problem,
    Scenario,
    VariableDefinition,
    VariableDimension,
)
```

- [ ] **Step 4: Append the problem Group B section to `backend/app/api/routers.py`**

```python
from app.models.problem import (
    ConstraintDefinition,
    ConstraintScope,
    Objective,
    ObjectiveComponent,
    Parameter,
)

# --- problem: group B (constraints, objectives, parameters) ---

ConstraintDefinitionCreate, ConstraintDefinitionUpdate, ConstraintDefinitionRead = make_crud_schemas(
    ConstraintDefinition, name="ConstraintDefinition", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=ConstraintDefinition,
        create_schema=ConstraintDefinitionCreate,
        update_schema=ConstraintDefinitionUpdate,
        read_schema=ConstraintDefinitionRead,
        schema_name="problem",
        table_name="constraint_definition",
    )
)

ConstraintScopeCreate, ConstraintScopeUpdate, ConstraintScopeRead = make_crud_schemas(
    ConstraintScope, name="ConstraintScope", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=ConstraintScope,
        create_schema=ConstraintScopeCreate,
        update_schema=ConstraintScopeUpdate,
        read_schema=ConstraintScopeRead,
        schema_name="problem",
        table_name="constraint_scope",
    )
)

ObjectiveCreate, ObjectiveUpdate, ObjectiveRead = make_crud_schemas(
    Objective, name="Objective", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Objective,
        create_schema=ObjectiveCreate,
        update_schema=ObjectiveUpdate,
        read_schema=ObjectiveRead,
        schema_name="problem",
        table_name="objective",
    )
)

ObjectiveComponentCreate, ObjectiveComponentUpdate, ObjectiveComponentRead = make_crud_schemas(
    ObjectiveComponent, name="ObjectiveComponent", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=ObjectiveComponent,
        create_schema=ObjectiveComponentCreate,
        update_schema=ObjectiveComponentUpdate,
        read_schema=ObjectiveComponentRead,
        schema_name="problem",
        table_name="objective_component",
    )
)

ParameterCreate, ParameterUpdate, ParameterRead = make_crud_schemas(
    Parameter, name="Parameter", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Parameter,
        create_schema=ParameterCreate,
        update_schema=ParameterUpdate,
        read_schema=ParameterRead,
        schema_name="problem",
        table_name="parameter",
    )
)
```

- [ ] **Step 5: Write the failing test `backend/tests/test_crud_problem_b.py`**

```python
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
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


@pytest.fixture
def organization_id(auth_headers):
    client = TestClient(app)
    response = client.get("/api/iam/organization/", headers=auth_headers)
    items = response.json()["items"]
    default_org = next(item for item in items if item["code"] == "default")
    return default_org["id"]


@pytest.fixture
def problem_id(auth_headers, organization_id):
    client = TestClient(app)
    response = client.post(
        "/api/problem/problem/",
        json={
            "organization_id": organization_id,
            "code": "shift-scheduling-b",
            "name": "Shift Scheduling",
            "version": 1,
            "status": "DRAFT",
        },
        headers=auth_headers,
    )
    return response.json()["id"]


def test_constraint_definition_and_scope(auth_headers, problem_id):
    client = TestClient(app)

    constraint_response = client.post(
        "/api/problem/constraint_definition/",
        json={
            "problem_id": problem_id,
            "code": "max-weekly-hours",
            "name": "Max Weekly Hours",
            "is_hard": True,
        },
        headers=auth_headers,
    )
    assert constraint_response.status_code == 201
    constraint_id = constraint_response.json()["id"]

    scope_response = client.post(
        "/api/problem/constraint_scope/",
        json={"constraint_id": constraint_id, "scope_type": "GLOBAL"},
        headers=auth_headers,
    )
    assert scope_response.status_code == 201


def test_objective_and_component(auth_headers, problem_id):
    client = TestClient(app)

    objective_response = client.post(
        "/api/problem/objective/",
        json={
            "problem_id": problem_id,
            "code": "minimize-cost",
            "name": "Minimize Cost",
            "objective_type": "MINIMIZE",
        },
        headers=auth_headers,
    )
    assert objective_response.status_code == 201
    objective_id = objective_response.json()["id"]

    component_response = client.post(
        "/api/problem/objective_component/",
        json={"objective_id": objective_id, "code": "overtime-penalty", "weight": 10},
        headers=auth_headers,
    )
    assert component_response.status_code == 201


def test_parameter_create(auth_headers, problem_id):
    client = TestClient(app)
    response = client.post(
        "/api/problem/parameter/",
        json={"problem_id": problem_id, "code": "max_overtime_hours", "data_type": "number", "value": 10},
        headers=auth_headers,
    )
    assert response.status_code == 201
```

Run: `cd backend && pytest tests/test_crud_problem_b.py -v`
Expected: FAIL (404s on `/api/problem/constraint_definition/...` etc.)

- [ ] **Step 6: Apply migrations and run tests against the real containers**

Run:
```bash
docker compose up -d postgres clickhouse
cd backend
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver alembic upgrade head
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver \
CLICKHOUSE_HOST=localhost JWT_SECRET=test-secret ADMIN_PASSWORD=change-me-admin \
pytest tests/ -v
```
Expected: PASS — this runs the full backend test suite (Tasks 3-17) together for the first time; all files' tests should be green now that all 31 tables are wired.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/problem.py backend/app/models/__init__.py backend/app/api/routers.py backend/tests/test_crud_problem_b.py
git commit -m "feat: problem group B models and CRUD routes (constraints, objectives, parameters)"
```

---

## Task 18: Metadata endpoint (`/api/meta/schema`)

**Files:**
- Create: `backend/app/api/meta.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_meta_schema.py`

**Interfaces:**
- Consumes: `app.crud.registry.TABLE_REGISTRY` (Task 12, populated by every `build_crud_router` call from Tasks 12-17).
- Produces: `GET /api/meta/schema` (authenticated) returning a JSON array of `{"schema": str, "table": str, "fields": [{"name": str, "type": "string"|"integer"|"number"|"boolean"|"date"|"datetime"|"uuid"|"json", "required": bool, "writable": bool, "is_fk": bool, "fk_table": str|None}]}`, one entry per registered table (31 by this point). This is the single source of truth Tasks 20-22 (frontend nav, DataTable, EntityForm) read from — no hardcoded table/field list on the frontend.

- [ ] **Step 1: Write `backend/app/api/meta.py`**

```python
import datetime
import typing
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import inspect

from app.api.deps import get_current_user
from app.crud.registry import TABLE_REGISTRY
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/meta", tags=["meta"])

_TYPE_LABELS: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    datetime.date: "date",
    datetime.datetime: "datetime",
    uuid.UUID: "uuid",
}


def _type_label(annotation) -> str:
    """Unwrap Optional[...] and map to a simple label the frontend
    renders directly (falls back to "json" for JSONB/Any columns)."""
    args = typing.get_args(annotation)
    base = args[0] if args else annotation
    return _TYPE_LABELS.get(base, "json")


@router.get("/schema")
def get_schema(_: UserAccount = Depends(get_current_user)) -> list[dict]:
    tables = []
    for meta in TABLE_REGISTRY:
        mapper = inspect(meta.model)
        fk_table_by_field: dict[str, str] = {}
        for attr in mapper.column_attrs:
            column = attr.columns[0]
            for fk in column.foreign_keys:
                fk_table_by_field[attr.key] = fk.column.table.fullname
                break

        writable_fields = set(meta.create_schema.model_fields)

        fields = []
        for field_name, field_info in meta.read_schema.model_fields.items():
            fields.append(
                {
                    "name": field_name,
                    "type": _type_label(field_info.annotation),
                    "required": field_info.is_required(),
                    "writable": field_name in writable_fields,
                    "is_fk": field_name in fk_table_by_field,
                    "fk_table": fk_table_by_field.get(field_name),
                }
            )

        tables.append({"schema": meta.schema, "table": meta.table, "fields": fields})

    return tables
```

- [ ] **Step 2: Wire the router into `backend/app/main.py`**

```python
from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.meta import router as meta_router
from app.api.routers import router as crud_router
from app.clickhouse_schema import create_analytics_schema
from app.core.db import SessionLocal, get_clickhouse_client
from app.seed import seed_admin

app = FastAPI(title="Problem Solver Platform API")

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(meta_router)
app.include_router(crud_router)


@app.on_event("startup")
def on_startup() -> None:
    create_analytics_schema(get_clickhouse_client())
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()
```

- [ ] **Step 3: Write the failing test `backend/tests/test_meta_schema.py`**

```python
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
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


def test_meta_schema_requires_auth():
    client = TestClient(app)
    response = client.get("/api/meta/schema")
    assert response.status_code == 401


def test_meta_schema_lists_all_31_tables(auth_headers):
    client = TestClient(app)
    response = client.get("/api/meta/schema", headers=auth_headers)
    assert response.status_code == 200
    tables = response.json()
    assert len(tables) == 31


def test_meta_schema_flags_foreign_keys_and_readonly_id(auth_headers):
    client = TestClient(app)
    response = client.get("/api/meta/schema", headers=auth_headers)
    tables = {(t["schema"], t["table"]): t for t in response.json()}

    entity = tables[("domain", "entity")]
    fields_by_name = {f["name"]: f for f in entity["fields"]}

    assert fields_by_name["id"]["writable"] is False
    assert fields_by_name["organization_id"]["is_fk"] is True
    assert fields_by_name["organization_id"]["fk_table"] == "iam.organization"
```

Run: `cd backend && pytest tests/test_meta_schema.py -v`
Expected: FAIL (`ModuleNotFoundError: app.api.meta`)

- [ ] **Step 4: Run tests against the real containers to verify they pass**

Run:
```bash
docker compose up -d postgres clickhouse
cd backend
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver \
CLICKHOUSE_HOST=localhost JWT_SECRET=test-secret ADMIN_PASSWORD=change-me-admin \
pytest tests/test_meta_schema.py -v
```
Expected: PASS

- [ ] **Step 5: Rebuild backend and confirm the full backend test suite is green**

Run:
```bash
docker compose up -d --build backend
DATABASE_URL=postgresql+psycopg2://solver:change-me@localhost:5544/solver \
CLICKHOUSE_HOST=localhost JWT_SECRET=test-secret ADMIN_PASSWORD=change-me-admin \
pytest -v
```
Expected: all tests across `tests/test_*.py` PASS. This is the last backend task — the API surface is complete.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/meta.py backend/app/main.py backend/tests/test_meta_schema.py
git commit -m "feat: metadata endpoint describing all registered tables for the frontend"
```

---

## Task 19: Frontend scaffold — Vite/TS/Tailwind, API client, Login page, Docker

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/index.css`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/pages/Login.tsx`
- Create: `frontend/src/test/setup.ts`
- Test: `frontend/src/api/client.test.ts`
- Test: `frontend/src/pages/Login.test.tsx`
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Modify: `docker-compose.yml` (add `frontend` service)

**Interfaces:**
- Consumes: `POST /api/auth/login` (Task 10) via `fetch`.
- Produces: `apiFetch<T>(path: string, options?: RequestInit): Promise<T>` in `src/api/client.ts` — every later frontend task (20-23) uses this for all backend calls; it attaches the stored bearer token, redirects to `/login` and clears the token on a 401. `getToken(): string | null`, `setToken(token: string | null): void`. `login(username: string, password: string): Promise<string>`. Vite/nginx both proxy `/api/*` to the backend, so frontend code always calls paths starting with `/api/...` exactly as the backend defines them (no extra prefixing).

- [ ] **Step 1: Write `frontend/package.json`**

```json
{
  "name": "solver-frontend",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.2",
    "@tanstack/react-query": "^5.56.2"
  },
  "devDependencies": {
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.3",
    "tailwindcss": "^3.4.10",
    "postcss": "^8.4.45",
    "autoprefixer": "^10.4.20",
    "vitest": "^2.0.5",
    "@testing-library/react": "^16.0.1",
    "@testing-library/jest-dom": "^6.5.0",
    "jsdom": "^25.0.0"
  }
}
```

- [ ] **Step 2: Write `frontend/vite.config.ts`**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8010",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
```

- [ ] **Step 3: Write `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Write `frontend/tailwind.config.js` and `frontend/postcss.config.js`**

```javascript
// tailwind.config.js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
```

```javascript
// postcss.config.js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 5: Write `frontend/index.html` and `frontend/src/index.css`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Problem Solver Platform</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

```css
/* src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 6: Write `frontend/src/test/setup.ts`**

```typescript
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 7: Write the failing test `frontend/src/api/client.test.ts`**

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, getToken, setToken } from "./client";

describe("apiFetch", () => {
  beforeEach(() => {
    setToken(null);
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("attaches the Authorization header when a token is stored", async () => {
    setToken("test-token");
    (fetch as any).mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await apiFetch("/api/iam/organization/");

    const [, options] = (fetch as any).mock.calls[0];
    expect(options.headers.get("Authorization")).toBe("Bearer test-token");
  });

  it("clears the token and throws on a 401 response", async () => {
    setToken("stale-token");
    (fetch as any).mockResolvedValue(new Response("unauthorized", { status: 401 }));

    await expect(apiFetch("/api/iam/organization/")).rejects.toThrow();
    expect(getToken()).toBeNull();
  });
});
```

Run: `cd frontend && npm install && npm test -- client.test.ts`
Expected: FAIL (`Cannot find module './client'`)

- [ ] **Step 8: Write `frontend/src/api/client.ts`**

```typescript
const TOKEN_KEY = "solver_token";

export function setToken(token: string | null) {
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // localStorage unavailable (private mode, etc.) — token just won't persist
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (!(options.body instanceof URLSearchParams)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(path, { ...options, headers });

  if (response.status === 401) {
    setToken(null);
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new ApiError(401, "unauthorized");
  }

  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(response.status, body || response.statusText);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export async function login(username: string, password: string): Promise<string> {
  const body = new URLSearchParams({ username, password });
  const response = await fetch("/api/auth/login", { method: "POST", body });
  if (!response.ok) {
    throw new ApiError(response.status, "invalid credentials");
  }
  const data = await response.json();
  setToken(data.access_token);
  return data.access_token as string;
}
```

- [ ] **Step 9: Run the client test to verify it passes**

Run: `cd frontend && npm test -- client.test.ts`
Expected: PASS

- [ ] **Step 10: Write the failing test `frontend/src/pages/Login.test.tsx`**

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Login from "./Login";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, login: vi.fn() };
});

import { login } from "../api/client";

describe("Login page", () => {
  beforeEach(() => {
    (login as any).mockResolvedValue("fake-token");
  });

  it("calls login with the entered credentials on submit", async () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByTestId("username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByTestId("password"), { target: { value: "secret" } });
    fireEvent.click(screen.getByText("Sign in"));

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith("admin", "secret");
    });
  });
});
```

Run: `cd frontend && npm test -- Login.test.tsx`
Expected: FAIL (`Cannot find module './Login'`)

- [ ] **Step 11: Write `frontend/src/pages/Login.tsx`**

```tsx
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/client";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await login(username, password);
      navigate("/");
    } catch {
      setError("Invalid username or password");
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <h1 className="text-lg font-semibold text-slate-900">Sign in</h1>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div>
          <label className="block text-sm font-medium text-slate-700">Username</label>
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            data-testid="username"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700">Password</label>
          <input
            type="password"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="password"
          />
        </div>
        <button
          type="submit"
          className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          Sign in
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 12: Write `frontend/src/App.tsx` and `frontend/src/main.tsx`**

```tsx
// src/App.tsx
import { Navigate, Route, Routes } from "react-router-dom";
import Login from "./pages/Login";
import { getToken } from "./api/client";

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function Placeholder() {
  return <div className="p-6">Logged in.</div>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <Placeholder />
          </RequireAuth>
        }
      />
    </Routes>
  );
}
```

```tsx
// src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
```

- [ ] **Step 13: Run the Login test to verify it passes**

Run: `cd frontend && npm test -- Login.test.tsx`
Expected: PASS

- [ ] **Step 14: Write `frontend/Dockerfile` and `frontend/nginx.conf`**

```dockerfile
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

```nginx
server {
    listen 80;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        root /usr/share/nginx/html;
        try_files $uri /index.html;
    }
}
```

- [ ] **Step 15: Add the `frontend` service to `docker-compose.yml`**

```yaml
  frontend:
    build: ./frontend
    restart: unless-stopped
    ports:
      - "3010:80"
    depends_on:
      - backend
    networks:
      - solver_net
```

- [ ] **Step 16: Run the full frontend test suite, then build through Docker**

Run:
```bash
cd frontend && npm test
docker compose up -d --build frontend
curl -I http://localhost:3010
```
Expected: all Vitest tests pass; `curl` returns `HTTP/1.1 200 OK`.

- [ ] **Step 17: Commit**

```bash
git add frontend docker-compose.yml
git commit -m "feat: frontend scaffold with API client, auth, and Docker build"
```

---

## Task 20: `AppShell` layout with metadata-driven sidebar

**Files:**
- Create: `frontend/src/types/meta.ts`
- Create: `frontend/src/api/meta.ts`
- Create: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/components/AppShell.test.tsx`

**Interfaces:**
- Consumes: `apiFetch` (Task 19), `GET /api/meta/schema` (Task 18).
- Produces: `TableMeta`/`FieldMeta` TypeScript types in `src/types/meta.ts` — Tasks 21-22 import these. `useSchema()` React Query hook in `src/api/meta.ts` returning `TableMeta[]`, cached (`staleTime: Infinity` — the schema only changes on a backend deploy). `AppShell` component (sidebar + `<Outlet/>`) used as the layout route in `App.tsx`.

- [ ] **Step 1: Write `frontend/src/types/meta.ts`**

```typescript
export type FieldType = "string" | "integer" | "number" | "boolean" | "date" | "datetime" | "uuid" | "json";

export type FieldMeta = {
  name: string;
  type: FieldType;
  required: boolean;
  writable: boolean;
  is_fk: boolean;
  fk_table: string | null;
};

export type TableMeta = {
  schema: string;
  table: string;
  fields: FieldMeta[];
};
```

- [ ] **Step 2: Write `frontend/src/api/meta.ts`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { TableMeta } from "../types/meta";

export function useSchema() {
  return useQuery({
    queryKey: ["meta", "schema"],
    queryFn: () => apiFetch<TableMeta[]>("/api/meta/schema"),
    staleTime: Infinity,
  });
}
```

- [ ] **Step 3: Write the failing test `frontend/src/components/AppShell.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppShell from "./AppShell";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderWithProviders() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    (apiFetch as any).mockResolvedValue([
      { schema: "iam", table: "organization", fields: [] },
      { schema: "domain", table: "entity", fields: [] },
    ]);
  });

  it("renders a nav group per schema with a link per table", async () => {
    renderWithProviders();

    expect(await screen.findByText("organization")).toBeInTheDocument();
    expect(screen.getByText("entity")).toBeInTheDocument();
    expect(screen.getByText("iam")).toBeInTheDocument();
    expect(screen.getByText("domain")).toBeInTheDocument();
  });
});
```

Run: `cd frontend && npm test -- AppShell.test.tsx`
Expected: FAIL (`Cannot find module './AppShell'`)

- [ ] **Step 4: Write `frontend/src/components/AppShell.tsx`**

```tsx
import { Link, Outlet, useNavigate } from "react-router-dom";
import { setToken } from "../api/client";
import { useSchema } from "../api/meta";
import type { TableMeta } from "../types/meta";

export default function AppShell() {
  const { data: tables, isLoading, error } = useSchema();
  const navigate = useNavigate();

  const grouped: Record<string, TableMeta[]> = {};
  for (const t of tables ?? []) {
    (grouped[t.schema] ??= []).push(t);
  }

  function handleLogout() {
    setToken(null);
    navigate("/login");
  }

  return (
    <div className="flex min-h-screen">
      <aside className="w-64 shrink-0 border-r border-slate-200 bg-white p-4">
        <div className="mb-4 flex items-center justify-between">
          <span className="font-semibold text-slate-900">Problem Solver</span>
          <button onClick={handleLogout} className="text-xs text-slate-500 hover:text-slate-900">
            Sign out
          </button>
        </div>
        <Link to="/" className="mb-4 block text-sm text-slate-600 hover:text-slate-900">
          Dashboard
        </Link>
        {isLoading && <p className="text-sm text-slate-400">Loading navigation…</p>}
        {error && <p className="text-sm text-red-600">Failed to load navigation</p>}
        {Object.entries(grouped).map(([schemaName, schemaTables]) => (
          <div key={schemaName} className="mb-4">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
              {schemaName}
            </div>
            <ul>
              {schemaTables.map((t) => (
                <li key={`${t.schema}.${t.table}`}>
                  <Link
                    to={`/${t.schema}/${t.table}`}
                    className="block rounded px-2 py-1 text-sm text-slate-700 hover:bg-slate-100"
                  >
                    {t.table}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </aside>
      <main className="flex-1 bg-slate-50 p-6">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Update `frontend/src/App.tsx` to use `AppShell` as the layout route**

```tsx
import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import Login from "./pages/Login";
import { getToken } from "./api/client";

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function Placeholder() {
  return <div>Select a table from the sidebar.</div>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Placeholder />} />
        <Route path=":schemaName/:tableName" element={<Placeholder />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd frontend && npm test -- AppShell.test.tsx`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types frontend/src/api/meta.ts frontend/src/components/AppShell.tsx frontend/src/App.tsx frontend/src/components/AppShell.test.tsx
git commit -m "feat: metadata-driven AppShell sidebar"
```

---

## Task 21: Generic `DataTable` component + `EntityList` page

**Files:**
- Create: `frontend/src/api/entities.ts`
- Create: `frontend/src/components/DataTable.tsx`
- Create: `frontend/src/pages/EntityList.tsx`
- Modify: `frontend/src/App.tsx` (wire the `:schemaName/:tableName` route to `EntityList`)
- Test: `frontend/src/components/DataTable.test.tsx`
- Test: `frontend/src/pages/EntityList.test.tsx`

**Interfaces:**
- Consumes: `apiFetch` (Task 19), `useSchema` (Task 20), `TableMeta`/`FieldMeta` (Task 20).
- Produces: `useEntityList(schemaName, tableName, limit, offset)` and `useDeleteEntity(schemaName, tableName)` React Query hooks in `src/api/entities.ts` — Task 22 appends `useEntity`, `useCreateEntity`, `useUpdateEntity` to this same file. `DataTable` component with props `{fields: FieldMeta[], rows: Record<string,unknown>[], total: number, limit: number, offset: number, onPageChange: (offset: number) => void, onDelete: (id: string) => void, onRowClick?: (id: string) => void}` — reused as-is by nothing else this phase, but its prop shape is what Task 22 matches when it needs equivalent read-only rendering.

- [ ] **Step 1: Write `frontend/src/api/entities.ts`**

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type ListResult<T = Record<string, unknown>> = { items: T[]; total: number };

export function useEntityList(schemaName: string, tableName: string, limit: number, offset: number) {
  return useQuery({
    queryKey: ["entities", schemaName, tableName, limit, offset],
    queryFn: () =>
      apiFetch<ListResult>(`/api/${schemaName}/${tableName}/?limit=${limit}&offset=${offset}`),
    enabled: Boolean(schemaName && tableName),
  });
}

export function useDeleteEntity(schemaName: string, tableName: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/api/${schemaName}/${tableName}/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["entities", schemaName, tableName] }),
  });
}
```

- [ ] **Step 2: Write the failing test `frontend/src/components/DataTable.test.tsx`**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DataTable from "./DataTable";

const fields = [
  { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
  { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null },
];

const rows = [{ id: "1", code: "employee" }];

describe("DataTable", () => {
  it("renders rows and pagination info", () => {
    render(
      <DataTable
        fields={fields}
        rows={rows}
        total={1}
        limit={20}
        offset={0}
        onPageChange={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(screen.getByText("employee")).toBeInTheDocument();
    expect(screen.getByText("1-1 of 1")).toBeInTheDocument();
  });

  it("calls onDelete with the row id when Delete is clicked", () => {
    const onDelete = vi.fn();
    render(
      <DataTable
        fields={fields}
        rows={rows}
        total={1}
        limit={20}
        offset={0}
        onPageChange={vi.fn()}
        onDelete={onDelete}
      />
    );

    fireEvent.click(screen.getByText("Delete"));
    expect(onDelete).toHaveBeenCalledWith("1");
  });

  it("calls onPageChange with the next offset", () => {
    const onPageChange = vi.fn();
    render(
      <DataTable
        fields={fields}
        rows={rows}
        total={50}
        limit={20}
        offset={0}
        onPageChange={onPageChange}
        onDelete={vi.fn()}
      />
    );

    fireEvent.click(screen.getByText("Next"));
    expect(onPageChange).toHaveBeenCalledWith(20);
  });

  it("calls onRowClick when a row is clicked, but not when Delete is clicked", () => {
    const onRowClick = vi.fn();
    const onDelete = vi.fn();
    render(
      <DataTable
        fields={fields}
        rows={rows}
        total={1}
        limit={20}
        offset={0}
        onPageChange={vi.fn()}
        onDelete={onDelete}
        onRowClick={onRowClick}
      />
    );

    fireEvent.click(screen.getByText("employee"));
    expect(onRowClick).toHaveBeenCalledWith("1");

    onRowClick.mockClear();
    fireEvent.click(screen.getByText("Delete"));
    expect(onRowClick).not.toHaveBeenCalled();
    expect(onDelete).toHaveBeenCalledWith("1");
  });
});
```

Run: `cd frontend && npm test -- DataTable.test.tsx`
Expected: FAIL (`Cannot find module './DataTable'`)

- [ ] **Step 3: Write `frontend/src/components/DataTable.tsx`**

```tsx
import type { FieldMeta } from "../types/meta";

type Row = Record<string, unknown>;

type DataTableProps = {
  fields: FieldMeta[];
  rows: Row[];
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
  onDelete: (id: string) => void;
  onRowClick?: (id: string) => void;
};

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function DataTable({
  fields,
  rows,
  total,
  limit,
  offset,
  onPageChange,
  onDelete,
  onRowClick,
}: DataTableProps) {
  const columns = fields.map((f) => f.name);

  return (
    <div>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-slate-500">
            {columns.map((col) => (
              <th key={col} className="px-3 py-2 font-medium">
                {col}
              </th>
            ))}
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={String(row.id)}
              onClick={() => onRowClick?.(String(row.id))}
              className={`border-b border-slate-100 hover:bg-slate-50 ${onRowClick ? "cursor-pointer" : ""}`}
            >
              {columns.map((col) => (
                <td key={col} className="px-3 py-2">
                  {formatCell(row[col])}
                </td>
              ))}
              <td className="px-3 py-2 text-right">
                <button
                  className="text-xs text-red-600 hover:underline"
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete(String(row.id));
                  }}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex items-center justify-between text-sm text-slate-500">
        <span>
          {total === 0 ? "0 rows" : `${offset + 1}-${Math.min(offset + limit, total)} of ${total}`}
        </span>
        <div className="space-x-2">
          <button
            disabled={offset === 0}
            onClick={() => onPageChange(Math.max(0, offset - limit))}
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
          >
            Previous
          </button>
          <button
            disabled={offset + limit >= total}
            onClick={() => onPageChange(offset + limit)}
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the DataTable test to verify it passes**

Run: `cd frontend && npm test -- DataTable.test.tsx`
Expected: PASS

- [ ] **Step 5: Write the failing test `frontend/src/pages/EntityList.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntityList from "./EntityList";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderWithProviders() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/domain/entity_type"]}>
        <Routes>
          <Route path=":schemaName/:tableName" element={<EntityList />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("EntityList", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      return Promise.resolve({ items: [{ id: "1", code: "employee" }], total: 1 });
    });
  });

  it("renders rows using the metadata field list", async () => {
    renderWithProviders();

    expect(await screen.findByText("employee")).toBeInTheDocument();
    expect(screen.getByText("domain.entity_type")).toBeInTheDocument();
  });
});
```

Run: `cd frontend && npm test -- EntityList.test.tsx`
Expected: FAIL (`Cannot find module './EntityList'`)

- [ ] **Step 6: Write `frontend/src/pages/EntityList.tsx`**

```tsx
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import DataTable from "../components/DataTable";
import { useDeleteEntity, useEntityList } from "../api/entities";
import { useSchema } from "../api/meta";

const PAGE_SIZE = 20;

export default function EntityList() {
  const { schemaName = "", tableName = "" } = useParams();
  const [offset, setOffset] = useState(0);
  const navigate = useNavigate();

  const { data: tables } = useSchema();
  const table = tables?.find((t) => t.schema === schemaName && t.table === tableName);

  const { data, isLoading, error } = useEntityList(schemaName, tableName, PAGE_SIZE, offset);
  const deleteEntity = useDeleteEntity(schemaName, tableName);

  if (!table) {
    return <p className="text-sm text-slate-400">Loading table definition…</p>;
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">
          {schemaName}.{tableName}
        </h1>
        <Link
          to={`/${schemaName}/${tableName}/new`}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700"
        >
          New
        </Link>
      </div>
      {isLoading && <p className="text-sm text-slate-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">Failed to load rows</p>}
      {data && (
        <DataTable
          fields={table.fields}
          rows={data.items}
          total={data.total}
          limit={PAGE_SIZE}
          offset={offset}
          onPageChange={setOffset}
          onDelete={(id) => deleteEntity.mutate(id)}
          onRowClick={(id) => navigate(`/${schemaName}/${tableName}/${id}`)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 7: Wire the list route in `frontend/src/App.tsx`**

Replace the `:schemaName/:tableName` route's element (still `Placeholder`) with `EntityList`:

```tsx
import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import Login from "./pages/Login";
import EntityList from "./pages/EntityList";
import { getToken } from "./api/client";

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function Placeholder() {
  return <div>Select a table from the sidebar.</div>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Placeholder />} />
        <Route path=":schemaName/:tableName" element={<EntityList />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 8: Run the EntityList test to verify it passes**

Run: `cd frontend && npm test -- EntityList.test.tsx`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/entities.ts frontend/src/components/DataTable.tsx frontend/src/pages/EntityList.tsx frontend/src/App.tsx frontend/src/components/DataTable.test.tsx frontend/src/pages/EntityList.test.tsx
git commit -m "feat: generic DataTable component and EntityList page"
```

---

## Task 22: Generic `EntityForm` component + `EntityDetail` page (create/edit)

**Files:**
- Modify: `frontend/src/api/entities.ts` (append `useEntity`, `useCreateEntity`, `useUpdateEntity`)
- Create: `frontend/src/components/EntityForm.tsx`
- Create: `frontend/src/pages/EntityDetail.tsx`
- Modify: `frontend/src/App.tsx` (add `new` and `:id` routes)
- Test: `frontend/src/components/EntityForm.test.tsx`
- Test: `frontend/src/pages/EntityDetail.test.tsx`

**Interfaces:**
- Consumes: `apiFetch` (Task 19), `FieldMeta` (Task 20), `ListResult` (Task 21).
- Produces: `useEntity(schemaName, tableName, id) `, `useCreateEntity(schemaName, tableName)`, `useUpdateEntity(schemaName, tableName, id)` in `src/api/entities.ts`. `EntityForm` component with props `{fields: FieldMeta[], initialValues?: Record<string,unknown>, onSubmit: (values: Record<string,unknown>) => void, submitLabel: string}` — renders only `writable` fields, omits empty optional fields from the submitted payload, coerces numbers, parses JSON textareas, and renders FK fields as a `<select>` populated from the referenced table.

- [ ] **Step 1: Append to `frontend/src/api/entities.ts`**

```typescript
export function useEntity(schemaName: string, tableName: string, id: string | undefined) {
  return useQuery({
    queryKey: ["entity", schemaName, tableName, id],
    queryFn: () => apiFetch<Record<string, unknown>>(`/api/${schemaName}/${tableName}/${id}`),
    enabled: Boolean(schemaName && tableName && id),
  });
}

export function useCreateEntity(schemaName: string, tableName: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiFetch(`/api/${schemaName}/${tableName}/`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["entities", schemaName, tableName] }),
  });
}

export function useUpdateEntity(schemaName: string, tableName: string, id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiFetch(`/api/${schemaName}/${tableName}/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["entities", schemaName, tableName] });
      queryClient.invalidateQueries({ queryKey: ["entity", schemaName, tableName, id] });
    },
  });
}
```

- [ ] **Step 2: Write the failing test `frontend/src/components/EntityForm.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntityForm from "./EntityForm";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const fields = [
  { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
  { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null },
  { name: "is_active", type: "boolean" as const, required: true, writable: true, is_fk: false, fk_table: null },
  {
    name: "organization_id",
    type: "uuid" as const,
    required: false,
    writable: true,
    is_fk: true,
    fk_table: "iam.organization",
  },
];

function renderWithProviders(onSubmit = vi.fn()) {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <EntityForm fields={fields} onSubmit={onSubmit} submitLabel="Create" />
    </QueryClientProvider>
  );
  return onSubmit;
}

describe("EntityForm", () => {
  beforeEach(() => {
    (apiFetch as any).mockResolvedValue({ items: [{ id: "org-1", code: "acme" }], total: 1 });
  });

  it("does not render non-writable fields", () => {
    renderWithProviders();
    expect(screen.queryByTestId("field-id")).not.toBeInTheDocument();
  });

  it("renders a checkbox for boolean fields and a select populated from the FK table", async () => {
    renderWithProviders();
    expect(screen.getByTestId("field-is_active")).toHaveAttribute("type", "checkbox");
    expect(await screen.findByText("acme")).toBeInTheDocument();
  });

  it("submits typed values and omits empty optional fields", async () => {
    const onSubmit = renderWithProviders();

    fireEvent.change(screen.getByTestId("field-code"), { target: { value: "employee" } });
    fireEvent.click(screen.getByTestId("field-is_active"));
    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({ code: "employee", is_active: true });
    });
  });
});
```

Run: `cd frontend && npm test -- EntityForm.test.tsx`
Expected: FAIL (`Cannot find module './EntityForm'`)

- [ ] **Step 3: Write `frontend/src/components/EntityForm.tsx`**

```tsx
import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import type { ListResult } from "../api/entities";
import type { FieldMeta } from "../types/meta";

type EntityFormProps = {
  fields: FieldMeta[];
  initialValues?: Record<string, unknown>;
  onSubmit: (values: Record<string, unknown>) => void;
  submitLabel: string;
};

function defaultValueFor(field: FieldMeta): unknown {
  return field.type === "boolean" ? false : "";
}

function FkSelect({
  fkTable,
  value,
  onChange,
}: {
  fkTable: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [schemaName, tableName] = fkTable.split(".");
  const { data } = useQuery({
    queryKey: ["fk-options", fkTable],
    queryFn: () => apiFetch<ListResult>(`/api/${schemaName}/${tableName}/?limit=200&offset=0`),
  });

  return (
    <select
      className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">—</option>
      {data?.items.map((row) => (
        <option key={String(row.id)} value={String(row.id)}>
          {String((row as Record<string, unknown>).code ?? (row as Record<string, unknown>).name ?? row.id)}
        </option>
      ))}
    </select>
  );
}

export default function EntityForm({ fields, initialValues, onSubmit, submitLabel }: EntityFormProps) {
  const writableFields = fields.filter((f) => f.writable);
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {};
    for (const field of writableFields) {
      initial[field.name] = initialValues?.[field.name] ?? defaultValueFor(field);
    }
    return initial;
  });

  function setField(name: string, value: unknown) {
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const payload: Record<string, unknown> = {};
    for (const field of writableFields) {
      const raw = values[field.name];
      if (raw === "") {
        continue; // omit empty optional fields so the backend/DB default applies
      }
      if (field.type === "json" && typeof raw === "string") {
        try {
          payload[field.name] = JSON.parse(raw);
        } catch {
          payload[field.name] = raw;
        }
      } else if (field.type === "integer" || field.type === "number") {
        payload[field.name] = Number(raw);
      } else {
        payload[field.name] = raw;
      }
    }
    onSubmit(payload);
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-xl space-y-4">
      {writableFields.map((field) => (
        <div key={field.name}>
          <label className="block text-sm font-medium text-slate-700">
            {field.name}
            {field.required && <span className="text-red-500"> *</span>}
          </label>
          {field.is_fk && field.fk_table ? (
            <FkSelect
              fkTable={field.fk_table}
              value={String(values[field.name] ?? "")}
              onChange={(v) => setField(field.name, v)}
            />
          ) : field.type === "boolean" ? (
            <input
              type="checkbox"
              checked={Boolean(values[field.name])}
              onChange={(e) => setField(field.name, e.target.checked)}
              data-testid={`field-${field.name}`}
            />
          ) : field.type === "json" ? (
            <textarea
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs"
              rows={4}
              value={
                typeof values[field.name] === "string"
                  ? (values[field.name] as string)
                  : JSON.stringify(values[field.name] ?? "")
              }
              onChange={(e) => setField(field.name, e.target.value)}
              data-testid={`field-${field.name}`}
            />
          ) : (
            <input
              type={
                field.type === "integer" || field.type === "number"
                  ? "number"
                  : field.type === "date"
                    ? "date"
                    : field.type === "datetime"
                      ? "datetime-local"
                      : "text"
              }
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              value={String(values[field.name] ?? "")}
              onChange={(e) => setField(field.name, e.target.value)}
              data-testid={`field-${field.name}`}
            />
          )}
        </div>
      ))}
      <button
        type="submit"
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
      >
        {submitLabel}
      </button>
    </form>
  );
}
```

- [ ] **Step 4: Run the EntityForm test to verify it passes**

Run: `cd frontend && npm test -- EntityForm.test.tsx`
Expected: PASS

- [ ] **Step 5: Write the failing test `frontend/src/pages/EntityDetail.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntityDetail from "./EntityDetail";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderAtNew() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/domain/entity_type/new"]}>
        <Routes>
          <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("EntityDetail (create mode)", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      if (path === "/api/domain/entity_type/" && options?.method === "POST") {
        return Promise.resolve({ id: "new-id", code: "employee" });
      }
      return Promise.resolve({ items: [], total: 0 });
    });
  });

  it("submits a create request with the entered values", async () => {
    renderAtNew();

    fireEvent.change(await screen.findByTestId("field-code"), { target: { value: "employee" } });
    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/domain/entity_type/",
        expect.objectContaining({ method: "POST" })
      );
    });
  });
});
```

Run: `cd frontend && npm test -- EntityDetail.test.tsx`
Expected: FAIL (`Cannot find module './EntityDetail'`)

- [ ] **Step 6: Write `frontend/src/pages/EntityDetail.tsx`**

```tsx
import { useNavigate, useParams } from "react-router-dom";
import EntityForm from "../components/EntityForm";
import { useCreateEntity, useEntity, useUpdateEntity } from "../api/entities";
import { useSchema } from "../api/meta";

export default function EntityDetail() {
  const { schemaName = "", tableName = "", id } = useParams();
  const isNew = id === undefined;
  const navigate = useNavigate();

  const { data: tables } = useSchema();
  const table = tables?.find((t) => t.schema === schemaName && t.table === tableName);

  const { data: existing } = useEntity(schemaName, tableName, isNew ? undefined : id);
  const createEntity = useCreateEntity(schemaName, tableName);
  const updateEntity = useUpdateEntity(schemaName, tableName, id ?? "");

  if (!table || (!isNew && !existing)) {
    return <p className="text-sm text-slate-400">Loading…</p>;
  }

  async function handleSubmit(values: Record<string, unknown>) {
    if (isNew) {
      await createEntity.mutateAsync(values);
    } else {
      await updateEntity.mutateAsync(values);
    }
    navigate(`/${schemaName}/${tableName}`);
  }

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold text-slate-900">
        {isNew ? "New" : "Edit"} {schemaName}.{tableName}
      </h1>
      <EntityForm
        fields={table.fields}
        initialValues={isNew ? undefined : existing}
        onSubmit={handleSubmit}
        submitLabel={isNew ? "Create" : "Save"}
      />
    </div>
  );
}
```

- [ ] **Step 7: Wire the create/edit routes in `frontend/src/App.tsx`**

```tsx
import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import Login from "./pages/Login";
import EntityList from "./pages/EntityList";
import EntityDetail from "./pages/EntityDetail";
import { getToken } from "./api/client";

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function Placeholder() {
  return <div>Select a table from the sidebar.</div>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Placeholder />} />
        <Route path=":schemaName/:tableName" element={<EntityList />} />
        <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
        <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 8: Run the EntityDetail test to verify it passes**

Run: `cd frontend && npm test -- EntityDetail.test.tsx`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/entities.ts frontend/src/components/EntityForm.tsx frontend/src/pages/EntityDetail.tsx frontend/src/App.tsx frontend/src/components/EntityForm.test.tsx frontend/src/pages/EntityDetail.test.tsx
git commit -m "feat: generic EntityForm component and EntityDetail create/edit page"
```

---

## Task 23: Dashboard page (health status + row counts)

**Files:**
- Create: `frontend/src/api/health.ts`
- Create: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/App.tsx` (index route uses `Dashboard` instead of `Placeholder`; remove `Placeholder`)
- Test: `frontend/src/pages/Dashboard.test.tsx`

**Interfaces:**
- Consumes: `apiFetch` (Task 19), `GET /api/health` (Task 2), `useSchema` (Task 20), `ListResult` (Task 21).
- Produces: `useHealth()` hook in `src/api/health.ts` returning `{postgres, clickhouse}`. This is the last frontend task — the app shell now has no placeholder routes left.

- [ ] **Step 1: Write `frontend/src/api/health.ts`**

```typescript
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type HealthStatus = { postgres: "ok" | "error"; clickhouse: "ok" | "error" };

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<HealthStatus>("/api/health"),
    refetchInterval: 30000,
  });
}
```

- [ ] **Step 2: Write the failing test `frontend/src/pages/Dashboard.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderWithProviders() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <Dashboard />
    </QueryClientProvider>
  );
}

describe("Dashboard", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/health") {
        return Promise.resolve({ postgres: "ok", clickhouse: "ok" });
      }
      if (path === "/api/meta/schema") {
        return Promise.resolve([{ schema: "iam", table: "organization", fields: [] }]);
      }
      return Promise.resolve({ items: [{ id: "1" }], total: 1 });
    });
  });

  it("renders health status for both databases", async () => {
    renderWithProviders();
    const okValues = await screen.findAllByText("ok");
    expect(okValues.length).toBe(2);
  });

  it("renders a row count per table", async () => {
    renderWithProviders();
    expect(await screen.findByText("iam.organization")).toBeInTheDocument();
    expect(await screen.findByText("1")).toBeInTheDocument();
  });
});
```

Run: `cd frontend && npm test -- Dashboard.test.tsx`
Expected: FAIL (`Cannot find module './Dashboard'`)

- [ ] **Step 3: Write `frontend/src/pages/Dashboard.tsx`**

```tsx
import { useQueries } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import type { ListResult } from "../api/entities";
import { useHealth } from "../api/health";
import { useSchema } from "../api/meta";

export default function Dashboard() {
  const { data: health, isLoading: healthLoading } = useHealth();
  const { data: tables } = useSchema();

  const countQueries = useQueries({
    queries: (tables ?? []).map((t) => ({
      queryKey: ["row-count", t.schema, t.table],
      queryFn: () => apiFetch<ListResult>(`/api/${t.schema}/${t.table}/?limit=1&offset=0`),
      enabled: Boolean(tables),
    })),
  });

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Dashboard</h1>

      <div className="mb-6 grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-xs uppercase text-slate-400">Postgres</div>
          <div
            className={`text-lg font-semibold ${health?.postgres === "ok" ? "text-emerald-600" : "text-red-600"}`}
          >
            {healthLoading ? "…" : (health?.postgres ?? "unknown")}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-xs uppercase text-slate-400">ClickHouse</div>
          <div
            className={`text-lg font-semibold ${health?.clickhouse === "ok" ? "text-emerald-600" : "text-red-600"}`}
          >
            {healthLoading ? "…" : (health?.clickhouse ?? "unknown")}
          </div>
        </div>
      </div>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">Row counts</h2>
      <table className="w-full max-w-md border-collapse text-sm">
        <tbody>
          {(tables ?? []).map((t, index) => (
            <tr key={`${t.schema}.${t.table}`} className="border-b border-slate-100">
              <td className="px-3 py-1.5 text-slate-600">
                {t.schema}.{t.table}
              </td>
              <td className="px-3 py-1.5 text-right font-medium text-slate-900">
                {countQueries[index]?.data?.total ?? "…"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Update `frontend/src/App.tsx` to use `Dashboard` at the index route**

```tsx
import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import Login from "./pages/Login";
import EntityList from "./pages/EntityList";
import EntityDetail from "./pages/EntityDetail";
import Dashboard from "./pages/Dashboard";
import { getToken } from "./api/client";

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path=":schemaName/:tableName" element={<EntityList />} />
        <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
        <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 5: Run the Dashboard test to verify it passes**

Run: `cd frontend && npm test -- Dashboard.test.tsx`
Expected: PASS

- [ ] **Step 6: Run the full frontend test suite**

Run: `cd frontend && npm test`
Expected: all tests across every `*.test.ts(x)` file PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/health.ts frontend/src/pages/Dashboard.tsx frontend/src/App.tsx frontend/src/pages/Dashboard.test.tsx
git commit -m "feat: dashboard page with health status and row counts"
```

---

## Task 24: Full-stack integration smoke test

**Files:**
- Create: `scripts/smoke_test.sh`

**Interfaces:**
- Consumes: every service and endpoint built in Tasks 1-23 — this task adds no new application code, it verifies the assembled system works end-to-end from a cold start, per spec §9's integration testing strategy.
- Produces: `scripts/smoke_test.sh`, an idempotent, re-runnable script that brings up the full stack via `docker-compose.yml`, applies migrations, and exercises the real HTTP surface (not mocks) for health, auth, metadata, a CRUD write, and the frontend's `/api` proxy.

- [ ] **Step 1: Write `scripts/smoke_test.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "== Bringing up full stack =="
docker compose up -d --build

echo "== Waiting for Postgres and ClickHouse to report healthy =="
for i in $(seq 1 30); do
  postgres_status=$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || echo "")
  clickhouse_status=$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q clickhouse)" 2>/dev/null || echo "")
  if [[ "$postgres_status" == "healthy" && "$clickhouse_status" == "healthy" ]]; then
    break
  fi
  sleep 2
done
if [[ "$postgres_status" != "healthy" || "$clickhouse_status" != "healthy" ]]; then
  echo "databases did not become healthy in time"
  exit 1
fi

echo "== Applying database migrations =="
docker compose exec -T backend alembic upgrade head

echo "== Checking backend health =="
curl -sf http://localhost:8010/api/health | tee /tmp/solver_health.json
grep -q '"postgres":"ok"' /tmp/solver_health.json
grep -q '"clickhouse":"ok"' /tmp/solver_health.json

echo "== Logging in as the seeded admin =="
TOKEN=$(curl -sf -X POST http://localhost:8010/api/auth/login \
  -d "username=${ADMIN_USERNAME:-admin}&password=${ADMIN_PASSWORD:-change-me-admin}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

echo "== Verifying the metadata endpoint lists all 31 registered tables =="
TABLE_COUNT=$(curl -sf -H "Authorization: Bearer $TOKEN" http://localhost:8010/api/meta/schema \
  | python3 -c "import sys,json;print(len(json.load(sys.stdin)))")
if [[ "$TABLE_COUNT" != "31" ]]; then
  echo "expected 31 registered tables, got $TABLE_COUNT"
  exit 1
fi

echo "== Creating an organization through the full stack =="
curl -sf -X POST http://localhost:8010/api/iam/organization/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"code":"smoke-test-org","name":"Smoke Test Org"}' | tee /tmp/solver_org.json
grep -q '"code":"smoke-test-org"' /tmp/solver_org.json

echo "== Checking the frontend serves and proxies /api to the backend =="
FRONTEND_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:3010)
[[ "$FRONTEND_STATUS" == "200" ]]
curl -sf http://localhost:3010/api/health | grep -q '"postgres":"ok"'

echo "== All smoke checks passed =="
```

- [ ] **Step 2: Make it executable and run it from a cold start**

Run:
```bash
chmod +x scripts/smoke_test.sh
docker compose down -v   # cold start: drop volumes so this proves the stack works from nothing
./scripts/smoke_test.sh
```
Expected: script prints `== All smoke checks passed ==` and exits 0. If a step fails, the script exits non-zero at that step via `set -e` — fix the underlying issue (not the script) and re-run.

- [ ] **Step 3: Manually verify the UI once**

Open `http://localhost:3010` in a browser:
1. Log in with `admin` / the `ADMIN_PASSWORD` from `.env`.
2. Confirm the Dashboard shows `postgres: ok` and `clickhouse: ok`, and a row count per table (31 rows in the table list).
3. Click `domain` → `entity_type` in the sidebar, click **New**, fill in `code`/`name`, submit — confirm it appears in the list.
4. Click the new row, edit `name`, save — confirm the change is reflected in the list.
5. Delete it — confirm it disappears from the list.

This confirms the generic CRUD/metadata pipeline works through the actual browser, not just curl.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_test.sh
git commit -m "test: add full-stack smoke test script"
```

---

## Plan-level verification

Once all 24 tasks are complete, the platform should satisfy every requirement in the spec:

- Four Docker services (postgres, clickhouse, backend, frontend) on one network, only the backend holding DB credentials (spec §3) — verified in Task 24.
- Full `iam`/`domain`/`problem` schema, 31 tables, UUID PKs (spec §4) — built across Tasks 3-7, 10, 13-17.
- ClickHouse analytics schema created and health-checked (spec §5) — Task 8.
- Generic CRUD backend via explicit models + shared factory (spec §6, approach B) — Tasks 9-18.
- Metadata-driven generic admin frontend (spec §7) — Tasks 19-23.
- Nothing from spec §8 (solver, Solution schema, RBAC enforcement, audit log, visual builders) was built — confirmed by absence, not by a task.
- Backend parametrized-style tests per table group, frontend component tests, and a real integration smoke test (spec §9) — one test file per backend task, one per frontend task, Task 24 ties it together.
