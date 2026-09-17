# Problem-Solver Platform — MVP Skeleton

The foundational skeleton of a general-purpose "problem solver" platform: model a
real-world domain (entities, relationships, hierarchies, roles, states, events,
resources, time), then define an optimization problem over that domain
(variables, constraints, objectives, parameters). This repository contains the
skeleton only — containerized infrastructure, a PostgreSQL schema of 31 tables
across three namespaces (`iam`, `domain`, `problem`), an empty ClickHouse
analytics schema, a generic FastAPI CRUD backend, and a metadata-driven React
admin UI. Solver execution, the Solution schema, enforced RBAC and audit logging
are explicitly out of scope for this phase. See
[`docs/superpowers/specs/2026-09-16-platform-skeleton-design.md`](docs/superpowers/specs/2026-09-16-platform-skeleton-design.md)
for the full design and
[`docs/superpowers/plans/2026-09-16-platform-skeleton.md`](docs/superpowers/plans/2026-09-16-platform-skeleton.md)
for the implementation plan.

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

The sidebar, tables and forms are generated entirely from `GET /api/meta/schema`
— there is no hardcoded table list in the frontend.

## Admin UI

The generic admin UI (list and detail/edit pages) is metadata-driven from
`GET /api/meta/schema` and talks to the same generic CRUD API you can call
directly.

### List endpoint query params

`GET /api/{schema}/{table}/` accepts:

- `limit` / `offset` — pagination (default `limit=50`, max `500`).
- `q` — free-text search, `ILIKE`-OR'd across the table's `String`/`Text`
  columns.
- `f_<column>=<value>` — an equality filter on any exposed column, one query
  param per column (e.g. `f_status=ACTIVE&f_is_active=true`). The value is
  cast to the column's Python type (bool/UUID/int/float/Decimal/date/
  datetime); an unknown column or a value that fails to cast returns `422`.
- `order_by=<column>&order=asc|desc` — sort by any exposed column.

A column dropped from the read schema (e.g. `hashed_password`) can't be
reached through `q`, `f_<column>` or `order_by` even though it's a real
mapped column.

`GET /api/{schema}/{table}/options` is the FK-dropdown endpoint: `?q=` runs
the same searchable-column search for a combobox, and `?ids=id1,id2,...`
(max 200) resolves a specific set of ids to `{id, label}` pairs, which is
how a list page batch-resolves every FK value shown on a page in one
request instead of one per row.

`GET /api/meta/schema` also reports, per field, a `default` (the column's
client-side scalar default, if any) and `choices` (a curated list of
suggested values for a handful of free-text fields like `status` — a hint
only; the CRUD routes still accept any string).

### Admin UI features

- Search, filters and sort are reflected in the URL (`q`, `f_<column>`,
  `order_by`, `order`, `offset`), so a filtered/sorted list view is a
  shareable, bookmarkable, back-button-safe link.
- Deleting a row asks for confirmation first.
- Foreign-key columns render as their resolved human label instead of a raw
  id, and editing one uses a searchable picker (type to query, pick from a
  dropdown) instead of a `<select>` that only showed the first page of
  rows.
- A detail page's "Related records" section lists every other table with a
  foreign key pointing at the current row, with a live count and a link to
  that filtered child list.
- A `401` (expired or invalid token) sends you to the login page with a
  message explaining why, and signing back in returns you to the page you
  were on.

## Graph Editor demo

`/graph` is a demo page for the Graph Editor sub-project: an interactive
Cytoscape.js canvas over the same `domain.entity`/`domain.relationship` tables
used by the generic CRUD admin UI, with drag-connect edge creation, a
create-node form, hierarchy nesting via ELK layout, and a property panel for
editing or deleting the selected node/edge. It reads and writes through
`GET/POST/PATCH/DELETE /api/graph/domain...`, not the generic CRUD routes.

- An **organisation selector** above the graph switches which org's graph is
  loaded (defaults to the org coded `default`); switching it resets the
  current hierarchy, selection and filters.
- A **compact type filter** ("Types: N of M") is a dropdown of per-type
  checkboxes (with its own text filter, "All"/"None") that narrows which
  node types are drawn, alongside a free-text search box and a "highlight
  connections" toggle that dims everything but the selected node's
  neighbors.
- **Connect mode**: toggle "Connect" to switch the canvas into drag-to-draw
  edge creation — drag from one node to another and a picker lets you
  choose from the relationship types valid between those two entity types,
  then confirms the edge.
