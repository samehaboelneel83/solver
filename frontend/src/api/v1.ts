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
import { ApiError, apiFetch, apiText } from "./client";
import { useDebouncedValue } from "../hooks/useDebouncedValue";

// --- shared -------------------------------------------------------------

export type Id = number;

export type Page<T> = { items: T[]; total: number };

/** `q` searches the list by name (or other text), and by id when it is a number (Epic UX, U-1). */
export type PageParams = { limit?: number; offset?: number; q?: string };

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
export type AttrType = "integer" | "number" | "text" | "boolean" | "enum" | "time" | "date" | "geometry" | "reference";

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
  /** Migration 0067 (queue R20a): a reference's mirror relationship type and the type it refers to. */
  references_id?: Id | null;
  target_type_id?: Id | null;
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
  /** A `reference` attribute's target entity type (queue R20a). */
  target_type_id?: Id | null;
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
  /** Migration 0033: a gallery key (`lib/entityIcons.ts`) or an uploaded
   * image's `data:` URI, or null for "not chosen" -- the Graph View then
   * picks a default from the name and role. */
  icon: string | null;
  /** Every attribute an entity of this type has: its own, then its ancestors' (queue R18), each
   * carrying the `entity_type_id` it is declared on. Carried on the list route too. */
  attributes: AttributeDef[];
  /** The type's own attribute definitions -- what its attribute editor adds, edits and orders. */
  own_attributes?: AttributeDef[];
  /** Migration 0066 (queue R18): an abstract type holds no entities of its own. */
  is_abstract?: boolean;
  /** The type this one inherits from, or null. */
  inherited_from?: Id | null;
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
  icon?: string | null;
  is_abstract?: boolean;
  inherited_from?: Id | null;
};
/** An explicit `null` clears the colour (or the icon); an omitted key leaves it alone.
 * `updated_at` is the value the form last read -- it is compared, never
 * stored (Ruling 42); omitting it means "no conflict check". */
export type EntityTypeUpdate = {
  name?: string;
  role?: EntityRole;
  colour?: string | null;
  icon?: string | null;
  is_abstract?: boolean;
  /** An explicit null takes the type out of its lineage. */
  inherited_from?: Id | null;
  updated_at?: string;
};

/** The server sends a type's own attributes and its ancestors' apart (queue R18); every screen
 * that asks "what does an entity of this type have" reads `attributes`, so they are joined here,
 * once -- own first, then nearest ancestor's -- and the own ones kept for the attribute editor. */
export function withInherited(type: EntityType & { inherited_attributes?: AttributeDef[] }): EntityType {
  if (!type || type.own_attributes || !Array.isArray(type.attributes)) return type;
  const { inherited_attributes: inherited, ...rest } = type;
  return { ...rest, own_attributes: type.attributes, attributes: [...type.attributes, ...(inherited ?? [])] };
}

export async function listEntityTypes(params: { domainId?: Id | null } & PageParams = {}): Promise<Page<EntityType>> {
  const { domainId, limit, offset, q } = params;
  const page = await apiFetch<Page<EntityType>>(`/api/v1/entity-types${query({ domain_id: domainId, q: q || undefined, limit, offset })}`);
  return page && Array.isArray(page.items) ? { ...page, items: page.items.map(withInherited) } : page;
}
export const getEntityType = async (id: Id) => withInherited(await apiFetch<EntityType>(`/api/v1/entity-types/${id}`));
export const createEntityType = async (body: EntityTypeCreate) =>
  withInherited(await send<EntityType>("POST", "/api/v1/entity-types", body));
