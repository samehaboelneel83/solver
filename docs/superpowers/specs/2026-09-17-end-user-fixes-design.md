# End-User Fixes — Design

**Date:** 2026-09-17
**Scope:** everything found by the 2026-09-17 end-user test session (real Chrome via Playwright against the docker stack, playing a hospital planner building a nurse-rostering domain and problem). Findings are grouped below with the decision taken for each. Items explicitly left out are listed at the end.

## 1. Generic CRUD backend (`backend/app/crud/factory.py`)

| Finding | Decision |
|---|---|
| Deleting a referenced row → HTTP 500 | Catch `IntegrityError` on delete → 409 `{"detail": "<table> row is still referenced by other records"}` (use `exc.orig.diag.table_name`/`constraint_name` in the message when available). |
| Duplicate unique value on create/update → 500 | Same guard on create and update → 409 with `"a <table> row with the same <constraint columns> already exists"` (columns from `exc.orig.diag.constraint_name` when it is a `uq_`/`_key` constraint, else generic wording). Bad FK on create/update → 409 `"referenced <column> does not exist"`. |
| No search on lists | `GET /api/{schema}/{table}/?q=` — case-insensitive `ILIKE '%q%'` OR-ed across every `String`/`Text` column of the model. |
| No per-column filtering (spec §6.2 of the skeleton) | `?f_<column>=<value>` equality filters; unknown column → 422. Values are cast through the column's Python type (UUID/int/bool/str). |
| New rows land on the last page | `?order_by=<column>&order=asc|desc` (unknown column → 422). Default stays insertion order; the frontend asks for `id desc` only when the user picks it. Search + filters make "find my new row" a one-keystroke job. |
| Two tabs, last write wins | Out of scope (needs row versioning). |

## 2. Options + metadata (`backend/app/api/options.py`, `backend/app/api/meta.py`)

- New `GET /api/{schema}/{table}/options?q=&ids=<comma list>&limit=50` (auth required) returning `[{"id": "...", "label": "..."}]`. `q` searches the same columns as §1; `ids` returns exactly those rows (for resolving foreign keys shown in lists).
- Label rules live in `backend/app/crud/labels.py`: default label is `code — name` when both exist, else `code`, `name`, `username`, `state_value`, else the id. Per-table overrides for rows that have no natural label: `hierarchy_node` → `"<entity.name> in <hierarchy.name>"`, `entity_attribute` → `"<entity.name>: <attribute_definition.code>"`, `variable_dimension` → `"<variable.code> #<dimension_order>"`, `user_role` → `"<username> / <role.code>"`, `objective_component` → `code` or `"<objective.code> component"`.
- `/api/meta/schema` gains two optional keys per field: `default` (the scalar client-side ORM default when there is one, e.g. `"DRAFT"`, `1`, `true`) and `choices` (a curated list for free-text "type" columns): `status` → DRAFT/ACTIVE/ARCHIVED; `attribute_definition.data_type` → string/number/boolean/date/datetime/json; `variable_type` → binary/integer/continuous; `objective_type` → minimize/maximize; `severity` → error/warning/info; `dimension_type` → entity/time/set; `cardinality` → one_to_one/one_to_many/many_to_many; `problem_type` → scheduling/assignment/routing/other. Choices are hints only; any value is still accepted.
- Every field also reports `label_field: bool` (whether it participates in the search/label logic) — not required by the UI, useful for debugging.

## 3. Admin UI (`frontend/src/pages`, `frontend/src/components`)

- `api/errors.ts` → `formatApiError(err): string`: 422 bodies become one line per field (`code: Field required`), 409/404/400 bodies show `detail` as text, anything else `"<status> <statusText>"`. Used by EntityDetail, DataTable/EntityList, Login, PropertyPanel, GraphEditor.
- **EntityList:** search box bound to `?q=`, page offset in the URL (`?offset=`), filters from `?f_<col>=` shown as removable chips, sortable headers (`?order_by=&order=`), "New" link carries current filters to prefill the form. Table wrapper is `overflow-x-auto`.
- **DataTable:** `window.confirm` before delete; failed delete shows the formatted error above the table; FK columns render the label from `/options?ids=` (batched per column, cached by React Query) with the UUID in a `title` tooltip.
- **EntityForm:** FK fields use a new `FkPicker` combobox (text input + debounced `/options?q=` list, keyboard selectable, shows the chosen label, clears to `—`); `json` fields are validated client-side and block submit with `"<field>: invalid JSON"`; `date`/`datetime` initial values are formatted for the input (`YYYY-MM-DD` / `YYYY-MM-DDTHH:mm`, local time); fields with `choices` render an `<input list>` datalist; fields with a `default` show `placeholder="default: X"`; initial values can be seeded from the query string (`/new?problem_id=<id>`).
- **EntityDetail:** 404 → "Record not found" with a link back to the list; a **Related records** section on edit pages listing every table with a FK to this one, its row count, a link to the filtered list and a prefilled "New" link. This is the per-problem (and per-entity, per-hierarchy…) view.
- **Routing:** unknown table → "Unknown table <schema>.<table>" instead of an endless "Loading…".
- **Auth:** the 401 redirect goes to `/login?reason=expired&next=<path>`; Login shows "Your session expired — please sign in again" and returns to `next` after sign-in.

