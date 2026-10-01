import { FormEvent, useState } from "react";
import {
  useApproveRun,
  useProblemApprovals,
  useScenario,
  type Id,
  type RunStatus,
} from "../api/v1";
import { formatApiError } from "../api/errors";
import { useCapabilities } from "../hooks/useCapability";
import { useToast } from "./ToastProvider";

/**
 * Business acceptance of an immutable run (OAAS Phase 5).
 * Requires `model.publish`. Distinct from solver status and version publish.
 */
export default function ApprovePlanPanel({
  runId,
  scenarioId,
  status,
}: {
  runId: Id;
  scenarioId: Id;
  status: RunStatus;
}) {
  const { can } = useCapabilities();
  const scenario = useScenario(scenarioId);
  const problemId = scenario.data?.problem_id ?? null;
  const approvals = useProblemApprovals(problemId, true);
  const approve = useApproveRun();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  if (!can("model.publish")) return null;

  const current = (approvals.data ?? []).find((row) => row.superseded_by == null);
  const thisApproved = current?.run_id === Number(runId);
  const usable = status === "optimal" || status === "feasible";

  function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    approve.mutate(
      {
        runId,
        body: {
          reason: reason.trim(),
          effective_from: from || null,
          effective_to: to || null,
        },
      },
      {
        onSuccess: () => {
          toast.success(`Run ${runId} approved as the current plan`);
          setOpen(false);
          setReason("");
        },
        onError: (err: unknown) => setError(formatApiError(err)),
      }
    );
  }

  return (
    <section className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-3" aria-label="Plan approval">
      <h3 className="mb-1 text-sm font-semibold text-slate-900">Plan approval</h3>
      {thisApproved ? (
        <p className="text-sm text-slate-700">
          This run is the current approved plan
          {current?.reason ? ` — ${current.reason}` : ""}.
          {current?.approved_at ? (
            <span className="text-slate-500"> ({new Date(current.approved_at).toLocaleString()})</span>
          ) : null}
          {problemId !== null && (
            <a className="ml-2 text-blue-700 underline" href={`/field/${String(problemId)}`} target="_blank" rel="noreferrer">
              Open the field view (phone, read-only)
            </a>
          )}
        </p>
      ) : current ? (
        <p className="mb-2 text-sm text-slate-700">
          Another run (#{current.run_id}) is the current approved plan
          {current.reason ? `: ${current.reason}` : ""}. Approving this run will supersede it.
        </p>
      ) : (
        <p className="mb-2 text-sm text-slate-700">No approved plan for this problem yet.</p>
      )}

      {!thisApproved && usable && (
        open ? (
          <form onSubmit={submit} className="mt-2 space-y-2">
            <label className="block text-sm text-slate-700">
              Reason
              <textarea
                required
                minLength={1}
                maxLength={2000}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={2}
                className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
            <div className="flex flex-wrap gap-3">
              <label className="text-sm text-slate-700">
                Effective from
                <input
                  type="date"
                  value={from}
                  onChange={(e) => setFrom(e.target.value)}
                  className="ml-2 rounded-md border border-slate-300 px-2 py-1 text-sm"
                />
              </label>
              <label className="text-sm text-slate-700">
                Effective to
                <input
                  type="date"
                  value={to}
                  onChange={(e) => setTo(e.target.value)}
                  className="ml-2 rounded-md border border-slate-300 px-2 py-1 text-sm"
                />
              </label>
            </div>
            {error && <p className="text-sm text-red-700">{error}</p>}
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={approve.isPending || reason.trim().length === 0}
                className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
              >
                {approve.isPending ? "Approving…" : current ? "Approve and supersede" : "Approve this plan"}
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-md px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100"
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="mt-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-800 hover:bg-slate-100"
          >
            {current ? "Approve this run instead" : "Approve this plan"}
          </button>
        )
      )}

      {!usable && !thisApproved && (
        <p className="text-sm text-slate-500">Only a usable plan (optimal or feasible) can be approved.</p>
      )}
    </section>
  );
}
