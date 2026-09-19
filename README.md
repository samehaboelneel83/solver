# Problem-Solver Platform — MVP Skeleton

The foundational skeleton of a general-purpose "problem solver" platform: model a
real-world domain (entity types, their attributes, entities, relationships and
parameters), then define an optimization problem over that domain. This
repository contains the skeleton only — containerized infrastructure, the
**schema v1** PostgreSQL schema (16 tables in `public`, plus the 4 `iam` tables),
an empty ClickHouse analytics schema, a FastAPI backend that is part
purpose-built and part generic CRUD, and a React admin UI. Solver execution is
explicitly out of scope for this phase: the RUN tables exist and nothing writes
to them yet.

- Schema v1 design: [`docs/superpowers/specs/2026-09-19-schema-v1-migration-design.md`](docs/superpowers/specs/2026-09-19-schema-v1-migration-design.md)
- The authoritative DDL it was built from: [`docs/schema/2026-09-18-schema-v1.sql`](docs/schema/2026-09-18-schema-v1.sql)
- Original platform skeleton design (v0, largely superseded): [`docs/superpowers/specs/2026-09-16-platform-skeleton-design.md`](docs/superpowers/specs/2026-09-16-platform-skeleton-design.md)

## The schema

Everything outside `iam` lives in `public`. There are three groups:

| Group | Tables |
|---|---|
| **Domain** | `domain`, `entity_type`, `attribute_def`, `entity`, `relationship_type`, `relationship`, `parameter_def`, `parameter_value` |
| **Problem** | `template`, `problem`, `model_version`, `scenario` |
| **Run** | `dataset`, `run`, `solution`, `constraint_result` |
| **Access** | `iam.organization`, `iam.user_account`, `iam.role`, `iam.user_role` |

Two things about this shape drive most of the code:

- **An entity's attributes are one `jsonb` column**, `entity.attrs` — not an
  EAV table. It is validated on write by the `entity_validate` trigger against
  the entity type's `attribute_def` rows, which is also what materialises an
  attribute's `default_value`. Unknown attribute, missing required attribute and
  wrong type are all database refusals, surfaced as a `422` naming the field.
- **Four tables are immutable.** `model_version`, `dataset`, `solution` and
  `constraint_result` carry a `forbid_update()` trigger. `model_version` has a
  read/create router whose `PUT`/`PATCH`/`DELETE` answer `405`; the other three
  have no router at all.

`GET /api/meta/schema` lists **7** tables, not 20: only the four `iam` tables and
the three flat `public` tables (`domain`, `template`, `problem`) go through the
generic CRUD factory. Everything else has a purpose-built router, or no router
at all — see the comment block in `backend/app/api/routers.py` for the reasoning
per table.

## Prerequisites

- Docker Desktop (Compose v2). Everything runs in containers; no local Python or
  Node install is needed to bring the stack up.
- Node 20+ only if you want to run the frontend test suite on the host.

## Setup

```bash
cp .env.example .env
```

`.env` is gitignored. The defaults are placeholder secrets (`change-me`,
`change-me-too`, `change-me-admin`) and are fine for local development. **Change
`POSTGRES_PASSWORD`, `JWT_SECRET` and `ADMIN_PASSWORD` before using this
anywhere other than your own machine.**

## Bring the stack up

```bash
docker compose up -d --build
```

### Apply migrations (required — the stack is not usable until you do)

The database schema is **not** created automatically on startup. Run:

```bash
docker compose run --rm --no-deps -T backend alembic upgrade head
```

Use `run --rm --no-deps` rather than `docker compose exec backend alembic ...`.
On a cold start the backend hasn't seeded its admin user yet and logs a warning
on every boot until migrations exist; an `exec`'d alembic process attached to
that service can be killed by a restart mid-transaction, and because each
migration is a single transaction the whole run then silently rolls back.
`run --rm --no-deps` applies them from an isolated one-off container instead.

Then restart the backend so it seeds the default organization and admin user:

```bash
docker compose restart backend
```

If you skip migrations the backend still boots and `/api/health` still responds;
you'll just see `Skipped admin seeding — have you run 'alembic upgrade head'?` in
`docker compose logs backend`, and login will fail until you run the two commands
above.

