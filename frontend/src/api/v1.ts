/**
 * Typed clients and React Query hooks for schema v1's purpose-built API
 * (`/api/v1`, backend Tasks 5-9), plus the generic domain list (Task 4).
 *
 * The types mirror the Pydantic models in `backend/app/api/*.py` as they
 * are, not as the plan described them. Things worth knowing before using
 * them:
 *
 * - Ids are `bigint` in Postgres and arrive as JSON numbers. They stay
 *   exact up to 2^53, which identity columns will not reach.
 * - Every list route returns `{items, total}` and accepts `limit` (1-500,
 *   default 50) and `offset` -- except `GET /entity-types/{id}/attributes`,
 *   which returns a bare array.
 * - Every update route is PATCH with "omitted means unchanged" semantics;
 *   there is no PUT anywhere except parameter values, and no update at all
 *   for model versions (immutable) or relationship types' `domain_id`.
 * - `attrs` on entities and relationships is replaced wholesale on PATCH,
 *   never merged.
 * - Entities have no `domain_id` filter; they are scoped by
 *   `entity_type_id`, whose type belongs to one domain.
 * - There is no `/api/v1/problems` list; problems are the generic
 *   `/api/problem/` table (`?f_domain_id=`).
 * - The model-version list returns summaries without `ir`; fetch one
 *   version to get it.
 * - The graph read (`/api/v1/graph`) is deliberately not here: the graph
 *   client in `graph.ts` and its types belong to Task 14.
 */
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ExpressionDocument } from "../expressions/document";
import { ApiError, apiFetch } from "./client";

// --- shared -------------------------------------------------------------

export type Id = number;

export type Page<T> = { items: T[]; total: number };

export type PageParams = { limit?: number; offset?: number };

/** The machine-readable reason a database trigger rejected a write. Only
 * present on 422 entries that came from a trigger (`translate_db_error`);
 * never shown to the user -- it is for code that must branch on it. */
export type TriggerKind =
  | "unknown_attribute"
  | "required_attribute"
  | "attribute_type"
  | "type_mismatch"
  | "cardinality"
  | "cycle"
  | "parameter_index";

/** One entry of a 422 body's `detail` list. Every 422 the v1 routes send is
 * list-shaped (Ruling 19): Pydantic's own errors, the routers' hand-raised
 * field errors, and trigger failures, which add `kind` (Rulings 21, 23).
 * `loc` starts with "body"/"query"/"path"; a batch write points into the
 * batch, e.g. `["body", "cells", 2, "entity_ids"]`. 409 and 404 bodies are
 * `{detail: string}` instead, and `formatApiError` renders both. */
export type ValidationErrorItem = {
  type?: string;
  loc: (string | number)[];
  msg: string;
  kind?: TriggerKind;
  input?: unknown;
};

/**
 * The entries of a list-shaped 422, or `[]` for anything else (another
 * status, a string `detail`, an unparseable body, a non-API error). For
 * forms that mark the offending field; use `formatApiError` for the text.
 */
export function validationErrors(err: unknown): ValidationErrorItem[] {
  if (!(err instanceof ApiError) || err.status !== 422) return [];
  try {
    const body = JSON.parse(err.message) as { detail?: unknown };
    return Array.isArray(body?.detail) ? (body.detail as ValidationErrorItem[]) : [];
  } catch {
    return [];
  }
}

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    // `false` is a real filter value (`is_hierarchy=false`); only absent ones are dropped.
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

function send<T>(method: "POST" | "PATCH" | "PUT", path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, { method, body: JSON.stringify(body) });
}

function remove(path: string): Promise<void> {
  return apiFetch<void>(path, { method: "DELETE" });
}

// --- domains (generic layer, Task 4) --------------------------------------

export type Domain = { id: Id; name: string; created_at: string };

/** Every domain, by name. Not under `/api/v1`: `domain` is one of the three
 * flat tables still served by the generic CRUD factory. */
export function listDomains(): Promise<Page<Domain>> {
  return apiFetch<Page<Domain>>("/api/domain/?limit=500&order_by=name&order=asc");
}

// --- entity types and attribute definitions (Task 5) ----------------------

export type EntityRole = "agent" | "resource" | "time" | "location" | "task" | "org" | "other";
export type AttrType = "integer" | "number" | "text" | "boolean" | "enum" | "time" | "date";

export type AttributeDef = {
  id: Id;
  entity_type_id: Id | null;
  relationship_type_id?: Id | null;
  name: string;
  data_type: AttrType;
  required: boolean;
  unit: string | null;
  enum_values: string[] | null;
  default_value: unknown;
  /** Lower first, name breaking ties (migration 0027). The API already
   * returns attributes in this order, so screens render them as given. */
  sort_order: number;
};

export type AttributeDefCreate = {
  name: string;
  data_type: AttrType;
  required?: boolean;
  unit?: string | null;
  enum_values?: string[] | null;
  default_value?: unknown;
  /** Omitted means "after the others". */
  sort_order?: number;
};

/** An explicit `null` is meaningful (it clears `enum_values`, `unit`,
 * `default_value`); an omitted key leaves the field unchanged. */
export type AttributeDefUpdate = Partial<AttributeDefCreate>;

