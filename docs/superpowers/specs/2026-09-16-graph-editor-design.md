# Graph Editor — Domain Graph, Full Editor (Sub-Project 1)

Status: approved for implementation planning
Date: 2026-09-16

## 1. Purpose

The problem-solver platform (built in the prior MVP skeleton) has a generic
table-by-table admin UI for its 31 tables, but modeling a domain — entities,
their types, their relationships, and organizational hierarchy — is
fundamentally a graph-shaped task that a row-by-row CRUD form represents
poorly. This sub-project adds a visual graph editor: a normalized graph
contract, a backend Graph API with atomic multi-table writes, and a
Cytoscape.js-based editor component that can view, create, edit, and delete
domain entities and relationships directly as a graph, including
hierarchy-driven visual nesting with collapse/expand.

This is the **first** of several planned graph-related sub-projects. It
covers the `domain` schema only. Later sub-projects (not covered here) will
add: NetworkX-based graph analysis (shortest path, centrality, cycle
detection), a Sigma.js-based read-only viewer for large graphs (2000+
nodes), a Problem-schema view (variables/constraints/objectives as typed
node groups — blocked on a real data-modeling decision, see §8), and
eventually solver-input/solution graph views once a solver exists.

## 2. Scope for this sub-project

**In scope:**
- A normalized graph contract (Pydantic backend model, matching TypeScript
  frontend type) covering nodes, edges, and the supporting metadata a
  client needs to render and edit without a second round-trip.
- A backend `GraphService` and `/api/graph/domain` endpoint family: read
  the full domain graph for an organization (optionally nested by a chosen
  hierarchy), and atomic create/update/delete for both nodes and edges.
- Type-aware edge creation: `relationship_type.source_entity_type` /
  `target_entity_type` (when set) are validated against the two entities'
  actual types before an edge is created.
- A `<GraphEditor/>` React component wrapping Cytoscape.js + the ELK
  layout extension: pan/zoom, drag nodes, drag-connect to create edges,
  select node/edge to open a property panel, a hierarchy-select dropdown
  driving compound-node nesting with collapse/expand, a filter bar
  (entity-type filter, label/code search, one-hop dependency highlight).
- A `<PropertyPanel/>` that edits both an entity's fixed columns (code,
  name, status, description) and its dynamic EAV attributes
  (`entity_attribute`, typed per `attribute_definition`).
- A seed script producing a small Employee/Unit demo dataset, run manually
  (not at application startup).
- A demo page at a new `/graph` route in the existing frontend app.

**Out of scope (future sub-projects, not designed here):**
- NetworkX analysis endpoints (shortest path, centrality, cycle detection).
- `<LargeGraphViewer/>` (Sigma.js), for graphs beyond what Cytoscape
  comfortably handles interactively.
- The Problem-schema graph view. The `problem` schema tables
  (`variable_definition`, `constraint_definition`, `objective`,
  `objective_component`) have no real foreign keys linking them to each
  other or to the variables/entities they reference — only opaque JSONB
  `expression`/`domain_definition` fields. Rendering
  "Employee → Shift → Assignment → Constraint → Objective" as real graph
  edges requires either adding explicit link tables or parsing JSONB
  expressions, and that data-modeling decision needs its own brainstorming
  pass before a Problem view can be designed.
- Solver-input and solution graph views (no solver exists yet).
- Subgraph save/bookmark functionality.
- Multi-organization graph views (this sub-project is organization-scoped,
  matching every other part of the platform, but only one organization
  exists today).

## 3. The normalized graph contract

Backend: `backend/app/graph/schemas.py` (Pydantic). Frontend:
`frontend/src/types/graph.ts` (TypeScript). The two must stay in sync by
hand (no code generation across the language boundary this phase).

