# Problem-Solver Platform — MVP Skeleton

A general-purpose problem-solving platform: model a real-world domain (entity
types, attributes, entities, relationships, parameters), write a problem over
that domain, and get an answer back. The **compiler** sits in the middle —
`classify` + `compile` + `choose` — so the Model editor never asks MILP vs
CP-SAT. LP, MILP and CP-SAT are execution targets, not the modelling language;
HiGHS is a fourth, when installed — it runs in a child process, because it
cannot share one with OR-Tools. An objective may mix terms by weight or
take them in order (`lex`).

This repository is the running product around that loop: containerized
infrastructure, the **schema v1** PostgreSQL schema (tables in `public`, plus
the 6 `iam` tables), an empty ClickHouse analytics schema, a FastAPI backend
that is part purpose-built and part generic CRUD, and a React admin UI.
Solving is async: `POST /api/v1/scenarios/{id}/runs` queues a `run`; a worker
records the roster, `constraint_result` (including slack), and, on
infeasibility, the fighting rules.

- Schema v1 design: [`docs/superpowers/specs/2026-09-19-schema-v1-migration-design.md`](docs/superpowers/specs/2026-09-19-schema-v1-migration-design.md)
- The Problem IR (what a model *means*): [`docs/contracts/problem-ir.md`](docs/contracts/problem-ir.md)
- The authoritative DDL it was built from: [`docs/schema/2026-09-18-schema-v1.sql`](docs/schema/2026-09-18-schema-v1.sql)
- Original platform skeleton design (v0, largely superseded): [`docs/superpowers/specs/2026-09-16-platform-skeleton-design.md`](docs/superpowers/specs/2026-09-16-platform-skeleton-design.md)

## The schema

Everything outside `iam` lives in `public`. There are three groups:

| Group | Tables |
|---|---|
| **Domain** | `domain`, `entity_type`, `attribute_def`, `entity`, `relationship_type`, `relationship`, `parameter_def`, `parameter_value` |
| **Problem** | `template`, `problem`, `model_version`, `scenario` |
| **Run** | `dataset`, `run`, `solution`, `constraint_result` |
| **Access** | `iam.organization`, `iam.user_account`, `iam.role`, `iam.user_role`, `iam.role_capability`, `iam.capability` |

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

`GET /api/meta/schema` lists **9** tables, not 20: the six `iam` tables and
the three flat `public` tables (`domain`, `template`, `problem`) go through the
generic CRUD factory. Everything else has a purpose-built router, or no router
at all — see the comment block in `backend/app/api/routers.py` for the reasoning
per table.

The compiler already sits in the middle: `classify` (what the IR is),
`compile` (IR + frozen dataset → solver-facing form), `choose` (capability
match). What a non-specialist needs from those three is not another backend.
It is seeing the outputs in domain language — on the Model editor before
publish, and on a run as held rules, fighting rules, empty ranges, and slack.

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
| `/entities`, `/entities/:id` | Entities, with attribute inputs typed by each attribute's `data_type`, and a condition builder that filters server-side (`?type=` `&expr=` `&q=` so a filtered list is a link) |
| `/parameters` | Parameter definitions and a grid for their cells |
| `/model` | The Model editor (below) — writes a new `model_version` |
| `/versions` | A problem's model versions, **read-only**, with an IR viewer |
| `/scenarios` | Patches over a version: disable, harden, or soften a rule. New / Edit need `model.publish`; Solve stays |
| `/runs` | Solve a scenario and read the answer (below) |
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
  Entities page sends to the server as `?expr=`. Fields are grouped by entity
  type. A rule about one type leaves every other type drawn; a relationship
  count still applies to every node.
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

## Model editor

`/model` is where a problem becomes a model: the rules a solver must respect,
and what it should make as small or as large as it can. It writes
`POST /api/v1/problems/{id}/versions`. `/versions` is the read-only twin — a
viewer over versions that already exist, including ones this page published.

A model belongs to a **problem**, and a problem belongs to a **domain**. Choose
the domain in the sidebar first; the page then lists that domain's problems
(`?problem=` in the URL). With no problem yet, it points at `/public/problem`
rather than inventing one.

**Publishing writes a new version. It never overwrites one.** `model_version`
is immutable (`forbid_update()`), which is what keeps a run's answer
attributable to the exact model that produced it. "Starting from" is a starting
point — including an older version — not an edit of that row. A problem with
no versions yet offers **Start a model**, which is an empty document of the
same shape, not a missing one: a missing `constraints` and an empty one are
different documents, and only one of them is valid.

The page has three parts, in the order a model is actually written:

1. **Declarations.** Which of the domain's entity types are this model's
   `sets`; which of its parameters it reads (the index comes from
   `parameter_def`, in order — typing `demand[shift, day]` would type-check by
   arity and silently mean a different model); and the **variables** a solver
   decides (`binary`, `integer` or `continuous`). Removing a declaration that
   a rule still uses is refused here, naming the rule, rather than after
   publish.
