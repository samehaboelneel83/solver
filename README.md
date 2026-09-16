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

## Tests

```bash
# Backend (41+ tests) — runs inside the backend container
docker compose exec -T backend pytest -v

# Frontend (Vitest + React Testing Library)
cd frontend && npm install && npm test
```

## Full-stack smoke test

Brings up a clean stack from scratch, applies migrations, logs in, exercises the
API and checks the frontend proxy:

```bash
docker compose down -v      # optional: start from a truly cold state
./scripts/smoke_test.sh
```

## Known limitations in this phase

- **Users cannot be created through the admin UI.** `hashed_password` is
  deliberately excluded from the generic CRUD API, so `iam.user_account` is
  read-only in practice and only the seeded admin exists. Provisioning
  additional users was never a stated MVP capability; it needs a dedicated
  endpoint that hashes a submitted plaintext password. Note that
  `POST /api/iam/user_account/` currently returns a 500 rather than a clean
  4xx, since the required column simply isn't in the schema any more.
- **No list filtering.** `GET /api/{schema}/{table}/` supports `limit`/`offset`
  pagination but not the per-column equality filtering described in spec §6.2,
  and `DataTable` has no filter UI. Recorded as a follow-up.
- **No enforced RBAC.** Auth is real (JWT, bearer token on every CRUD and meta
  route), but `role`/`user_role` are not checked per endpoint — any
  authenticated user can read and write every table. Deferred by spec §2.
- **Styling is plain Tailwind,** not the shadcn/ui component library named in
  spec §7.1. Components were hand-rolled instead; functionally equivalent, but
  don't go looking for a shadcn install that isn't there.
- **JSONB fields are edited as raw JSON** in the generic form, with no shape
  validation. Deferred by spec §2.
- The backend image has no bind mount: after changing anything under `backend/`,
  run `docker compose build backend && docker compose up -d backend` before the
  container sees it.
