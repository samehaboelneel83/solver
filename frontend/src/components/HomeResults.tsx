import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import type { Page, RunSummary } from "../api/v1";

export default function HomeResults() {
  const runs = useQuery({ queryKey: ["v1", "home-results"], queryFn: () => apiFetch<Page<RunSummary>>("/api/v1/runs?limit=6") });
  const items = runs.data?.items ?? [];
  const attention = items.filter(run => ["error", "failed", "infeasible"].includes(run.status));
  const list = (rows: RunSummary[]) => <ul className="divide-y divide-slate-100">{rows.map(run =>
    <li key={run.id}><Link className="flex justify-between gap-4 py-3 text-sm text-blue-700" to={`/runs?scenario=${run.scenario_id}&run=${run.id}`}>
      <span>Run {run.id}</span><span>{run.status}</span>
    </Link></li>)}</ul>;
  return <div className="my-6 grid gap-4 md:grid-cols-2">
    <section id="recent-results" aria-labelledby="recent-results-title" className="rounded-xl border bg-white p-5">
      <h2 id="recent-results-title" className="font-semibold">Recent results</h2>
      {runs.isError ? <p role="alert">Results could not be loaded. <button className="p-2 underline" onClick={() => void runs.refetch()}>Retry</button></p>
        : runs.fetchStatus === "paused" ? <p role="status">Waiting for the server connection.</p>
        : runs.isLoading ? <p role="status">Loading results…</p>
        : items.length ? list(items) : <p className="mt-3 text-sm">No runs yet. Choose a problem to start.</p>}
    </section>
    <section id="attention-needed" aria-labelledby="attention-needed-title" className="rounded-xl border bg-white p-5">
      <h2 id="attention-needed-title" className="font-semibold">Attention needed</h2>
      <p className="mt-2 text-sm text-slate-600">Failed or infeasible runs among the six most recent runs.</p>
      {runs.isError || runs.isLoading || runs.fetchStatus === "paused" ? <p className="mt-3 text-sm">Status is not available yet.</p>
        : attention.length ? list(attention) : <p className="mt-3 text-sm">None in the recent runs.</p>}
    </section>
  </div>;
}
