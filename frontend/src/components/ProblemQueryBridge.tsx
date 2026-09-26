import { useEffect } from "react";
import { Outlet, useParams, useSearchParams } from "react-router-dom";
import { useRun } from "../api/v1";
import { parseRouteId } from "../lib/routeId";

/**
 * Copies path-scoped problem/version/scenario/run ids into the query string
 * that existing pages already read (OAAS N04 URL migration).
 */
export default function ProblemQueryBridge() {
  const params = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const problemId = parseRouteId(params.problemId ?? null);
  const versionId = parseRouteId(params.versionId ?? null);
  const scenarioId = parseRouteId(params.scenarioId ?? null);
  const runId = parseRouteId(params.runId ?? null);
  const run = useRun(runId);

  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    let changed = false;
    const set = (key: string, value: number | null) => {
      if (value === null) return;
      if (next.get(key) !== String(value)) {
        next.set(key, String(value));
        changed = true;
      }
    };
    set("problem", problemId);
    set("version", versionId);
    set("scenario", scenarioId ?? (run.data ? Number(run.data.scenario_id) : null));
    set("run", runId);
    if (changed) setSearchParams(next, { replace: true });
  }, [problemId, versionId, scenarioId, runId, run.data, searchParams, setSearchParams]);

  return <Outlet />;
}
