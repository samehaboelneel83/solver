/**
 * The field view (improvement plan 5.7): an approved plan as the people who act on it read it --
 * on a phone, read-only, always the plan that was approved (never the newest run). The map of the
 * answer, then each decision as a list a person filters to their own name or place ("my assignments").
 */
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import GeoMap from "../components/map/GeoMap";
import { marksOf } from "../components/RunOutputs";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

type Row = { keys: string[]; names: (string | null)[]; value: number };
type ApprovedPlan = {
  problem: string;
  approval: { reason: string; approved_at: string; effective_from: string | null; effective_to: string | null };
  run: { id: number; status: string; scenario: string };
  decisions: Record<string, { index: string[]; rows: Row[] }>;
};

export default function FieldPlan() {
  const { problemId } = useParams();
  const plan = useQuery({
    queryKey: ["approved-plan", problemId],
    queryFn: () => apiFetch<ApprovedPlan>(`/api/v1/problems/${problemId}/approved-plan`),
    retry: false,
  });
  const runId = plan.data?.run.id;
  const map = useQuery({
    queryKey: ["answer-map", runId],
    queryFn: () => apiFetch<Parameters<typeof marksOf>[0]>(`/api/v1/runs/${runId}/answer-map`),
    enabled: runId !== undefined,
    retry: false,
  });
  const [mine, setMine] = useState("");
  useDocumentTitle(plan.data ? `${plan.data.problem} — approved plan` : "Approved plan");
  const drawn = useMemo(() => (map.data && Array.isArray(map.data.features) && map.data.features.length ? marksOf(map.data) : null), [map.data]);
  const needle = mine.trim().toLowerCase();
  const match = (row: Row) => !needle || row.keys.some((k) => k.toLowerCase().includes(needle))
    || row.names.some((n) => (n ?? "").toLowerCase().includes(needle));

  if (plan.isLoading) return <main className="mx-auto max-w-xl p-4 text-sm text-slate-600">Loading the approved plan…</main>;
  if (plan.error || !plan.data) {
    return (
      <main className="mx-auto max-w-xl p-4 text-sm">
        <h1 className="text-lg font-semibold">No approved plan to show</h1>
        <p className="mt-2 text-slate-700">{plan.error ? formatApiError(plan.error) : "Nothing came back."}</p>
        <p className="mt-2"><Link className="text-blue-700 underline" to="/">Open the app</Link></p>
      </main>
    );
  }
  const { problem, approval, run, decisions } = plan.data;
  return (
    <main className="mx-auto max-w-xl space-y-4 p-4 text-sm text-slate-900">
      <header>
        <p className="text-xs font-medium uppercase tracking-wide text-emerald-700">Approved plan</p>
        <h1 className="text-xl font-semibold">{problem}</h1>
        <p className="text-slate-600">
          Run {run.id} · {run.scenario} · approved {new Date(approval.approved_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}
          {approval.effective_from ? ` · from ${approval.effective_from}` : ""}{approval.effective_to ? ` to ${approval.effective_to}` : ""}
        </p>
        <p className="mt-1 italic text-slate-700">&ldquo;{approval.reason}&rdquo;</p>
      </header>
      {drawn && <GeoMap marks={drawn.marks} legend={drawn.legend} caption="Where it happens" />}
      <label className="block">
        <span className="text-xs font-medium text-slate-700">My assignments: type your name, a place or a code</span>
        <input className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-base" value={mine}
          onChange={(e) => setMine(e.target.value)} placeholder="e.g. Operator 12, Y3, H09" />
      </label>
      {Object.entries(decisions).filter(([, d]) => d.rows.length).map(([name, d]) => {
        const rows = d.rows.filter(match);
        return (
          <section key={name} aria-label={name}>
            <h2 className="mb-1 font-semibold">{name} <span className="font-normal text-slate-500">({rows.length}{needle ? ` of ${d.rows.length}` : ""})</span></h2>
            <ul className="divide-y divide-slate-200 rounded-md border border-slate-200">
              {rows.slice(0, 300).map((row, i) => (
                <li key={`${row.keys.join("|")}-${i}`} className="flex justify-between gap-3 px-3 py-2">
                  <span>{row.keys.map((k, j) => row.names[j] && row.names[j] !== k ? `${row.names[j]} (${k})` : k).join(" → ")}</span>
                  {row.value !== 1 && <span className="font-mono">{row.value}</span>}
                </li>
              ))}
            </ul>
            {rows.length > 300 && <p className="mt-1 text-xs text-slate-500">The first 300 shown; narrow it with the box above.</p>}
          </section>
        );
      })}
    </main>
  );
}
