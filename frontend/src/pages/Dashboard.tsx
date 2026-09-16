import { useQueries } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import type { ListResult } from "../api/entities";
import { useHealth } from "../api/health";
import { useSchema } from "../api/meta";

export default function Dashboard() {
  const { data: health, isLoading: healthLoading } = useHealth();
  const { data: tables } = useSchema();

  const countQueries = useQueries({
    queries: (tables ?? []).map((t) => ({
      queryKey: ["row-count", t.schema, t.table],
      queryFn: () => apiFetch<ListResult>(`/api/${t.schema}/${t.table}/?limit=1&offset=0`),
      enabled: Boolean(tables),
    })),
  });

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Dashboard</h1>

      <div className="mb-6 grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-xs uppercase text-slate-400">Postgres</div>
          <div
            className={`text-lg font-semibold ${health?.postgres === "ok" ? "text-emerald-600" : "text-red-600"}`}
          >
            {healthLoading ? "…" : (health?.postgres ?? "unknown")}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-xs uppercase text-slate-400">ClickHouse</div>
          <div
            className={`text-lg font-semibold ${health?.clickhouse === "ok" ? "text-emerald-600" : "text-red-600"}`}
          >
            {healthLoading ? "…" : (health?.clickhouse ?? "unknown")}
          </div>
        </div>
      </div>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">Row counts</h2>
      <table className="w-full max-w-md border-collapse text-sm">
        <tbody>
          {(tables ?? []).map((t, index) => (
            <tr key={`${t.schema}.${t.table}`} className="border-b border-slate-100">
              <td className="px-3 py-1.5 text-slate-600">
                {t.schema}.{t.table}
              </td>
              <td className="px-3 py-1.5 text-right font-medium text-slate-900">
                {countQueries[index]?.data?.total ?? "…"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
