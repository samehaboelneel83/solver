# Schema v1 Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the platform's 31-table schema with the user's 16-table schema v1, and rebuild the API and UI around it so the product expresses v1's intent (typed attributes, entity roles, hierarchies-as-relationships, indexed parameters, immutable model versions) instead of presenting the database as tables.

**Architecture:** Hybrid. Purpose-built routers and screens for the domain-modelling core (entity types with attribute defs, entities with `attribute_def`-driven forms, relationship types and the graph, the parameter grid, model versions). The existing generic CRUD factory is retained only for the flat tables (`domain`, `template`, `problem`), narrowed to `bigint` keys and gaining per-table capability flags. Validation lives in Postgres triggers; the API translates their structured errors into 422 responses naming the offending field.

**Tech Stack:** FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2.9, Alembic 1.13, PostgreSQL 14+, React 18, TypeScript, Vite, React Query v5, React Router 6, Tailwind 3, Cytoscape.js, pytest, vitest, Playwright + axe-core.

**Spec:** `docs/superpowers/specs/2026-09-19-schema-v1-migration-design.md`
**Authoritative DDL:** `docs/schema/2026-09-18-schema-v1.sql`

## Global Constraints

- Schema v1's 16 tables live in the `public` schema. The 4 `iam` tables stay in the `iam` schema, unchanged. Do not add `organization_id` to any v1 table.
- Primary keys are `bigint GENERATED ALWAYS AS IDENTITY`. No UUIDs in v1 tables.
- The 4 RUN tables (`dataset`, `run`, `solution`, `constraint_result`) are **created and tested but not wired**: no router, no UI, no queue. The solver they serve does not exist in this repository.
- Existing domain/problem data is dropped, not migrated.
- Backend suite must stay green (114 tests at plan time, growing). Frontend suite must stay green (335 tests at plan time, growing) and `npm run build` clean.
- No new npm dependencies. New Python dependencies require justification in the task report.
- Neither Docker image has a bind mount: run `bash scripts/rebuild.sh` before any browser check or the container serves stale code.
- Every UI task is verified in real Chrome with axe. Current baseline: **0 axe violations across 10 page states** — no task may regress it.
- Playwright harness: `C:/Users/user/AppData/Local/Temp/claude/d--solver/808fd578-f87a-41ee-9abc-5d2d5ccc96d4/scratchpad/e2e/` — `lib.js` exports `launch()`, `loginUI(page)`, `api(method, path, body)`, `shot()`, `note()`, `finding(sev, area, title, detail)`, `finish(browser, name)`. Drives installed Chrome; `@axe-core/playwright` installed. Write new scripts; never modify existing ones.
- Backend tests run against an isolated `solver_test` database via `backend/tests/conftest.py`, which rewrites `DATABASE_URL` at import time. The app's own database is never touched by the suite.
- Compose service for Postgres is named `postgres`, not `db`. Credentials come from `.env` (`POSTGRES_USER`, `POSTGRES_DB`).
- Two traps this codebase has sprung repeatedly: Playwright's auto-scroll hides clipped-element bugs — assert reachability with `elementFromPoint`, not a click; and `.click({force:true})` bypasses event dispatch and gives false focus results — use real `page.mouse.click()` at unobscured coordinates.
- Cytoscape: node `position` is stored **by reference** (never share one object across nodes); the container rect is cached at mount, so call `cy.resize()` after scrolling before hit-testing.

---

## File Structure

**Backend — created**
- `backend/alembic/versions/0006_schema_v1_domain.py` — drops `domain.*`/`problem.*`, creates enums + the 8 DOMAIN tables, their functions and triggers.
- `backend/alembic/versions/0007_schema_v1_problem_run.py` — creates the 4 PROBLEM + 4 RUN tables, hashing, immutability, versioning, `snapshot_dataset()`, `run_overview`.
- `backend/app/models/v1_domain.py` — SQLAlchemy models for the 8 DOMAIN tables.
- `backend/app/models/v1_problem.py` — models for the 4 PROBLEM + 4 RUN tables.
- `backend/app/api/entity_types.py`, `entities.py`, `relationships.py`, `parameters.py`, `problems.py` — purpose-built routers.
- `backend/app/crud/db_errors.py` — `translate_db_error()`.

