# End-User Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every problem found by the 2026-09-17 end-user test session so a planner can model a domain, draw its graph, and define a problem without hitting silent failures, unpickable records, or crashes.

**Architecture:** Backend changes stay inside the generic CRUD factory, a new options endpoint, meta hints, and the graph service. Frontend changes add a small error-formatting helper, a searchable foreign-key picker, URL-backed list state, a related-records section on detail pages, and a graph editor that updates its canvas incrementally, can actually draw edges, and lays out hierarchies without crashing. Tests get their own database.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Pydantic v2 (backend), React 18 + TypeScript + React Query + Cytoscape.js/ELK/edgehandles (frontend), pytest, Vitest + React Testing Library, Docker Compose.

**Spec:** docs/superpowers/specs/2026-09-17-end-user-fixes-design.md

## Global Constraints

- Backend tests: unique test values get a `uuid.uuid4().hex[:8]` suffix. New tests go in the existing per-area test files or a new file named after the feature.
- Frontend tests: mock the API with `vi.mock("../api/client", async () => {...})` keeping `getToken`/`setToken` real; mock `cytoscape`, `cytoscape-elk`, `cytoscape-edgehandles` entirely with the existing `vi.hoisted()` pattern in `GraphEditor.test.tsx`; never render a real canvas in jsdom.
- Every API error the user can see goes through `formatApiError` (Task 3) — no raw JSON bodies in the UI.
- Do not change the shape of `GraphResponse` (`backend/app/graph/schemas.py` ↔ `frontend/src/types/graph.ts`); both files carry a "keep in sync by hand" note.
- The backend image has no bind mount: after backend changes, `docker compose build backend && docker compose up -d --force-recreate backend` before running `docker compose exec -T backend pytest`. Same for the frontend image before any browser check.
- Existing tests must keep passing (backend 72, frontend 40 at the start of this plan).
- No new npm or pip dependencies except where a task says so (none are planned).

---

### Task 1: Generic CRUD — conflict handling, search, filters, ordering

**Files:**
- Modify: `backend/app/crud/factory.py`
- Create: `backend/app/crud/errors.py`
- Test: `backend/tests/test_crud_hardening.py`

**Interfaces:**
- Produces: `conflict_detail(exc: IntegrityError, table: str) -> str` in `errors.py`; list endpoint query params `q`, `f_<column>`, `order_by`, `order`; `searchable_columns(model) -> list[Column]` in `factory.py` (reused by Task 2).

- [ ] **Step 1: Write failing tests** in `backend/tests/test_crud_hardening.py` using `TestClient(app)` and a bearer token the way `backend/tests/test_crud_domain_a.py` does (copy its `auth_headers` helper). Cover:
  - `test_delete_referenced_row_returns_409`: create an `entity_type` and an `entity` using it; `DELETE /api/domain/entity_type/{id}` → 409 and `detail` contains `"still referenced"`.
  - `test_duplicate_code_returns_409`: create `entity_type` with code `dup-<sfx>` twice with the same `organization_id` (use the default org id via `GET /api/iam/organization/`) → second returns 409 and `detail` contains `"already exists"`.
  - `test_bad_fk_on_create_returns_409`: `POST /api/domain/entity/` with a random `entity_type_id` → 409, `detail` contains `"does not exist"`.
  - `test_list_search_q`: create two `role_type` rows `alpha-<sfx>`/`beta-<sfx>`; `GET /api/domain/role_type/?q=alpha-<sfx>` returns exactly one item.
  - `test_list_filter_by_column`: two `entity` rows of different types; `?f_entity_type_id=<id>` returns only the matching one; `?f_nope=1` → 422.
  - `test_list_order_by`: `?order_by=code&order=desc` returns codes sorted descending for the filtered set; `?order_by=nope` → 422.
- [ ] **Step 2: Run** `docker compose exec -T backend pytest tests/test_crud_hardening.py -v` (after rebuilding the image) → all fail (500s / missing params).
- [ ] **Step 3: Implement** `backend/app/crud/errors.py`:

