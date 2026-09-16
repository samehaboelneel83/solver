# Problem-Solver Platform — MVP Skeleton Design

Status: approved for implementation planning
Date: 2026-09-16

## 1. Purpose

Build the foundational skeleton of a general-purpose "problem solver" platform:
a system where users can model a real-world domain (entities, relationships,
hierarchies, roles, states, events, resources, time), define an optimization
problem over that domain (variables, constraints, objectives, parameters),
and — in a later phase — compile and run that problem through an actual
solver (CP-SAT, MILP, etc.) and inspect the results.

This spec covers **only the skeleton**: containerized infrastructure,
databases, a generic CRUD backend, and a generic admin frontend for the
Domain and Problem layers. Solver execution and the Solution/Analytics data
flow are explicitly out of scope (see §8) and will be their own spec once
this skeleton is running.

## 2. Non-goals for this phase

- No solver integration (CP-SAT/MILP/etc.), no model compiler, no solver_run
  execution.
- No Solution schema (assignments, schedules, allocations, metrics,
  violations) and no real data flowing into ClickHouse.
- No enforced RBAC — auth exists (JWT, single seeded admin) but role/permission
  checks are not implemented per-endpoint yet.
- No audit logging.
- No visual builders (hierarchy tree editor, constraint expression builder).
  JSONB fields are edited as raw JSON in the generic form for now.
- No direct browser-to-database access of any kind. The browser only ever
  talks to the FastAPI backend.

## 3. Architecture overview

```
Browser (React SPA)
      │  HTTPS, JWT bearer token
      ▼
FastAPI backend  ──────►  PostgreSQL 16   (iam / domain / problem schemas)
      │
      └──────────────►  ClickHouse       (analytics schemas, empty until solver phase)
```

Four services, each its own Docker image, orchestrated by one
`docker-compose.yml`:

| service    | image basis           | internal port | host port (dev) |
|------------|------------------------|---------------|------------------|
| postgres   | `postgres:16`           | 5432          | 5432             |
| clickhouse | `clickhouse/clickhouse-server` | 8123 / 9000 | 8123 / 9000 |
| backend    | custom (Python 3.12 + FastAPI) | 8000 | 8000 |
| frontend   | custom (Node build → nginx) | 80 | 3000 |

All four sit on one internal Docker network (`solver_net`). Only the backend
holds database credentials; Postgres/ClickHouse ports are exposed to the host
for local administration/debugging convenience, not for browser access.
Named volumes persist Postgres and ClickHouse data across restarts.
Configuration (DB passwords, JWT secret) lives in a `.env` file, gitignored,
with a checked-in `.env.example`.

## 4. Database schema — PostgreSQL

Three schemas: `iam`, `domain`, `problem`. This is the authoritative table
list for this phase (field types abbreviated; full column definitions go in
the Alembic migration during implementation).

### 4.1 `iam`

- `organization(id, parent_id, code, name, description, is_active, created_at)`
- `user_account(id, organization_id, username, display_name, email, hashed_password, is_active, created_at)`
- `role(id, code, name)`
- `user_role(user_id, role_id)` — composite PK, tables exist but not enforced this phase

### 4.2 `domain`

- `entity_type(id, organization_id, code, name, description, parent_type_id, is_abstract, created_at)`
- `entity(id, organization_id, entity_type_id, code, name, description, valid_from, valid_to, status, created_at, updated_at)`
- `attribute_definition(id, entity_type_id, code, name, data_type, is_required, is_multi_value, default_value, validation_rule)`
- `entity_attribute(id, entity_id, attribute_id, value_string, value_number, value_boolean, value_date, value_datetime, value_json)`
- `relationship_type(id, code, name, source_entity_type, target_entity_type, cardinality, is_directed, metadata)`
- `relationship(id, relationship_type_id, source_entity_id, target_entity_id, valid_from, valid_to, attributes)`
- `hierarchy(id, organization_id, code, name, entity_type_id, description)`
- `hierarchy_node(id, hierarchy_id, entity_id, parent_node_id, level, sort_order)`
- `role_type(id, code, name, description)`
- `entity_role(id, entity_id, role_type_id, valid_from, valid_to, attributes)`
- `state_type(id, code, name, entity_type_id)`
- `entity_state(id, entity_id, state_type_id, state_value, valid_from, valid_to)`
- `event_type(id, code, name, description)`
- `event(id, event_type_id, entity_id, occurred_at, data)`
- `resource_type(id, code, name, capacity_type)`
- `resource(id, resource_type_id, entity_id, capacity, unit, availability_rule)`
- `time_calendar(id, organization_id, code, name, timezone)`
- `time_period(id, calendar_id, parent_id, name, start_time, end_time, level, metadata)`

