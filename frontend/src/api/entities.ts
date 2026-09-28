import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { tableApiPath } from "./paths";
import { apiFetch } from "./client";

export type ListResult<T = Record<string, unknown>> = { items: T[]; total: number };

export type EntityListParams = {
  limit: number;
  offset: number;
  q?: string;
  filters?: Record<string, string>;
  orderBy?: string;
  order?: "asc" | "desc";
  /** False holds the query (a search box with nothing typed in it). */
  enabled?: boolean;
};

export function useEntityList(schemaName: string, tableName: string, params: EntityListParams) {
  const { limit, offset, q = "", filters = {}, orderBy, order, enabled = true } = params;
  const filterEntries = Object.entries(filters).sort(([a], [b]) => a.localeCompare(b));

  return useQuery({
    queryKey: ["entities", schemaName, tableName, limit, offset, q, filterEntries, orderBy ?? "", order ?? ""],
    queryFn: () => {
      const search = new URLSearchParams();
      search.set("limit", String(limit));
      search.set("offset", String(offset));
      if (q) search.set("q", q);
      if (orderBy) search.set("order_by", orderBy);
      if (order) search.set("order", order);
      for (const [key, value] of filterEntries) {
        search.set(`f_${key}`, value);
      }
      return apiFetch<ListResult>(`${tableApiPath(schemaName, tableName)}/?${search.toString()}`);
    },
    enabled: enabled && Boolean(schemaName && tableName),
    // Keep the previous page's rows on screen while the next query (sort,
    // page, or search) is in flight, instead of dropping straight to
    // `isLoading` -- without this every sort/page/search click unmounted
    // the whole table (skeleton flash) and, worse, destroyed and recreated
    // the row-count `aria-live` region, so screen readers never got a
    // reliable "1-20 of 50 -> 1-20 of 37" announcement. A genuine first
    // load still has no previous data to keep, so the skeleton still shows
    // then.
    placeholderData: keepPreviousData,
  });
}

export function useDeleteEntity(schemaName: string, tableName: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`${tableApiPath(schemaName, tableName)}/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["entities", schemaName, tableName] }),
  });
}

export function useEntity(schemaName: string, tableName: string, id: string | undefined) {
  return useQuery({
    queryKey: ["entity", schemaName, tableName, id],
    queryFn: () => apiFetch<Record<string, unknown>>(`${tableApiPath(schemaName, tableName)}/${id}`),
    enabled: Boolean(schemaName && tableName && id),
  });
}

export function useCreateEntity(schemaName: string, tableName: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiFetch(`${tableApiPath(schemaName, tableName)}/`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["entities", schemaName, tableName] }),
  });
}

export function useUpdateEntity(schemaName: string, tableName: string, id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiFetch(`${tableApiPath(schemaName, tableName)}/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["entities", schemaName, tableName] });
      queryClient.invalidateQueries({ queryKey: ["entity", schemaName, tableName, id] });
    },
  });
}