## 4. Graph backend (`backend/app/graph`)

- `_write_entity_attributes` validates by `data_type`: number → int/float or numeric string (else `GraphValidationError("attribute <code> expects a number")`); boolean → bool or `"true"/"false"/"1"/"0"`; date/datetime → ISO strings parsed; json → any; unknown attribute code → `GraphValidationError("unknown attribute <code> for this entity type")` (no more silent skip). Validation errors map to 422 as today.
- Clearing: `UpdateNodeRequest` distinguishes omitted from `null` via `model_fields_set`; `update_node` takes a sentinel `UNSET` default so `status=None`/`description=None` explicitly sent clears the column. Attributes sent as `null` delete the `entity_attribute` row.
- `get_domain_graph` filters edges to those whose source **and** target are in the organisation; `EntityTypeOption`/`RelationshipTypeOption`/`HierarchyOption` already carry `code` and `name` (no contract change).
- Seed demo gains two attribute definitions on `employee-demo` (`rank` number, `is_manager` boolean) with values, so the demo page and the smoke check exercise EAV.

## 5. Graph page (`frontend/src/components/GraphEditor.tsx`, `FilterBar.tsx`, `PropertyPanel.tsx`, `pages/GraphDemo.tsx`)

- **Edges can be drawn:** a "Connect" toggle in the toolbar calls `eh.enableDrawMode()` / `disableDrawMode()`; while on, the button reads "Connecting: drag from one node to another" and node dragging is disabled (`cy.autoungrabify(true)`).
- **Layout:** ELK options `{ name: "elk", elk: { algorithm: "layered", "elk.hierarchyHandling": "INCLUDE_CHILDREN" } }`; layout promise errors are caught and shown as an inline message; a "Laying out…" note is visible between `layoutstart` and `layoutstop`.
- **No rebuild on save:** the cytoscape instance is created once per mount. On data change the component diffs elements by id: removes missing, adds new (positioned at the viewport centre), updates `data` (label/parent/type) of existing. A layout runs only when nodes were added/removed or a parent changed; property saves and edge creation keep zoom, pan and dragged positions.
- **Feedback:** node/edge create failures show `formatApiError` in a banner under the toolbar; the picker explains "No relationship type allows <SourceType> → <TargetType>" when the list is empty; duplicate/409 messages are visible.
- **FilterBar:** compact — a searchable type dropdown (checkbox list with `name (code)`, All / None buttons, "n of m types" summary) instead of one checkbox per type; the search box also matches `attributes.code`; state is controlled by `GraphDemo` so it survives hierarchy switches; highlight logic unchanged.
- **Dropdowns:** hierarchy select shows `name (code)`; relationship picker shows `name (code)`, type-constrained matches first, unconstrained ("any → any") after a divider.
- **PropertyPanel:** heading `"<Type name>: <label>"`; attribute inputs typed by `data_type` (number → `type=number`, boolean → checkbox, date/datetime → native inputs, json → textarea); status and description can be cleared (empty input sends `null`); errors formatted.
- **Create-node form:** shows attribute inputs for the chosen type; Parent dropdown lists only nodes placed in the current hierarchy.
- **Organisation:** `GraphDemo` has an organisation selector (default "default"); every hook is keyed by the chosen organisation.

## 6. Tests, tooling, docs

- `backend/tests/conftest.py`: tests run against `<database>_test` (created on demand from the maintenance DB and migrated with Alembic once per session) so `pytest` no longer pollutes the app database. `DATABASE_URL` is rewritten before the app is imported.
- `scripts/rebuild.sh`: `docker compose up -d --build --force-recreate backend frontend` + a sanity curl; README documents that **both** images must be rebuilt.
- README: remove the limitations that are fixed (list filtering, EAV editing partially, shared test DB), add the new features and the remaining known gaps.
- `scripts/graph_smoke_check.py` updated for the new behaviours (409 detail wording, attributes in the seed).

## Out of scope (disclosed, not fixed)

- Optimistic locking for concurrent edits (needs a version column on every table).
- Moving the session token out of localStorage / hiding `/docs` (deployment concerns, not product bugs).
- Hierarchy collapse/expand (still requires `cytoscape-expand-collapse`).