```python
class GraphNode(BaseModel):
    id: str                          # entity.id
    type: str                        # entity_type.code
    label: str                       # entity.name, falling back to entity.code, falling back to id
    parent: str | None               # entity id of this node's hierarchy_node parent, within the
                                      # requested hierarchy_id; null if root or hierarchy_id was omitted
    attributes: dict[str, Any]       # merged: {code, status, description} + EAV values keyed by attribute code

class GraphEdge(BaseModel):
    id: str                          # relationship.id
    source: str                      # relationship.source_entity_id
    target: str                      # relationship.target_entity_id
    type: str                        # relationship_type.code
    label: str                       # relationship_type.name
    attributes: dict[str, Any]       # relationship.attributes JSONB, or {} if null

class EntityTypeOption(BaseModel):
    id: str
    code: str
    name: str
    is_abstract: bool

class RelationshipTypeOption(BaseModel):
    id: str
    code: str
    name: str
    is_directed: bool
    source_entity_type: str | None   # entity_type.code, or null if unconstrained
    target_entity_type: str | None

class HierarchyOption(BaseModel):
    id: str
    code: str
    name: str

class AttributeDefinitionOption(BaseModel):
    id: str
    entity_type_id: str
    code: str
    name: str
    data_type: str                   # matches attribute_definition.data_type, e.g. "string"/"number"/"boolean"/"date"

class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    entity_types: list[EntityTypeOption]
    relationship_types: list[RelationshipTypeOption]
    hierarchies: list[HierarchyOption]
    attribute_definitions: list[AttributeDefinitionOption]
```

All ids are stringified UUIDs (matching how the rest of the platform's API
already serializes them). `attributes` values are whatever JSON-compatible
type the underlying `entity_attribute.value_*` column or `data_type`
implies — no further type coercion in the contract itself.

## 4. Backend

### 4.1 `GraphService` (`backend/app/graph/service.py`)

- `get_domain_graph(db, organization_id, hierarchy_id=None) -> GraphResponse`
  — queries `entity` (+ `entity_type` for `type`/label fallback),
  `entity_attribute` (+ `attribute_definition` for the code key),
  `relationship` (+ `relationship_type`), and, if `hierarchy_id` is given,
  `hierarchy_node` for that hierarchy to compute each node's `parent`.
  Also returns the four metadata lists (entity types, relationship types,
  hierarchies, attribute definitions) for the organization, unfiltered by
  the selected hierarchy.
- `create_node(db, *, organization_id, entity_type_id, name, code=None,
  status=None, description=None, attributes: dict, hierarchy_id=None,
  parent_entity_id=None) -> GraphNode` — inserts one `entity` row; for each
  key in `attributes` that matches an `attribute_definition` for the given
  `entity_type_id`, inserts an `entity_attribute` row into the correct
  `value_*` column per that definition's `data_type`; if `hierarchy_id` is
  given, inserts one `hierarchy_node` row (`parent_node_id` resolved from
  `parent_entity_id`'s existing `hierarchy_node` row in that hierarchy, or
  null for a root placement). All in one DB transaction. Note the
  asymmetry with §3's `GraphNode.attributes`: on write, `attributes` here
  is EAV values only (keyed by `attribute_definition.code`) — `code`,
  `status`, and `description` are separate named parameters because they
  map to real `entity` columns, not EAV rows. On read, `GraphService`
  merges both into one flat `GraphNode.attributes` dict for the frontend's
  convenience. `PropertyPanel` (§5.2) is responsible for splitting a saved
  edit back into the two write-side buckets before calling
  `useUpdateNode`.
- `update_node(db, entity_id, **same fields as create, all optional) ->
  GraphNode` — updates `entity` columns given; upserts `entity_attribute`
  rows for any `attributes` keys given; if `hierarchy_id` is given,
  updates (or inserts) the `hierarchy_node` row's `parent_node_id` for
  that hierarchy to `parent_entity_id`'s resolved node — including
  setting it to `null` (move to root) when `parent_entity_id` is
  explicitly passed as `null`, distinct from omitting it entirely (leave
  the current placement untouched).
