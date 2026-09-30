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

/** One part of the platform: whether it works and, when not, the command that brings it back. */
export type HealthCheck = { name: string; ok: boolean; needed: boolean; says: string; fix: string | null };
export type HealthDetails = { ready: boolean; checks: HealthCheck[] };

export function useHealthDetails() {
  return useQuery({
    queryKey: ["health", "details"],
    queryFn: () => apiFetch<HealthDetails>("/api/health/details"),
    refetchInterval: 5000,
  });
}