export type EntityType = {
  id: Id;
  domain_id: Id;
  name: string;
  role: EntityRole;
  /** Lowercase `#rrggbb`, or null for "not chosen" -- the graph then draws
   * a deterministic fallback (`lib/colour.ts`). The API accepts either
   * case and stores lower case. */
  colour: string | null;
  /** Ordered by name. Carried on the list route too. */
  attributes: AttributeDef[];
  /** Migration 0010, Ruling 42. An opaque token, never parsed here: it is
   * sent back verbatim on PATCH and the server refuses a save built on a
   * superseded read with a 409. Parsing it into a `Date` would lose the
   * microseconds Postgres stores and make every save look stale. */
  updated_at: string;
};

export type EntityTypeCreate = {
  domain_id: Id;
  name: string;
  role?: EntityRole;
  colour?: string | null;
};
/** An explicit `null` clears the colour; an omitted key leaves it alone.
 * `updated_at` is the value the form last read -- it is compared, never
 * stored (Ruling 42); omitting it means "no conflict check". */
export type EntityTypeUpdate = {
  name?: string;
  role?: EntityRole;
  colour?: string | null;
  updated_at?: string;
};

export function listEntityTypes(params: { domainId?: Id | null } & PageParams = {}): Promise<Page<EntityType>> {
  const { domainId, limit, offset } = params;
  return apiFetch(`/api/v1/entity-types${query({ domain_id: domainId, limit, offset })}`);
}
export const getEntityType = (id: Id) => apiFetch<EntityType>(`/api/v1/entity-types/${id}`);
export const createEntityType = (body: EntityTypeCreate) => send<EntityType>("POST", "/api/v1/entity-types", body);
export const updateEntityType = (id: Id, body: EntityTypeUpdate) =>
  send<EntityType>("PATCH", `/api/v1/entity-types/${id}`, body);
export const deleteEntityType = (id: Id) => remove(`/api/v1/entity-types/${id}`);

export const listAttributes = (entityTypeId: Id) =>
  apiFetch<AttributeDef[]>(`/api/v1/entity-types/${entityTypeId}/attributes`);
export const createAttribute = (entityTypeId: Id, body: AttributeDefCreate) =>
  send<AttributeDef>("POST", `/api/v1/entity-types/${entityTypeId}/attributes`, body);
export const createRelationshipAttribute = (relationshipTypeId: Id, body: AttributeDefCreate) =>
  send<AttributeDef>("POST", `/api/v1/relationship-types/${relationshipTypeId}/attributes`, body);
export const updateAttribute = (id: Id, body: AttributeDefUpdate) =>
  send<AttributeDef>("PATCH", `/api/v1/attributes/${id}`, body);
export const deleteAttribute = (id: Id) => remove(`/api/v1/attributes/${id}`);
/** The whole list, in the order wanted. The server refuses anything that is
 * not exactly the owner's attributes once each, so two people reordering at
 * once cannot interleave into an order neither chose. */
export const orderAttributes = (entityTypeId: Id, attributeIds: Id[]) =>
  send<AttributeDef[]>("PUT", `/api/v1/entity-types/${entityTypeId}/attribute-order`, {
    attribute_ids: attributeIds,
  });
export const orderRelationshipAttributes = (relationshipTypeId: Id, attributeIds: Id[]) =>
  send<AttributeDef[]>("PUT", `/api/v1/relationship-types/${relationshipTypeId}/attribute-order`, {
    attribute_ids: attributeIds,
  });

// --- entities (Task 6) ------------------------------------------------------

export type Entity = {
  id: Id;
  entity_type_id: Id;
  key: string;
  label: string | null;
  sort_order: number;
  active: boolean;
  attrs: Record<string, unknown>;
  /** Migration 0010, Ruling 42. An opaque token, never parsed here: it is
   * sent back verbatim on PATCH and the server refuses a save built on a
   * superseded read with a 409. Parsing it into a `Date` would lose the
   * microseconds Postgres stores and make every save look stale. */
  updated_at: string;
};

export type EntityCreate = {
  entity_type_id: Id;
  key: string;
  label?: string | null;
  sort_order?: number;
  active?: boolean;
  attrs?: Record<string, unknown>;
};

/** `entity_type_id` is not patchable. `attrs` replaces the whole object.
 * `updated_at` is the value the form last read -- it is compared, never
 * stored (Ruling 42); omitting it means "no conflict check". */
export type EntityUpdate = Partial<Omit<EntityCreate, "entity_type_id">> & { updated_at?: string };

/**
 * Ordered by `sort_order`, then `key`. `q` matches key or label.
 *
 * `expression` is the condition builder's document (Task 14d). It is sent
 * as JSON in the `expr` query parameter and compiled to SQL on the server,
 * where it can only ever NARROW this list -- the predicate is ANDed with
 * the `entity_type_id` and `q` filters, never substituted for them. Send
 * only a document `validateExpression` accepts: the server validates it
 * again against the same shared catalogue and answers 422 with
 * `loc: ["query", "expr", ...]` pointing at the rule it could not use.
 */
export function listEntities(
  params: { entityTypeId?: Id | null; q?: string; expression?: ExpressionDocument | null } & PageParams = {}
): Promise<Page<Entity>> {
  const { entityTypeId, q, expression, limit, offset } = params;
  return apiFetch(
    `/api/v1/entities${query({
      entity_type_id: entityTypeId,
      q,
      expr: expression ? JSON.stringify(expression) : undefined,
      limit,
      offset,
    })}`
  );
}
export const getEntity = (id: Id) => apiFetch<Entity>(`/api/v1/entities/${id}`);
export const createEntity = (body: EntityCreate) => send<Entity>("POST", "/api/v1/entities", body);
export const updateEntity = (id: Id, body: EntityUpdate) => send<Entity>("PATCH", `/api/v1/entities/${id}`, body);
export const deleteEntity = (id: Id) => remove(`/api/v1/entities/${id}`);

