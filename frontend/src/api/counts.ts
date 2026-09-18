import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type TableCount = {
  schema: string;
  table: string;
  label_plural: string;
  total: number;
};

/**
 * One row count per registered table, in a single request (A-1/A-2). Backs
 * the dashboard's row-counts panel, which used to fire one
 * `/api/<schema>/<table>/?limit=1` request per table (34 requests on a
 * freshly migrated database) just to show a count. The backend's dedicated
 * `/api/meta/counts` endpoint (added alongside this fix) returns every
 * table's `{schema, table, label_plural, total}` in one round trip instead.
 */
export function useCounts() {
  return useQuery({
    queryKey: ["meta", "counts"],
    queryFn: () => apiFetch<TableCount[]>("/api/meta/counts"),
  });
}