```python
from sqlalchemy.exc import IntegrityError

def conflict_detail(exc: IntegrityError, table: str) -> str:
    diag = getattr(exc.orig, "diag", None)
    code = getattr(exc.orig, "pgcode", "") or ""
    constraint = (getattr(diag, "constraint_name", None) or "") if diag else ""
    if code == "23503":  # foreign_key_violation
        # deleting a parent vs inserting a child with a bad reference
        if diag is not None and diag.table_name and diag.table_name != table:
            return f"{table} row is still referenced by {diag.table_name} records"
        column = (getattr(diag, "message_detail", "") or "").split("(")[1].split(")")[0] if diag and "(" in (getattr(diag, "message_detail", "") or "") else "a referenced row"
        return f"referenced {column} does not exist"
    if code == "23505":  # unique_violation
        cols = constraint.replace(f"{table}_", "").replace("_key", "").replace("uq_", "")
        return f"a {table} row with the same {cols or 'unique value'} already exists"
    if code == "23502":  # not_null_violation
        return f"{getattr(diag, 'column_name', 'a required field')} is required"
    return "the change conflicts with existing data"
```

  In `factory.py`: wrap `db.commit()` in create/update/delete with `try/except IntegrityError as exc: db.rollback(); raise HTTPException(409, conflict_detail(exc, table_name))`. Add `searchable_columns(model)` returning columns whose type is `String`/`Text` (use `isinstance(col.type, (String, Text))`). Extend `list_items` with `q: str | None`, `order_by: str | None`, `order: str = "asc"`, and dynamic `f_<column>` filters read from `request.query_params` (inject `request: Request`). Validate `order_by`/filter columns against `mapper.column_attrs` keys → 422 via `HTTPException(422, detail=f"unknown column {name}")`. Cast filter values with the column's Python type (`uuid.UUID`, `int`, `bool` from `"true"/"false"`, else str). Apply `total = query.count()` after filters.
- [ ] **Step 4: Run** the new tests and the full backend suite → all pass.
- [ ] **Step 5: Commit** `feat(crud): 409 on integrity errors, search/filter/order on list endpoints`.

---

### Task 2: Options endpoint, labels, meta hints

**Files:**
- Create: `backend/app/crud/labels.py`, `backend/app/api/options.py`
- Modify: `backend/app/api/meta.py`, `backend/app/main.py` (include the options router)
- Test: `backend/tests/test_options_meta.py`

**Interfaces:**
- Produces: `GET /api/{schema}/{table}/options?q=&ids=&limit=` → `list[{"id": str, "label": str}]`; `label_for(row, model) -> str`; meta fields gain optional `default` and `choices`.
- Consumes: `searchable_columns` from Task 1; `TABLE_REGISTRY`.

- [ ] **Step 1: Tests** (`test_options_meta.py`): `test_options_search_returns_code_and_name_label` (create `entity_type` code `opt-<sfx>` name `Opt Name`; `?q=opt-<sfx>` → one item whose label is `"opt-<sfx> — Opt Name"`); `test_options_ids_resolves_exact_rows` (two ids → two items in any order); `test_hierarchy_node_label_uses_entity_and_hierarchy_names` (create hierarchy + entity + node; label `"<entity name> in <hierarchy name>"`); `test_user_account_label_is_username`; `test_meta_reports_defaults_and_choices` (`problem.problem` field `status` has `default == "DRAFT"` and `choices` containing `"ACTIVE"`; `attribute_definition.data_type` choices contain `"boolean"`; a field with neither has both keys absent or null).
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** `labels.py` with `DEFAULT_LABEL_COLUMNS = ("code", "name", "username", "state_value")` and `LABEL_OVERRIDES: dict[str, Callable[[Session, row], str]]` keyed by `"schema.table"` for `domain.hierarchy_node`, `domain.entity_attribute`, `problem.variable_dimension`, `iam.user_role`, `problem.objective_component` exactly as spec §2 (fetch the related rows with `db.get`). `options.py`: one router built in a loop over `TABLE_REGISTRY` (register it in `main.py` **before** `crud_router` — FastAPI matches routes in registration order, so if `/{item_id}` came first it would swallow `/options` and answer 422 "invalid uuid"; verify with a test hitting `/options` and getting 200). `q` uses Task 1's `searchable_columns`; `ids` splits on commas and validates UUIDs (bad id → 422); `limit` default 50, max 200. `meta.py`: `CHOICES: dict[tuple[str, str], list[str]]` keyed by `(table, field)` plus a `(None, field)` fallback for `status`, `severity`, `objective_type`, `variable_type`, `dimension_type`, `cardinality`, `problem_type`, `data_type`; `default` from `column.default.arg` when it is a scalar (`str|int|bool|float`).
- [ ] **Step 4: Run** new + full suite → pass.
- [ ] **Step 5: Commit** `feat(api): options endpoint with human labels, meta defaults and choices`.

