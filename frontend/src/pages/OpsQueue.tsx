import LoadFailure from "../components/LoadFailure";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { NetworkError } from "../api/client";
import { Link } from "react-router-dom";
import { useQueueMetrics, useRunQueue, type RunQueue } from "../api/v1";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/**
 * Run queue & capacity (OAAS OPS01 / R33): per-organization depth, running
 * solves, and oldest wait — the same gauges operators scrape from /metrics.
 */

function seconds(value: number): string {
  if (value < 1) return "—";
  if (value < 60) return `${Math.round(value)} s`;
  if (value < 3600) return `${Math.round(value / 60)} min`;
  return `${(value / 3600).toFixed(1)} h`;
}

export default function OpsQueue() {
  useDocumentTitle("Run queue");
  const metrics = useQueueMetrics();

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold text-slate-900">Run queue</h1>
      <p className="mt-1 text-sm text-slate-600">
        Depth, running solves and oldest wait per organization. Refreshes every ten seconds.
        When runs wait here for long, an administrator can add workers (the workers runbook says how).
      </p>

      {metrics.isError ? (
        <div className="mt-6">
          {metrics.error instanceof NetworkError ? (
            <OfflineNotice subject="Queue metrics" reason="unreachable" />
          ) : (
            <LoadFailure subject="Queue metrics" error={metrics.error} retry={() => void metrics.refetch()} />
          )}
        </div>
      ) : metrics.isLoading ? (
        <div className="mt-6"><Skeleton rows={4} cols={4} /></div>
      ) : !metrics.data?.length ? (
        <p className="mt-6 text-sm text-slate-600">No queued or running solves right now.</p>
      ) : (
        <table className="mt-6 w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-slate-500">
              <th className="py-2 font-medium">Organization</th>
              <th className="py-2 font-medium">Queued</th>
              <th className="py-2 font-medium">Running</th>
              <th className="py-2 font-medium">Oldest wait</th>
            </tr>
          </thead>
          <tbody>
            {metrics.data.map((row) => (
              <tr key={row.org} className="border-b border-slate-100">
                <td className="py-2 font-mono text-xs text-slate-700">{row.org}</td>
                <td className="py-2">{row.depth}</td>
                <td className="py-2">{row.running}</td>
                <td className="py-2">{seconds(row.oldestWaitSeconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <RunsInQueue />
    </div>
  );
}

/** Each waiting or solving run: its problem, lane, the workers and memory it holds, and why it waits
 * (handover of 8 October 2026: a queue panel). */
function RunsInQueue() {
  const queue = useRunQueue();
  const data: RunQueue | undefined = queue.data;
  return (
    <section aria-label="Runs in the queue" className="mt-8">
      <h2 className="text-lg font-semibold text-slate-900">Runs in the queue</h2>
      {data && (
        <p className="mt-1 text-sm text-slate-600">
          This host gives solving {data.capacity.workers} workers and {Math.round(data.capacity.memory_mb / 1024)} GB.
          {data.capacity.short_share > 0 && ` A share of ${Math.round(data.capacity.short_share * 100)}% is kept for short
          runs (a time limit of ${data.capacity.short_seconds} s or less), so they start while long ones fill the rest.`}
        </p>
      )}
      {queue.isError ? (
        <div className="mt-3"><LoadFailure subject="The run queue" error={queue.error} retry={() => void queue.refetch()} /></div>
      ) : queue.isLoading ? (
        <div className="mt-3"><Skeleton rows={3} cols={6} /></div>
      ) : !data?.runs.length ? (
        <p className="mt-3 text-sm text-slate-600">No run is waiting or solving.</p>
      ) : (
        <table className="mt-3 w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-slate-500">
              <th className="py-2 font-medium">Run</th>
              <th className="py-2 font-medium">Problem · scenario</th>
              <th className="py-2 font-medium">State</th>
              <th className="py-2 font-medium">Lane</th>
              <th className="py-2 font-medium">Holds</th>
              <th className="py-2 font-medium">Why it waits</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((r) => (
              <tr key={r.run_id} className="border-b border-slate-100 align-top">
                <td className="py-2">
                  <Link className="text-blue-700 underline" to={`/runs?scenario=${r.scenario_id}&run=${r.run_id}`}>{r.run_id}</Link>
                </td>
                <td className="py-2">{r.problem} · {r.scenario}</td>
                <td className="py-2">
                  {r.status === "running" ? `solving for ${seconds(r.running_s ?? 0)}` : `waiting ${seconds(r.waited_s)}`}
                  {r.time_limit_s !== null && <span className="text-slate-500"> (limit {seconds(r.time_limit_s)})</span>}
                </td>
                <td className="py-2">{r.lane}</td>
                <td className="py-2">
                  {r.workers ? `${r.workers} workers` : "—"}{r.memory_mb ? `, ${Math.round(r.memory_mb / 1024 * 10) / 10} GB` : ""}
                </td>
                <td className="py-2 text-slate-600">{r.waits_because ?? (r.status === "queued" ? "next free worker" : "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
