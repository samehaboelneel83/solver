import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { GraphEdge, GraphNode, GraphResponse } from "../types/graph";

export function graphQueryPath(organizationId: string, hierarchyId: string | null): string {
  const params = new URLSearchParams({ organization_id: organizationId });
  if (hierarchyId) {
    params.set("hierarchy_id", hierarchyId);
  }
  return `/api/graph/domain?${params.toString()}`;
}

function graphQueryKey(organizationId: string, hierarchyId: string | null) {
  return ["graph", "domain", organizationId, hierarchyId];
}

export function useGraph(organizationId: string, hierarchyId: string | null) {
  return useQuery({
    queryKey: graphQueryKey(organizationId, hierarchyId),
    queryFn: () => apiFetch<GraphResponse>(graphQueryPath(organizationId, hierarchyId)),
    enabled: Boolean(organizationId),
  });
}

export type CreateNodePayload = {
  organization_id: string;
  entity_type_id: string;
  name: string;
  code?: string;
  status?: string;
  description?: string;
  attributes?: Record<string, unknown>;
  hierarchy_id?: string;
  parent_entity_id?: string;
};

export function useCreateNode(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateNodePayload) =>
      apiFetch<GraphNode>("/api/graph/domain/nodes", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}

export type UpdateNodePayload = Partial<Omit<CreateNodePayload, "organization_id" | "entity_type_id">>;

export function useUpdateNode(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ entityId, payload }: { entityId: string; payload: UpdateNodePayload }) =>
      apiFetch<GraphNode>(`/api/graph/domain/nodes/${entityId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}

export function useDeleteNode(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entityId: string) => apiFetch(`/api/graph/domain/nodes/${entityId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}

export type CreateEdgePayload = {
  relationship_type_id: string;
  source_entity_id: string;
  target_entity_id: string;
  attributes?: Record<string, unknown>;
};

export function useCreateEdge(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateEdgePayload) =>
      apiFetch<GraphEdge>("/api/graph/domain/edges", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}

export function useUpdateEdge(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ relationshipId, attributes }: { relationshipId: string; attributes: Record<string, unknown> }) =>
      apiFetch<GraphEdge>(`/api/graph/domain/edges/${relationshipId}`, {
        method: "PATCH",
        body: JSON.stringify({ attributes }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}

export function useDeleteEdge(organizationId: string, hierarchyId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (relationshipId: string) =>
      apiFetch(`/api/graph/domain/edges/${relationshipId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: graphQueryKey(organizationId, hierarchyId) }),
  });
}