---

### Task 3: Frontend error formatting, list search/filter/paging, safe delete, FK labels

**Files:**
- Create: `frontend/src/api/errors.ts`, `frontend/src/api/options.ts`
- Modify: `frontend/src/api/entities.ts` (list params), `frontend/src/pages/EntityList.tsx`, `frontend/src/components/DataTable.tsx`, `frontend/src/pages/EntityDetail.tsx`, `frontend/src/pages/Login.tsx`, `frontend/src/types/meta.ts` (add `default?`, `choices?`)
- Test: `frontend/src/api/errors.test.ts`, `frontend/src/pages/EntityList.test.tsx`, `frontend/src/components/DataTable.test.tsx`

**Interfaces:**
- Produces: `formatApiError(err: unknown): string`; `useOptions(fkTable: string, q: string)`, `useOptionLabels(fkTable: string, ids: string[])` in `options.ts`; `useEntityList(schema, table, {limit, offset, q, filters, orderBy, order})`.
- Consumes: Task 1 query params, Task 2 options endpoint.

- [ ] **Step 1: Tests.** `errors.test.ts`: an `ApiError(422, '{"detail":[{"loc":["body","code"],"msg":"Field required"}]}')` → `"code: Field required"`; `ApiError(409, '{"detail":"x already exists"}')` → `"x already exists"`; `ApiError(500, "Internal Server Error")` → `"Server error (500). Please try again."`; a plain `Error("boom")` → `"boom"`. `EntityList.test.tsx`: typing in the search box updates the URL (`?q=alpha`) and the request URL contains `q=alpha`; clicking Next puts `offset=20` in the URL; a `?f_entity_type_id=abc` in the URL renders a chip "entity_type_id = abc" and the request contains `f_entity_type_id=abc`. `DataTable.test.tsx`: Delete calls `window.confirm` (mock it) and skips `onDelete` when cancelled; an FK column with mocked `/options?ids=` renders the label text, not the UUID.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.** `formatApiError` parses `ApiError.message` as JSON when possible. `EntityList` uses `useSearchParams` for `q`, `offset`, `order_by`, `order`, `f_*`; renders a search input (`data-testid="list-search"`, debounced 300 ms), filter chips with an × that removes the param, clickable column headers toggling sort; wraps the table in `<div className="overflow-x-auto">`; shows `formatApiError` of a failed delete above the table (`useDeleteEntity(...).mutate(id, { onError })`). `DataTable` takes `fields` and, for `is_fk` columns, collects the page's ids and calls `useOptionLabels` once per FK table (React Query key `["options", fkTable, ids.sort().join(",")]`), rendering `label` with `title={id}`; `window.confirm("Delete this row? This cannot be undone.")` before `onDelete`. `EntityDetail` and `Login` switch to `formatApiError`. Unknown table (meta loaded, no match) → `<p>Unknown table {schema}.{table}</p>`.
- [ ] **Step 4: Run** `npm test` → pass; `npm run build` clean.
- [ ] **Step 5: Commit** `feat(admin): searchable lists with URL state, confirmed deletes, readable errors and FK labels`.

---

### Task 4: EntityForm — searchable FK picker, JSON validation, date formatting, hints, 404

**Files:**
- Create: `frontend/src/components/FkPicker.tsx`
- Modify: `frontend/src/components/EntityForm.tsx`, `frontend/src/pages/EntityDetail.tsx`
- Test: `frontend/src/components/FkPicker.test.tsx`, `frontend/src/components/EntityForm.test.tsx` (extend), `frontend/src/pages/EntityDetail.test.tsx` (extend)

**Interfaces:**
- Produces: `<FkPicker fkTable value onChange required? />` storing the id, displaying the label.
- Consumes: `useOptions`/`useOptionLabels` (Task 3), meta `default`/`choices` (Task 2).

