import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { NetworkError } from "../api/client";
import { formatApiError } from "../api/errors";
import { useQueueMetrics } from "../api/v1";
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
    <div className="mx-auto max-w-4xl px-4 py-6">
      <h1 className="text-2xl font-semibold text-slate-900">Run queue</h1>
      <p className="mt-1 text-sm text-slate-600">
        Depth, running solves and oldest wait per organization. Refreshes every ten seconds.
        Scale workers with <code className="text-xs">docker compose up --scale worker=N</code>
        {" "}(see the workers runbook).
      </p>

      {metrics.isError ? (
        <div className="mt-6">
          {metrics.error instanceof NetworkError ? (
            <OfflineNotice subject="Queue metrics" reason="unreachable" />
          ) : (
            <p role="alert" className="text-sm text-red-700">{formatApiError(metrics.error)}</p>
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
    </div>
  );
}