// --- relationship types and relationships (Task 7) --------------------------

export type Cardinality = "one_to_one" | "one_to_many" | "many_to_one" | "many_to_many";

export type RelationshipType = {
  id: Id;
  domain_id: Id;
  name: string;
  from_type_id: Id;
  to_type_id: Id;
  cardinality: Cardinality;
  is_hierarchy: boolean;
  /** Same rules as `EntityType.colour`. */
  colour: string | null;
  /** Migration 0010, Ruling 42. An opaque token, never parsed here: it is
   * sent back verbatim on PATCH and the server refuses a save built on a
   * superseded read with a 409. Parsing it into a `Date` would lose the
   * microseconds Postgres stores and make every save look stale. */
  updated_at: string;
  /** Migration 0024. Empty until the type declares some. */
  attributes?: AttributeDef[];
};

export type RelationshipTypeCreate = {
  domain_id: Id;
  name: string;
  from_type_id: Id;
  to_type_id: Id;
  cardinality?: Cardinality;
  is_hierarchy?: boolean;
  colour?: string | null;
};

/** `domain_id` is not patchable. `updated_at` is the value the form last
 * read -- compared, never stored (Ruling 42). */
export type RelationshipTypeUpdate = Partial<Omit<RelationshipTypeCreate, "domain_id">> & {
  updated_at?: string;
};

export type Relationship = {
  id: Id;
  relationship_type_id: Id;
  from_entity_id: Id;
  to_entity_id: Id;
  attrs: Record<string, unknown>;
  /** ISO dates (`YYYY-MM-DD`). */
  valid_from: string | null;
  valid_to: string | null;
  /** Migration 0021, Ruling 42. An opaque token, never parsed here. */
  updated_at: string;
  /** Migration 0024. Empty until the type declares some. */
  attributes?: AttributeDef[];
};

export type RelationshipCreate = {
  relationship_type_id: Id;
  from_entity_id: Id;
  to_entity_id: Id;
  attrs?: Record<string, unknown>;
  valid_from?: string | null;
  valid_to?: string | null;
};

/** Re-typing an edge is delete + create; re-pointing it is a PATCH.
 * `updated_at` is the value the form last read -- compared, never stored. */
export type RelationshipUpdate = Partial<Omit<RelationshipCreate, "relationship_type_id">> & {
  updated_at?: string;
};

export function listRelationshipTypes(
  params: { domainId?: Id | null; isHierarchy?: boolean } & PageParams = {}
): Promise<Page<RelationshipType>> {
  const { domainId, isHierarchy, limit, offset } = params;
  return apiFetch(`/api/v1/relationship-types${query({ domain_id: domainId, is_hierarchy: isHierarchy, limit, offset })}`);
}
export const getRelationshipType = (id: Id) => apiFetch<RelationshipType>(`/api/v1/relationship-types/${id}`);
export const createRelationshipType = (body: RelationshipTypeCreate) =>
  send<RelationshipType>("POST", "/api/v1/relationship-types", body);
export const updateRelationshipType = (id: Id, body: RelationshipTypeUpdate) =>
  send<RelationshipType>("PATCH", `/api/v1/relationship-types/${id}`, body);
export const deleteRelationshipType = (id: Id) => remove(`/api/v1/relationship-types/${id}`);

export function listRelationships(
  params: { relationshipTypeId?: Id | null; fromEntityId?: Id | null; toEntityId?: Id | null } & PageParams = {}
): Promise<Page<Relationship>> {
  const { relationshipTypeId, fromEntityId, toEntityId, limit, offset } = params;
  return apiFetch(
    `/api/v1/relationships${query({
      relationship_type_id: relationshipTypeId,
      from_entity_id: fromEntityId,
      to_entity_id: toEntityId,
      limit,
      offset,
    })}`
  );
}
export const getRelationship = (id: Id) => apiFetch<Relationship>(`/api/v1/relationships/${id}`);
export const createRelationship = (body: RelationshipCreate) =>
  send<Relationship>("POST", "/api/v1/relationships", body);
export const updateRelationship = (id: Id, body: RelationshipUpdate) =>
  send<Relationship>("PATCH", `/api/v1/relationships/${id}`, body);
export const deleteRelationship = (id: Id) => remove(`/api/v1/relationships/${id}`);

// --- parameters (Task 8) ----------------------------------------------------

export type ParameterDef = {
  id: Id;
  domain_id: Id;
  name: string;
  /** Index order as defined: demand[day, shift] is not demand[shift, day]. */
  index_type_ids: Id[];
  /** int4. Values are integer-only throughout. */
  default_value: number;
  unit: string | null;
};

export type ParameterDefCreate = {
  domain_id: Id;
  name: string;
  /** At least one. The same type may appear twice (`distance[location, location]`). */
  index_type_ids: Id[];
  default_value?: number;
  unit?: string | null;
};