### 4.3 `problem`

- `problem(id, organization_id, code, name, description, problem_type, version, status, created_by, created_at)`
- `scenario(id, problem_id, code, name, description, parent_scenario_id, parameters)`
- `variable_definition(id, problem_id, code, name, variable_type, description, domain_definition)`
- `variable_dimension(id, variable_id, dimension_order, dimension_type, domain_source)`
- `constraint_definition(id, problem_id, code, name, constraint_type, expression, severity, is_hard, weight, priority, description)`
- `constraint_scope(id, constraint_id, hierarchy_id, hierarchy_node_id, entity_id, scope_type, parameters)`
- `objective(id, problem_id, code, name, objective_type, expression, priority, weight)`
- `objective_component(id, objective_id, code, expression, weight, priority)`
- `parameter(id, problem_id, code, name, data_type, value, is_runtime)`

All tables use UUID primary keys. This matches the design already agreed
with the user prior to this spec (see prior conversation); it is treated as
fixed rather than re-derived here.

## 5. Database schema — ClickHouse

Created at backend startup via raw SQL (no ORM), stays empty until the
solver phase writes to it. Included now so the container, connection, and
health check are proven end-to-end:

- `analytics.solver_runs` — organization_id, problem_id, scenario_id, solver_run_id, solver_type, started_at, finished_at, duration_ms, status, objective_value, best_bound, gap, variables, constraints, iterations, nodes. `ORDER BY (organization_id, problem_id, started_at)`.
- `analytics.solution_metrics` — organization_id, problem_id, scenario_id, solution_id, metric_code, metric_value, measured_at, dimensions (Map). `ORDER BY (organization_id, problem_id, metric_code, measured_at)`.
- `analytics.constraint_violations` — organization_id, problem_id, solution_id, constraint_id, entity_id, severity, violation_value, penalty, occurred_at. `ORDER BY (organization_id, problem_id, constraint_id, occurred_at)`.

## 6. Backend (FastAPI)

### 6.1 Layout

```
backend/
  app/
    main.py                 # app factory, router registration, startup hooks
    core/
      config.py              # settings (env vars)
      security.py             # JWT encode/decode, password hashing
      db.py                   # SQLAlchemy engine/session, ClickHouse client
    models/
      iam.py, domain.py, problem.py     # SQLAlchemy ORM models
    schemas/
      iam.py, domain.py, problem.py     # Pydantic Create/Update/Read schemas per table
    crud/
      factory.py               # build_crud_router(...)
    api/
      auth.py                  # /api/auth/login
      meta.py                  # /api/meta/schema
      health.py                 # /api/health
      routers.py                 # instantiates factory routers for all ~30 tables
    seed.py                    # seeds default organization + admin user
  alembic/                    # migrations
  Dockerfile
  requirements.txt
```

### 6.2 CRUD factory

`build_crud_router(model, create_schema, update_schema, read_schema, prefix, tags)`
returns a FastAPI `APIRouter` with:

- `GET /` — paginated list (`limit`/`offset`), basic equality filtering on
  query params matching column names. Response shape is
  `{items: [...], total: <int>}`, not a bare array, so the frontend can
  show pagination controls and row counts without a separate count call.
- `GET /{id}`
- `POST /`
- `PUT /{id}`
- `DELETE /{id}`

All routes depend on `get_current_user`. Applied once per table (~30 calls
in `api/routers.py`) rather than writing 30 near-identical route files.

### 6.3 Metadata endpoint

`GET /api/meta/schema` returns, per table: schema name, table name, and a
field list (`name`, `type`, `required`, `is_fk`, `fk_table`) derived by
introspecting the Pydantic Create schema plus SQLAlchemy FK metadata. The
frontend uses this single endpoint to build its entire navigation and forms —
no hardcoded table list on the frontend.

