# Schema v1 Migration — Design

**Date:** 2026-09-19
**Status:** approved (design); awaiting spec review
**Base:** master @ `5d1ca66` (31 tables, UUID PKs, EAV attributes, fully generic CRUD)
**Authoritative DDL:** [`docs/schema/2026-09-18-schema-v1.sql`](../../schema/2026-09-18-schema-v1.sql) — supplied verbatim by the user

## Goal

Replace the platform's 31-table schema with the user's 16-table "schema v1", and rebuild the API and UI around it. v1 is an opinionated model — typed attributes, entity roles, hierarchies as relationships, indexed parameters, immutable model versions and reproducible run snapshots — and the migration's job is to make the product express that intent rather than continue to present the database as a set of tables.

## 1. Scope

### In scope

- The 8 **DOMAIN** tables: `domain`, `entity_type`, `attribute_def`, `entity`, `relationship_type`, `relationship`, `parameter_def`, `parameter_value`.
- The 4 **PROBLEM** tables: `template`, `problem`, `model_version`, `scenario`.
- The 4 existing **`iam`** tables, kept unchanged (`organization`, `user_account`, `role`, `user_role`).
- The 4 **RUN** tables — `dataset`, `run`, `solution`, `constraint_result` — **created only**: DDL, migration, immutability triggers, `snapshot_dataset()`, `run_overview`, and tests. No API, no UI, no queue.

### Out of scope

- The solver and compiler (`psp/`, `ProblemIR`, cp-sat). **They do not exist in this repository.** Verified 2026-09-19: no `psp/` directory, no `ortools` dependency, no match for `ProblemIR` or `cp-sat` anywhere in the tree.
- The run queue, worker, run-submission UI and results screens. These become their own project once the solver exists.
- Multi-tenancy changes. `iam` is carried over as-is; v1's own tables gain no `organization_id`.

### Why RUN's tables are created but not wired

`snapshot_dataset()` is the single most failure-prone object in v1: it reads set and parameter names out of the IR, resolves them against live domain data, and must emit "exactly the JSON shape `psp/data.py` reads". Creating the tables and the function now lets it be tested against real seeded domain data, months before the solver arrives. Deferring them would mean writing that function later with no way to exercise it.

## 2. Decisions taken

| Question | Decision | Rationale |
|---|---|---|
| Scope boundary | DOMAIN + PROBLEM now; RUN tables created, not wired | The solver is absent; a run subsystem cannot be verified without it |
| Auth / tenancy | Keep the 4 `iam` tables alongside v1 | v1 has no auth at all, and `get_current_user` is a dependency on *every* generated route. Dropping it would open the API and orphan the session-expiry UX work |
| Existing data | **Drop and recreate** | The database holds 3 entity types, 7 entities, 0 problems (measured 2026-09-19). A migration path would have to synthesise `attribute_def` rows and guess each `data_type` in order to carry ten rows |
| API / UI architecture | **Hybrid** — purpose-built for the domain-modelling core, generic CRUD for flat tables | v1's core concepts are not row-shaped; a generic table editor cannot express them. Flat tables keep the existing factory and its UX investment |
| DDL amendments | Allowed, listed here for approval | The user approved proposing amendments rather than freezing the DDL or amending silently |
| Nav grouping | Three UI groups: Domain, Problem, Runs | Postgres schemas are gone, but the grouping is still how users think about it |
| `entity_role` | Drives UI affordances (grouping, icons); reserved for the compiler | v1 enforces nothing beyond the enum |
| Parameter numeric type | Integer-only, surfaced explicitly in the UI | `parameter_def.default_value int`, `parameter_value.value int`, `run.objective bigint` — deliberate for CP-SAT. The UI must say so rather than let a user type `2.5` and hit a trigger error |

## 3. Database

One Alembic migration: drop the 24 `domain.*` and `problem.*` tables, create v1's 16 tables in `public`, leave the `iam` schema untouched. Enums `entity_role`, `attr_type`, `run_status`. All triggers, functions and the `run_overview` view exactly as supplied, with three amendments.