**Backend — modified**
- `backend/app/crud/registry.py` — `TableMeta` gains capability flags.
- `backend/app/crud/factory.py` — `int` route params; honour capability flags.
- `backend/app/api/routers.py` — register only `iam` + the three flat v1 tables.
- `backend/app/api/meta.py` — expose capabilities; label maps for v1 tables.
- `backend/app/graph/service.py`, `schemas.py` — hierarchy from `is_hierarchy`.
- `backend/app/seed.py`, `seed_graph_demo.py` — v1 demo domain.

**Backend — deleted**
- `backend/app/models/domain.py`, `backend/app/models/problem.py` (replaced).

**Frontend — created**
- `src/api/v1.ts` — typed clients for the purpose-built endpoints.
- `src/pages/EntityTypes.tsx`, `src/pages/EntityTypeDetail.tsx`, `src/pages/Entities.tsx`, `src/pages/EntityRecord.tsx`, `src/pages/Parameters.tsx`, `src/pages/ModelVersions.tsx`.
- `src/components/AttributeDefEditor.tsx`, `src/components/AttrsForm.tsx`, `src/components/ParameterGrid.tsx`, `src/components/DomainSelector.tsx`.

**Frontend — modified**
- `src/components/DataTable.tsx` — `bigint` keys, tables with no single `id`, `isIdentifierColumn`.
- `src/components/AppShell.tsx` — three nav groups.
- `src/components/GraphEditor.tsx`, `src/pages/GraphDemo.tsx`, `src/components/PropertyPanel.tsx` — v1 graph shape.

---

## Task 1: DOMAIN schema — migration, models, triggers

**Files:**
- Create: `backend/alembic/versions/0006_schema_v1_domain.py`, `backend/app/models/v1_domain.py`, `backend/tests/test_v1_domain_triggers.py`
- Delete: `backend/app/models/domain.py`
- Modify: `backend/app/models/__init__.py`

**Interfaces:**
- Produces: models `Domain`, `EntityType`, `AttributeDef`, `Entity`, `RelationshipType`, `Relationship`, `ParameterDef`, `ParameterValue` in `app.models.v1_domain`; enums `entity_role`, `attr_type`; SQL function `entity_descendants(p_entity bigint, p_rel_type bigint)`.

- [ ] **Step 1: Write failing trigger tests.** Copy the DDL from `docs/schema/2026-09-18-schema-v1.sql` for reference. Test file asserts, via raw SQL against the test DB:

```python
def test_unknown_attribute_rejected(db):
    et = make_entity_type(db, name="employee")
    with pytest.raises(ProgrammingError) as exc:
        db.execute(text("INSERT INTO entity (entity_type_id, key, attrs) VALUES (:t, 'a', '{\"nope\": 1}')"), {"t": et})
    assert exc.value.orig.pgcode == "23514"
    detail = json.loads(exc.value.orig.diag.message_detail)
    assert detail["kind"] == "unknown_attribute"
    assert detail["field"] == "nope"
```

Write one test per row of this table — each must assert `pgcode == "23514"` and the `DETAIL` payload's `kind` and `field`:

| Test | Trigger | `kind` |
|---|---|---|
| unknown attribute key | `entity_validate` | `unknown_attribute` |
| required attribute missing | `entity_validate` | `required_attribute` |
| integer given a float | `entity_validate` | `attribute_type` |
| number given a string | `entity_validate` | `attribute_type` |
| boolean given a string | `entity_validate` | `attribute_type` |
| enum value not in `enum_values` | `entity_validate` | `attribute_type` |
| default applied when absent | `entity_validate` | *(succeeds; assert `attrs` contains it)* |
| from/to entity type mismatch | `relationship_validate` | `type_mismatch` |
| `one_to_many` target already has a source | `relationship_validate` | `cardinality` |
| `many_to_one` source already has a target | `relationship_validate` | `cardinality` |
| `one_to_one` both directions | `relationship_validate` | `cardinality` |
| hierarchy self-loop | `relationship_validate` | `cycle` |
| hierarchy multi-hop cycle | `relationship_validate` | `cycle` |
| **legal re-point of an existing edge succeeds** | `relationship_validate` | *(amendment c — must PASS)* |
| parameter index wrong arity | `parameter_value_validate` | `parameter_index` |
| parameter index wrong entity types | `parameter_value_validate` | `parameter_index` |
| deleting an entity removes its parameter values | `parameter_value_cleanup` | *(assert row gone)* |
| `entity_descendants` returns node + subtree with depths | — | *(assert rows)* |