2. **Rules.** Each constraint has an id (the same one a scenario patch and
   `constraint_result` will use), an optional `forall` of index bindings, a
   left-hand term, a relation (`<=`, `=`, `>=`), a right-hand term, and
   `hard` or `soft`. A soft one carries a positive integer **weight** — the
   cost of one unit of violation. A binding is an index over a set, optionally
   filtered (`where`: only the weekend days) and optionally walked (`via`:
   everything under North Region). The filter is react-querybuilder, because
   a filter is a boolean condition tree; the arithmetic around it is not, so
   `TermBuilder` edits that. A walk names the relationship and **which end of
   the edge the anchor sits at**, not a direction — `from: "r"` on
   `reports_to` walks down because `r` is at the parent end.
3. **Objective.** Minimize or maximize a weighted sum of terms. Omit it
   entirely for a pure feasibility problem; an empty objective and a missing
   one would otherwise be two spellings of "optimise nothing", so the page
   drops the key when there are no terms.

`relationships` is not a fourth editor. The page derives it from the `via`
walks actually written, because a relationship has no use except to walk it.
`sets` stays declared by hand: a set may be carried and never used.

The document this produces is the Problem IR. The contract —
[`docs/contracts/problem-ir.md`](docs/contracts/problem-ir.md) — is what a
model *means*; `backend/app/ir/contract.json` is what a validator may
accept. This page runs the **shape** half in the browser (`checkIrShape`)
and disables Publish on the first refusal. The server judges it again,
including the **domain** half (do these names exist, do the walk's ends
match the relationship type). A wrongly built model is named, not stored.

When the shape is valid, the page posts the draft to `POST /api/v1/classify`
with the problem id — the same Python `classify()` a run records, compiled
against a **read** of the live domain (not `snapshot_dataset()`, which writes).
**What this model is** is planner language: every decision is yes or no;
every rule is linear; at least one rule can bend. A `where`/`via` that matches
nobody is listed the same way a run lists it. `fractional-data` can appear
here because those numbers live in the domain, not the IR. The editor never
offers a solver; it does say which kind `choose()` would pick (a
combinatorial solver, a linear one, a mixed one, or that this platform has
nothing that can take the draft).

A **template** is a starting IR, not a solver and not a second model
language. The seeded `weekly_rota` row is the same document the Workforce
demo publishes. `POST /api/v1/templates/{id}/apply` walks `domain_seed`
first — missing types, people, days, shifts and demand cells are created;
names that already exist are left alone — then writes a problem, its first
version, and an `as modelled` scenario. Dashboard **Start from weekly_rota**
is that verb; if the domain already has a problem from that template, it
opens it instead. An empty `domain_seed` still 422s from `validate_ir`, so
a template that only carries IR cannot half-build a domain.

Two leftovers from before that contract, still sitting on a long-lived
database, are handled rather than crashed on:

- A constraint that is an id and a note with no `left`/`right` — the seeded
  demo's original version 1. The page says it is named but not expressed,
  and **Start expressing it** fills in empty arithmetic so it can be written
  rather than re-typed from scratch.
- An objective term with no `expression`, same treatment.

A version like that cannot be published as-is: the contract refuses an
unexpressed constraint, and so does the compiler.

## Runs

`/runs` is where a scenario becomes an answer. A run belongs to a
**scenario**, not to a problem: the scenario names the model version and any
patch (`disable` / `harden` / `soften`), so "solve this" is only well defined
once one is chosen. The page lists a domain's problems, then that problem's
scenarios (`?problem=` / `?scenario=`).

**Submitting queues a run.** `POST /api/v1/scenarios/{id}/runs` freezes a
`dataset` and returns `queued`; a worker solves it. The page polls until the
status settles. A run is immutable once written — solving again makes a new
one, which is what lets two be compared.

The detail leads in planner language, not solver names:

- **Optimal / feasible.** All mandatory rules held (or N broke); preferences
  bent at a cost. Then the roster, in the names frozen on the dataset
  (migration `0012`).
- **Infeasible.** Why there is no answer: the fighting rules and the days
  they collide on. **Make these preferences** creates a scenario
  `{soften: {id: weight}}` from those ids — the same `patched()` verb a
  scenario already implements. It is not a second relaxation solver.
- A `where`/`via` that matched nobody is listed as a rule that never applied
  to anyone (a vacuously true constraint, usually a filter or a missing
  population).
- Held rules with slack `0` are marked **no room left**. Slack is the
  residual at the assignment (migration `0017`), filled for every backend.
  A linear solver also reports a **shadow price** (migration `0019`): how
  much the goal would move if that rule moved, and **reduced costs**
  (migration `0020`) on decisions that would move it. CP-SAT leaves both blank.