> **Already have data in an older database? Stop and read
> [`docs/runbooks/schema-v1-cutover.md`](docs/runbooks/schema-v1-cutover.md)
> first.** Migration `0006` begins with `DROP SCHEMA domain CASCADE` and there is
> no data migration from the old schema; the downgrade drops the v1 tables and
> recreates nothing. Take a `pg_dump` before you migrate. `scripts/smoke_test.sh`
> refuses to migrate anything that is neither empty nor already on v1, so you
> cannot trip over this by running the smoke test.

## URLs and ports

These are **not** the default ports. They were remapped because 5432, 8000 and
3000 are commonly occupied by other local projects.

| Service    | URL / binding            | Container port |
|------------|--------------------------|----------------|
| Frontend   | http://localhost:3010    | 80             |
| Backend    | http://localhost:8010    | 8000           |
| Postgres   | `127.0.0.1:5544`         | 5432           |
| ClickHouse | `127.0.0.1:8123` / `9000`| 8123 / 9000    |

The two database services bind to `127.0.0.1` only, so they're reachable from
host tooling (`psql`, `curl`) but not from other machines on your network —
ClickHouse in particular runs with no password in this MVP. The backend and
frontend bind to all interfaces as normal.

Interactive API docs: http://localhost:8010/docs

## Log in

Navigate to http://localhost:3010 and sign in with the seeded admin:

- **Username:** `admin` (`ADMIN_USERNAME` in `.env`)
- **Password:** `change-me-admin` (`ADMIN_PASSWORD` in `.env`)

## Seed a demo domain

An empty installation has nothing to look at. The seed writes a small
**Workforce** domain — employees, units, days and shifts, with a `reports_to`
hierarchy and `works_in` edges, a two-dimensional `demand` parameter, a problem
and one model version:

```bash
docker compose exec -T backend python -m app.seed
```

It is idempotent by refusing: run it twice and the second run writes nothing and
reports the existing ids.

## The UI

The sidebar is a fixed set of groups (Domain, Problem, Runs, Access), not a list
generated from the schema. Within it, some screens are purpose-built for a v1
table and some are the generic metadata-driven ones.

### Purpose-built screens

| Route | What it does |
|---|---|
| `/entity-types`, `/entity-types/:id` | Entity types and their attribute definitions — data type, required, unit, enum values, default, colour |
| `/relationship-types`, `/relationship-types/:id` | Relationship types: endpoint types, cardinality, whether it is a hierarchy, colour |
| `/entities`, `/entities/:id` | Entities, with attribute inputs typed by each attribute's `data_type`, and a condition builder that filters server-side |
| `/parameters` | Parameter definitions and a grid for their cells |
| `/versions` | A problem's model versions, **read-only**, with an IR viewer |
| `/graph` | The Graph Editor (below) |

### Generic screens

`/public/domain`, `/public/template`, `/public/problem` and the four
`/iam/<table>` routes are the metadata-driven list/detail pages, generated
entirely from `GET /api/meta/schema` and talking to the generic CRUD API you can
call directly.

#### List endpoint query params

`GET /api/{schema}/{table}/` accepts:

- `limit` / `offset` — pagination (default `limit=50`, max `500`).
- `q` — free-text search, `ILIKE`-OR'd across the table's `String`/`Text`
  columns.
- `f_<column>=<value>` — an equality filter on any exposed column, one query
  param per column (e.g. `f_domain_id=1`). The value is cast to the column's
  Python type (bool/UUID/int/float/Decimal/date/datetime); an unknown column
  or a value that fails to cast returns `422`.
- `order_by=<column>&order=asc|desc` — sort by any exposed column.

A column dropped from the read schema (e.g. `hashed_password`) can't be
reached through `q`, `f_<column>` or `order_by` even though it's a real
mapped column.

`GET /api/{schema}/{table}/options` is the FK-dropdown endpoint: `?q=` runs
the same searchable-column search for a combobox, and `?ids=id1,id2,...`
(max 200) resolves a specific set of ids to `{id, label}` pairs. Ids are cast
per model, so the bigint-keyed `public` tables and the UUID-keyed `iam` tables
both work.

`GET /api/meta/schema` also reports, per field, a `default` and `choices` (a
curated list of suggested values for a handful of free-text fields — a hint
only), and per table the `creatable`/`updatable`/`deletable` capability flags
the UI uses to hide actions the API does not offer.

#### Admin UI features

- Search, filters and sort are reflected in the URL (`q`, `f_<column>`,
  `order_by`, `order`, `offset`), so a filtered/sorted list view is a
  shareable, bookmarkable, back-button-safe link.