- [ ] **Step 2: Run them.** `docker compose exec -T backend pytest backend/tests/test_v1_domain_triggers.py -q` — expect collection errors or failures; the tables do not exist yet.

- [ ] **Step 3: Write the migration.** `0006_schema_v1_domain.py`, `down_revision = "0005"`. Upgrade: `op.execute("DROP SCHEMA IF EXISTS domain CASCADE")`, same for `problem`, then `op.execute(...)` the DDL for enums `entity_role` and `attr_type`, the 8 DOMAIN tables, indexes (`entity_attrs_gin`, `relationship_to_idx`, `parameter_value_entities_gin`), and the functions/triggers — taken verbatim from the DDL file **except** amendments (a) and (c).

**Amendment (a)** — every `RAISE EXCEPTION` in `entity_validate`, `relationship_validate` and `parameter_value_validate` becomes, e.g.:

```sql
RAISE EXCEPTION 'entity %: attribute "%" must be %', NEW.key, d.name, d.data_type
    USING ERRCODE = '23514',
          DETAIL  = jsonb_build_object(
              'kind', 'attribute_type', 'field', d.name,
              'record', NEW.key, 'expected', d.data_type)::text;
```

Use `kind` values exactly as tabulated in Step 1. `field` is the attribute or column at fault; for `cardinality`/`cycle`/`type_mismatch` use the relationship type's `name` as `field`.

**Amendment (c)** — in `relationship_validate`, exclude the row under validation from both terms of the recursive walk:

```sql
WITH RECURSIVE down AS (
    SELECT to_entity_id AS id FROM relationship
     WHERE relationship_type_id = rt.id AND from_entity_id = NEW.to_entity_id
       AND id IS DISTINCT FROM NEW.id
    UNION
    SELECT r.to_entity_id FROM relationship r JOIN down ON r.from_entity_id = down.id
     WHERE r.relationship_type_id = rt.id AND r.id IS DISTINCT FROM NEW.id)
SELECT 1 FROM down WHERE id = NEW.from_entity_id
```

Downgrade: drop the v1 tables, enums and functions, and recreate nothing — add a comment saying the dropped data is unrecoverable by design (spec §8).

- [ ] **Step 4: Write the models.** `v1_domain.py` mirrors the tables. Use `BigInteger` with `Identity(always=True)`, `ARRAY(Text)` for `enum_values`, `ARRAY(BigInteger)` for `index_type_ids`/`entity_ids`, `JSONB` for `attrs`/`default_value`, and `ENUM(..., name="entity_role", create_type=False)`. `ParameterValue` declares a composite primary key: `__table_args__` with `PrimaryKeyConstraint("parameter_def_id", "entity_ids")`.

- [ ] **Step 5: Run the tests.** All tests from Step 1 pass. Then `docker compose exec -T backend pytest -q` — the existing suite will fail where it imports `app.models.domain`; update those imports or mark them for Task 4, and say which in the report.

- [ ] **Step 6: Commit.** `feat(db): schema v1 domain tables, triggers and models`

---

## Task 2: PROBLEM + RUN schema — immutability, versioning, snapshot

**Files:**
- Create: `backend/alembic/versions/0007_schema_v1_problem_run.py`, `backend/app/models/v1_problem.py`, `backend/tests/test_v1_problem_run.py`
- Delete: `backend/app/models/problem.py`

**Interfaces:**
- Consumes: Task 1's DOMAIN tables and models.
- Produces: models `Template`, `Problem`, `ModelVersion`, `Scenario`, `Dataset`, `Run`, `Solution`, `ConstraintResult`; SQL function `snapshot_dataset(p_model_version bigint) RETURNS bigint`; view `run_overview`.

- [ ] **Step 1: Write failing tests** in `test_v1_problem_run.py`:

```python
def test_model_version_is_immutable(db):
    mv = insert_model_version(db, problem_id=p, ir={"sets": []})
    with pytest.raises(ProgrammingError) as exc:
        db.execute(text("UPDATE model_version SET note = 'x' WHERE id = :i"), {"i": mv})
    assert "immutable" in str(exc.value)

def test_snapshot_dedup_returns_same_id(db):
    first = db.execute(text("SELECT snapshot_dataset(:mv)"), {"mv": mv}).scalar()
    second = db.execute(text("SELECT snapshot_dataset(:mv)"), {"mv": mv}).scalar()
    assert first == second
```