/** `domain_id` is not patchable; `name`, `index_type_ids` and
 * `default_value` refuse an explicit null; re-indexing a parameter that
 * has stored cells is a 409. */
export type ParameterDefUpdate = Partial<Omit<ParameterDefCreate, "domain_id">>;

export type ParameterCell = { entity_ids: Id[]; value: number; updated_at?: string };

export type ParameterValues = {
  /** `name` is null when the index type was deleted after the parameter was defined. */
  index_types: { id: Id; name: string | null }[];
  /** Sparse: only cells whose value differs from the default are stored. */
  cells: ParameterCell[];
  default_value: number;
};

export function listParameters(params: { domainId?: Id | null } & PageParams = {}): Promise<Page<ParameterDef>> {
  const { domainId, limit, offset } = params;
  return apiFetch(`/api/v1/parameters${query({ domain_id: domainId, limit, offset })}`);
}
export const getParameter = (id: Id) => apiFetch<ParameterDef>(`/api/v1/parameters/${id}`);
export const createParameter = (body: ParameterDefCreate) =>
  send<ParameterDef>("POST", "/api/v1/parameters", body);
export const updateParameter = (id: Id, body: ParameterDefUpdate) =>
  send<ParameterDef>("PATCH", `/api/v1/parameters/${id}`, body);
export const deleteParameter = (id: Id) => remove(`/api/v1/parameters/${id}`);
export const getParameterValues = (id: Id) => apiFetch<ParameterValues>(`/api/v1/parameters/${id}/values`);
/** Upserts the given cells; a cell set to the default is deleted rather
 * than stored. Returns the whole grid afterwards. A bad cell's 422 points
 * at `["body", "cells", i, ...]`. */
export const putParameterValues = (id: Id, body: { cells: ParameterCell[] }) =>
  send<ParameterValues>("PUT", `/api/v1/parameters/${id}/values`, body);

// --- model versions and scenarios (Task 9) --------------------------------

export type ModelVersionSummary = {
  id: Id;
  problem_id: Id;
  version: number;
  ir_hash: string;
  note: string | null;
  created_at: string;
};

export type ModelVersion = ModelVersionSummary & { ir: Record<string, unknown> };

/** `version` and `ir_hash` are assigned by the database; sending them has no effect. */
export type ModelVersionCreate = { ir: Record<string, unknown>; note?: string | null };

/** Each key optional; an explicit null is refused. A constraint may appear
 * under one instruction only; `soften` weights must be positive. */
export type ScenarioPatch = {
  disable?: string[];
  harden?: string[];
  soften?: Record<string, number>;
};

export type Scenario = {
  id: Id;
  problem_id: Id;
  model_version_id: Id;
  name: string;
  patch: ScenarioPatch;
  created_at: string;
};

export type ScenarioCreate = { problem_id: Id; model_version_id: Id; name: string; patch?: ScenarioPatch };

/** `problem_id` is not patchable; the version must belong to the scenario's problem. */
export type ScenarioUpdate = { name?: string; model_version_id?: Id; patch?: ScenarioPatch };


// --- runs ------------------------------------------------------------------

/** `run_status`, straight from the database's own enum. `optimal` and
 * `feasible` are both answers; the schema keeps them apart, so the UI does
 * too -- "a solution" and "the best solution" are different claims. */
export type RunStatus = "queued" | "running" | "optimal" | "feasible" | "infeasible" | "unknown" | "error" | "cancelled";

export type ConstraintOutcome = {
  constraint_id: string;
  label: string;
  hard: boolean;
  satisfied: boolean;
  total_violation: number;
  penalty_paid: number;
  /** Which instances broke, worst first: `[{index: ["thu","morning"], by: 4}]`. */
  violations: { index: string[]; by: number }[];
  /** Residual at the assignment. Zero means the rule has no room left.
   * Null on runs made before the column existed. */
  slack: number | null;
  /** Shadow price from a linear solver. Null when the backend has none. */
  dual: number | null;
};

export type RunSummary = {
  id: Id;
  scenario_id: Id;
  dataset_id: Id;
  status: RunStatus;
  solver: string;
  solver_version: string | null;
  compiler_version: string | null;
  objective: number | null;
  wall_time_s: number | null;
  error: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Set when someone asked this run to stop. A queued run is already
   * `cancelled`; a running one is still `running` until the worker records it. */
  cancel_requested: boolean;
};

/** One instance of a rule that is part of why there is no answer. */
export type ConflictItem = { constraint_id: string; instance: string[] };

export type Run = RunSummary & {
  params: Record<string, unknown>;
  /** Display names as they were when the run was made, `{set: {key: label}}`.
   * Read from the frozen dataset, so renaming someone does not rewrite an
   * answer already given. Empty for runs made before migration 0012. */
  labels: Record<string, Record<string, string>>;
  /** Which set each position of an index tuple names, so a key can be looked
   * up in the right type: keys are unique within a type, not across them. */
  index_sets: { variables: Record<string, string[]>; constraints: Record<string, string[]> };
  /** Rules that cannot hold together. Null unless the run was infeasible. */
  conflict: ConflictItem[] | null;
  /** True when every listed rule was shown to be needed, so removing any one
   * of them makes the model solvable. False means the search was cut short:
   * the set conflicts, but may be bigger than it needs to be. */
  conflict_minimal: boolean | null;
  /** Variable name -> the index tuples it took. Null when the run found
   * nothing, which is not the same as an empty roster. */
  assignments: Record<string, string[][]> | null;
  /** Reduced costs from a linear solver. Null when the backend has none. */
  reduced_costs: Record<string, { index: string[]; value: number }[]> | null;
  constraints: ConstraintOutcome[];
};

