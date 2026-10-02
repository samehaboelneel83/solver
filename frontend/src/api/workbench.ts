/**
 * The data workbench (`app/api/workbench.py`): a domain's records as one tree read from the model.
 *
 * A **group** is how records sit under a parent: `ref:<attribute id>` (a reference field naming the
 * parent), `rel:<relationship type id>` (a hierarchy), or `root:<kind id>` (a kind's records with no
 * parent at all -- every record of a root kind, or the "not placed" ones of another kind).
 */
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { Entity, Id, Page } from "./v1";

export type WorkbenchKind = { id: Id; name: string; is_abstract: boolean; inherited_from: Id | null; count: number };
export type WorkbenchEdge = {
  group_key: string;
  child_kind: Id;
  parent_kind: Id;
  field: string;
  required: boolean;
  relationship_type_id: Id;
  child_end: "from_entity_id" | "to_entity_id";
};
export type WorkbenchSchema = { domain_id: Id; kinds: WorkbenchKind[]; edges: WorkbenchEdge[]; roots: Id[] };
export type TreeRecord = Entity & { children: number };
export type ChildGroup = {
  group: string;
  kind_id: Id;
  kind: string;
  field: string;
  via: "reference" | "hierarchy";
  required: boolean;
  count: number;
};
export type PathStep = { id: Id; key: string; label: string | null; entity_type_id: Id; child_group: string };
export type SearchHit = { id: Id; key: string; label: string | null; entity_type_id: Id; kind: string; path: PathStep[] };
export type ProblemRecord = { id: Id; key: string; label: string | null; entity_type_id: Id; kind: string; codes: string[] };
export type RecordValues = {
  parameter_id: Id;
  name: string;
  unit: string | null;
  index_kinds: string[];
  default_value: number | null;
  entity_valued: boolean;
  single: boolean;
  cells: { entity_ids: Id[]; keys: string[]; value: number | null; value_key: string | null; updated_at: string }[];
};

const W = "workbench";
const base = (domainId: Id) => `/api/v1/domains/${domainId}/workbench`;
const qs = (params: Record<string, string | number | undefined | null>) => {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
};

export function useWorkbenchSchema(domainId: Id | null) {
  return useQuery({
    queryKey: ["v1", W, "schema", domainId],
    queryFn: () => apiFetch<WorkbenchSchema>(`${base(domainId as Id)}/schema`),
    enabled: domainId != null,
  });
}

export function useChildren(domainId: Id | null, group: string | null, parent: Id | null, opts: { q?: string; limit?: number; enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["v1", W, "children", domainId, group, parent, opts.q ?? "", opts.limit ?? 100],
    queryFn: () =>
      apiFetch<Page<TreeRecord>>(`${base(domainId as Id)}/children${qs({ group, parent, q: opts.q, limit: opts.limit ?? 100 })}`),
    enabled: domainId != null && group != null && (opts.enabled ?? true),
  });
}

export function useGroups(domainId: Id | null, parent: Id | null, enabled = true) {
  return useQuery({
    queryKey: ["v1", W, "groups", domainId, parent],
    queryFn: () => apiFetch<{ parent: Id; groups: ChildGroup[] }>(`${base(domainId as Id)}/groups${qs({ parent })}`),
    enabled: domainId != null && parent != null && enabled,
  });
}

export function useWorkbenchSearch(domainId: Id | null, q: string) {
  return useQuery({
    queryKey: ["v1", W, "search", domainId, q],
    queryFn: () => apiFetch<{ items: SearchHit[] }>(`${base(domainId as Id)}/search${qs({ q })}`),
    enabled: domainId != null && q.trim().length > 0,
  });
}

export function useProblems(domainId: Id | null) {
  return useQuery({
    queryKey: ["v1", W, "problems", domainId],
    queryFn: () =>
      apiFetch<{ records: Record<string, string[]>; items: ProblemRecord[] }>(`${base(domainId as Id)}/problems`),
    enabled: domainId != null,
  });
}

export function useRecordValues(entityId: Id | null) {
  return useQuery({
    queryKey: ["v1", W, "values", entityId],
    queryFn: () => apiFetch<{ entity_id: Id; parameters: RecordValues[] }>(`/api/v1/entities/${entityId}/values`),
    enabled: entityId != null,
  });
}

export type Place = {
  entity: Id;
  kind_id: Id;
  group: string;
  parent: { id: Id; key: string; label: string | null; entity_type_id: Id } | null;
  /** Every record above, top first, each with the group its child is listed in. */
  path: PathStep[];
};

/** Where a record sits: the list its siblings are in. */
export function usePlace(domainId: Id | null, entityId: Id | null, enabled = true) {
  return useQuery({
    queryKey: ["v1", W, "place", domainId, entityId],
    queryFn: () => apiFetch<Place>(`${base(domainId as Id)}/place${qs({ entity: entityId })}`),
    enabled: domainId != null && entityId != null && enabled,
  });
}

/** The kinds this kind is, nearest first: itself and every kind it inherits from. */
export function lineageOf(kinds: WorkbenchKind[], kindId: Id): Id[] {
  const byId = new Map(kinds.map((k) => [k.id, k]));
  const out: Id[] = [];
  let at: Id | null = kindId;
  while (at != null && !out.includes(at)) {
    out.push(at);
    at = byId.get(at)?.inherited_from ?? null;
  }
  return out;
}

/** Edges by which a record of `childKind` could be placed under a record of `parentKind`. */
export function placingEdges(schema: WorkbenchSchema, childKind: Id, parentKind: Id): WorkbenchEdge[] {
  const child = lineageOf(schema.kinds, childKind);
  const parent = lineageOf(schema.kinds, parentKind);
  return schema.edges.filter((e) => child.includes(e.child_kind) && parent.includes(e.parent_kind));
}
