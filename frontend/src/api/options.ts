import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type Option = { id: string; label: string };

const IDS_BATCH_SIZE = 200;

/** `fk_table` from meta is "schema.table" (e.g. "iam.organization"); the
 * options route is `/api/{schema}/{table}/options`. */
function optionsPath(fkTable: string): string {
  return `/api/${fkTable.replace(".", "/")}/options`;
}

function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    chunks.push(items.slice(i, i + size));
  }
  return chunks;
}

/** Search options for an FK dropdown. */
export function useOptions(fkTable: string, q: string) {
  return useQuery({
    queryKey: ["options", fkTable, "q", q],
    queryFn: () => {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      const qs = params.toString();
      return apiFetch<Option[]>(`${optionsPath(fkTable)}${qs ? `?${qs}` : ""}`);
    },
    enabled: Boolean(fkTable),
  });
}

/** Resolve a set of FK ids to human labels, as a map of id -> label.
 * Batches at most 200 ids per request (the server's own cap) and skips
 * the request entirely when there are no ids to resolve. */
export function useOptionLabels(fkTable: string, ids: string[]) {
  const uniqueSortedIds = Array.from(new Set(ids.filter((id) => id))).sort();
  const key = uniqueSortedIds.join(",");

  return useQuery({
    queryKey: ["options", fkTable, "ids", key],
    queryFn: async () => {
      const batches = chunk(uniqueSortedIds, IDS_BATCH_SIZE);
      const results = await Promise.all(
        batches.map((batch) => apiFetch<Option[]>(`${optionsPath(fkTable)}?ids=${batch.join(",")}`))
      );
      const labels: Record<string, string> = {};
      for (const batch of results) {
        for (const option of batch) {
          labels[option.id] = option.label;
        }
      }
      return labels;
    },
    enabled: Boolean(fkTable) && uniqueSortedIds.length > 0,
  });
}