export type RunRequest = { time_limit_s?: number; seed?: number; solver?: string | null };

export type SolverInfo = {
  name: string;
  available: boolean;
  classes: string[];
  note: string;
};

/** What this build can solve with. Hardcoding the list would offer a solver
 * a different build does not have. */
export const listSolvers = () => apiFetch<Page<SolverInfo>>("/api/v1/solvers");

/** What kind of model this IR is. Posted, not stored: the same function a
 * run records, so the editor cannot disagree with the run about the class.
 * `empty_ranges` is filled when a `problem_id` is posted so the compiler
 * can see the live domain; it stays empty when the shape is classified
 * alone. */
export type EmptyRange = {
  constraint_id: string;
  kind: string;
  index: Record<string, string>;
};

export type Classification = {
  model_class: string;
  needs: string[];
  reasons: string[];
  planner: string[];
  empty_ranges: EmptyRange[];
  /** `choose()`'s pick in planner language, or null when this platform
   * has nothing that can take the model. The editor shows this; it never
   * offers a solver picker. */
  would_solve: string | null;
};

export const classifyIr = (ir: Record<string, unknown>, problemId?: Id | null) =>
  send<Classification>("POST", "/api/v1/classify", {
    ir,
    ...(problemId != null ? { problem_id: problemId } : {}),
  });

/** Who the caller is and what they may do. Computed by the API in the same
 * place it enforces them, so the screen and the server cannot disagree. */
export type Me = {
  username: string;
  display_name: string | null;
  email?: string | null;
  capabilities: string[];
};

export const getMe = () => apiFetch<Me>("/api/v1/me");

export type MeUpdate = {
  display_name?: string | null;
  email?: string | null;
  password?: string;
};

export const updateMe = (body: MeUpdate) => send<Me>("PATCH", "/api/v1/me", body);

export type SettingScope = "platform" | "domain" | "problem";

export type SettingValue = {
  key: string;
  value: number | string | boolean | null;
  /** Which level supplied it: a value nobody can attribute is one nobody can
   * change with confidence. `"default"` means nothing is set anywhere. */
  source: SettingScope | "default";
  value_type: "number" | "string" | "boolean";
  description: string;
};

export function listSettings(params: { problemId?: Id | null; domainId?: Id | null } = {}) {
  const { problemId, domainId } = params;
  return apiFetch<Page<SettingValue>>(
    `/api/v1/settings${query({ problem_id: problemId, domain_id: domainId })}`
  );
}

/** `value: null` unsets this level, restoring whatever the level above says. */
export const setSetting = (body: {
  scope: SettingScope;
  scope_id: Id | null;
  key: string;
  value: number | string | boolean | null;
}) => send<Record<string, unknown>>("PUT", "/api/v1/settings", body);

export function listRuns(params: { scenarioId?: Id | null } & PageParams = {}): Promise<Page<RunSummary>> {
  const { scenarioId, limit, offset } = params;
  return apiFetch(`/api/v1/runs${query({ scenario_id: scenarioId, limit, offset })}`);
}
export const getRun = (id: Id) => apiFetch<Run>(`/api/v1/runs/${id}`);

/** What moved between two runs -- and what may honestly be credited for it. */
export type RunComparison = {
  left: ComparedRun;
  right: ComparedRun;
  /** right - left. Null when either run has no objective. */
  objective_delta: number | null;
  /** Per variable, only the ones that moved. */
  moved: Record<string, { added: string[][]; removed: string[][]; unchanged: number }>;
  rules: {
    constraint_id: string;
    left_satisfied: boolean;
    right_satisfied: boolean;
    left_violation: number;
    right_violation: number;
    left_penalty: number;
    right_penalty: number;
  }[];
  /** Everything not equal between the two runs, e.g. ["patch"]. */
  differs_by: string[];
  /** True only when the patch is the sole difference, so the change in the
   * answer can be laid at its door. */
  patch_is_the_only_difference: boolean;
  note: string;
};

export type ComparedRun = {
  id: Id;
  scenario_id: Id;
  scenario_name: string;
  status: RunStatus;
  solver: string;
  solver_version: string | null;
  objective: number | null;
  wall_time_s: number | null;
  dataset_id: Id;
  patch: Record<string, unknown>;
};

export const compareRuns = (left: Id, right: Id) =>
  apiFetch<RunComparison>(`/api/v1/runs/${left}/compare/${right}`);
export const createRun = (scenarioId: Id, body: RunRequest = {}) =>
  send<Run>("POST", `/api/v1/scenarios/${scenarioId}/runs`, body);
export const cancelRun = (id: Id) => send<Run>("POST", `/api/v1/runs/${id}/cancel`, {});

export function listVersions(problemId: Id, params: PageParams = {}): Promise<Page<ModelVersionSummary>> {
  return apiFetch(`/api/v1/problems/${problemId}/versions${query({ limit: params.limit, offset: params.offset })}`);
}
export const createVersion = (problemId: Id, body: ModelVersionCreate) =>
  send<ModelVersion>("POST", `/api/v1/problems/${problemId}/versions`, body);