- `delete_node(db, entity_id) -> None` — deletes the `entity` row. If
  Postgres raises an `IntegrityError` (the entity is still referenced by a
  `relationship`, `hierarchy_node`, or elsewhere), catch it and raise a
  `GraphConflictError` that the route layer maps to **HTTP 409** with a
  message naming what's still attached (e.g. "entity has 2 relationship(s)
  and 1 hierarchy placement — remove them first"). This is a deliberate
  fix of the pattern the platform-skeleton's final review already flagged
  once (an unhandled `IntegrityError` surfacing as a bare 500) — new code
  in this sub-project does not repeat it.
- `create_edge(db, *, relationship_type_id, source_entity_id,
  target_entity_id, attributes: dict) -> GraphEdge` — loads the
  `relationship_type` and both entities' `entity_type_id`; if
  `source_entity_type`/`target_entity_type` on the relationship type are
  set (non-null) and don't match the entities' actual types, raises a
  `GraphValidationError` the route layer maps to **HTTP 422** naming the
  mismatch. Otherwise inserts one `relationship` row.
- `update_edge(db, relationship_id, attributes: dict | None) -> GraphEdge`
  — updates `relationship.attributes` only; source/target/type are
  immutable after creation for this phase (deleting and recreating covers
  the rare re-type case, avoiding re-running type validation against a
  partially-changed edge).
- `delete_edge(db, relationship_id) -> None` — straightforward delete;
  `relationship` has no downstream FK dependents in the current schema.

### 4.2 Routes (`backend/app/api/graph.py`, prefix `/api/graph/domain`)

All routes depend on `get_current_user` (the same dependency every other
route in the platform uses — no new auth mechanism).

- `GET /api/graph/domain?organization_id=<uuid>&hierarchy_id=<uuid|omit>`
  → `GraphResponse`
- `POST /api/graph/domain/nodes` (body: the `create_node` fields) → `GraphNode`, 201
- `PATCH /api/graph/domain/nodes/{entity_id}` (body: `update_node` fields, all optional) → `GraphNode`, 200
- `DELETE /api/graph/domain/nodes/{entity_id}` → 204, or 409 on conflict
- `POST /api/graph/domain/edges` (body: `create_edge` fields) → `GraphEdge`, 201, or 422 on type mismatch
- `PATCH /api/graph/domain/edges/{relationship_id}` (body: `{attributes}`) → `GraphEdge`, 200
- `DELETE /api/graph/domain/edges/{relationship_id}` → 204

## 5. Frontend

### 5.1 Data layer

- `frontend/src/types/graph.ts` — TypeScript types mirroring §3 exactly.
- `frontend/src/api/graph.ts` — React Query hooks: `useGraph(organizationId,
  hierarchyId)`, `useCreateNode`, `useUpdateNode`, `useDeleteNode`,
  `useCreateEdge`, `useUpdateEdge`, `useDeleteEdge`. Same `apiFetch`-based
  pattern as the platform skeleton's `entities.ts` — the browser never
  talks to Postgres directly, only through these calls to
  `/api/graph/domain/...`.

### 5.2 Components

- `frontend/src/components/GraphEditor.tsx` — the core component. Wraps
  `cytoscape` (registering the `cytoscape-elk` extension for layout).
  Renders nodes/edges from `useGraph(...)`; a node's `parent` field maps
  directly to Cytoscape's compound-node `parent` property, giving
  collapse/expand for free via Cytoscape's own compound-node interaction
  model. Toolbar: zoom/fit, re-run ELK layout, a hierarchy-select dropdown
  (options from the response's `hierarchies` list; changing it re-fetches
  `useGraph` with the new `hierarchy_id`). Drag-connecting two nodes opens
  a small relationship-type picker filtered to types whose
  source/target constraints (if any) match the two nodes' entity types,
  then calls `useCreateEdge`. Clicking empty canvas (or a toolbar "+"
  button) opens a create-node form (entity-type picker + name/code +
  attribute inputs from `attribute_definitions`, filtered by the chosen
  type) and calls `useCreateNode`, placed under whatever compound parent
  was clicked if the click landed inside one. Clicking a node or edge sets
  a `selected` state that renders `PropertyPanel`.
