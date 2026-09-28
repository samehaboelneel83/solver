import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Play, TriangleAlert } from "lucide-react";
import { apiFetch } from "../api/client";
import type { Page, RunSummary } from "../api/v1";
import { relativeTime } from "../lib/relativeTime";
import HomeSection, { HOME_CARD, HOME_ICON } from "./HomeSection";

const TONE: Record<string, string> = {
  optimal: "bg-green-50 text-green-800 border-green-200",
  feasible: "bg-green-50 text-green-800 border-green-200",
  infeasible: "bg-amber-50 text-amber-800 border-amber-200",
  unbounded: "bg-amber-50 text-amber-800 border-amber-200",
  error: "bg-red-50 text-red-800 border-red-200",
  failed: "bg-red-50 text-red-800 border-red-200",
  queued: "bg-sky-50 text-sky-800 border-sky-200",
  running: "bg-sky-50 text-sky-800 border-sky-200",
};

function RunCards({ rows, alert }: { rows: RunSummary[]; alert?: boolean }) {
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {rows.map((run) => {
        const when = relativeTime(run.finished_at ?? run.started_at ?? run.queued_at);
        return (
          <li key={run.id}>
            <Link className={HOME_CARD} to={`/runs?scenario=${run.scenario_id}&run=${run.id}`}>
              <span className={alert ? "flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-red-50 text-red-700" : HOME_ICON} aria-hidden="true">
                {alert ? <TriangleAlert size={16} /> : <Play size={16} />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-semibold text-slate-900">Run {run.id}</span>
                  <span className={`shrink-0 rounded border px-1.5 py-0.5 text-xs font-medium ${TONE[run.status] ?? "border-slate-200 bg-slate-100 text-slate-700"}`}>
                    {run.status}
                  </span>
                </span>
                <span className="mt-1 block truncate text-xs text-slate-500">
                  {run.objective !== null && run.objective !== undefined ? `Objective ${run.objective.toLocaleString("en")}` : run.solver}
                  {when ? ` · ${when}` : ""}
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export default function HomeResults() {
  const runs = useQuery({ queryKey: ["v1", "home-results"], queryFn: () => apiFetch<Page<RunSummary>>("/api/v1/runs?limit=6") });
  const items = runs.data?.items ?? [];
  const attention = items.filter((run) => ["error", "failed", "infeasible"].includes(run.status));
  const unavailable = runs.isError || runs.isLoading || runs.fetchStatus === "paused";
  return (
    <>
      <HomeSection id="recent-results" title="Recent results" note="The six most recent runs, newest first." viewAll={{ to: "/runs" }}>
        {runs.isError ? (
          <p role="alert" className="text-sm">Results could not be loaded. <button className="p-2 underline" onClick={() => void runs.refetch()}>Retry</button></p>
        ) : runs.fetchStatus === "paused" ? (
          <p role="status" className="text-sm text-slate-500">Waiting for the server connection.</p>
        ) : runs.isLoading ? (
          <p role="status" className="text-sm text-slate-500">Loading results…</p>
        ) : items.length ? (
          <RunCards rows={items} />
        ) : (
          <p className="rounded-lg border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">No runs yet. Choose a problem to start.</p>
        )}
      </HomeSection>
      <HomeSection id="attention-needed" title="Attention needed" note="Failed or infeasible runs among the six most recent runs.">
        {unavailable ? (
          <p className="text-sm text-slate-500">Status is not available yet.</p>
        ) : attention.length ? (
          <RunCards rows={attention} alert />
        ) : (
          <p className="text-sm text-slate-500">None in the recent runs.</p>
        )}
      </HomeSection>
    </>
  );
}