export type TemplateSeed = {
  note?: string;
  entity_types?: unknown[];
  relationship_types?: unknown[];
  parameters?: unknown;
  entities?: unknown[];
  relationships?: unknown[];
  parameter_values?: unknown[];
  sets?: string[];
};

export type ModelTemplate = {
  id: Id;
  name: string;
  ir_version: string;
  domain_seed: TemplateSeed;
  default_ir: Record<string, unknown>;
};

export type ApplyTemplateRequest = {
  domain_id?: Id;
  domain_name?: string;
  problem_id?: Id;
  name?: string;
};

export type ApplyTemplateResult = {
  template_id: Id;
  domain_id: Id;
  problem_id: Id;
  model_version_id: Id;
  scenario_id: Id;
};

export const listTemplates = () => apiFetch<Page<ModelTemplate>>("/api/template/?limit=50");
export const applyTemplate = (id: Id, body: ApplyTemplateRequest) =>
  send<ApplyTemplateResult>("POST", `/api/v1/templates/${id}/apply`, body);
export const getVersion = (id: Id) => apiFetch<ModelVersion>(`/api/v1/versions/${id}`);

export function listScenarios(
  params: { problemId?: Id | null; modelVersionId?: Id | null } & PageParams = {}
): Promise<Page<Scenario>> {
  const { problemId, modelVersionId, limit, offset } = params;
  return apiFetch(`/api/v1/scenarios${query({ problem_id: problemId, model_version_id: modelVersionId, limit, offset })}`);
}
export const getScenario = (id: Id) => apiFetch<Scenario>(`/api/v1/scenarios/${id}`);
export const createScenario = (body: ScenarioCreate) => send<Scenario>("POST", "/api/v1/scenarios", body);
export const updateScenario = (id: Id, body: ScenarioUpdate) =>
  send<Scenario>("PATCH", `/api/v1/scenarios/${id}`, body);
export const deleteScenario = (id: Id) => remove(`/api/v1/scenarios/${id}`);

// --- React Query hooks ------------------------------------------------------
//
// Every key starts with "v1". A mutation invalidates the whole "v1"
// namespace rather than guessing its blast radius: deletes cascade in the
// database (an entity takes its relationships and parameter cells with it;
// an entity type takes its attributes, entities and relationship types),
// and an attribute change alters the entity-type read model. A refetch of
// what is on screen is cheap; a stale grid is not.

const V1 = "v1";

/** The generic CRUD layer's own list hooks (`api/entities.ts`) key on
 * ["entities", schema, table, ...] and invalidate that prefix after a
 * create/update/delete, so keying the domain list under it keeps the
 * selector current when a domain is added or removed on its list page. */
export const DOMAINS_QUERY_KEY = ["entities", "public", "domain", "all-by-name"] as const;

export function useDomains() {
  return useQuery({ queryKey: DOMAINS_QUERY_KEY, queryFn: listDomains });
}

function useV1Mutation<TVars, TResult>(fn: (vars: TVars) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [V1] }),
  });
}

const isId = (id: Id | null | undefined): id is Id => id !== null && id !== undefined;

// entity types
export function useEntityTypes(
  domainId: Id | null,
  page: PageParams = {},
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: [V1, "entity-types", { domainId, ...page }],
    queryFn: () => listEntityTypes({ domainId, ...page }),
    // `options.enabled` only ever *narrows*: a caller can switch a query
    // off (the graph's inactive mode), never on for a null domain.
    enabled: isId(domainId) && options.enabled !== false,
  });
}
export function useEntityType(id: Id | null | undefined) {
  return useQuery({ queryKey: [V1, "entity-type", id], queryFn: () => getEntityType(id as Id), enabled: isId(id) });
}
export const useCreateEntityType = () => useV1Mutation(createEntityType);
export const useUpdateEntityType = () =>
  useV1Mutation(({ id, body }: { id: Id; body: EntityTypeUpdate }) => updateEntityType(id, body));
export const useDeleteEntityType = () => useV1Mutation(deleteEntityType);
export const useCreateAttribute = () =>
  useV1Mutation(({ entityTypeId, body }: { entityTypeId: Id; body: AttributeDefCreate }) =>
    createAttribute(entityTypeId, body)
  );
export const useCreateRelationshipAttribute = () =>
  useV1Mutation(({ relationshipTypeId, body }: { relationshipTypeId: Id; body: AttributeDefCreate }) =>
    createRelationshipAttribute(relationshipTypeId, body)
  );
export const useUpdateAttribute = () =>
  useV1Mutation(({ id, body }: { id: Id; body: AttributeDefUpdate }) => updateAttribute(id, body));
export const useDeleteAttribute = () => useV1Mutation(deleteAttribute);
export const useOrderAttributes = () =>
  useV1Mutation(({ entityTypeId, attributeIds }: { entityTypeId: Id; attributeIds: Id[] }) =>
    orderAttributes(entityTypeId, attributeIds)
  );
export const useOrderRelationshipAttributes = () =>
  useV1Mutation(({ relationshipTypeId, attributeIds }: { relationshipTypeId: Id; attributeIds: Id[] }) =>
    orderRelationshipAttributes(relationshipTypeId, attributeIds)
  );