- `frontend/src/components/PropertyPanel.tsx` — for a selected node: an
  editable form for `code`/`name`/`status`/`description`, plus one input
  per `attribute_definition` matching the node's `type`, typed by
  `data_type` (string/number/boolean/date — same input-type mapping
  convention the platform skeleton's `EntityForm` already established).
  For a selected edge: `type`/`label` shown read-only, `attributes` as a
  raw JSON textarea (matching the platform skeleton's JSON-field
  convention). Saves call `useUpdateNode`/`useUpdateEdge`; a delete button
  calls the corresponding delete hook and surfaces a 409 conflict message
  inline rather than failing silently (same fix as §4.1's `delete_node`,
  carried through to the UI).
- `frontend/src/components/FilterBar.tsx` — an entity-type multi-select
  (hides non-matching nodes client-side; their edges hide too since
  Cytoscape can't render a dangling edge), a text search box matching
  node `label`/`attributes.code` substrings, and a "highlight
  dependencies" toggle that, given a selected node, walks the already-
  loaded `edges` array one hop upstream and downstream in plain
  JavaScript (no backend call, no NetworkX — the full domain graph is
  already client-side after `useGraph` resolves).
- `frontend/src/pages/GraphDemo.tsx` — the demo page; a new `/graph` route
  added to the existing `AppShell`-nested route tree in `App.tsx`, sitting
  alongside the generic admin routes from the platform skeleton (both
  continue to work independently — this does not replace or modify the
  generic `EntityList`/`EntityDetail` pages for `domain.entity` etc.,
  which remain available as a fallback row-level editor).

## 6. Seed data

`backend/app/seed_graph_demo.py` — a standalone, idempotent function
(check-then-insert per row, same pattern as the platform skeleton's
`seed_admin`) creating:
- `entity_type` rows: `Employee`, `Unit`.
- `relationship_type` row: `works_for` (source `Employee`, target `Unit`,
  `is_directed=true`).
- `hierarchy` row: `Org Chart`.
- A handful of `entity` rows (e.g. 2 units, 3 employees) and matching
  `relationship` (`works_for`) and `hierarchy_node` (employees nested
  under their unit) rows.

Run manually: `docker compose exec -T backend python -m app.seed_graph_demo`.
**Not** wired into the FastAPI startup hook — this is demo data, and a
real deployment should not get it for free just by starting the service.

## 7. Testing

- **Backend**: pytest against the real Postgres test pattern already
  established (docker-compose containers, real DB, no mocks). Cover:
  `get_domain_graph`'s assembled shape (nodes/edges/metadata all present
  and correctly typed); `create_node` writing entity + hierarchy_node +
  entity_attribute atomically in one call; `create_edge` both accepting a
  valid type combination and rejecting a mismatched one with 422;
  `delete_node` returning 409 (not 500) when the entity is still
  referenced.
- **Frontend**: Vitest component tests for `GraphEditor`, `PropertyPanel`,
  and `FilterBar` focused on the React-level contract — props received,
  hooks called with correct arguments, callbacks fired on interaction —
  not on Cytoscape's actual canvas/WebGL rendering, which jsdom cannot
  meaningfully verify. Where a test needs to simulate "the user clicked
  node X," it does so through Cytoscape's own JS event API (`cy.emit(...)`
  or triggering the registered handler directly) rather than simulating
  real mouse coordinates on a canvas.

## 8. Open questions for the next sub-project (not blocking this one)

- How should `problem`-schema dependency edges (variable → constraint →
  objective) actually be represented — new explicit link tables, or
  parsed from the existing JSONB `expression`/`domain_definition` fields?
  This needs its own brainstorming pass before the Problem view can be
  designed.
- Whether NetworkX-based analysis should run against a live query each
  request or a cached in-memory graph — deferred until that sub-project
  is scoped, since it depends on expected graph size and update frequency
  neither of which is known yet.