Cover: immutability on all four RUN tables (`model_version`, `dataset`, `solution`, `constraint_result`); `version` auto-increments per problem starting at 1; two problems number independently; `ir_hash` and `data_hash` are stable for equal `jsonb` regardless of key order written; `snapshot_dataset` raises when the IR names a set with no `entity_type`; raises when it names a parameter with no `parameter_def`; excludes `active = false` entities; orders set members by `sort_order` then `key`; **dedups** (same id twice); returns a new id after the underlying data changes; and `run_overview` reports `violated` and `penalty` correctly for a run with mixed `constraint_result` rows.

Add one test pinning the exact snapshot shape, because no reader exists yet (spec §8):

```python
def test_snapshot_shape_is_pinned(db):
    data = db.execute(text("SELECT data FROM dataset WHERE id = :d"), {"d": ds}).scalar()
    assert set(data) == {"sets", "parameters"}
    assert data["sets"]["employee"][0]["id"] == "ahmed"          # entity.key -> "id"
    assert data["parameters"]["demand"][0] == {"day": "mon", "shift": "morning", "value": 3}
```

- [ ] **Step 2: Run them.** Expect failures — tables absent.

- [ ] **Step 3: Write the migration.** `0007_...`, `down_revision = "0006"`. Creates `run_status`, the 8 tables, `run_scenario_idx`, `run_queue_idx`, `constraint_result_violated_idx`, `set_hash()`, `forbid_update()`, `next_model_version()`, `snapshot_dataset()` and `run_overview`, verbatim from the DDL file except amendment (b):

```sql
CREATE FUNCTION next_model_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.version IS NULL THEN
        PERFORM pg_advisory_xact_lock(NEW.problem_id);
        SELECT coalesce(max(version), 0) + 1 INTO NEW.version
          FROM model_version WHERE problem_id = NEW.problem_id;
    END IF;
    RETURN NEW;
END $$;
```

Single-argument `pg_advisory_xact_lock` takes a `bigint`, so `problem_id` is used directly rather than cast down to `int`.

- [ ] **Step 4: Write the models.** Mark the four immutable tables in a module constant `IMMUTABLE_TABLES = {"model_version", "dataset", "solution", "constraint_result"}` — Task 4 consumes it. `Solution.run_id` is the primary key; `ConstraintResult` uses a composite `PrimaryKeyConstraint("run_id", "constraint_id")`.

- [ ] **Step 5: Run the tests.** All pass. Full backend suite runs.

- [ ] **Step 6: Commit.** `feat(db): schema v1 problem and run tables, snapshot and immutability`

---

## Task 3: Structured database errors → 422

**Files:**
- Create: `backend/app/crud/db_errors.py`, `backend/tests/test_db_errors.py`
- Modify: `backend/app/crud/factory.py` (exception handling)

**Interfaces:**
- Produces: `translate_db_error(exc: DBAPIError, table: str) -> HTTPException`. Returns **422** with body `{"detail": {"message": str, "field": str | None, "kind": str}}` for `23514` carrying a JSON `DETAIL`; **409** with the existing `conflict_detail()` string for `23503`/`23505`/`23502`; re-raises otherwise.

- [ ] **Step 1: Write the failing test.**

```python
def test_check_violation_with_detail_becomes_422_naming_the_field():
    exc = fake_dbapi_error(pgcode="23514", message_detail=json.dumps(
        {"kind": "attribute_type", "field": "hours", "record": "ahmed", "expected": "integer"}))
    http = translate_db_error(exc, table="entity")
    assert http.status_code == 422
    assert http.detail["field"] == "hours"
    assert http.detail["kind"] == "attribute_type"

def test_unique_violation_still_becomes_409():
    exc = fake_dbapi_error(pgcode="23505", constraint_name="entity_entity_type_id_key_key")
    assert translate_db_error(exc, table="entity").status_code == 409

def test_check_violation_without_json_detail_falls_back_to_409():
    exc = fake_dbapi_error(pgcode="23514", message_detail="not json")
    assert translate_db_error(exc, table="entity").status_code == 409
```

- [ ] **Step 2: Run it.** Expect `ImportError`.

- [ ] **Step 3: Implement.** Read `exc.orig.pgcode` and `exc.orig.diag.message_detail`; `json.loads` inside a `try` so a non-JSON detail degrades to the 409 path rather than raising. Reuse `conflict_detail()` from `app/crud/errors.py` unchanged for the 409 cases.

