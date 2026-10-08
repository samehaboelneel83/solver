import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

/** What the platform did for the person while they were away (migration 0119): a scheduled refresh's changes. */
export type Notice = { id: number; kind: string; title: string; body: string; link: string | null; created_at: string; read_at: string | null };
export const NOTICES_KEY = ["v1", "notices"];
export function useNotices() {
  return useQuery({ queryKey: NOTICES_KEY, queryFn: () => apiFetch<{ items: Notice[]; unread: number }>("/api/v1/notices?limit=8"),
    refetchInterval: 60_000 });
}

/** The bell's panel: the person's notices, then the organization's latest runs and how each ended, each opening its
 * scenario's runs (queue R22). */
export default function RecentRuns({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const notices = useNotices();
  const settle = () => void client.invalidateQueries({ queryKey: NOTICES_KEY });
  const read = useMutation({ mutationFn: (id: number) => apiFetch(`/api/v1/notices/${id}/read`, { method: "POST" }), onSuccess: settle });
  const readAll = useMutation({ mutationFn: () => apiFetch("/api/v1/notices/read-all", { method: "POST" }), onSuccess: settle });
  const shown = notices.data?.items ?? [];
  const runs = useQuery({
    queryKey: ["v1", "recent-runs"],
    queryFn: () => apiFetch<Page<RunSummary>>("/api/v1/runs?limit=6"),
    refetchInterval: 15_000,
  });
  return (
    <div role="dialog" aria-label="Notices and recent runs" className="absolute end-0 z-50 mt-1 w-80 rounded-md border border-slate-200 bg-white shadow-lg">
      {shown.length > 0 && (
        <section aria-label="Notices" className="border-b border-slate-100">
          <div className="flex items-center justify-between px-3 py-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Notices</p>
            {(notices.data?.unread ?? 0) > 0 && (
              <button type="button" className="text-xs text-blue-700 hover:underline" onClick={() => readAll.mutate()}>Mark all read</button>
            )}
          </div>
          <ul className="pb-1">
            {shown.map((n) => {
              const inner = <><span className={`block text-sm ${n.read_at ? "text-slate-600" : "font-medium text-slate-900"}`}>{n.title}</span>
                {n.body && <span className="block text-xs text-slate-500">{n.body}</span>}
                <span className="block text-[11px] text-slate-400">{ago(n.created_at)}</span></>;
              return (
                <li key={n.id}>
                  {n.link ? (
                    <Link to={n.link} onClick={() => { if (!n.read_at) read.mutate(n.id); onClose(); }} className="block px-3 py-2 hover:bg-slate-50">{inner}</Link>
                  ) : (
                    <button type="button" onClick={() => { if (!n.read_at) read.mutate(n.id); }} className="block w-full px-3 py-2 text-start hover:bg-slate-50">{inner}</button>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
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