export const updateEntityType = async (id: Id, body: EntityTypeUpdate) =>
  withInherited(await send<EntityType>("PATCH", `/api/v1/entity-types/${id}`, body));
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
  params: { entityTypeId?: Id | null; q?: string; expression?: ExpressionDocument | null; family?: boolean } & PageParams = {}
): Promise<Page<Entity>> {
  const { entityTypeId, q, expression, limit, offset, family } = params;
  return apiFetch(
    `/api/v1/entities${query({
      entity_type_id: entityTypeId,
      family: family ? "true" : undefined,
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
/** Several records at once, all or none (`POST /entities/delete`). */
export const deleteEntities = (ids: Id[]) => send<{ deleted: number }>("POST", "/api/v1/entities/delete", { ids });

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
  const { domainId, isHierarchy, limit, offset, q } = params;
  return apiFetch(`/api/v1/relationship-types${query({ domain_id: domainId, is_hierarchy: isHierarchy, q: q || undefined, limit, offset })}`);
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
  /** Migration 0068 (queue R20b): its values are entities of this type; absent or null: numbers. */
  value_type_id?: Id | null;
  /** How it was made when computed (from the map, from an answer); read-only. */
  source?: Record<string, unknown> | null;
};

export type ParameterDefCreate = {
  domain_id: Id;
  name: string;
  /** At least one. The same type may appear twice (`distance[location, location]`). */
  index_type_ids: Id[];
  default_value?: number;
  unit?: string | null;
  value_type_id?: Id | null;
};

/** `domain_id` is not patchable; `name`, `index_type_ids` and
 * `default_value` refuse an explicit null; re-indexing a parameter that
 * has stored cells is a 409. */
export type ParameterDefUpdate = Partial<Omit<ParameterDefCreate, "domain_id">>;

/** A number cell carries `value`; an entity-valued parameter's (queue R20b) `value_entity_id`,
 * null to clear it, and reads back its `value_key`. */
export type ParameterCell = {
  entity_ids: Id[];
  value?: number | null;
  value_entity_id?: Id | null;
  value_key?: string | null;
  updated_at?: string;
};

export type ParameterValues = {
  /** `name` is null when the index type was deleted after the parameter was defined. */
  index_types: { id: Id; name: string | null }[];
  /** Sparse: only cells whose value differs from the default are stored. */
  cells: ParameterCell[];
  default_value: number;
};

export function listParameters(params: { domainId?: Id | null } & PageParams = {}): Promise<Page<ParameterDef>> {
  const { domainId, limit, offset, q } = params;
  return apiFetch(`/api/v1/parameters${query({ domain_id: domainId, q: q || undefined, limit, offset })}`);
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
/** Queue R24: part of a plan held fixed -- a cell, a slice of an earlier run, or a horizon. */
export type Lock =
  | { var: string; index: string[]; value: number }
  | { var: string; where: Record<string, string[]>; from_run: number }
  | { before: string | number; attr: string; set: string; from_run: number; vars?: string[] };

export type ScenarioPatch = {
  disable?: string[];
  harden?: string[];
  soften?: Record<string, number>;
  lock?: Lock[];
  /** Queue R25: change as little as possible from an earlier run. */
  stay_close?: { from_run: number; mode?: "weighted" | "lex"; weight?: number; vars?: string[] };
  /** Data what-ifs (improvement plan 3.3), applied to a copy of the frozen data when solved. */
  remove?: Record<string, string[]>;
  set_param?: { param: string; index: string[]; value: number }[];
  scale_param?: Record<string, number>;
  set_attr?: { set: string; key: string; attr: string; value: unknown }[];
  /** A field of every record of a set (or of those the conditions keep) times a factor: demand +30%. */
  scale_attr?: { set: string; attr: string; factor: number; where?: { attr: string; op: string; value: unknown }[] }[];
  /** A rule's limit (the side of it that is one number), changed for this scenario. */
  set_limit?: Record<string, number>;
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
export type RunStatus =
  | "queued"
  | "running"
  | "optimal"
  | "feasible"
  | "infeasible"
  | "unbounded"
  | "unknown"
  | "error"
  | "cancelled";

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

/** What an answer may claim (migration 0028). `global`: proven the best of
 * all answers. `local`: the best among its neighbours -- a better one may
 * exist. `none`: an answer, with no claim to be the best. */
/** `approximate` (migration 0051): optimal to a tolerance, not proven -- PDLP. */
export type Optimality = "global" | "local" | "approximate" | "none";

export type RunSummary = {
  id: Id;
  scenario_id: Id;
  dataset_id: Id;
  status: RunStatus;
  /** Null when there is no answer to make a claim about. */
  optimality?: Optimality | null;
  solver: string;
  /** The run whose proven optimum answered this one without a solve
   * (migration 0042); absent or null for a run that was solved. */
  reused_from?: number | null;
  solver_version: string | null;
  compiler_version: string | null;
  objective: number | null;
  /** Migration 0029: no answer can beat this. Null when the solver has no bound. */
  best_bound?: number | null;
  /** How far the answer may be from the best, as a fraction; 0 when proven optimal. */
  gap?: number | null;
  wall_time_s: number | null;
  error: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Set when someone asked this run to stop. A queued run is already
   * `cancelled`; a running one is still `running` until the worker records it. */
  cancel_requested: boolean;
  /** Queue R26: a plan, or a question about another run (`why_not`) and its answer. */
  purpose?: "plan" | "why_not" | "shadow" | "suite";
  parent_run_id?: number | null;
  verdict?: Verdict | null;
  /** Runs this one made as its parts (alternative plans, a front's points), not listed as rows (F26). */
  part_runs?: number[];
};

/** A why-not probe's answer (queue R26). */
export type Verdict =
  | { kind: "already"; cells: WhyNotCell[] }
  | { kind: "blocked"; forced: string[]; conflict: ConflictItem[] | null; minimal: boolean | null; note?: string }
  | {
      kind: "possible"; proven: boolean; objective: number | null; delta: number | null; change: number | null;
      turned_on: string[][]; turned_off: string[][]; override?: WhatIfValue[];
    }
  | { kind: "unanswered"; status: string; error: string | null };

export type WhyNotCell = { var: string; index: string[]; value: number };
export type WhatIfValue = { param: string; index: string[]; value: number };

/** LP ranging at a proven optimum (queue R27): how far each number may move. */
export type RunRanges = {
  rows: { rule: string; index: Record<string, string>; rhs: number | null; dual: number; low: number | null; high: number | null }[];
  costs: { var: string; index: string[]; cost: number | null; low: number | null; high: number | null }[];
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
  /** What each rule means, in its author's words (`note` in the model
   * version the run solved). Only rules that carry one; absent from servers
   * before it was added. */
  rule_notes?: Record<string, string>;
  /** The trade-off front, when one was asked for: points in order of the
   * first term, each linked to its run; and the two terms' ids. */
  pareto?: ParetoPoint[] | null;
  pareto_terms?: string[] | null;
  /** The next-best distinct plans, when asked for (Epic engine E-1): best first, each linked to its run. */
  alternatives?: AlternativePlan[] | null;
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
  /** What a view is chosen from (queue R17): each decision's kind, each set's role, each set's
   * members in the dataset's order. Absent from servers before them. */
  variable_kinds?: Record<string, string>;
  set_roles?: Record<string, string>;
  set_order?: Record<string, string[]>;
  /** Each interval decision's start, end and presence decisions (queue R17b: what a Gantt draws). */
  intervals?: Record<string, { start?: string; end?: string; presence?: string }>;
  /** How much each whole-number or continuous decision took (migration 0065). Null for older runs. */
  amounts?: Record<string, { index: string[]; value: number }[]> | null;
  /** Queue R27: null for any run that is not a proven optimum of a linear program. */
  ranges?: RunRanges | null;
  constraints: ConstraintOutcome[];
};

export type RunRequest = {
  time_limit_s?: number;
  seed?: number;
  solver?: string | null;
  /** Ask for the trade-off front between the goal's two terms (migration 0045). */
  pareto_steps?: number;
  /** Solve the robust counterpart and report the price (app.solve.robust). */
  robust?: boolean;
  /** False to solve even when an identical run's answer could be reused. */
  reuse?: boolean;
  /** List this many next-best distinct plans (1-20), each within `alternatives_within` of the best. */
  alternatives?: number;
  alternatives_within?: number;
  /** Each plan differs from every other in at least this many decisions (1-50). */
  alternatives_min_changes?: number;
};

/** One next-best plan: its goal, how many yes-or-no decisions differ from the best, and its run. */
export type AlternativePlan = {
  seq: number;
  objective: number;
  changed: number;
  status: "optimal" | "feasible";
  run_id: number | null;
};

/** One point of a run's trade-off front, and the run that holds its answer. */
export type ParetoPoint = {
  seq: number;
  first: number;
  second: number;
  epsilon: number | null;
  status: "optimal" | "feasible";
  run_id: number | null;
};

/** An added solver's last conformance report (queue R43). */
export type SolverConformance = {
  passed: boolean;
  version: string;
  /** Whether it was run on the version installed now: a pass for another counts for nothing. */
  current: boolean;
  ran_at: string;
  ran_by: string | null;
  failed: string[];
  notes: string[];
};

export type SolverInfo = {
  name: string;
  available: boolean;
  classes: string[];
  note: string;
  /** Queue R41: a built-in, or added from a manifest. */
  origin?: "built-in" | "adapter";
  /** Whether the rules may choose it unasked. */
  automatic?: boolean;
  /** Whether the rules actually do choose it for a model it fits: never a local solver (operator trial F17). */
  chosen_unasked?: boolean;
  /** Queue R42: whether this organization has the licence it needs. */
  licence?: "not needed" | "set" | "missing";
  kind?: "ortools-engine" | "command-line" | "python";
  version?: string;
  proves?: "global" | "local" | "approximate";
  conformance?: SolverConformance | null;
};

export type SkippedAdapter = { folder: string; reason: string };

/** What this build can solve with. Hardcoding the list would offer a solver
 * a different build does not have. */
export const listSolvers = () => apiFetch<Page<SolverInfo> & { skipped?: SkippedAdapter[] }>("/api/v1/solvers");

export type SolverLicence = {
  adapter: string;
  required: boolean;
  /** The environment values its manifest takes, by name. */
  env: string[];
  /** Whether it takes a licence file. */
  file: boolean;
  set: boolean;
  fingerprint?: string;
  set_by?: string | null;
  set_at?: string;
};
export type SolverLicenceWrite = { env?: Record<string, string>; file?: string };
export type ConformanceCheck = { check: string; result: "pass" | "fail" | "skip" | "note"; detail: string };
export type ConformanceReport = { adapter: string; version: string; passed: boolean; checks: ConformanceCheck[] };

export const listSolverLicences = () => apiFetch<{ items: SolverLicence[] }>("/api/v1/solver-licences");
export const setSolverLicence = ({ adapter, licence }: { adapter: string; licence: SolverLicenceWrite }) =>
  send<{ adapter: string; set: boolean; fingerprint: string }>("PUT", `/api/v1/solver-licences/${adapter}`, licence);
export const removeSolverLicence = (adapter: string) => remove(`/api/v1/solver-licences/${adapter}`);
export const runConformance = (name: string) =>
  send<ConformanceReport>("POST", `/api/v1/solvers/${name}/conformance`, undefined);

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
  /** How the model splits (queue R4): blocks, and the rules that tie them. Null without the domain. */
  structure?: ModelStructure | null;
};

export type ModelStructure = {
  blocks: number;
  linking_rules: number;
  linking: string[];
  by: string | null;
  largest_share: number;
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

/** A credential for a program (migration 0035). The token itself is in
 * `ApiKeyCreated` only: the server never shows it again. */
export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  user_id: string;
  username: string;
  capabilities: string[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
};
export type ApiKeyCreated = ApiKey & { token: string };
export type ApiKeyCreate = { name: string; capabilities?: string[]; expires_in_days?: number | null };

export const listApiKeys = () => apiFetch<{ items: ApiKey[] }>("/api/v1/api-keys");
export const createApiKey = (body: ApiKeyCreate) => send<ApiKeyCreated>("POST", "/api/v1/api-keys", body);
export const revokeApiKey = (id: string) => remove(`/api/v1/api-keys/${id}`);

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

export function listRuns(params: { scenarioId?: Id | null; problemId?: Id | null } & PageParams = {}): Promise<Page<RunSummary>> {
  const { scenarioId, problemId, limit, offset, q } = params;
  return apiFetch(`/api/v1/runs${query({ scenario_id: scenarioId, problem_id: problemId, q: q || undefined, limit, offset })}`);
}
export const getRun = (id: Id) => apiFetch<Run>(`/api/v1/runs/${id}`);

/** A spatial run's answer as GeoJSON (GIS 7): one Feature per unit with its
 * group, or -- dissolved -- one per group with its cell count and totals. */
export type RunMapFeature = {
  type: "Feature";
  geometry: { type: "Polygon" | "MultiPolygon"; coordinates: unknown };
  properties: Record<string, unknown> & { group?: string | null; subgroup?: string | null };
};
/** `none`: why a run asked quietly has no map (operator trial F7). */
export type RunMap = { type: "FeatureCollection"; features: RunMapFeature[]; none?: string };
/** Where each member of each located set stood when a run was made (queue R17b): `{set: {key: [x, y]}}`. */
export type RunPlaces = Record<string, Record<string, [number, number]>>;
export const getRunPlaces = (id: Id) => apiFetch<RunPlaces>(`/api/v1/runs/${id}/places`);

export const getRunMap = (id: Id, dissolve = false, quiet = false) =>
  apiFetch<RunMap>(`/api/v1/runs/${id}/map${dissolve ? "?dissolve=true" : quiet ? "?quiet=true" : ""}`);

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
  /** When the two answers claim different things, what that means for their values (Epic UX, U-5). */
  claims?: string | null;
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
  optimality?: "global" | "local" | "approximate" | "none" | null;
  gap?: number | null;
  classified_as?: string | null;
};

/** One solver against a scenario's model (Epic UX, U-5): does it fit, would the rules choose it, and why. */
export type SolverFit = { name: string; fits: boolean; automatic: boolean; chosen: boolean; proves: string; why: string; note: string };
export type WorkerStatus = { state: "ready" | "busy" | "offline"; online: number; solving: number; queued: number; last_seen: string | null; says: string };
/** Records without a value the model reads as a number, with what a form needs to fill them in place. */
export type MissingGap = {
  set: string; attribute: string; attribute_id: Id | null; entity_type_id: Id | null;
  data_type: string | null; enum_values: string[] | null; default_value: unknown;
  records: { id: Id; key: string; label: string | null; updated_at: string }[];
};
export type PreflightFinding = {
  kind: "blocker" | "warning"; code: string; says: string; rules?: string[]; set?: string;
  /** `newer_version`: the latest published version, which the scenario can be moved to. */
  latest_version?: number; latest_version_id?: Id;
  /** `missing_values`: the records to fill in. */
  missing?: MissingGap;
};
export type Preflight = {
  scenario_id: Id; version: number; ready: boolean; findings: PreflightFinding[]; model_class: string;
  planner: string[]; solvers: SolverFit[]; workers: WorkerStatus;
};
export const getWorkers = () => apiFetch<WorkerStatus>("/api/v1/workers");
/** Online workers, runs solving and queued (operator trial F16): followed every 15 s. */
export function useWorkers() {
  return useQuery({ queryKey: [V1, "workers"], queryFn: getWorkers, refetchInterval: 15_000 });
}
export const getPreflight = (scenarioId: Id) => apiFetch<Preflight>(`/api/v1/scenarios/${scenarioId}/preflight`);
export function usePreflight(scenarioId: Id | null) {
  return useQuery({ queryKey: [V1, "preflight", scenarioId], queryFn: () => getPreflight(scenarioId as Id), enabled: isId(scenarioId),
    // The data and the workers move under it; a planner looking at the page sees them move.
    refetchInterval: 30_000 });
}

/** Where a problem stands, step by step (simplification plan, phase 1). */
export type Readiness = {
  problem: { id: Id; domain_id: Id; name: string };
  latest_version: { id: Id; version: number; created_at: string } | null;
  draft: { revision: number; updated_at: string; unpublished: boolean } | null;
  check: { ready: boolean; findings: PreflightFinding[]; model_class: string; sets: Record<string, number> } | null;
  base_scenario: { id: Id; version: number } | null;
  last_run: {
    id: Id; status: RunStatus; optimality: string | null; objective: number | null;
    queued_at: string; finished_at: string | null; scenario_id: Id; scenario: string;
  } | null;
  workers: WorkerStatus;
};
export const getReadiness = (problemId: Id) => apiFetch<Readiness>(`/api/v1/problems/${problemId}/readiness`);
export function useReadiness(problemId: Id | null) {
  return useQuery({ queryKey: [V1, "readiness", problemId], queryFn: () => getReadiness(problemId as Id), enabled: isId(problemId),
    // A run settles, a worker comes and goes: the page follows.
    refetchInterval: 10_000 });
}
/** Solve the latest published version on the problem's "Base" scenario, made or moved forward first. */
export const solveProblem = (problemId: Id, timeLimitS?: number) =>
  send<Run>("POST", `/api/v1/problems/${problemId}/solve`, timeLimitS ? { time_limit_s: timeLimitS } : {});
/** Publish the caller's draft as the next version. */
export const publishDraft = (problemId: Id, expectedRevision: number, note: string) =>
  send<ModelVersionSummary>("POST", `/api/v1/problems/${problemId}/draft/publish`, { expected_revision: expectedRevision, note });

export const compareRuns = (left: Id, right: Id) =>
  apiFetch<RunComparison>(`/api/v1/runs/${left}/compare/${right}`);
export const createRun = (scenarioId: Id, body: RunRequest = {}) =>
  send<Run>("POST", `/api/v1/scenarios/${scenarioId}/runs`, body);
export const cancelRun = (id: Id) => send<Run>("POST", `/api/v1/runs/${id}/cancel`, {});

export function listVersions(problemId: Id, params: PageParams = {}): Promise<Page<ModelVersionSummary>> {
  return apiFetch(`/api/v1/problems/${problemId}/versions${query({ q: params.q || undefined, limit: params.limit, offset: params.offset })}`);
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
// --- starting a problem (simplification plan, phase 3) ---------------------

/** A problem with a name and nothing else: its model is built next. */
export const createProblem = (body: { domain_id: Id; name: string }) =>
  send<{ id: Id; domain_id: Id; name: string }>("POST", "/api/problem/", body);

export type SheetField = { column: string; name: string; data_type: AttrType; enum_values: string[] | null; samples: string[]; skip: boolean };
export type SheetLink = { column: string; name: string; to: string; skip: boolean };
/** Where a sheet's rows are (improvement plan 1.2): a longitude + latitude pair, or a WKT column. */
export type SheetLocation = { name: string; lon: string | null; lat: string | null; wkt: string | null; skip: boolean };
export type SheetKind = { sheet: string; name: string; key: string | null; rows: number; exists: boolean; fields: SheetField[]; links: SheetLink[]; location?: SheetLocation | null; skip: boolean };
export type SheetProposal = { kinds: SheetKind[] };
export type SheetImported = { made: { kinds: number; fields: number; records: number; link_types: number; links: number } };

function upload(file: File, extra: Record<string, string> = {}): FormData {
  const form = new FormData();
  form.append("file", file);
  Object.entries(extra).forEach(([key, value]) => form.append(key, value));
  return form;
}
/** What a workbook would make: a kind of record per sheet, a field per column, links between sheets. */
export const proposeSpreadsheet = (domainId: Id, file: File) =>
  apiFetch<SheetProposal>(`/api/v1/domains/${domainId}/spreadsheet/propose`, { method: "POST", body: upload(file) });
/** Make it, as the (edited) proposal says. */
export const importSpreadsheet = (domainId: Id, file: File, proposal: SheetProposal) =>
  apiFetch<SheetImported>(`/api/v1/domains/${domainId}/spreadsheet/import`,
    { method: "POST", body: upload(file, { proposal: JSON.stringify(proposal) }) });

export const getVersion = (id: Id) => apiFetch<ModelVersion>(`/api/v1/versions/${id}`);

export function listScenarios(
  params: { problemId?: Id | null; modelVersionId?: Id | null } & PageParams = {}
): Promise<Page<Scenario>> {
  const { problemId, modelVersionId, limit, offset, q } = params;
  return apiFetch(`/api/v1/scenarios${query({ problem_id: problemId, model_version_id: modelVersionId, q: q || undefined, limit, offset })}`);
}
export const getScenario = (id: Id) => apiFetch<Scenario>(`/api/v1/scenarios/${id}`);
/** Ask why a plan is not otherwise (queue R26): a probe to poll, or the verdict at once. */
export const askWhyNot = ({ runId, force, override }: { runId: Id; force: WhyNotCell[]; override?: WhatIfValue[] }) =>
  send<{ run_id: number | null; verdict: Verdict | null }>("POST", `/api/v1/runs/${runId}/why-not`, { force, override: override ?? [] });
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

/** Resolve explicit context independently of the paginated domain picker. */
export function useDomainDetail(id: number | null) {
  return useQuery({
    queryKey: ["entities", "public", "domain", id],
    queryFn: () => apiFetch<Domain>(`/api/domain/${id}`),
    enabled: id !== null,
  });
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
  params: { q?: string; expression?: ExpressionDocument | null; family?: boolean } & PageParams = {}
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
/** One relationship that nests a record's kind inside itself (`app/api/hierarchies.py`). */
export type TreeNode = { id: Id; key: string; label: string | null; entity_type_id: Id; depth: number; parent_id?: Id };
export type EntityTree = {
  relationship_type_id: Id;
  name: string;
  is_hierarchy: boolean;
  /** Set when the relationship is a reference attribute's mirror: the attribute names the parent. */
  via_attribute: string | null;
  /** Nearest first. */
  ancestors: TreeNode[];
  descendants: TreeNode[];
  loop: boolean;
  truncated: boolean;
  /** Keys this record may not take as its parent: itself and everything below it. */
  blocked: string[];
};
export const getEntityTrees = (id: Id) => apiFetch<{ entity_id: Id; trees: EntityTree[] }>(`/api/v1/entities/${id}/trees`);
export function useEntityTrees(id: Id | null | undefined) {
  return useQuery({ queryKey: [V1, "entity-trees", id], queryFn: () => getEntityTrees(id as Id), enabled: isId(id) });
}
/** Records naming this one in a reference field (`app/api/referrers.py`). */
export type ReferrerField = {
  kind: string;
  attribute: string;
  /** A required reference refuses the delete; an optional one is cleared by it. */
  required: boolean;
  count: number;
  records: { id: Id; key: string; label: string | null }[];
};
export function useEntityReferrers(id: Id | null | undefined) {
  return useQuery({
    queryKey: [V1, "entity-referrers", id],
    queryFn: () => apiFetch<{ entity_id: Id; fields: ReferrerField[]; blocks_delete: boolean }>(`/api/v1/entities/${id}/referrers`),
    enabled: isId(id),
  });
}
export const useCreateEntity = () => useV1Mutation(createEntity);
export const useUpdateEntity = () =>
  useV1Mutation(({ id, body }: { id: Id; body: EntityUpdate }) => updateEntity(id, body));
export const useDeleteEntity = () => useV1Mutation(deleteEntity);
export const useDeleteEntities = () => useV1Mutation(deleteEntities);

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
/** The most entities one list request returns; a kind with this many is searched, not listed. */
export const ENTITY_PAGE = MAX_PAGE;

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

/** Distances and nearness from the map (queue R16a): what the platform computed, and how. */
export type ComputedSource = {
  /** distance / within from the map; other kinds (too_close, inside, count_within, elevation...) carry their own fields. */
  kind: "distance" | "within" | (string & {});
  metric: string;
  from: string;
  to: string;
  unit?: "m" | "km" | "s" | "min";
  max_min?: number;
  no_road?: number;
  off_road?: string[];
  /** Places further than the join limit from the lines layer, as "key (metres)". */
  off_network?: string[];
  nearest?: number;
  far?: number;
  max_m?: number;
  pairs?: number;
  edges?: number;
  missing?: string[];
  computed_at: string;
};
export type Metric = "straight" | "road" | "time" | "network" | "network_time";
/** A lines layer of imported map data to travel along (improvement plan 2.9). */
export type NetworkSource = { dataset_id: number; layer: string; speed_field?: string; default_kmh?: number; join_m?: number };
export type DistancesBody = { name: string; from_type_id: Id; to_type_id: Id; metric: Metric; unit: "m" | "km" | "s" | "min"; nearest?: number; network?: NetworkSource };
export type WithinBody = { name: string; from_type_id: Id; to_type_id: Id; metric: Metric; max_m?: number; max_min?: number; network?: NetworkSource; output?: "relationship" | "parameter" };
export const computeDistances = ({ domainId, ...body }: DistancesBody & { domainId: Id }) =>
  send<{ parameter_id: Id; pairs: number; missing: string[]; source: ComputedSource }>(
    "POST", `/api/v1/domains/${domainId}/distances`, body);
export const computeWithin = ({ domainId, ...body }: WithinBody & { domainId: Id }) =>
  send<{ relationship_type_id: Id; edges: number; missing: string[]; source: ComputedSource }>(
    "POST", `/api/v1/domains/${domainId}/within`, body);
export const useComputeDistances = () => useV1Mutation(computeDistances);

// The other "From the map" operations (improvement plan, phase 2): each writes a link, a field or a parameter.
export type SpatialOp = "inside" | "count" | "nearest" | "touching" | "overlap" | "elevation";
export type SpatialOpBody =
  | { op: "inside" | "overlap"; name: string; from_type_id: Id; to_type_id: Id }
  | { op: "count"; name: string; from_type_id: Id; to_type_id: Id; max_m: number }
  | { op: "nearest"; name: string; from_type_id: Id; to_type_id: Id; k: number }
  | { op: "touching" | "elevation"; name: string; type_id: Id };
export type SpatialOpReport = {
  relationship_type_id?: Id; parameter_id?: Id; field?: string; links?: number; pairs?: number; records?: number;
  with_any?: number; outside?: string[]; missing: string[]; uncovered?: string[]; slope_field?: string;
};
export const computeSpatial = ({ domainId, op, ...body }: SpatialOpBody & { domainId: Id }) =>
  send<SpatialOpReport>("POST", `/api/v1/domains/${domainId}/spatial/${op}`, body);
export const useComputeSpatial = () => useV1Mutation(computeSpatial);
export const useComputeWithin = () => useV1Mutation(computeWithin);
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
/** A template can make a domain, so the domain lists (sidebar, chooser) are refreshed too (F2). */
export function useApplyTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: Id; body: ApplyTemplateRequest }) => applyTemplate(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [V1] });
      void queryClient.invalidateQueries({ queryKey: ["entities"] });
    },
  });
}

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

export function useApiKeys() {
  return useQuery({ queryKey: [V1, "api-keys"], queryFn: listApiKeys });
}
export const useCreateApiKey = () => useV1Mutation(createApiKey);
export const useRevokeApiKey = () => useV1Mutation(revokeApiKey);

export function useSolvers() {
  return useQuery({ queryKey: [V1, "solvers"], queryFn: listSolvers, staleTime: 5 * 60 * 1000 });
}

export type QueueOrgRow = { org: string; depth: number; running: number; oldestWaitSeconds: number };

/** Parse Prometheus text exposition into per-org queue gauges (R33 / OPS01). */
export function parseQueueMetrics(text: string): QueueOrgRow[] {
  const depth = new Map<string, number>();
  const running = new Map<string, number>();
  const wait = new Map<string, number>();
  for (const line of text.split("\n")) {
    if (!line || line.startsWith("#")) continue;
    const m = /^(queue_depth|runs_running|queue_oldest_wait_seconds)\{org="([^"]*)"\}\s+(\S+)/.exec(line);
    if (!m) continue;
    const [, name, org, raw] = m;
    const value = Number(raw);
    if (!Number.isFinite(value)) continue;
    if (name === "queue_depth") depth.set(org, value);
    else if (name === "runs_running") running.set(org, value);
    else wait.set(org, value);
  }
  const orgs = new Set([...depth.keys(), ...running.keys(), ...wait.keys()]);
  return [...orgs]
    .sort()
    .map((org) => ({
      org,
      depth: depth.get(org) ?? 0,
      running: running.get(org) ?? 0,
      oldestWaitSeconds: wait.get(org) ?? 0,
    }));
}

export const fetchMetricsText = () => apiText("/api/v1/metrics");

export function useQueueMetrics() {
  return useQuery({
    queryKey: [V1, "metrics", "queue"],
    queryFn: async () => parseQueueMetrics(await fetchMetricsText()),
    refetchInterval: 10_000,
  });
}

export type AuditEvent = {
  id: number;
  at: string | null;
  organization_id: string;
  actor_id: string | null;
  /** The account's username, or the API key's name (operator trial F30). */
  actor?: string | null;
  api_key_name?: string | null;
  api_key_id: string | null;
  action: string;
  object_type: string | null;
  object_id: string | null;
  before_hash: string | null;
  after_hash: string | null;
  ip: string | null;
};

export const listAudit = (params: { limit?: number; offset?: number; action?: string } = {}) => {
  const q = new URLSearchParams();
  if (params.limit != null) q.set("limit", String(params.limit));
  if (params.offset != null) q.set("offset", String(params.offset));
  if (params.action) q.set("action", params.action);
  const qs = q.toString();
  return apiFetch<Page<AuditEvent>>(`/api/v1/audit${qs ? `?${qs}` : ""}`);
};

export function useAudit(params: { limit?: number; offset?: number; action?: string } = {}) {
  return useQuery({
    queryKey: [V1, "audit", params],
    queryFn: () => listAudit(params),
  });
}

export type BackupStatus = {
  root: string;
  reachable: boolean;
  rpo_hours: number;
  rto_hours: number;
  latest: Record<string, string> | null;
  dumps: string[];
  dump_count: number;
  wal_present: boolean;
  runbook: string;
};

export const fetchBackupStatus = () => apiFetch<BackupStatus>("/api/v1/backups");

export function useBackupStatus() {
  return useQuery({ queryKey: [V1, "backups"], queryFn: fetchBackupStatus, staleTime: 30_000 });
}

export function useSolverLicences() {
  return useQuery({ queryKey: [V1, "solver-licences"], queryFn: listSolverLicences });
}
export const useSetSolverLicence = () => useV1Mutation(setSolverLicence);
export const useRemoveSolverLicence = () => useV1Mutation(removeSolverLicence);
export const useRunConformance = () => useV1Mutation(runConformance);

/** What publishing `ir` would say, without publishing it (Blocks 4). */
export const validateVersion = (problemId: Id, ir: Record<string, unknown>) =>
  send<{ ok: true }>("POST", `/api/v1/problems/${problemId}/versions/validate`, { ir });

/** The domain's check of a draft, asked once it has been still for half a second; `ir` null asks nothing. */
export function useValidateVersion(problemId: Id | null | undefined, ir: Record<string, unknown> | null) {
  const text = useDebouncedValue(ir === null ? null : JSON.stringify(ir), 500);
  return useQuery({
    queryKey: [V1, "validate-version", problemId, text],
    queryFn: () => validateVersion(problemId as Id, JSON.parse(text as string) as Record<string, unknown>),
    enabled: isId(problemId) && text !== null,
    retry: false,
    staleTime: 30_000,
  });
}

/** A 422 from publish or validate as the refusal it names: where in the IR, and why. Anything else is null. */
export function irRefusalOf(error: unknown): { loc: (string | number)[]; message: string } | null {
  const first = validationErrors(error)[0];
  if (!first) return null;
  const loc = first.loc[0] === "body" ? first.loc.slice(1) : first.loc;
  return { loc: loc[0] === "ir" ? loc.slice(1) : loc, message: first.msg };
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
/** Whether a problem has any run yet, over all its scenarios (operator trial F10). */
export function useProblemRuns(problemId: Id | null) {
  return useQuery({
    queryKey: [V1, "runs", { problemId, limit: 1 }],
    queryFn: () => listRuns({ problemId, limit: 1, offset: 0 }),
    enabled: isId(problemId),
  });
}
/** Runs over every scenario of a problem, newest first: what a run can be compared with. */
export function useProblemRunList(problemId: Id | null, page: PageParams = {}) {
  return useQuery({
    queryKey: [V1, "runs", { problemId, ...page }],
    queryFn: () => listRuns({ problemId, ...page }),
    enabled: isId(problemId),
  });
}
export const useAskWhyNot = () => useV1Mutation(askWhyNot);

/** Where a version stands against its problem's acceptance cases (queue R30 / R32). */
export type VersionChecks = {
  model_version_id: number;
  state: "no cases" | "unchecked" | "checking" | "failed" | "passed";
  cases: {
    case_id: number;
    name: string;
    run_id: number | null;
    state: "unchecked" | "checking" | "failed" | "passed";
    reasons: string[];
    nightly_regressed?: boolean;
  }[];
};
export const getVersionChecks = (id: Id) => apiFetch<VersionChecks>(`/api/v1/model-versions/${id}/checks`);
export const checkVersion = (id: Id) => send<VersionChecks & { run_ids: number[] }>("POST", `/api/v1/model-versions/${id}/check`, {});
export function useVersionChecks(id: Id | null | undefined) {
  return useQuery({
    queryKey: [V1, "version-checks", id],
    queryFn: () => getVersionChecks(id as Id),
    enabled: isId(id),
    refetchInterval: (query) => ((query.state.data as VersionChecks | undefined)?.state === "checking" ? 1500 : false),
  });
}
export const useCheckVersion = () => useV1Mutation(checkVersion);

export type ShadowReport = {
  problem_id: number;
  candidates: {
    model_version_id: number;
    runs: number;
    compared: number;
    at_least_as_good: number;
    share_at_least_as_good: number | null;
    median_time_ratio: number | null;
    worst: Record<string, unknown> | null;
    recent: {
      real_run: number;
      shadow_run: number;
      status: string;
      verdict: { delta?: number; at_least_as_good?: boolean } | null;
    }[];
  }[];
};
export const getShadowReport = (problemId: Id) =>
  apiFetch<ShadowReport>(`/api/v1/problems/${problemId}/shadow`);
export function useShadowReport(problemId: Id | null | undefined) {
  return useQuery({
    queryKey: [V1, "shadow", problemId],
    queryFn: () => getShadowReport(problemId as Id),
    enabled: isId(problemId),
  });
}

export const gateOverride = ({ versionId, reason }: { versionId: Id; reason: string }) =>
  send<{ model_version_id: number; reason: string; overridden: boolean }>(
    "POST",
    `/api/v1/model-versions/${versionId}/gate-override`,
    { reason },
  );
export const useGateOverride = () => useV1Mutation(gateOverride);

/** A why-not probe, polled until its verdict is written (just after the run settles). */
export function useProbe(id: Id | null | undefined) {
  return useQuery({
    queryKey: [V1, "run", id],
    queryFn: () => getRun(id as Id),
    enabled: isId(id),
    refetchInterval: (query) => ((query.state.data as Run | undefined)?.verdict ? false : 1000),
  });
}

/** How long a run is expected to take (Epic ML): an estimate from this
 * organization's settled runs, or the reason there is none yet. */
export type RunEta = {
  run_id: number;
  settled: boolean;
  seconds?: number | null;
  elapsed_seconds?: number | null;
  estimate_seconds: number | null;
  low_seconds?: number;
  high_seconds?: number;
  based_on_runs?: number;
  reason?: string;
};
export const getRunEta = (id: Id) => apiFetch<RunEta>(`/api/v1/runs/${id}/eta`);

/** Asked while the run is unfinished; the estimate changes once it compiles. */
export function useRunEta(id: Id | null | undefined, live: boolean) {
  return useQuery({
    queryKey: [V1, "run-eta", id],
    queryFn: () => getRunEta(id as Id),
    enabled: isId(id) && live,
    refetchInterval: live ? 5000 : false,
    retry: false,
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

/** Business acceptance of an immutable run (OAAS Phase 5). */
export type ApprovedPlan = {
  id: Id;
  run_id: Id;
  problem_id: Id;
  reason: string;
  approved_by: string | null;
  approved_at: string;
  effective_from: string | null;
  effective_to: string | null;
  superseded_by: Id | null;
};

export type ApproveBody = {
  reason: string;
  effective_from?: string | null;
  effective_to?: string | null;
};

export const approveRun = (runId: Id, body: ApproveBody) =>
  send<ApprovedPlan>("POST", `/api/v1/runs/${runId}/approve`, body);

export const listProblemApprovals = (problemId: Id, currentOnly = true) =>
  apiFetch<ApprovedPlan[]>(
    `/api/v1/problems/${problemId}/approvals${query({ current_only: currentOnly })}`
  );

export function useProblemApprovals(problemId: Id | null | undefined, currentOnly = true) {
  return useQuery({
    queryKey: [V1, "approvals", problemId, currentOnly],
    queryFn: () => listProblemApprovals(problemId as Id, currentOnly),
    enabled: isId(problemId),
  });
}

export const useApproveRun = () =>
  useV1Mutation(({ runId, body }: { runId: Id; body: ApproveBody }) => approveRun(runId, body));

export type AmountsPage = {
  run_id: Id;
  variable: string | null;
  offset: number;
  limit: number;
  total: number;
  chunked: boolean;
  items: { variable: string; index: string[]; value: number }[];
};

export const getRunAmounts = (
  runId: Id,
  params: { variable?: string; offset?: number; limit?: number } = {}
) =>
  apiFetch<AmountsPage>(
    `/api/v1/runs/${runId}/amounts${query({
      variable: params.variable,
      offset: params.offset,
      limit: params.limit,
    })}`
  );

export function useRunAmounts(
  runId: Id | null | undefined,
  params: { variable?: string; offset?: number; limit?: number } = {}
) {
  return useQuery({
    queryKey: [V1, "run-amounts", runId, params],
    queryFn: () => getRunAmounts(runId as Id, params),
    enabled: isId(runId),
  });
}

// --- grids (spatial, GIS 3) -------------------------------------------------

export type GridRequest = {
  boundary_entity_id?: Id | null;
  boundary?: Record<string, unknown> | null;
  shape: "square" | "hex";
  size_m: number;
  entity_type: string;
  keep?: "centre" | "overlap";
  layers?: Record<string, unknown>[];
  replace?: boolean;
  /** Each cell's mean elevation and slope from the terrain tiles (GIS 10). */
  elevation?: boolean;
};

export type GridReport = {
  entity_type_id: Id;
  relationship_type_id: Id;
  cells: number;
  edges: number;
  dropped: number;
  layer_totals: Record<string, number>;
  layer_outside: Record<string, number>;
  elevation_missing?: number;
  elevation_range?: [number, number] | null;
};

export const makeGrid = (domainId: Id, body: GridRequest) =>
  send<GridReport>("POST", `/api/v1/domains/${domainId}/grids`, body);
export const useMakeGrid = () =>
  useV1Mutation(({ domainId, body }: { domainId: Id; body: GridRequest }) => makeGrid(domainId, body));

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

// predictors (Epic ML): trained models a domain holds, read by the IR's `predict` term

export type PredictorMetrics = {
  rows?: number;
  rows_skipped?: number;
  holdout_rows?: number;
  evaluated_on?: string;
  r2?: number | null;
  mae?: number | null;
  rmse?: number | null;
  /** Random forests: how often held-out values fell inside the trees' 10th-90th percentile. */
  interval?: string;
  interval_coverage?: number | null;
  /** Yes-or-no models: which value counts as yes, and how well it is told apart. */
  positive?: string;
  negative?: string;
  predicts?: string;
  accuracy?: number | null;
  auc?: number | null;
  brier?: number | null;
};

export type Predictor = {
  id: Id;
  domain_id: Id;
  name: string;
  note: string | null;
  /** The model's inputs, in order: what `predict name(...)` passes. */
  inputs: string[];
  metrics: PredictorMetrics | null;
  /** How it was trained, or null for an uploaded model. */
  training: {
    kind?: string; entity_type?: string; features?: string[]; target?: string; trees?: number; max_depth?: number; positive?: string;
  } | null;
  summary: { inputs?: number; trees?: number; nodes?: number; leaves?: number; aggregation?: string } | null;
  created_at: string;
  updated_at: string;
};

export type PredictorTrain = {
  domain_id: number;
  name: string;
  note?: string | null;
  entity_type: string;
  features: string[];
  target: string;
  kind: "random_forest" | "gradient_boosting" | "random_forest_classifier";
  /** Yes-or-no models: the target value that counts as yes. */
  positive?: string;
  trees?: number;
  max_depth?: number;
  replace?: boolean;
};

export const listPredictors = (domainId: Id) =>
  apiFetch<Page<Predictor>>(`/api/v1/predictors?domain_id=${domainId}&limit=200`);
/** Training goes on after the answer (operator trial F31): ask after it with `usePredictorTraining`. */
export const trainPredictor = (body: PredictorTrain) =>
  send<{ training_id: number; state: "running" }>("POST", "/api/v1/predictors/train?background=true", body);
export type PredictorTraining = {
  id: number; domain_id: number; state: "running" | "done" | "failed"; predictor_id: number | null;
  error: string | null; seconds: number; request: { name: string; entity_type: string; target: string; kind: string };
};
export const getPredictorTraining = (id: Id) => apiFetch<PredictorTraining>(`/api/v1/predictor-trainings/${id}`);
export const uploadPredictor = (body: { domain_id: number; name: string; note?: string | null; model: unknown }) =>
  send<Predictor>("POST", "/api/v1/predictors", body);
export const deletePredictor = (id: Id) => remove(`/api/v1/predictors/${id}`);
export const predictWith = (id: Id, inputs: number[][]) =>
  send<{ predictions: number[]; ranges?: { low: number; high: number }[] }>("POST", `/api/v1/predictors/${id}/predict`, { inputs });

/** Keep a trained predictor's predictions in a number field of its records (a forecast as data). */
export const applyPredictor = (id: Id, body: { field: string; only_missing: boolean }) =>
  send<{ field: string; entity_type: string; written: number; skipped: string[]; skipped_count: number }>(
    "POST", `/api/v1/predictors/${id}/apply`, body);
export const useApplyPredictor = () =>
  useV1Mutation(({ id, body }: { id: Id; body: { field: string; only_missing: boolean } }) => applyPredictor(id, body));
/** Number fields made from a date, a text or a linked record's number (`app/api/derive.py`). */
export type DeriveBody = { op: "date_parts" | "categories" | "from_link" | "formula"; field: string; of?: string; formula?: string };
export const deriveFields = (entityTypeId: Id, body: DeriveBody) =>
  send<{ made: string[]; records: number; left_empty: number; empty?: string[] }>("POST", `/api/v1/entity-types/${entityTypeId}/derive`, body);
export const useDeriveFields = () =>
  useV1Mutation(({ entityTypeId, body }: { entityTypeId: Id; body: DeriveBody }) => deriveFields(entityTypeId, body));

export function usePredictors(domainId: Id | null) {
  return useQuery({
    queryKey: [V1, "predictors", domainId],
    queryFn: () => listPredictors(domainId!),
    enabled: domainId !== null,
  });
}
export const useTrainPredictor = () => useV1Mutation(trainPredictor);
/** Asked every second while it runs; the predictors list is asked again once it is done. */
export function usePredictorTraining(id: Id | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: [V1, "predictor-training", id],
    queryFn: async () => {
      const training = await getPredictorTraining(id as Id);
      if (training.state === "done") void client.invalidateQueries({ queryKey: [V1, "predictors"] });
      return training;
    },
    enabled: isId(id),
    refetchInterval: (query) => ((query.state.data as PredictorTraining | undefined)?.state === "running" || !query.state.data ? 1000 : false),
  });
}
export const useUploadPredictor = () => useV1Mutation(uploadPredictor);
export const useDeletePredictor = () => useV1Mutation(deletePredictor);

/** Where a person put the cards of a problem's graph, kept on the server so
 * it follows them to another browser. Presentation only: never in the IR. */
export type GraphLayout = { positions: Record<string, { x: number; y: number }>; updated_at: string | null };
export const getGraphLayout = (problemId: Id) => apiFetch<GraphLayout>(`/api/v1/problems/${problemId}/graph-layout`);
export const saveGraphLayout = (problemId: Id, positions: GraphLayout["positions"]) =>
  send<GraphLayout>("PUT", `/api/v1/problems/${problemId}/graph-layout`, { positions });

// --- people and roles (UX audit A-1) ---------------------------------------

export type PersonRole = { id: string; code: string; name: string };
export type Person = { id: string; username: string; display_name: string | null; email: string | null; is_active: boolean; roles: PersonRole[] };
export type RoleSummary = PersonRole & { capabilities: string[]; users: number };
export type People = { users: Person[]; roles: RoleSummary[] };

export function usePeople() {
  return useQuery({ queryKey: [V1, "people"], queryFn: () => apiFetch<People>("/api/v1/people") });
}
export const setPersonRoles = (userId: string, roleIds: string[]) =>
  send<Person>("PUT", `/api/v1/people/${userId}/roles`, { role_ids: roleIds });
export const setPersonActive = (userId: string, isActive: boolean) =>
  send<Person>("PATCH", `/api/v1/people/${userId}`, { is_active: isActive });