- [ ] **Step 1: Tests.** FkPicker: typing `nur` calls `/options?q=nur`, the list shows labels, choosing one calls `onChange(id)` and the input shows the label; with an initial `value` the label is resolved via `ids=`; the clear button calls `onChange("")`. EntityForm: a `json` field containing `{"a":` blocks submit and shows `"expression: invalid JSON"`; a `datetime` initial value `"2026-10-01T08:00:00Z"` renders as a `datetime-local` value in `YYYY-MM-DDTHH:mm` form (compute the expected string with `new Date(...)` in the test so it is timezone-safe); a field with `choices` renders a `<datalist>` with those options; a field with `default: "DRAFT"` has `placeholder="default: DRAFT"`; `initialValues` from the query string (`/domain/entity/new?entity_type_id=abc`) prefill the FK. EntityDetail: a 404 on load renders "Record not found" and a link to the list.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.** FkPicker: controlled text input + dropdown list (`role="listbox"`, arrow keys + Enter, Escape closes), debounced 250 ms, shows "No matches" / "Type to search"; when `value` is set and the label is unknown, fetch `ids=`. EntityForm replaces `FkSelect` with `FkPicker`; JSON validation on submit; `toInputValue(field, value)` for date/datetime; `<input list=...>` + `<datalist>` when `field.choices`; placeholder when `field.default !== undefined`; read `useSearchParams` in EntityDetail and pass as `initialValues` for new records. EntityDetail: `useEntity` error with status 404 → not-found view.
- [ ] **Step 4: Run** `npm test && npm run build` → pass.
- [ ] **Step 5: Commit** `feat(forms): searchable FK picker, JSON validation, date formatting, choice hints, 404 view`.

---

### Task 5: Related records on detail pages

**Files:**
- Create: `frontend/src/components/RelatedRecords.tsx`
- Modify: `frontend/src/pages/EntityDetail.tsx`
- Test: `frontend/src/components/RelatedRecords.test.tsx`

**Interfaces:**
- Consumes: meta (`fk_table` of every table), list endpoint `f_<fk>=<id>&limit=1` for counts (Task 1), `/new?<fk>=<id>` prefill (Task 4).

- [ ] **Step 1: Tests.** Given mocked meta where `problem.variable_definition.problem_id` → `problem.problem` and `problem.constraint_definition.problem_id` → `problem.problem`, rendering `<RelatedRecords schema="problem" table="problem" id="p1" />` shows two rows "variable_definition (3)" / "constraint_definition (0)" (counts from mocked list responses `total`), each linking to `/problem/variable_definition?f_problem_id=p1` and a "New" link to `/problem/variable_definition/new?problem_id=p1`. A table with no children renders nothing.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** with `useQueries` for the counts; render under the edit form as "Related records". Self-references (a table pointing at itself, e.g. `parent_type_id`) are included and labelled by the field name (`entity_type via parent_type_id`).
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat(admin): related records section on detail pages`.

---

### Task 6: Session expiry messaging and return-to-page

**Files:**
- Modify: `frontend/src/api/client.ts`, `frontend/src/pages/Login.tsx`, `frontend/src/App.tsx`
- Test: `frontend/src/api/client.test.ts` (extend), `frontend/src/pages/Login.test.tsx` (extend)

- [ ] **Step 1: Tests.** `apiFetch` on 401 sets `window.location.href` to `/login?reason=expired&next=<encoded current path+search>` (stub `window.location` as the existing client tests do). Login with `?reason=expired` shows "Your session expired — please sign in again"; after a successful login with `?next=/domain/entity` it navigates there; without `next` it navigates to `/`. `RequireAuth` redirects to `/login?next=<path>`.
- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat(auth): explain session expiry and return to the previous page`.

---

### Task 7: Graph backend — typed attributes, clearing, org-scoped edges, richer seed

**Files:**
- Modify: `backend/app/graph/service.py`, `backend/app/api/graph.py`, `backend/app/seed_graph_demo.py`
- Test: `backend/tests/test_graph_nodes.py` (extend), `backend/tests/test_graph_read.py` (extend), `backend/tests/test_seed_graph_demo.py` (extend)

**Interfaces:**
- Produces: `UNSET` sentinel in `service.py`; `update_node(..., status: str | None | Unset = UNSET, description: ... = UNSET, attributes: dict | None = None)`; attribute value coercion `coerce_attribute_value(data_type, value)` raising `GraphValidationError`.
- Consumes: nothing new.

