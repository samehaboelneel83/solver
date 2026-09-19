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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  entity_type_id: Id;
  name: string;
  data_type: AttrType;
  required: boolean;
  unit: string | null;
  enum_values: string[] | null;
  default_value: unknown;
};

export type AttributeDefCreate = {
  name: string;
  data_type: AttrType;
  required?: boolean;
  unit?: string | null;
  enum_values?: string[] | null;
  default_value?: unknown;
};

/** An explicit `null` is meaningful (it clears `enum_values`, `unit`,
 * `default_value`); an omitted key leaves the field unchanged. */
export type AttributeDefUpdate = Partial<AttributeDefCreate>;

export type EntityType = {
  id: Id;
  domain_id: Id;
  name: string;
  role: EntityRole;
  /** Ordered by name. Carried on the list route too. */
  attributes: AttributeDef[];
};

export type EntityTypeCreate = { domain_id: Id; name: string; role?: EntityRole };
export type EntityTypeUpdate = { name?: string; role?: EntityRole };

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
export const updateAttribute = (id: Id, body: AttributeDefUpdate) =>
  send<AttributeDef>("PATCH", `/api/v1/attributes/${id}`, body);
export const deleteAttribute = (id: Id) => remove(`/api/v1/attributes/${id}`);

// --- entities (Task 6) ------------------------------------------------------

export type Entity = {
  id: Id;
  entity_type_id: Id;
  key: string;
  label: string | null;
  sort_order: number;
  active: boolean;
  attrs: Record<string, unknown>;
};

export type EntityCreate = {
  entity_type_id: Id;
  key: string;
  label?: string | null;
  sort_order?: number;
  active?: boolean;
  attrs?: Record<string, unknown>;
};

/** `entity_type_id` is not patchable. `attrs` replaces the whole object. */
export type EntityUpdate = Partial<Omit<EntityCreate, "entity_type_id">>;

/** Ordered by `sort_order`, then `key`. `q` matches key or label. */
export function listEntities(
  params: { entityTypeId?: Id | null; q?: string } & PageParams = {}
): Promise<Page<Entity>> {
  const { entityTypeId, q, limit, offset } = params;
  return apiFetch(`/api/v1/entities${query({ entity_type_id: entityTypeId, q, limit, offset })}`);
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
};

export type RelationshipTypeCreate = {
  domain_id: Id;
  name: string;
  from_type_id: Id;
  to_type_id: Id;
  cardinality?: Cardinality;
  is_hierarchy?: boolean;
};

/** `domain_id` is not patchable. */
export type RelationshipTypeUpdate = Partial<Omit<RelationshipTypeCreate, "domain_id">>;

export type Relationship = {
  id: Id;
  relationship_type_id: Id;
  from_entity_id: Id;
  to_entity_id: Id;
  attrs: Record<string, unknown>;
  /** ISO dates (`YYYY-MM-DD`). */
  valid_from: string | null;
  valid_to: string | null;
};

export type RelationshipCreate = {
  relationship_type_id: Id;
  from_entity_id: Id;
  to_entity_id: Id;
  attrs?: Record<string, unknown>;
  valid_from?: string | null;
  valid_to?: string | null;
};

/** Re-typing an edge is delete + create; re-pointing it is a PATCH. */
export type RelationshipUpdate = Partial<Omit<RelationshipCreate, "relationship_type_id">>;

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
  /** At least one, no duplicates (a temporary restriction -- see the 422's message). */
  index_type_ids: Id[];
  default_value?: number;
  unit?: string | null;
};

/** `domain_id` is not patchable; `name`, `index_type_ids` and
 * `default_value` refuse an explicit null; re-indexing a parameter that
 * has stored cells is a 409. */
export type ParameterDefUpdate = Partial<Omit<ParameterDefCreate, "domain_id">>;

export type ParameterCell = { entity_ids: Id[]; value: number };

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

export function listVersions(problemId: Id, params: PageParams = {}): Promise<Page<ModelVersionSummary>> {
  return apiFetch(`/api/v1/problems/${problemId}/versions${query({ limit: params.limit, offset: params.offset })}`);
}
export const createVersion = (problemId: Id, body: ModelVersionCreate) =>
  send<ModelVersion>("POST", `/api/v1/problems/${problemId}/versions`, body);
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
export function useEntityTypes(domainId: Id | null, page: PageParams = {}) {
  return useQuery({
    queryKey: [V1, "entity-types", { domainId, ...page }],
    queryFn: () => listEntityTypes({ domainId, ...page }),
    enabled: isId(domainId),
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
export const useUpdateAttribute = () =>
  useV1Mutation(({ id, body }: { id: Id; body: AttributeDefUpdate }) => updateAttribute(id, body));
export const useDeleteAttribute = () => useV1Mutation(deleteAttribute);

// entities
export function useEntities(entityTypeId: Id | null, params: { q?: string } & PageParams = {}) {
  return useQuery({
    queryKey: [V1, "entities", { entityTypeId, ...params }],
    queryFn: () => listEntities({ entityTypeId, ...params }),
    enabled: isId(entityTypeId),
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
export function useRelationshipTypes(domainId: Id | null, params: { isHierarchy?: boolean } & PageParams = {}) {
  return useQuery({
    queryKey: [V1, "relationship-types", { domainId, ...params }],
    queryFn: () => listRelationshipTypes({ domainId, ...params }),
    enabled: isId(domainId),
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