// entities
export function useEntities(
  entityTypeId: Id | null,
  params: { q?: string; expression?: ExpressionDocument | null } & PageParams = {}
) {
  return useQuery({
    // The document goes into the key by value, so two different
    // expressions are two cached lists and the same one is one request.
    queryKey: [V1, "entities", { entityTypeId, ...params }],
    queryFn: () => listEntities({ entityTypeId, ...params }),
    enabled: isId(entityTypeId),
    // No `retry` override: the app's default (`lib/queryRetry.ts`) already
    // gives up immediately on any 4xx, which is exactly right for the
    // compiler's 422 -- the same document sent again gets the same answer.
  });
}
export function useEntityRecord(id: Id | null | undefined) {
  return useQuery({ queryKey: [V1, "entity", id], queryFn: () => getEntity(id as Id), enabled: isId(id) });
}
export const useCreateEntity = () => useV1Mutation(createEntity);
export const useUpdateEntity = () =>
  useV1Mutation(({ id, body }: { id: Id; body: EntityUpdate }) => updateEntity(id, body));
export const useDeleteEntity = () => useV1Mutation(deleteEntity);

// relationship types and relationships
export function useRelationshipTypes(
  domainId: Id | null,
  params: { isHierarchy?: boolean } & PageParams = {},
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: [V1, "relationship-types", { domainId, ...params }],
    queryFn: () => listRelationshipTypes({ domainId, ...params }),
    enabled: isId(domainId) && options.enabled !== false,
  });
}
export function useRelationshipType(id: Id | null | undefined) {
  return useQuery({
    queryKey: [V1, "relationship-type", id],
    queryFn: () => getRelationshipType(id as Id),
    enabled: isId(id),
  });
}
export const useCreateRelationshipType = () => useV1Mutation(createRelationshipType);
export const useUpdateRelationshipType = () =>
  useV1Mutation(({ id, body }: { id: Id; body: RelationshipTypeUpdate }) => updateRelationshipType(id, body));
export const useDeleteRelationshipType = () => useV1Mutation(deleteRelationshipType);

export function useRelationships(
  params: { relationshipTypeId?: Id | null; fromEntityId?: Id | null; toEntityId?: Id | null } & PageParams
) {
  return useQuery({ queryKey: [V1, "relationships", params], queryFn: () => listRelationships(params) });
}
export function useRelationship(id: Id | null | undefined) {
  return useQuery({
    queryKey: [V1, "relationship", id],
    queryFn: () => getRelationship(id as Id),
    enabled: isId(id),
  });
}

/** The API's largest page. Both multi-list hooks below ask for it, the
 * way every other v1 screen does, and report when a list was cut off
 * rather than quietly showing part of one. */
const MAX_PAGE = 500;

type MultiList<T> = {
  items: T[];
  isLoading: boolean;
  error: unknown;
  /** True when at least one of the lists held more rows than one page. */
  truncated: boolean;
};

/**
 * Every relationship of several types, as one list.
 *
 * `GET /api/v1/relationships` filters by `relationship_type_id`,
 * `from_entity_id` and `to_entity_id` and has no domain filter, so "this
 * domain's relationships" is one request per relationship type. A domain
 * holds a handful of types -- the same assumption `EntityTypes` and
 * `RelationshipTypes` already make when they ask for 500 and do not
 * paginate -- and React Query serves each list once however many callers
 * ask for it.
 *
 * The keys are built to match `useRelationships`'s exactly, so a list
 * fetched here and the same list fetched there are one cache entry and
 * one request.
 */
export function useRelationshipsOfTypes(relationshipTypeIds: Id[]): MultiList<Relationship> {
  const results = useQueries({
    queries: relationshipTypeIds.map((relationshipTypeId) => {
      const params = { relationshipTypeId, limit: MAX_PAGE };
      return {
        queryKey: [V1, "relationships", params],
        queryFn: () => listRelationships(params),
      };
    }),
  });
  return {
    items: results.flatMap((result) => result.data?.items ?? []),
    isLoading: results.some((result) => result.isLoading),
    error: results.find((result) => result.error)?.error ?? null,
    truncated: results.some((result) => (result.data?.total ?? 0) > (result.data?.items.length ?? 0)),
  };
}

/**
 * Every entity of several entity types, as one list.
 *
 * What names the two ends of a relationship: a relationship row carries
 * ids, and the type it belongs to says which entity type each end is, so
 * the rows needed to turn `to_entity_id: 4` into "North Depot" are
 * exactly the entities of the types that appear as ends. Same key shape
 * as `useEntities(id, { limit: 500 })`, for the same reason as above.
 */
export function useEntitiesOfTypes(entityTypeIds: Id[]): MultiList<Entity> {
  const results = useQueries({
    queries: entityTypeIds.map((entityTypeId) => {
      const params = { entityTypeId, limit: MAX_PAGE };
      return {
        queryKey: [V1, "entities", params],
        queryFn: () => listEntities(params),
      };
    }),
  });
  return {
    items: results.flatMap((result) => result.data?.items ?? []),
    isLoading: results.some((result) => result.isLoading),
    error: results.find((result) => result.error)?.error ?? null,
    truncated: results.some((result) => (result.data?.total ?? 0) > (result.data?.items.length ?? 0)),
  };
}
export const useCreateRelationship = () => useV1Mutation(createRelationship);
export const useUpdateRelationship = () =>
  useV1Mutation(({ id, body }: { id: Id; body: RelationshipUpdate }) => updateRelationship(id, body));