- [ ] **Step 1: Tests.** `test_update_node_rejects_text_in_number_attribute` (422, detail mentions the attribute code); `test_update_node_accepts_numeric_string_for_number` ("36" → stored 36); `test_update_node_boolean_accepts_true_string`; `test_update_node_unknown_attribute_code_returns_422`; `test_update_node_explicit_null_clears_description` (PATCH `{"description": null}` → GET graph shows `attributes.description is None`; PATCH `{}` leaves it untouched); `test_update_node_null_attribute_removes_value`; `test_graph_edges_exclude_cross_org_targets` (relationship from an entity in org A to an entity in org B is absent from org A's graph); seed test asserts `attribute_definitions` for `employee-demo` contain `rank` and `is_manager` and Ahmed has `rank` set.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.** `coerce_attribute_value`: number → `float(value)` (accept int/float/str; `ValueError` → `GraphValidationError(f"attribute {code} expects a number")`), boolean → bool or one of `true/false/1/0/yes/no` (case-insensitive), date → `date.fromisoformat`, datetime → `datetime.fromisoformat` (accept trailing `Z`), string → `str`, json → as is. Unknown code → `GraphValidationError(f"unknown attribute {code} for this entity type")`. `None` value → delete the row if it exists. `UpdateNodeRequest`: keep fields `Optional`; in the route pass only fields in `payload.model_fields_set`, using `UNSET` for the rest. `get_domain_graph`: build the set of entity ids in the org once and keep edges whose source and target are both in it. Seed: two attribute definitions + values (Ahmed rank 3 is_manager true, Sara rank 2, Mostafa rank 1), idempotent like the rest. Route already maps `GraphValidationError` → 422 for update; confirm for create.
- [ ] **Step 4: Run** full backend suite → pass.
- [ ] **Step 5: Commit** `feat(graph): typed attribute validation, explicit clearing, org-scoped edges, EAV in demo seed`.

---

### Task 8: GraphEditor canvas — draw mode, safe ELK, incremental updates, feedback

**Files:**
- Modify: `frontend/src/components/GraphEditor.tsx`, `frontend/src/components/GraphEditor.test.tsx`

**Interfaces:**
- Produces: toolbar button `data-testid="toggle-connect"`; banner `data-testid="graph-error"`; status `data-testid="layout-status"`; helper `applyGraphToCy(cy, graph)` (exported for tests) returning `{ structureChanged: boolean }`.
- Consumes: `formatApiError` (Task 3).

- [ ] **Step 1: Tests** (extend the mocked-cytoscape file; add `add`, `remove`, `getElementById`, `autoungrabify`, `layout().promiseOn`, `on` to the hoisted instance; the `edgehandles()` mock returns `{ enableDrawMode, disableDrawMode, destroy }` spies). Cases: the ELK options passed to `cy.layout` include `"elk.hierarchyHandling": "INCLUDE_CHILDREN"`; clicking `toggle-connect` calls `enableDrawMode` and `autoungrabify(true)`, clicking again calls `disableDrawMode` and `autoungrabify(false)`; when the graph query returns new data after mount, the `cytoscape` constructor is **not** called again and `cy.add`/`cy.remove` are used; `applyGraphToCy` returns `structureChanged: false` when only labels changed and `true` when a node was added or a `parent` changed; a rejected `createEdge` (mock `apiFetch` to throw `ApiError(409, '{"detail":"this relationship already exists"}')`) shows that text in `graph-error`; the picker with zero valid types shows "No relationship type allows <sourceType> → <targetType>"; a layout promise rejection (mock `layout().run` to return a promise that rejects) shows "Layout failed" in `graph-error` instead of throwing.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.** Create the instance once (`useEffect` with `[]` deps and a `containerRef` guard), keep `graphRef` of the last applied data; a second effect on `[data]` calls `applyGraphToCy` and runs the layout only when `structureChanged`. `applyGraphToCy`: compute desired elements; `cy.remove` ids not desired; for existing ones `ele.data({...})` and `node.move({ parent })` when the parent differs; `cy.add` new ones positioned at `cy.extent()` centre. Layout: `const lay = cy.layout(ELK_LAYOUT); lay.on("layoutstart"/"layoutstop") → setLayoutStatus; lay.promiseOn("layoutstop")` plus a try/catch around `run()`; ELK options as spec §5. Draw mode toggle as spec. `createNode.mutate(..., { onError: e => setError(formatApiError(e)) })` and same for `createEdge`; banner dismissible. Keep `onSelectionChange` and existing props unchanged (`filter` still applied by the third effect).
- [ ] **Step 4: Run** `npm test && npm run build` → pass.
- [ ] **Step 5: Commit** `feat(graph): draw-mode edge creation, crash-free ELK hierarchy layout, incremental canvas updates, visible errors`.

---

### Task 9: Graph page filter bar, dropdown labels, picker, property panel, create form

**Files:**
- Modify: `frontend/src/components/FilterBar.tsx`, `frontend/src/components/PropertyPanel.tsx`, `frontend/src/components/GraphEditor.tsx` (picker labels/order, create-node attributes, parent list, hierarchy labels, search on code), `frontend/src/pages/GraphDemo.tsx`
- Test: `FilterBar.test.tsx`, `PropertyPanel.test.tsx`, `GraphEditor.test.tsx`, `GraphDemo.test.tsx` (all extended)

**Interfaces:**
- Produces: `FilterBar` becomes controlled: props `{ entityTypes, edges, selectedNodeId, value: FilterState, onChange(value) }` where `FilterState = { selectedTypes: string[] | null; search: string; highlighting: boolean }`; `deriveFilterCriteria(state, selectedNodeId, edges): FilterCriteria` exported (pure). `FilterCriteria` type is unchanged.
- Consumes: Task 7 attribute semantics, Task 3 `formatApiError`.

- [ ] **Step 1: Tests.** FilterBar: renders a "Types: n of m" button that opens a panel with a search box and checkboxes labelled `name (code)`, plus All/None; toggling a type calls `onChange` with the new `selectedTypes`; `deriveFilterCriteria` with highlighting on and a selected node returns one-hop ids, with `selectedNodeId=null` returns `highlightIds: null`. GraphDemo: switching hierarchy keeps the search text (state lives in GraphDemo). GraphEditor: hierarchy options render `name (code)`; picker buttons render `name (code)` with constrained types before a divider `data-testid="picker-divider"`; search matches `attributes.code`; with a hierarchy selected the Parent dropdown only lists nodes whose `parent` is not undefined or that are in the hierarchy (i.e. nodes present in the hierarchy query — use the flag that a node has a placement: the graph query with `hierarchy_id` returns `parent` for placed nodes; treat `parent !== undefined` in the data as placed — see note); create-node form shows an input per attribute definition of the chosen type, typed by `data_type`, and sends `attributes`. PropertyPanel: heading `"Nurse: Alice"` (type name); number attribute renders `type="number"`, boolean a checkbox, date `type="date"`; clearing status sends `status: null`; a 409 renders the formatted text.
  Note on "placed" nodes: `GraphNode.parent` is `null` both for root placements and for unplaced nodes. To keep the contract unchanged, derive placement from the hierarchy_node data by adding nothing to the contract: instead list all nodes but put "(root)" first and label the list "Parent (any node placed in this hierarchy will be used; others get an error)"; and surface the 404 through the banner. Implement that simpler behaviour and say so in the report.
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement** as spec §5. `GraphDemo` owns `filterState` (`useState<FilterState>`), passes `value/onChange` to FilterBar and `filter={deriveFilterCriteria(filterState, selectedNodeId, graph?.edges ?? [])}` to GraphEditor; remove the `key={hierarchyId}` remount. PropertyPanel keeps the `key` remount from GraphDemo (selection-based) and switches inputs by `def.data_type`; empty status/description → `null` in the payload (backend Task 7 clears).
- [ ] **Step 4: Run** `npm test && npm run build` → pass.
- [ ] **Step 5: Commit** `feat(graph): compact type filter, readable dropdowns and picker, typed attribute editing, attributes on create`.

---

### Task 10: Organisation selector on the graph page

**Files:**
- Modify: `frontend/src/pages/GraphDemo.tsx`, `frontend/src/pages/GraphDemo.test.tsx`

- [ ] **Step 1: Test.** With two organisations from the mocked API (`default`, `north-clinic`), the page renders a select `data-testid="org-select"` defaulting to `default`; choosing `north-clinic` makes the next graph request use that organisation id and clears the selection/hierarchy.
- [ ] **Step 2: Run** → fail. **Step 3: Implement** (`useOrganizations` query; `organizationId` state; reset `hierarchyId`, `selection` on change). **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat(graph): organisation selector`.

---

### Task 11: Test database isolation, rebuild script, README, smoke check

**Files:**
- Create: `backend/tests/conftest.py`, `scripts/rebuild.sh`
- Modify: `README.md`, `scripts/graph_smoke_check.py`, `scripts/smoke_test.sh` (only if it runs pytest)

- [ ] **Step 1: conftest.** At import time (before any `app` import): read `DATABASE_URL`, derive `<db>_test` (`TEST_DATABASE_URL` env overrides), connect to the same server's `postgres` maintenance database with `psycopg2` (`autocommit=True`) and `CREATE DATABASE` if missing, set `os.environ["DATABASE_URL"]` to the test URL, then run `alembic.command.upgrade(Config("alembic.ini"), "head")` — check `backend/alembic/env.py` for how it reads the URL (it must read `get_settings().database_url` or `DATABASE_URL`; adjust env.py if it reads the `.ini` value). A session-scoped autouse fixture is not needed if this runs at module import; document that in a comment. Verify: `docker compose exec -T backend pytest -q` passes and `SELECT count(*) FROM domain.entity` in the app database does not change across a run (write a small script or check via the API before/after and put the numbers in the report).
- [ ] **Step 2: rebuild script.** `scripts/rebuild.sh`: `set -euo pipefail; docker compose build backend frontend; docker compose up -d --force-recreate backend frontend; curl -fsS http://localhost:8010/api/health; curl -fsS -o /dev/null http://localhost:3010/`. Make executable.
- [ ] **Step 3: README.** Document search/filter/order params, the options endpoint, the graph page features (Connect mode, organisation selector), `scripts/rebuild.sh`, the test database. Remove from Known limitations: list filtering, EAV editing, shared test DB. Keep: collapse/expand, no RBAC, no user creation, optimistic locking (new).
- [ ] **Step 4: smoke check.** Update `scripts/graph_smoke_check.py` to also: PATCH a node with `{"attributes": {"rank": "not a number"}}` expecting 422; PATCH `{"attributes": {"rank": 5}}` expecting 200 and `attributes.rank == 5`; assert the 409-on-delete `detail` is a string (not JSON of JSON). Run it against the rebuilt stack.
- [ ] **Step 5: Commit** `chore: isolated test database, rebuild script, docs and smoke check updates`.

---

### Task 12: Full-stack verification

**Files:** none new (report only, at `.superpowers/sdd/2026-09-17-end-user-fixes/task-12-report.md`).

- [ ] **Step 1:** `scripts/rebuild.sh`; `docker compose exec -T backend pytest -v`; `cd frontend && npm test && npm run build`; `docker compose exec -T backend python -m app.seed_graph_demo`; `python scripts/graph_smoke_check.py`.
- [ ] **Step 2:** Through the real API (curl or python): create an entity type, `GET /api/domain/entity_type/options?q=<code>` returns it; `GET /api/domain/entity/?f_entity_type_id=<id>` works; delete of a referenced row → 409 with readable detail.
- [ ] **Step 3:** Record every command and result in the report. No commit unless something had to be fixed (then a `fix:` commit with the reason).

---

## Plan-level verification

- Every BUG from the test session maps to a task: 500s on delete/duplicate/FK (T1), unpickable FK rows (T2+T4), silent delete failure + no confirm (T3), raw JSON errors (T3), datetime not shown (T4), invalid JSON stored (T4), Loading forever (T3/T4), drag-to-connect impossible (T8), ELK crash (T8), canvas rebuild (T8), silent 409s on the graph page (T8), stale/lost filters (T9), number attribute 500 (T7+T9), cannot clear fields (T7+T9), org hard-wiring (T10), test pollution (T11), deploy drift (T11).
- Every UX item maps too: no search / page in URL / newest rows (T1+T3), UUID pickers and columns (T2+T3+T4), free-text types and blank defaults (T2+T4), per-problem view (T5), session expiry (T6), wall of checkboxes / identical names / picker wall / type-code heading / raw JSON attributes (T9), tables overflow (T3).
- Out of scope per spec: concurrent-edit locking, token storage, public docs, collapse/expand.
