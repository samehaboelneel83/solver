import LoadFailure from "../components/LoadFailure";
import { useState } from "react";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { NetworkError, apiDownload } from "../api/client";
import { useAudit } from "../api/v1";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/**
 * Audit history (OAAS OPS01 / R34): append-only events for the signed-in
 * organization (operators see every org). CSV export uses the same route.
 */

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function OpsAudit() {
  useDocumentTitle("Audit history");
  const [action, setAction] = useState("");
  const audit = useAudit({ limit: 100, action: action || undefined });

  async function downloadCsv() {
    const qs = action ? `?format=csv&action=${encodeURIComponent(action)}` : "?format=csv";
    const { blob, filename } = await apiDownload(`/api/v1/audit${qs}`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename.endsWith(".csv") ? filename : "audit.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="max-w-5xl">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Audit history</h1>
          <p className="mt-1 text-sm text-slate-600">
            Who changed what. Retention is four hundred days; prune runs with the nightly job.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex flex-col text-xs text-slate-600">
            Action filter
            <input
              value={action}
              onChange={(e) => setAction(e.target.value)}
              placeholder="e.g. login"
              className="mt-1 rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <button
            type="button"
            onClick={() => void downloadCsv()}
            className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-800 hover:bg-slate-50"
          >
            Download CSV
          </button>
        </div>
      </div>

      {audit.isError ? (
        <div className="mt-6">
          {audit.error instanceof NetworkError ? (
            <OfflineNotice subject="Audit history" reason="unreachable" />
          ) : (
            <LoadFailure subject="Audit history" error={audit.error} retry={() => void audit.refetch()} />
          )}
        </div>
      ) : audit.isLoading ? (
        <div className="mt-6"><Skeleton rows={5} cols={5} /></div>
      ) : (
        <>
          <p className="mt-4 text-xs text-slate-500">{audit.data?.total ?? 0} events</p>
          <table className="mt-2 w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-slate-500">
                <th className="py-2 font-medium">When</th>
                <th className="py-2 font-medium">Action</th>
                <th className="py-2 font-medium">Object</th>
                <th className="py-2 font-medium">Actor</th>
                <th className="py-2 font-medium">IP</th>
              </tr>
            </thead>
            <tbody>
              {(audit.data?.items ?? []).map((row) => (
                <tr key={row.id} className="border-b border-slate-100">
                  <td className="py-2 whitespace-nowrap text-slate-700">{when(row.at)}</td>
                  <td className="py-2 font-mono text-xs">{row.action}</td>
                  <td className="py-2 text-xs text-slate-600">
                    {row.object_type ?? "—"}
                    {row.object_id ? ` ${row.object_id}` : ""}
                  </td>
                  <td className="py-2 font-mono text-xs text-slate-500">
                    {row.actor_id?.slice(0, 8) ?? row.api_key_id?.slice(0, 8) ?? "—"}
                  </td>
                  <td className="py-2 text-xs text-slate-500">{row.ip ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
