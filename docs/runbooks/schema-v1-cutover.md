# Cutting a live database over to schema v1

Read this before running `alembic upgrade head` on any database that holds
data you care about.

## The one thing that matters

**Migrating to schema v1 destroys everything in the v0 `domain` and
`problem` schemas, and nothing brings it back except a backup you took
first.** Migration `0006`'s first two statements are:

```sql
DROP SCHEMA IF EXISTS domain CASCADE;
DROP SCHEMA IF EXISTS problem CASCADE;
```

There is no data migration. v0's 31 tables and v1's 16 do not correspond
row for row, and the design (`docs/superpowers/specs/2026-09-19-schema-v1-migration-design.md`,
§2) settled on drop-and-recreate rather than a mapping.

So: **take a dump, then migrate.** In that order, every time.

## Is this database affected?

Check the revision. Anything at `0005` or below is a v0 database with data
to lose; `0006` or above is already v1.

```bash
docker compose exec -T postgres psql -U solver -d solver \
  -tAc "SELECT version_num FROM alembic_version"
```

At the time of writing, the development `solver` database is at `0005`
with real rows in `domain.entity`. It has not been cut over.

`scripts/smoke_test.sh` makes this same check and refuses to migrate
anything that is neither empty nor already on v1, so you cannot trip over
the cutover by running the smoke test.

## Procedure

### 1. Stop writing to the database

```bash
docker compose stop backend frontend
```

Leave `postgres` running — the dump needs it.

### 2. Take the dump, and check it

```bash
docker compose exec -T postgres pg_dump -U solver -Fc solver > solver-pre-v1.dump
ls -l solver-pre-v1.dump          # not zero bytes
docker compose exec -T postgres pg_restore -l /dev/stdin < solver-pre-v1.dump | head
```

`-Fc` (custom format) is what `pg_restore` reads, and it is what makes a
selective restore of just the old `domain` schema possible later. A plain
`.sql` dump works too but gives you less to work with.

Keep this file somewhere that is not the container.

### 3. Migrate

```bash
docker compose run --rm --no-deps -T backend alembic upgrade head
```

Use `run --rm --no-deps`, not `exec`. On a cold start the backend's own
startup hook crashes until the tables exist and `restart: unless-stopped`
restarts it; an `exec`'d alembic process attached to that container can be
killed mid-transaction, and since each migration is one transaction the
whole run then silently rolls back.

### 4. Bring the stack back and seed something to look at

```bash
docker compose up -d backend frontend
docker compose exec -T backend python -m app.seed      # optional demo domain
```

The database is empty of domain data at this point: v1 has no rows until
you create them or run the seed.

### 5. Confirm

```bash
./scripts/smoke_test.sh
```

## The downgrade will not undo this

`alembic downgrade 0005` runs `0007.downgrade()` then `0006.downgrade()`.
Both are pure `DROP`s:

| Migration | `downgrade()` does | `downgrade()` does **not** do |
|---|---|---|
| `0007` | drops the 8 v1 PROBLEM/RUN tables, the `run_overview` view, `run_status`, and the hash/immutability/version functions and triggers | recreate anything |
| `0006` | drops the 8 v1 DOMAIN tables, `entity_role`/`attr_type`, and the validation functions and triggers | recreate the v0 `domain` and `problem` schemas, or their 27 tables, or a single row of their data |

The net effect of a full downgrade is a database with only the four `iam`
tables and an `alembic_version` of `0005` — a v0 revision marker over a
database with no v0 schema in it. The application will not start against
that state, and `alembic upgrade head` from there simply builds v1 again.

**A downgrade is not a rollback plan. The dump is the rollback plan.**

### Rolling back for real

```bash
docker compose stop backend frontend
docker compose exec -T postgres dropdb -U solver solver
docker compose exec -T postgres createdb -U solver solver
docker compose exec -T postgres pg_restore -U solver -d solver --no-owner < solver-pre-v1.dump
docker compose up -d backend frontend
```

That restores the schema, the data *and* the `alembic_version` row, so the
database is back at `0005` exactly as it was.

## Deviation from the design spec, recorded

Spec §8 says, of the migration's irreversibility:

> The downgrade should recreate the old structure and say so.

**The implementation does not recreate the old structure.** Both
`downgrade()` functions drop the v1 objects and create nothing; the
comments at the top of each say so plainly, and this note is the "say so".

This was not decided; it is simply what was built, and it is recorded here
as a deviation rather than presented as the design. Two things follow:

* **Closing it is not free.** Recreating v0's structure means carrying the
  full v0 DDL — 27 tables across two schemas — inside the downgrade of a
  migration whose entire purpose is to delete them, and it would still
  restore no data, so it would produce an empty v0 schema that looks like
  a rollback and is not one. That is arguably worse than an honest refusal.
* **The useful half is cheap.** If this is reopened, the version worth
  building is a downgrade that *refuses* unless the operator passes an
  explicit override, pointing at this runbook — a guard rather than a
  reconstruction.

Until someone rules on it, the position is: the downgrade is a
development convenience for moving between revisions on a database you do
not mind losing, and the dump in step 2 is the only rollback.
