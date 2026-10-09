import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";

/**
 * A good run kept as an acceptance case: every later model version must reach its answer before a scenario uses it
 * (`/problems/{id}/suite-cases/from-run/{run}`).
 */
export function KeepAsCase({ problemId, runId }: { problemId: number; runId: number }) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const keep = useMutation({
    mutationFn: () => apiFetch(`/api/v1/problems/${problemId}/suite-cases/from-run/${runId}`, {
      method: "POST", body: JSON.stringify({ name: name.trim() }),
    }),
    onSuccess: () => void client.invalidateQueries(),
  });
  return (
    <details className="mt-4 text-sm">
      <summary className="cursor-pointer text-slate-800">Keep this answer as an acceptance case</summary>
      <p className="mt-1 text-xs text-slate-600">Later versions of the model must reach this answer on this data before a
        scenario may use them (see a version's Acceptance checks).</p>
      <form className="mt-2 flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); keep.mutate(); }}>
        <label>Case name{" "}
          <input className="rounded border border-slate-300 px-2 py-1" value={name} onChange={(e) => setName(e.target.value)} /></label>
        <button type="submit" className="rounded border px-3 py-1 disabled:opacity-50" disabled={!name.trim() || keep.isPending || keep.isSuccess}>
          Keep it</button>
      </form>
      {keep.isError && <p role="alert" className="text-red-700">{formatApiError(keep.error)}</p>}
      {keep.isSuccess && <p role="status" className="text-green-800">Kept as “{name.trim()}”.</p>}
    </details>
  );
}