- Deleting a row asks for confirmation first.
- Foreign-key columns render as their resolved human label instead of a raw
  id, and editing one uses a searchable picker.
- A detail page's "Related records" section lists every other table with a
  foreign key pointing at the current row, with a live count and a link to
  that filtered child list.
- A `401` (expired or invalid token) sends you to the login page with a
  message explaining why, and signing back in returns you to the page you
  were on.

### One error shape

Every `422` on this API is FastAPI's list shape —
`{"detail": [{"type", "loc", "msg", ...}]}` — whether it came from Pydantic, a
hand-written router rule or a database trigger. A trigger's entry carries an
extra `kind` key (`unknown_attribute`, `cardinality`, `cycle`,
`parameter_index`, …), which is the only thing that distinguishes the two.
Conflicts (unique, foreign key, not-null, and any attempt to update an
immutable row) are `409` with a string `detail`.

## Graph Editor

`/graph` is an interactive Cytoscape.js canvas over `entity` and `relationship`.
It reads `GET /api/v1/graph?domain_id=&hierarchy_type_id=` and writes through
the same `/api/v1/entities` and `/api/v1/relationships` routers the rest of the
UI uses — the graph has no write routes of its own.

- A **domain selector** above the canvas chooses which domain is drawn;
  switching it resets the hierarchy, selection and filters.
- An **objects/types toggle**: the objects view draws entities and their
  relationships; the types view draws the domain's *schema* — entity types and
  the relationship types between them — in the same colours.
- **Hierarchy nesting**: pick a relationship type marked as a hierarchy and its
  rows become Cytoscape compound parents, laid out with ELK.
- A **compact type filter** ("Types: N of M"), a free-text search box over
  labels and keys, and a "highlight connections" toggle.
- **Connect mode**: drag from one node to another and pick from the relationship
  types valid between those two entity types.
- A **condition builder** filters the canvas by a typed expression over the
  domain's attribute definitions — the same builder and the same document the
  Entities page sends to the server as `?expr=`.
- A **property panel** edits the selected node's `label` and `attrs` (inputs
  typed per `data_type`) or the selected edge's relationship type and validity
  window, and can delete either.

Two implementation notes worth knowing before you change anything here:

- **Cytoscape keeps nodes and edges in one id space**, and answers a duplicate
  id `add()` by silently doing nothing. Entity ids and relationship ids are two
  independent sequences, so they collide from row 1; edge ids are namespaced at
  the canvas boundary and the wire id is kept for the panel and `DELETE`.
- Cytoscape caches its container's bounding rect when the instance is created;
  if the page scrolls or reflows afterwards, call `cy.resize()` before relying on
  rendered node positions or hit-testing.

## Tests

```bash
# Backend — 733 tests
docker compose run --rm --no-deps -T backend pytest -q

# Frontend — 1108 tests across 57 files
cd frontend && npm ci && npm test -- --run
```

Use `run --rm`, not `docker compose exec backend pytest`. Neither image has a
bind mount, so `exec` runs the code baked into the image, which is not
necessarily the code in your working tree — a green run against stale code is
the most expensive failure mode available here. `run --rm` has the same problem
unless the image is current, so rebuild first (`./scripts/rebuild.sh`) or mount
the tree explicitly:

```bash
docker run --rm --network solver_solver_net \
  -v "$PWD/backend:/app" -w /app --env-file .env \
  -e DATABASE_URL=postgresql+psycopg2://solver:change-me@postgres:5432/solver \
  -e CLICKHOUSE_HOST=clickhouse \
  solver-backend pytest -q
```

The backend suite runs against its own `<db>_test` database, never the one the
running stack uses. `backend/tests/conftest.py` rewrites `DATABASE_URL` to
`<db>_test` (override with `TEST_DATABASE_URL`) and **drops, recreates and
migrates it** before any test code imports `app`, so a session always starts
from zero rows — several tests commit through real HTTP requests, and at least
one test's correctness depends on its table being small. The drop is guarded by
an explicit check that the name ends in `_test`.

## Rebuilding after a code change

Neither the backend nor the frontend Docker image has a bind mount, so a
code change under `backend/` or `frontend/` is invisible to the running
containers until the image is rebuilt and the container recreated from it.

```bash
./scripts/rebuild.sh
```