Solver, class, `why_solver` and wall time sit under **Technical**. The solver
dropdown on submit is optional and gated on `solver.configure`; the default
is `choose()`.

**Stop this run** (`POST /api/v1/runs/{id}/cancel`) is how a queued or
running solve is abandoned. A queued run becomes `cancelled` immediately. A
running one is asked to stop; the worker records `cancelled` instead of an
answer. A settled run is refused: the result is already written. The worker
heartbeats while it solves (migration `0018`); a dead worker is reclaimed
from silence on that clock, not from a thirty-minute guess at `started_at`.

## Checks

There is no CI here and no git remote for a hosted runner to hook into, so the
only check that ever runs is one you run. `scripts/check.sh` is that one
command.

```bash
scripts/check.sh              # full: frontend + build + backend  (~2 min)
scripts/check.sh --fast       # frontend only, no Docker          (~20 s)
scripts/check.sh --backend    # the backend suite on its own
```

It reports pass/fail per step, prints a summary, and exits non-zero if
anything failed:

| step | what it is |
| --- | --- |
| frontend deps | `npm ci`, but only when `node_modules` is missing or older than `package-lock.json`. A stale `node_modules` fails with "cannot find module" errors that read exactly like broken source code. |
| frontend lint | `npm run lint` — ESLint with `--max-warnings 0` (see **Known limitations**). |
| frontend typecheck | `tsc --noEmit`. A separate signal from the tests: vitest transpiles each file and never type-checks, so a type error does not fail the suite. |
| frontend tests | `vitest run` — 1268 tests across 62 files. |
| frontend build | `npm run build` — a third signal again: `tsc -b` plus a real rollup resolve. |
| backend tests | `pytest -q` — 754 tests, in a throwaway container with the working tree bind-mounted. |

That last one is the reason this script exists rather than a README paragraph.
`docker compose exec -T backend pytest` runs the code baked into the image, not
the code in your working tree, and will report a confident pass for a change
you have not built. `check.sh` always runs `docker run --rm` with the tree
mounted over `/app`.

What it never does: migrate a database, build an image, run `docker compose
up` / `restart` / `scripts/rebuild.sh`, create or recreate a container, or
touch the `solver` database or ports 3010/8010. If a precondition is missing
it names the command that fixes it and exits non-zero, rather than fixing it
for you. The backend suite runs against `solver_test`, which
`backend/tests/conftest.py` drops and recreates — guarded there, and again in
`check.sh`, by a check that the name ends in `_test`.

It needs an env file for the backend container: `<repo>/.env`, or, in a
worktree (where `.env` is gitignored and therefore absent), the main
checkout's. Override with `SOLVER_ENV_FILE`.

On Windows it is written for Git Bash, and sets `MSYS_NO_PATHCONV` itself —
without it, MSYS rewrites the container-side `-w /app` into
`C:/Program Files/Git/app` and docker refuses.

### The pre-commit hook

Opt-in, and installed by hand, because git never shares `.git/hooks`: a hook
committed to this tree does nothing at all until someone installs it.

```bash
bash scripts/install-hooks.sh              # install
bash scripts/install-hooks.sh --status     # what is installed
bash scripts/install-hooks.sh --uninstall  # remove it again
```

The `pre-commit` hook runs `scripts/check.sh --fast` and refuses the commit if
it fails. Skip it for one commit with `git commit --no-verify`, or for a shell
session with `SOLVER_SKIP_CHECKS=1`. It checks the working tree, not the staged
snapshot, and it says so rather than printing a meaningless green summary when
a commit stages nothing under `frontend/` — the fast checks cover only the
frontend, so run the full `scripts/check.sh` before merging a branch.

A worktree shares its main checkout's `.git/hooks`, so installing from one
worktree installs for all of them.

## Tests

`scripts/check.sh` runs both suites for you, the right way; these are the
individual commands.