- [ ] **Step 4: Run tests.** Pass.

- [ ] **Step 5: Commit.** `feat(api): translate structured trigger errors into 422 field errors`

---

## Task 4: Registry capabilities, bigint routes, rewired generic CRUD

**Files:**
- Modify: `backend/app/crud/registry.py`, `backend/app/crud/factory.py`, `backend/app/api/routers.py`, `backend/app/api/meta.py`
- Test: `backend/tests/test_capabilities.py`, existing `backend/tests/test_options_meta.py`

**Interfaces:**
- Consumes: `IMMUTABLE_TABLES` (Task 2), `translate_db_error` (Task 3).
- Produces: `TableMeta(..., creatable: bool = True, updatable: bool = True, deletable: bool = True)`; `/api/meta/schema` entries gain `"creatable"`, `"updatable"`, `"deletable"`.

- [ ] **Step 1: Write failing tests.** The generic router set is exactly `iam.organization`, `iam.user_account`, `iam.role`, `iam.user_role`, `domain`, `template`, `problem` — assert the full set, so a stray registration fails. `GET /api/meta/schema` reports all three capability flags for every registered table, defaulting to `true`. A router built with `updatable=False, deletable=False` exposes GET and POST but **no** PUT, PATCH or DELETE — assert against the router's own route table, since no registered table is read-only today:

```python
def test_capability_flags_suppress_write_routes():
    r = build_crud_router(model=Domain, create_schema=C, update_schema=U, read_schema=R,
                          schema_name="public", table_name="domain",
                          updatable=False, deletable=False)
    methods = {m for route in r.routes for m in route.methods}
    assert methods == {"GET", "POST"}
```

And `GET /api/domain/1` accepts an integer id where `GET /api/domain/not-an-int` returns 422.

Note: the four immutable tables are **not** in the generic registry — `model_version` is served by Task 9's purpose-built router and the other three have no router at all. `IMMUTABLE_TABLES` from Task 2 is therefore used here only to assert that none of its members appears in `TABLE_REGISTRY`.

- [ ] **Step 2: Run them.** Expect failures.

- [ ] **Step 3: Implement.** Add the three flags to `TableMeta` and `register_table`. In `factory.py` change every `item_id: UUID` to `item_id: int` and drop the `uuid` import; skip generating POST/PUT/PATCH/DELETE routes when the corresponding flag is false; replace `IntegrityError` handling with `translate_db_error`. In `routers.py` delete the 27 old `domain.*`/`problem.*` registrations and register only the three flat v1 tables. In `meta.py` emit the flags and add `FIELD_LABELS`/`TABLE_LABELS` entries for the v1 tables.

- [ ] **Step 4: Run the full backend suite.** Tests referencing removed tables must be deleted or rewritten against v1 — list every one you touched in the report.

- [ ] **Step 5: Commit.** `feat(api): per-table capabilities and bigint keys in the generic CRUD layer`

---

## Task 5: Entity types and attribute definitions API