- **Typed attribute editing**: node attribute inputs, in both the
  create-node form and the property panel, are rendered per the
  attribute's declared `data_type` — a checkbox for `boolean`, a
  finite-number input for `number`, a date/datetime picker, and so on —
  instead of one plain text box. Edge (relationship) attributes are still
  edited as raw JSON.

An attribute definition whose `code` collides with a node's built-in
fields (`code`, `status`, `description`, `name`) is hidden from both the
create-node form and the property panel, with a small note explaining why
— the built-in column always wins server-side, so an input for the
shadowed attribute would silently never take effect.

Cytoscape caches its container's bounding rect when the instance is
created; if the page scrolls afterward (or in an automated browser test
that scrolls/resizes after mount), call `cy.resize()` before relying on
rendered node positions or hit-testing (tap/drag) — otherwise they're
computed against the stale rect.

To see anything on the page, seed some demo data first:

```bash
docker compose exec -T backend python -m app.seed_graph_demo
```

The seed is idempotent — re-running it does not create duplicates.

## Tests

```bash
# Backend (107 tests) — runs inside the backend container
docker compose exec -T backend pytest -v

# Frontend (Vitest + React Testing Library)
cd frontend && npm install && npm test
```

The backend test suite runs against its own `<db>_test` database, never the
one the running stack (and its admin UI / `/graph` demo page) uses.
`backend/tests/conftest.py` rewrites `DATABASE_URL` to `<db>_test`
(override with `TEST_DATABASE_URL`) and migrates it to head before any test
code imports `app` — the first `pytest` run creates and migrates that
database automatically; later runs just reuse it. Data created while
running `pytest` no longer shows up anywhere in the running stack.

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

Brings up a clean stack from scratch, applies migrations, logs in, exercises the
API and checks the frontend proxy:

```bash
docker compose down -v      # optional: start from a truly cold state
./scripts/smoke_test.sh
```

`scripts/graph_smoke_check.py` is the equivalent smoke check for the Graph
Editor sub-project: it assumes the stack is already up and migrated and that
`app.seed_graph_demo` has been run, then exercises `/api/graph/domain...`
end-to-end and checks the `/graph` page is served by the frontend proxy.

```bash
docker compose exec -T backend python -m app.seed_graph_demo
python scripts/graph_smoke_check.py
```

## Known limitations in this phase

- **Users cannot be created through the admin UI.** `hashed_password` is
  deliberately excluded from the generic CRUD API, so `iam.user_account` is
  read-only in practice and only the seeded admin exists. Provisioning
  additional users was never a stated MVP capability; it needs a dedicated
  endpoint that hashes a submitted plaintext password. `POST
  /api/iam/user_account/` returns a clean `409` (`hashed_password is
  required`) rather than a raw 500, since the NOT NULL column is simply
  unreachable through the generic schema any more.
- **Graph search matches labels and codes, not attribute values.** The
  Graph Editor's free-text search filters nodes by their label and their
  `code` attribute only; other EAV attribute values (e.g. a custom `rank`
  or `hired` attribute) are not searched.
- **No enforced RBAC.** Auth is real (JWT, bearer token on every CRUD and meta
  route), but `role`/`user_role` are not checked per endpoint — any
  authenticated user can read and write every table. Deferred by spec §2.
- **Styling is plain Tailwind,** not the shadcn/ui component library named in
  spec §7.1. Components were hand-rolled instead; functionally equivalent, but
  don't go looking for a shadcn install that isn't there.
- **JSONB fields are edited as raw JSON**, with no shape validation: any
  JSONB column in the generic admin form, and the Graph Editor demo page's
  edge (relationship) attribute editor. Node attributes on the Graph Editor
  demo page are the exception — those are typed by the attribute's declared
  `data_type`.
- **No optimistic locking.** Neither the generic CRUD `PUT` nor the Graph
  Editor's `PATCH` routes carry a version/etag check — the last save wins,
  silently overwriting a concurrent edit.
- Neither the backend nor the frontend image has a bind mount; see
  "Rebuilding after a code change" above — a code change is invisible to the
  running containers until `./scripts/rebuild.sh` rebuilds and recreates
  them.
- **Hierarchy collapse/expand is not implemented** on the Graph Editor demo
  page. Cytoscape's compound nodes provide nesting only; collapsing or
  expanding a compound node's children would require the
  `cytoscape-expand-collapse` extension, which is not currently installed.