```bash
# Backend — 754 tests
docker compose run --rm --no-deps -T backend pytest -q

# Frontend — 1268 tests across 62 files
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

- **The Model editor is what creates a model version.** `/model` publishes an
  IR through `POST /api/v1/problems/{id}/versions`; `/versions` remains the
  read-only viewer. Submitting a scenario writes `dataset`, `run`, `solution`
  and `constraint_result`. The editor classifies a draft; it does not solve.
- **A parameter may be indexed by the same entity type twice.**
  `distance[location, location]` is an ordinary grid. Migration `0025` dropped
  the temporary CHECK that refused it: snapshots now key a repeated index by
  position (`"0"`, `"1"`) so the two ends stay distinct, and uniquely-typed
  parameters (`demand[day, shift]`) keep their type-name keys so existing
  dataset hashes do not move.
- **The migration is one-way.** See
  [`docs/runbooks/schema-v1-cutover.md`](docs/runbooks/schema-v1-cutover.md):
  the downgrade drops the v1 tables and recreates nothing, contrary to what
  the design spec (§8) asked for. A `pg_dump` is the only rollback.
- **Users are created with a password, never a hash.** The Users form
  (generic CRUD on `iam.user_account`) sends `password`; the factory hashes
  it and `hashed_password` stays hidden — it is not in the metadata, not
  filterable, and never returned. An empty password on edit leaves the
  stored hash. Creating a user opens that row so Related records can offer
  **User roles → New** (the same prefilled form as any other child table).
  The form remounts when the table changes, so the parent id from the
  query string is not left behind from the record you just left.
  A user with no role can sign in and cannot do anything else.
- **Capabilities gate writes.** Auth is JWT on every route; what the
  caller may do is a row on a role (migration `0013`), enforced in one
  API dependency and reported by `GET /api/v1/me`. Screens hide New /
  Save / Delete unless the matching capability is present, and the API
  refuses a write that arrives anyway. A planner can solve without being
  able to change the model. Creating users and assigning roles is
  `iam.manage`, not `domain.edit` — a modeller shapes the domain, they do
  not decide who else may. Changing your own name, email or password is
  `PATCH /api/v1/me`, not that grant: Settings offers it to whoever is
  signed in.   The Access nav offers Users, Roles, User roles, Role
  capabilities and Capabilities only to an account that holds `iam.manage`, and
  Organizations only to one that holds `domain.edit`. A planner sees
  none of those links, and the Access heading goes with them. Assigning a role is
  not saying what that role may do — the grant is a `role_capability`
  row, the same factory form, and `capability_code` is a foreign key to
  `iam.capability` — the same picker as any other reference, not a
  datalist of codes. That catalogue is itself a factory table, read-only:
  New / Save / Delete stay off, and POST is 405. A new verb is still an
  INSERT in a migration. Creating a problem or a template is
  `model.publish`, not `domain.edit` — starting a model is not shaping
  entity types. The Problem nav offers Templates only to an account that
  holds that grant; Problems and the Model editor stay, because a planner
  still reads them. A typed URL still reads.
- **Styling is plain Tailwind,** not the shadcn/ui component library named in
  the original spec §7.1. Components were hand-rolled instead; functionally
  equivalent, but don't go looking for a shadcn install that isn't there.
- **Relationship attributes are typed when the type declares them.** The same
  `attribute_def` object now belongs to exactly one owner (entity type or
  relationship type; migration `0024`). A type with no defs still edits `attrs`
  as JSON, which is why existing free-form payloads stay legal. Once a def
  exists, the graph panel uses the same typed controls as an entity, and the
  database refuses an unknown key or a wrong type with the same `kind`s as
  `entity_validate`. Generic JSONB columns on other tables remain a JSON box.
- **Optimistic locking covers the purpose-built forms and generic CRUD.**
  `entity`, `entity_type`, `relationship_type`, `relationship` and
  `parameter_value` plus the factory tables (`domain`, `template`,
  `problem`, `iam.organization`, `iam.user_account`, `iam.role`,
  `iam.user_role`, `iam.role_capability`) carry an `updated_at` (migrations
  `0010`, `0021`, `0022`, `0023` and `0026`, maintained by a trigger so
  every writer moves it). Their forms
  send it back and a save built on a superseded read is refused with a
  **409**, offering a reload that keeps whatever the person has typed. The
  check is also opt-in per request: a write that omits `updated_at` is not
  checked, which is what keeps scripts, a first write into an empty parameter
  cell, and the graph's node rename working.
- **Hierarchy collapse sits on the existing canvas.** Compound nodes still
  nest; with a hierarchy selected, Minus on a focused parent (or Collapse
  all) removes its descendants from the canvas and names how many are
  sitting under it. Equals and Expand all put them back. The keyboard only
  walks what is still drawn, the same rule a filter already uses. No extra
  Cytoscape extension.
- **Lint is on, and it is green.** `npm run lint` is the stock Vite React-TS
  set minus the rules that would start this tree on a wall:
  `@typescript-eslint/no-explicit-any` (a typing debate), react-hooks v7's
  compiler rules (`set-state-in-effect`, `refs`), and
  `react-refresh/only-export-components` (HMR, not product). Unused
  bindings that start with `_` are allowed. `scripts/check.sh` runs it
  because `package.json` now has a `lint` script; `--max-warnings 0` so a
  new unused import fails the step. Twelve disable comments remain: ten
  `react-hooks/exhaustive-deps` on mount-only effects, Login's
  `no-control-regex` for the `next` sanitiser, and `dom.d.ts` keeping
  the React merge parameter named `T` (`_T` replaces the interface).
- Neither image has a bind mount; see "Rebuilding after a code change".
