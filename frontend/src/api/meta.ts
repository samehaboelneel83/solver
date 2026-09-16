import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { TableMeta } from "../types/meta";

export function useSchema() {
  return useQuery({
    queryKey: ["meta", "schema"],
    queryFn: () => apiFetch<TableMeta[]>("/api/meta/schema"),
    staleTime: Infinity,
  });
}
