import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type ListResult<T = Record<string, unknown>> = { items: T[]; total: number };

export function useEntityList(schemaName: string, tableName: string, limit: number, offset: number) {
  return useQuery({
    queryKey: ["entities", schemaName, tableName, limit, offset],
    queryFn: () =>
      apiFetch<ListResult>(`/api/${schemaName}/${tableName}/?limit=${limit}&offset=${offset}`),
    enabled: Boolean(schemaName && tableName),
  });
}

export function useDeleteEntity(schemaName: string, tableName: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/api/${schemaName}/${tableName}/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["entities", schemaName, tableName] }),
  });
}