**Files:**
- Create: `backend/app/api/entity_types.py`, `backend/tests/test_api_entity_types.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces: `GET/POST /api/v1/entity-types`, `GET/PATCH/DELETE /api/v1/entity-types/{id}`, `GET/POST /api/v1/entity-types/{id}/attributes`, `PATCH/DELETE /api/v1/attributes/{id}`. Read model includes `attributes: list[AttributeDefRead]`.

- [ ] **Step 1: Write failing tests.** Creating a type with `name="Employee"` returns 422 (the `^[a-z][a-z0-9_]*$` check); `name="employee"` succeeds with `role` defaulting to `"other"`; the detail response embeds its attribute defs; creating an `enum` attribute without `enum_values` returns 422; a non-enum attribute *with* `enum_values` returns 422; an attribute named `id` returns 422; duplicate attribute names within a type return 409.

- [ ] **Step 2: Run them.** Expect 404s — routes absent.

- [ ] **Step 3: Implement** with Pydantic v2 schemas hand-written in the router module (not `make_crud_schemas`), all writes wrapped in `translate_db_error`.

- [ ] **Step 4: Run tests.** Pass. **Step 5: Commit.** `feat(api): entity types and attribute definitions`

---

## Task 6: Entities API

**Files:** Create `backend/app/api/entities.py`, `backend/tests/test_api_entities.py`

**Interfaces:**
- Produces: `GET /api/v1/entities?entity_type_id=&q=&limit=&offset=`, `POST /api/v1/entities`, `GET/PATCH/DELETE /api/v1/entities/{id}`. `attrs` is a free-form object validated by the database.

- [ ] **Step 1: Write failing tests.** Every trigger failure from Task 1 must surface as **422 with the field named** — one test per `kind`. Creating with a missing required attribute returns 422 and `detail["field"]` is that attribute's name. Creating without an optional attribute that has a default returns 201 and the response `attrs` **contains the materialised default**. Deleting an entity used in `parameter_value` succeeds and removes those values. List filters by `entity_type_id` and searches `key`/`label` with `q`.

- [ ] **Step 2: Run them.** Expect 404s. **Step 3: Implement.** **Step 4: Run tests.** **Step 5: Commit.** `feat(api): entities with database-validated typed attributes`

---

## Task 7: Relationship types, relationships, and the graph read

**Files:** Create `backend/app/api/relationships.py`, `backend/tests/test_api_relationships.py`; modify `backend/app/graph/service.py`, `backend/app/graph/schemas.py`, `backend/app/api/graph.py`

**Interfaces:**
- Produces: CRUD for both resources, plus `GET /api/v1/graph?domain_id=&hierarchy_type_id=` returning the existing normalized graph contract — `{nodes, edges, entity_types}` — where compound parents come from the `is_hierarchy` relationship type.

- [ ] **Step 1: Write failing tests.** Creating a `relationship_type` with `is_hierarchy=true` and differing from/to types returns 422 (the table CHECK); with `cardinality != 'one_to_many'` returns 422. Each cardinality violation and both cycle cases return 422 naming the relationship type. **Re-pointing an existing hierarchy edge to a legal new parent returns 200** — this is amendment (c) at the API level. The graph endpoint returns each entity's parent id from the hierarchy type and nothing from non-hierarchy types.

- [ ] **Step 2: Run them.** **Step 3: Implement.** Replace `hierarchy`/`hierarchy_node` traversal in `graph/service.py` with a query over `relationship` filtered to the hierarchy type; use `entity_descendants()` for subtree queries. Keep the wire contract in `graph/schemas.py` unchanged so the frontend `types/graph.ts` still matches. **Step 4: Run tests.** **Step 5: Commit.** `feat(api): relationships, hierarchy-as-relationship, and the v1 graph read`

---

## Task 8: Parameters API

**Files:** Create `backend/app/api/parameters.py`, `backend/tests/test_api_parameters.py`

**Interfaces:**
- Produces: CRUD for `parameter_def`; `GET /api/v1/parameters/{id}/values` returning `{index_types: [{id, name}], cells: [{entity_ids: [int], value: int}], default_value: int}`; `PUT /api/v1/parameters/{id}/values` taking `{cells: [{entity_ids, value}]}` and upserting, where a cell whose value equals `default_value` is **deleted** rather than stored.

- [ ] **Step 1: Write failing tests.** Creating a def with an empty `index_type_ids` returns 422. Upserting a cell with the wrong arity returns 422 `kind="parameter_index"`; with the right arity but wrong entity types, likewise. Upserting a value equal to the default removes the row. Re-reading returns cells in a stable order. A non-integer value returns 422 before it reaches the database.

- [ ] **Step 2: Run them.** **Step 3: Implement.** **Step 4: Run tests.** **Step 5: Commit.** `feat(api): parameter definitions and sparse value grid`

---

## Task 9: Problems, model versions and scenarios API

**Files:** Create `backend/app/api/problems.py`, `backend/tests/test_api_problems.py`

**Interfaces:**
- Produces: `GET /api/v1/problems/{id}/versions`, `GET /api/v1/versions/{id}`, `POST /api/v1/problems/{id}/versions` taking `{ir, note}` and returning the created version with its server-assigned `version` and `ir_hash`; CRUD for `scenario`. No PUT or PATCH on `model_version`.

- [ ] **Step 1: Write failing tests.** Posting two versions yields `version` 1 then 2. `PATCH /api/v1/versions/{id}` returns 405. Posting identical IR twice yields two versions with the **same** `ir_hash` (hashing is content-based, not a dedup). A scenario referencing a version of a different problem returns 422.

- [ ] **Step 2: Run them.** **Step 3: Implement.** **Step 4: Run tests.** **Step 5: Commit.** `feat(api): problems, immutable model versions and scenarios`

---

## Task 10: Frontend foundations for v1

**Files:**
- Create: `frontend/src/api/v1.ts`, `frontend/src/components/DomainSelector.tsx`, `frontend/src/hooks/useDomain.ts`
- Modify: `frontend/src/components/DataTable.tsx`, `frontend/src/components/AppShell.tsx`, `frontend/src/App.tsx`

**Interfaces:**
- Produces: typed clients and React Query hooks for every Task 5–9 endpoint; `useDomain()` returning `{domainId, setDomainId}` persisted in `localStorage`; nav grouped as Domain / Problem / Runs.

- [ ] **Step 1: Write failing tests.** `DataTable` renders a row link for a numeric `id`; renders **plain text, not a link,** for a row with no `id` (guards `…/undefined`); `isIdentifierColumn` hides an `integer` surrogate key named `id` as well as a `uuid` one. `DomainSelector` restores the stored domain on mount and falls back to the first domain when the stored one is gone.

- [ ] **Step 2: Run them.** `cd frontend && npm test -- --run` — expect failures.

- [ ] **Step 3: Implement.** In `DataTable.tsx` the row link already guards a missing id (`hasUsableId`); extend `isIdentifierColumn` from `field.type === "uuid"` to also match an `integer` field named `id` that is not an FK. Nav: three groups from a static map, not from `/api/meta/schema` schema names.

- [ ] **Step 4: Run tests and build.** Both clean.

- [ ] **Step 5: Verify in the browser.** `bash scripts/rebuild.sh`, then confirm the three nav groups render, the domain selector persists across a reload, and axe reports **0 violations** on the dashboard and a list page.

- [ ] **Step 6: Commit.** `feat(ui): v1 API clients, domain scope and identifier handling`

---

## Task 11: Entity type and attribute definition UI

**Files:** Create `frontend/src/pages/EntityTypes.tsx`, `frontend/src/pages/EntityTypeDetail.tsx`, `frontend/src/components/AttributeDefEditor.tsx` (+ tests)

- [ ] **Step 1: Write failing tests.** The list shows types for the selected domain with their `role`. The detail page edits the type and its attributes together. Adding an `enum` attribute reveals an `enum_values` editor and hides it for other types. A 422 from the API marks the offending field using the existing `EntityForm` error conventions. Editing a default shows the note that **existing rows keep their materialised default** (spec §3).

- [ ] **Step 2: Run them.** **Step 3: Implement**, reusing `EntityForm`'s label/error conventions and `ToastProvider` for success. **Step 4: Run tests and build.** **Step 5: Verify in the browser** after `rebuild.sh`: create a type with three attribute types, reload, confirm persistence, axe 0. **Step 6: Commit.** `feat(ui): entity types with their attribute definitions`

---

## Task 12: Entity form driven by attribute_def

**Files:** Create `frontend/src/components/AttrsForm.tsx`, `frontend/src/pages/Entities.tsx`, `frontend/src/pages/EntityRecord.tsx` (+ tests)

**Interfaces:** Consumes `attributeInputs.tsx`'s typed controls, which map to `attr_type` as: `integer`/`number` → number input, `boolean` → checkbox, `text` → text input, `enum` → select from `enum_values`, `date` → date input, `time` → time input.

- [ ] **Step 1: Write failing tests.** The form renders one control per `attribute_def`, in definition order, labelled by `name` with `unit` shown when present. Required attributes are marked and block submit. A number field rejects a non-numeric string client-side. A server 422 naming `field` marks that control and announces via the live region. Values round-trip through save and reload.

- [ ] **Step 2: Run them.** **Step 3: Implement.** **Step 4: Run tests and build.** **Step 5: Verify in the browser:** create an entity exercising every `attr_type`, read it back **through the API** (not the screen), and confirm axe 0 on list and form. **Step 6: Commit.** `feat(ui): entity records with attribute-driven forms`

---

## Task 13: Parameter grid UI

**Files:** Create `frontend/src/components/ParameterGrid.tsx`, `frontend/src/pages/Parameters.tsx` (+ tests)

- [ ] **Step 1: Write failing tests.** A two-index parameter renders a matrix with the first index down the rows and the second across the columns, headed by entity labels. An empty cell shows the default, visually distinguished from a stored value. Editing a cell to the default clears it. Integer-only is stated in the UI and a decimal entry is refused client-side with a message. A three-or-more-index parameter falls back to a flat list of index/value rows rather than rendering nothing.

- [ ] **Step 2: Run them.** **Step 3: Implement.** **Step 4: Run tests and build.** **Step 5: Verify in the browser:** edit cells, reload, confirm persistence via the API; check the grid scrolls within its own container and does not overflow the page at 375px; axe 0. **Step 6: Commit.** `feat(ui): sparse parameter grid`

---

## Task 14: Graph adaptation

**Files:** Modify `frontend/src/components/GraphEditor.tsx`, `frontend/src/pages/GraphDemo.tsx`, `frontend/src/components/PropertyPanel.tsx`, `frontend/src/components/FilterBar.tsx` (+ tests)

- [ ] **Step 1: Write failing tests.** The hierarchy selector lists `relationship_type` rows with `is_hierarchy = true` (replacing the old hierarchy list). Selecting one nests nodes as compound parents. The property panel edits an entity's `attrs` through the same `AttrsForm` as Task 12. Creating an edge picks a `relationship_type` and a 422 from a cardinality or cycle violation surfaces as a readable message, not a generic failure.

- [ ] **Step 2: Run them.** **Step 3: Implement.** Keep the existing keyboard navigation, `role="application"`, live region and `cy.resize()` handling intact. **Step 4: Run tests and build.** **Step 5: Verify in the browser:** load the seeded graph, drag a node, create a legal edge, attempt a cycle and read the message, scroll and click a node to confirm hit-testing (`cy.resize()`), axe 0 across all graph states. **Step 6: Commit.** `feat(ui): graph over v1 relationships and hierarchy types`

---

## Task 15: Seed and full verification

**Files:** Modify `backend/app/seed.py`, `backend/app/seed_graph_demo.py`; create `backend/tests/test_seed_v1.py`; report at `.superpowers/sdd/2026-09-19-schema-v1-migration/task-15-report.md`

- [ ] **Step 1: Write the seed.** One `domain` ("Workforce"), entity types `employee` (role `agent`), `unit` (role `org`), `day` and `shift` (role `time`), with `attribute_def` rows covering **every** `attr_type`; entities with `sort_order` set so days and shifts order correctly; a `reports_to` hierarchy relationship type over `unit` with a real tree; a `works_in` relationship type; a two-index `demand[day, shift]` parameter with values; one `problem`, one `model_version` whose IR names those sets and that parameter, and one `scenario`.

- [ ] **Step 2: Test the seed.** `snapshot_dataset()` on the seeded model version returns a dataset whose `sets` and `parameters` are non-empty and match the pinned shape from Task 2.

- [ ] **Step 3: Full suite.** `bash scripts/rebuild.sh`; `docker compose exec -T backend pytest -q`; `cd frontend && npm test -- --run && npm run build`; seed; `python scripts/graph_smoke_check.py`.

- [ ] **Step 4: Browser verification.** Walk the whole product as a new user: pick a domain, create an entity type with attributes, create entities, define a relationship type, connect two entities in the graph, define a parameter and fill cells, create a problem and a model version. Report what broke. Re-run axe across every page state; the target is **0 violations**, matching the pre-migration baseline.

- [ ] **Step 5: Report honestly.** Anything still failing is listed with the reason. Commit only if a fix was required.

- [ ] **Step 6: Commit.** `feat(seed): v1 workforce demo domain` (plus any `fix:` commits from Step 4)

---

## Plan-level verification

Spec coverage: §1 scope → T1, T2 (RUN created not wired); §2 decisions → T1–T4 (iam untouched by T4's rewire), T10 (nav grouping), T13 (integer-only surfaced); §3 amendment (a) → T1 + T3; (b) → T2; (c) → T1 Step 3 and T7 Step 1; documented default materialisation → T11; §4 backend → T3–T9; §5 frontend → T10–T14, with the two carried-forward `DataTable` corrections in T10; graph → T7 + T14; §6 seed → T15; §7 testing → every task's test steps, with direct trigger tests in T1/T2 and browser+axe verification in T10–T15; §8 risks → snapshot shape pinned in T2 Step 1, irreversible downgrade documented in T1 Step 3.

**Out of scope, by decision:** the solver and compiler; the run queue, worker and results UI; any API or UI for `dataset`, `run`, `solution`, `constraint_result`; migrating existing domain data; adding tenancy to v1 tables.
