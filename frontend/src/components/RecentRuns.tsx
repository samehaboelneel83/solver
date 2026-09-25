import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import type { Page, RunSummary } from "../api/v1";

const TONE: Record<string, string> = {
  optimal: "bg-emerald-100 text-emerald-800",
  feasible: "bg-amber-100 text-amber-800",
  infeasible: "bg-red-100 text-red-800",
  error: "bg-red-100 text-red-800",
  running: "bg-blue-100 text-blue-800",
  queued: "bg-slate-100 text-slate-700",
};

function ago(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}

/** The bell's panel: the organization's latest runs and how each ended, each opening its scenario's runs (queue R22). */
export default function RecentRuns({ onClose }: { onClose: () => void }) {
  const runs = useQuery({
    queryKey: ["v1", "recent-runs"],
    queryFn: () => apiFetch<Page<RunSummary>>("/api/v1/runs?limit=6"),
    refetchInterval: 15_000,
  });
  return (
    <div role="dialog" aria-label="Recent runs" className="absolute end-0 z-50 mt-1 w-80 rounded-md border border-slate-200 bg-white shadow-lg">
      <p className="border-b border-slate-100 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Recent runs</p>
      {runs.isLoading ? (
        <p className="px-3 py-3 text-sm text-slate-500">Loading…</p>
      ) : (runs.data?.items ?? []).length === 0 ? (
        <p className="px-3 py-3 text-sm text-slate-500">No runs yet.</p>
      ) : (
        <ul className="py-1">
          {(runs.data?.items ?? []).map((run) => (
            <li key={run.id}>
              <Link to={`/runs?scenario=${run.scenario_id}`} onClick={onClose} className="flex items-center justify-between gap-2 px-3 py-2 text-sm hover:bg-slate-50">
                <span className="text-slate-700">Run {run.id}</span>
                <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${TONE[run.status] ?? "bg-slate-100 text-slate-700"}`}>{run.status}</span>
                <span className="ms-auto text-xs text-slate-400">{ago(run.finished_at ?? run.queued_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Link to="/runs" onClick={onClose} className="block border-t border-slate-100 px-3 py-2 text-center text-xs font-medium text-blue-700 hover:bg-slate-50">
        All runs
      </Link>
    </div>
  );
}
