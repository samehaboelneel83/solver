import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";

/**
 * The run's answer in the platform's words -- the goal and its parts, what each decision chose with its records'
 * names, totals per record, room left, busy time, rules held or tight, what a change of a number would do while
 * the plan stays the same, routes and layouts: what the Assistant reads, for anyone (owner, 9 October 2026).
 */
export function AnswerExplained({ runId }: { runId: number }) {
  const [open, setOpen] = useState(false);
  const said = useQuery({
    queryKey: ["run-explanation", runId],
    queryFn: () => apiFetch<{ text: string }>(`/api/v1/runs/${runId}/explanation`),
    enabled: open,
    staleTime: Infinity,
  });
  return (
    <details className="mt-6 text-sm" onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer font-semibold text-slate-900">The answer explained</summary>
      {said.isLoading && <p role="status" className="mt-2">Reading the answer…</p>}
      {said.isError && <p role="alert" className="mt-2 text-red-700">{formatApiError(said.error)}</p>}
      {said.data && (
        <div aria-label="The answer explained" className="mt-2 max-h-[36rem] overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm leading-relaxed">
          {said.data.text}
        </div>
      )}
    </details>
  );
}