### Amendment (a) — structured validation errors

**Problem.** `entity_validate`, `relationship_validate` and `parameter_value_validate` raise bare `RAISE EXCEPTION`, which reaches the driver as SQLSTATE **P0001** with a free-text message and no constraint name. The API cannot attribute it to a field, so the per-field error messages built for audit finding C-5 would regress to generic 500s.

**Change.** Every `RAISE EXCEPTION` in those three functions gains an explicit error code and a machine-readable detail payload, keeping the human sentence as the message:

```sql
RAISE EXCEPTION 'entity %: attribute "%" must be %', NEW.key, d.name, d.data_type
    USING ERRCODE = '23514',
          DETAIL  = jsonb_build_object(
              'kind',   'attribute_type',
              'field',  d.name,
              'record', NEW.key,
              'expected', d.data_type
          )::text;
```

`23514` is `check_violation`, which is what these are. The API reads `DETAIL`, parses the JSON and returns 422 with the offending field named.

### Amendment (b) — `next_model_version` race

`SELECT max(version)+1` lets two concurrent inserts for one problem compute the same version and collide on `UNIQUE (problem_id, version)`. Take a transaction-scoped advisory lock keyed on the problem first:

```sql
PERFORM pg_advisory_xact_lock(NEW.problem_id);
```

The single-argument form takes a `bigint`, so `problem_id` is used directly. The
two-argument `(int, int)` form would require casting a `bigint` down to `int`,
which is lossy for large ids. This is the only advisory lock in the schema, so
there is no key-space collision to design around; if others are added later they
must share a documented key space.

### Amendment (c) — `relationship_validate` false cycle on UPDATE

The trigger fires on UPDATE while the row's **pre-update** version is still in the table, so the recursive descent can traverse the old edge and report a cycle that re-pointing would not create. Exclude the row under validation from the walk:

```sql
WITH RECURSIVE down AS (
    SELECT to_entity_id AS id FROM relationship
     WHERE relationship_type_id = rt.id
       AND from_entity_id = NEW.to_entity_id
       AND id IS DISTINCT FROM NEW.id
    UNION
    SELECT r.to_entity_id FROM relationship r JOIN down ON r.from_entity_id = down.id
     WHERE r.relationship_type_id = rt.id
       AND r.id IS DISTINCT FROM NEW.id)
SELECT 1 FROM down WHERE id = NEW.from_entity_id
```

A test must re-point an existing hierarchy edge to a legal new parent and assert it succeeds.

### Documented, not changed

`entity_validate` **materialises** defaults into `attrs` on write. Changing an `attribute_def.default_value` later therefore does not update existing rows. This is a reasonable choice — it makes each row self-describing and keeps snapshots stable — but it must be stated in the UI when editing a default.

### Also noted

The DDL as supplied opens `BEGIN;` and never commits. `COMMIT;` was appended with an inline note.

## 4. Backend

### Generic factory — retained, narrowed

Kept for the genuinely flat tables: `domain`, `template`, `problem`, `scenario`. Two changes:

1. **`bigint` keys.** Route parameters become `int`, not `UUID`; `backend/app/crud/factory.py` types `item_id: UUID` on every by-id route today.
2. **Per-table capabilities.** Table metadata gains `creatable` / `updatable` / `deletable`. Immutable tables (`model_version`, `dataset`, `solution`, `constraint_result`) expose no PUT or PATCH, so the UI never renders an edit form that a trigger will reject.

### Purpose-built routers

| Resource | Endpoints | Why not generic |
|---|---|---|
| Entity types | CRUD + nested `attribute_def` CRUD | A type and its attributes are edited as one thing |
| Entities | list / get / create / update / delete, `attrs` validated | The form is generated from `attribute_def`, not from columns |
| Relationship types | CRUD | `is_hierarchy` has structural consequences |
| Relationships | CRUD, plus a graph read | Edges, not rows |
| Parameters | `GET` a grid slice; `PUT` upserts cells | Composite array key; a spreadsheet, not a list |
| Model versions | list / get / create-next-version | Immutable; "edit" means insert |

