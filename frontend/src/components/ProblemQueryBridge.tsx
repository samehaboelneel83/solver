import LoadFailure from "./LoadFailure";
import { useEffect } from "react";
import { Outlet, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ApiError, apiFetch } from "../api/client";
import { useRun, useScenario, useVersion } from "../api/v1";
import { parseRouteId } from "../lib/routeId";
import ContextMismatch from "./ContextMismatch";

/**
 * Copies path-scoped problem/version/scenario/run ids into the query string
 * that existing pages already read (OAAS N04 URL migration).
 */
export default function ProblemQueryBridge() {
  const params = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const problemId = parseRouteId(params.problemId ?? null);
  const domainId = parseRouteId(params.domainId ?? null);
  const versionId = parseRouteId(params.versionId ?? null);
  const scenarioId = parseRouteId(params.scenarioId ?? null);
  const runId = parseRouteId(params.runId ?? null);
  const run = useRun(runId);
  const problem = useQuery({
    queryKey: ["entities", "public", "problem", problemId],
    queryFn: () => apiFetch<{ id: number; domain_id: number }>(`/api/problem/${problemId}`),
    enabled: problemId !== null,
  });
  const selectedScenarioId = scenarioId ?? run.data?.scenario_id ?? null;
  const scenario = useScenario(selectedScenarioId);
  const version = useVersion(versionId);
  const invalid = domainId === null || problemId === null ||
    (params.runId !== undefined && runId === null) ||
    (params.scenarioId !== undefined && scenarioId === null) ||
    (params.versionId !== undefined && versionId === null);
  const mismatch = (problem.data && Number(problem.data.domain_id) !== domainId) ||
    (scenario.data && Number(scenario.data.problem_id) !== problemId) ||
    (version.data && Number(version.data.problem_id) !== problemId);
  const checks = [problem, ...(runId !== null ? [run] : []),
    ...(selectedScenarioId !== null ? [scenario] : []), ...(versionId !== null ? [version] : [])];
  const failed = checks.find((check) => check.isError);
  const pending = checks.some((check) => !check.data);
  const ready = !invalid && !mismatch && !failed && !pending;
  const next = new URLSearchParams(searchParams);
  if (ready) {
    next.set("problem", String(problemId));
    if (versionId !== null) next.set("version", String(versionId));
    if (selectedScenarioId !== null) next.set("scenario", String(selectedScenarioId));
    if (runId !== null) next.set("run", String(runId));
  }
  const canonicalSearch = next.toString();

  useEffect(() => {
    if (ready && canonicalSearch !== searchParams.toString()) {
      setSearchParams(canonicalSearch, { replace: true });
    }
  }, [ready, canonicalSearch, searchParams, setSearchParams]);

  if (invalid || mismatch || (failed?.error instanceof ApiError && [403, 404].includes(failed.error.status))) {
    return <ContextMismatch title="This problem link is not available"
      detail="The requested problem or result is unavailable or does not belong to this context. Nothing was substituted."
      parentHref={domainId === null ? "/domains" : `/domains/${domainId}/problems`} parentLabel="Open problems" />;
  }
  if (failed) return <LoadFailure subject="The problem context" error={failed.error} retry={() => void failed.refetch()} />;
  // Never mount a legacy page with the previous query's object ids.
  if (!ready || canonicalSearch !== searchParams.toString()) return <p role="status">Loading problem…</p>;

  return <Outlet />;
}