rebuilds both images, recreates both containers, and waits (retrying for up
to ~30s) for each to actually start serving — `/api/health` on the backend,
`/` on the frontend — before confirming. Rebuild **both** even if you only
touched one side — a stale image on the side you didn't touch is easy to
miss and has shipped before.

## Full-stack smoke test

```bash
./scripts/smoke_test.sh
```

Checks a stack that is already running: `/api/health` (including ClickHouse),
login, that `/api/meta/schema` lists the 7 registered tables, a create/delete
round trip through the generic CRUD API, that a NUL byte in a query parameter is
a `422`, and that the frontend serves and proxies `/api`. **It changes nothing**
— it does not build, create containers or migrate.

```bash
./scripts/smoke_test.sh --bootstrap
```

additionally brings the stack up and applies migrations, but only after a
preflight that refuses any database which is neither empty nor already on schema
v1, and only after you type the database name back to confirm (or set
`SMOKE_CONFIRM=<name>`). There is deliberately no flag that migrates a populated
older database; that is a cutover and it has a
[runbook](docs/runbooks/schema-v1-cutover.md).

Point `SMOKE_API_URL` / `SMOKE_WEB_URL` / `POSTGRES_DB` at a throwaway stack to
smoke-test something other than your own.

`scripts/graph_smoke_check.py` is the equivalent check for the Graph Editor: it
assumes a migrated, seeded stack and exercises the v1 graph read, hierarchy
placement, entity and relationship creation through the v1 routers, and three
trigger refusals. It defaults to an isolated stack on `8011`/`3011`
(`SMOKE_API_URL` / `SMOKE_WEB_URL` override it) and cleans up everything it
creates.

```bash
docker compose exec -T backend python -m app.seed
python scripts/graph_smoke_check.py
```

## Known limitations in this phase

- **Nothing in the product creates a model version.** You can create a problem
  and read the versions a seed or a script wrote, but there is no screen or
  route that produces an IR — the compiler that would is out of scope. The
  Runs group in the sidebar is empty for the same reason: `dataset`, `run`,
  `solution` and `constraint_result` exist and have no writer.
- **A parameter cannot be indexed by the same entity type twice.** A `CHECK`
  on `parameter_def` refuses duplicate `index_type_ids`. This is **temporary**
  and not a modelling judgement: `snapshot_dataset()` keys parameter rows by
  index-*type* name, so `distance[location, location]` would silently collapse
  both coordinates onto one key. The restriction stands until that contract is
  redesigned; self-indexed parameters (distance matrices, transition costs,
  precedence) are perfectly ordinary and will be supported.
- **The migration is one-way.** See
  [`docs/runbooks/schema-v1-cutover.md`](docs/runbooks/schema-v1-cutover.md):
  the downgrade drops the v1 tables and recreates nothing, contrary to what
  the design spec (§8) asked for. A `pg_dump` is the only rollback.
- **Users cannot be created through the admin UI.** `hashed_password` is
  deliberately excluded from the generic CRUD API, so `iam.user_account` is
  read-only in practice and only the seeded admin exists. `POST
  /api/iam/user_account/` returns a clean `409` rather than a raw 500.
- **No enforced RBAC.** Auth is real (JWT, bearer token on every route), but
  `role`/`user_role` are not checked per endpoint — any authenticated user can
  read and write everything. Deferred by spec §2.
- **Styling is plain Tailwind,** not the shadcn/ui component library named in
  the original spec §7.1. Components were hand-rolled instead; functionally
  equivalent, but don't go looking for a shadcn install that isn't there.
- **Relationship attributes are edited as raw JSON**, as is any JSONB column on
  a generic form. Entity attributes are the exception — those are typed by the
  attribute's declared `data_type`.
- **No optimistic locking.** Nothing carries a version or etag check — the last
  save wins, silently overwriting a concurrent edit.
- **The graph's expression filter mixes every entity type's attributes** in one
  flat list, and a rule on one type empties the rest of the canvas.
- **A filtered entity list is not linkable.** The type filter is in the URL; the
  expression is not, so a filtered list cannot be shared or survive a reload.
- **Hierarchy collapse/expand is not implemented.** Cytoscape's compound nodes
  provide nesting only; collapsing would need the `cytoscape-expand-collapse`
  extension, which is not installed.
- Neither image has a bind mount; see "Rebuilding after a code change".