export const useDeleteRelationship = () => useV1Mutation(deleteRelationship);

// parameters
export function useParameters(domainId: Id | null, page: PageParams = {}) {
  return useQuery({
    queryKey: [V1, "parameters", { domainId, ...page }],
    queryFn: () => listParameters({ domainId, ...page }),
    enabled: isId(domainId),
  });
}
export function useParameter(id: Id | null | undefined) {
  return useQuery({ queryKey: [V1, "parameter", id], queryFn: () => getParameter(id as Id), enabled: isId(id) });
}
export function useParameterValues(id: Id | null | undefined) {
  return useQuery({
    queryKey: [V1, "parameter-values", id],
    queryFn: () => getParameterValues(id as Id),
    enabled: isId(id),
  });
}
export const useCreateParameter = () => useV1Mutation(createParameter);
export const useUpdateParameter = () =>
  useV1Mutation(({ id, body }: { id: Id; body: ParameterDefUpdate }) => updateParameter(id, body));
export const useDeleteParameter = () => useV1Mutation(deleteParameter);
export const usePutParameterValues = () =>
  useV1Mutation(({ id, cells }: { id: Id; cells: ParameterCell[] }) => putParameterValues(id, { cells }));

// model versions and scenarios
export function useVersions(problemId: Id | null, page: PageParams = {}) {
  return useQuery({
    queryKey: [V1, "versions", { problemId, ...page }],
    queryFn: () => listVersions(problemId as Id, page),
    enabled: isId(problemId),
  });
}
export function useVersion(id: Id | null | undefined) {
  return useQuery({ queryKey: [V1, "version", id], queryFn: () => getVersion(id as Id), enabled: isId(id) });
}
export const useCreateVersion = () =>
  useV1Mutation(({ problemId, body }: { problemId: Id; body: ModelVersionCreate }) => createVersion(problemId, body));

export function useTemplates() {
  return useQuery({ queryKey: [V1, "templates"], queryFn: listTemplates, staleTime: 60_000 });
}
export const useApplyTemplate = () =>
  useV1Mutation(({ id, body }: { id: Id; body: ApplyTemplateRequest }) => applyTemplate(id, body));

export function useSettings(params: { problemId?: Id | null; domainId?: Id | null } = {}) {
  return useQuery({
    queryKey: [V1, "settings", params],
    queryFn: () => listSettings(params),
  });
}
export const useSetSetting = () => useV1Mutation(setSetting);

export function useMe() {
  return useQuery({ queryKey: [V1, "me"], queryFn: getMe, staleTime: 5 * 60 * 1000 });
}
export const useUpdateMe = () => useV1Mutation(updateMe);

export function useSolvers() {
  return useQuery({ queryKey: [V1, "solvers"], queryFn: listSolvers, staleTime: 5 * 60 * 1000 });
}

export function useClassify(ir: Record<string, unknown> | null, problemId?: Id | null) {
  return useQuery({
    queryKey: [V1, "classify", ir, problemId ?? null],
    queryFn: () => classifyIr(ir as Record<string, unknown>, problemId),
    enabled: ir !== null,
    staleTime: 30_000,
  });
}

export function useRuns(scenarioId: Id | null, page: PageParams = {}) {
  return useQuery({
    queryKey: [V1, "runs", { scenarioId, ...page }],
    queryFn: () => listRuns({ scenarioId, ...page }),
    enabled: isId(scenarioId),
  });
}
export function useRun(id: Id | null | undefined) {
  return useQuery({
    queryKey: [V1, "run", id],
    queryFn: () => getRun(id as Id),
    enabled: isId(id),
    // Solving happens in a worker, so a run arrives `queued` and settles
    // later. Poll while it is unfinished and stop as soon as it is: a run is
    // immutable once written, so there is nothing to poll for afterwards.
    refetchInterval: (query) => {
      const status = (query.state.data as Run | undefined)?.status;
      return status === "queued" || status === "running" ? 1000 : false;
    },
  });
}
/** Returns the run `queued`: the worker solves it, and `useRun` polls until
 * it settles. */
export const useCreateRun = () =>
  useV1Mutation(({ scenarioId, body }: { scenarioId: Id; body?: RunRequest }) => createRun(scenarioId, body));
export const useCancelRun = () => useV1Mutation((id: Id) => cancelRun(id));

export function useRunComparison(left: Id | null | undefined, right: Id | null | undefined) {
  return useQuery({
    queryKey: [V1, "compare", left, right],
    queryFn: () => compareRuns(left as Id, right as Id),
    enabled: isId(left) && isId(right) && left !== right,
  });
}

export function useScenarios(problemId: Id | null, params: { modelVersionId?: Id | null } & PageParams = {}) {
  return useQuery({
    queryKey: [V1, "scenarios", { problemId, ...params }],
    queryFn: () => listScenarios({ problemId, ...params }),
    enabled: isId(problemId),
  });
}
export function useScenario(id: Id | null | undefined) {
  return useQuery({ queryKey: [V1, "scenario", id], queryFn: () => getScenario(id as Id), enabled: isId(id) });
}
export const useCreateScenario = () => useV1Mutation(createScenario);
export const useUpdateScenario = () =>
  useV1Mutation(({ id, body }: { id: Id; body: ScenarioUpdate }) => updateScenario(id, body));
export const useDeleteScenario = () => useV1Mutation(deleteScenario);