### Error translation

A single `translate_db_error()` handles both paths — existing unique-violation mapping by constraint name, and the new `23514` + JSON `DETAIL` payload — and returns 422 with a field name. `formatApiError` and the per-field form errors from the merged UX branch then keep working unchanged.

## 5. Frontend

Everything from the merged `ux-fixes` branch is retained: app shell, skip link, drawer, toasts and live regions, skeletons, offline notice, `DataTable` with its card layout and row-actions portal, `FkPicker`, the unsaved-changes guard.

Two carried-forward corrections, from that branch's own final review:

- `DataTable` builds a row link from `row.id`; it must handle `bigint` keys and the tables that have no single `id`.
- `isIdentifierColumn` keys on `type === "uuid"`, which stops firing under identity keys — surrogate keys would render as ordinary data columns.

New screens:

- **Domain selector** — everything below is domain-scoped.
- **Entity type editor** — the type plus its `attribute_def` rows, including `role`.
- **Entity form generated from `attribute_def`** — the typed controls in `attributeInputs.tsx` port over almost directly; the EAV work anticipated this shape.
- **Parameter grid** — pick the index types, edit cells, sparse with a default.

### Graph editor

Adapts without redesign. Nodes are `entity`, edges are `relationship`, and compound nesting comes from a relationship type with `is_hierarchy = true` plus `entity_descendants()`, replacing the `hierarchy` / `hierarchy_node` tables. The Cytoscape gotchas already documented in the codebase continue to apply: node `position` is stored by reference, and the container rect is cached at mount so `cy.resize()` is required after scrolling.

## 6. Seed data

The existing demo (employee / unit / shift) is reproduced in v1's shape: one `domain`, entity types with roles (`agent`, `org`, `time`), `attribute_def` rows exercising every `attr_type`, entities, a hierarchy relationship type with a real tree, a two-index `parameter_def` with values, one `problem`, one `model_version` with a small IR, and one `scenario`. The seed must be sufficient for `snapshot_dataset()` to run and produce a non-empty dataset.

## 7. Testing

**Backend** — pytest against the isolated `solver_test` database. Triggers are tested *directly*, not only through the API: unknown attribute, missing required attribute, wrong type per `attr_type`, enum value not in `enum_values`, relationship type mismatch, each cardinality violation, hierarchy self-loop, hierarchy cycle, legal re-point of an existing edge (amendment c), parameter index arity and type mismatch, parameter cleanup on entity delete, immutability on all four RUN tables, version auto-increment, hash stability, and `snapshot_dataset()` dedup returning the same id for unchanged data. Then API-level tests asserting each maps to a 422 naming the field.

**Frontend** — vitest; the 335 existing tests must stay green except where a screen is deliberately replaced.

**Browser** — real-Chrome verification for every UI task, with axe. This is the practice that caught the bugs a green suite missed on the previous branch: an unreachable skeleton, a double-navigating row link, and a portal that drifted from its row on scroll.

## 8. Risks

- **`snapshot_dataset()` has no consumer yet.** Its output shape is asserted against the DDL's comments, not against a real reader. Tests must pin the shape explicitly so a future `psp/data.py` mismatch is a visible test failure rather than a silent one.
- **The migration is not reversible.** Drop-and-recreate is agreed, but the Alembic downgrade cannot restore dropped data. The downgrade should recreate the old structure and say so.
- **Two UI idioms.** Generic and purpose-built screens coexist. The generic ones must not drift visually from the hand-built ones.

## 9. Decomposition

This is large enough that the plan should sequence it as: migration and models → meta layer and capabilities → generic CRUD adaptation → error translation → domain core API → domain core UI → parameters → problem and model versions → graph adaptation → seed → verification. Each stage should leave the application working.
