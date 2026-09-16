import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type HealthStatus = { postgres: "ok" | "error"; clickhouse: "ok" | "error" };

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<HealthStatus>("/api/health"),
    refetchInterval: 30000,
  });
}