### 6.4 Auth

JWT via `python-jose`, password hashing via `passlib[bcrypt]`. One admin
user seeded on first startup (`seed.py`, idempotent). `get_current_user`
dependency validates the bearer token on every CRUD/meta route; `/api/auth/login`
and `/api/health` are the only unauthenticated routes.

### 6.5 Health check

`GET /api/health` returns `{postgres: "ok"|"error", clickhouse: "ok"|"error"}`
by running a trivial query against each.

## 7. Frontend (React + Vite + TypeScript)

### 7.1 Stack

Vite, TypeScript, Tailwind CSS, shadcn/ui components, React Router,
TanStack Query for data fetching/caching.

### 7.2 Layout

```
frontend/
  src/
    api/client.ts            # fetch wrapper, JWT header injection, 401 handling
    api/meta.ts               # loads /api/meta/schema, cached via React Query
    pages/
      Login.tsx
      Dashboard.tsx           # health status cards, row counts
      EntityList.tsx           # generic table view for one schema.table
      EntityDetail.tsx          # generic create/edit form
    components/
      AppShell.tsx             # sidebar nav grouped by schema, built from meta
      DataTable.tsx             # generic paginated/filterable table
      EntityForm.tsx             # generic form: text/number/boolean/date/FK-dropdown/JSON editor
    App.tsx, main.tsx
  Dockerfile                  # multi-stage: vite build -> nginx serve
```

### 7.3 Behavior

- Login page posts to `/api/auth/login`, stores JWT (memory + localStorage
  for refresh survival), attaches it to every request via the API client.
- On 401, redirect to login.
- Sidebar is generated from `/api/meta/schema`, grouped by schema
  (`iam` / `domain` / `problem`); clicking a table navigates to
  `EntityList` for that table.
- `EntityList` fetches `GET /api/{schema}/{table}`, renders `DataTable`
  with columns from metadata, pagination controls, and a "New" button.
- `EntityForm` renders inputs per field type from metadata: text for
  strings, number inputs for numeric, checkbox for boolean, date picker
  for date/datetime, searchable dropdown for FK fields (populated from the
  referenced table's list endpoint), and a JSON textarea for JSONB fields.
- Dashboard shows the `/api/health` status and a row count per table
  (via a lightweight `GET /api/{schema}/{table}?limit=1` and reading
  the `total` field from the response).

## 8. Explicitly deferred to future specs

- Solver model schema, model compiler / solver adapters (CP-SAT, MILP,
  routing, etc.), solver_run execution engine.
- Solution schema (assignment, schedule, allocation, metric, violation,
  explanation) and the ClickHouse write path from real solver runs.
- Enforced RBAC (role/user_role checked per endpoint), multi-organization
  UX (org switcher, org-scoped data isolation in the UI).
- Audit log table and write-through from CRUD operations.
- Visual domain/problem builders (hierarchy tree editor, constraint
  expression builder, dependency graph view).

## 9. Testing strategy

- **Backend**: `pytest` + `httpx.AsyncClient` against a disposable test
  Postgres (docker-compose test profile or testcontainers). One
  parametrized test suite exercises the CRUD factory generically across all
  ~30 registered models (create → get → update → list → delete), plus
  dedicated tests for auth (login success/failure, unauthenticated access
  rejected) and `/api/meta/schema` (all registered tables present, FK
  fields flagged correctly).
- **Frontend**: component-level smoke tests for `DataTable` and
  `EntityForm` against mocked metadata/API responses (Vitest + React
  Testing Library). Full e2e is deferred — not needed to validate this
  skeleton.
- **Integration**: a `docker-compose up` smoke test (can be manual for
  this phase) confirming all four containers start, `/api/health` reports
  both databases OK, and the frontend loads and can log in.

## 10. Open implementation decisions (left to the plan, not blocking)

- Exact Alembic migration structure (single initial migration vs. one per
  schema).
- Whether Pydantic schemas are hand-written per table or generated once
  from SQLAlchemy models via a small one-time script (either is fine;
  approach B from the design discussion only requires that they end up as
  explicit, real schemas — not that they're typed by hand forever).
