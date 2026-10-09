import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import { useCheckVersion, useGateOverride, useVersionChecks, type Id } from "../api/v1";
import { useToast } from "./ToastProvider";

const TONE: Record<string, string> = {
  passed: "bg-green-100 text-green-900",
  failed: "bg-red-100 text-red-900",
  checking: "bg-sky-100 text-sky-900",
  unchecked: "bg-amber-100 text-amber-900",
  "no cases": "bg-slate-100 text-slate-700",
};

const STATE_LABEL: Record<string, string> = {
  passed: "Passed",
  failed: "Failed",
  checking: "Checking",
  unchecked: "Not checked yet",
  "no cases": "No cases",
};

/**
 * A version against its problem's acceptance cases (queue R30 / OAAS W02): each case's latest
 * verdict on this version, and a button to ask them all. A problem with cases puts a new version
 * into use -- points a scenario at it -- only once every case has passed here (or an admin records
 * a gate override).
 */
export default function VersionChecks({ versionId }: { versionId: Id }) {
  const checks = useVersionChecks(versionId);
  const run = useCheckVersion();
  const override = useGateOverride();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const removeCase = useMutation({
    mutationFn: (caseId: Id) => apiFetch(`/api/v1/suite-cases/${caseId}`, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries(),
    onError: (error) => toast.error(formatApiError(error)),
  });
  if (!checks.data) return null;
  const { state, cases } = checks.data;
  return (
    <section aria-label="Acceptance checks" className="mb-4 rounded-md border border-slate-200 bg-white p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-slate-900">Acceptance checks</h3>
        <span className={`rounded px-2 py-0.5 text-xs ${TONE[state]}`}>{STATE_LABEL[state] ?? state}</span>
        {cases.length > 0 && (
          <button type="button" disabled={run.isPending || state === "checking"}
                  onClick={() => run.mutate(versionId, { onError: (error) => toast.error(formatApiError(error)) })}
                  className="ml-auto rounded-md border border-blue-700 px-3 py-1 text-xs text-blue-800 disabled:opacity-60">
            {state === "checking" ? "Checking…" : "Run checks"}
          </button>
        )}
      </div>
      {cases.length === 0 ? (
        <p className="mt-1 text-xs text-slate-600">
          This problem has no acceptance cases yet, so a new version can be used as soon as a
          scenario points at it. Save a case from any good run to hold future versions to that
          answer.
        </p>
      ) : (
        <ul className="mt-2 space-y-1">
          {cases.map((c) => (
            <li key={c.case_id} className="text-xs">
              <span className={`rounded px-1.5 py-0.5 ${TONE[c.state]}`}>{STATE_LABEL[c.state] ?? c.state}</span>{" "}
              {c.nightly_regressed && (
                <span className="rounded px-1.5 py-0.5 bg-red-200 text-red-950">regressed overnight</span>
              )}{" "}
              <span className="font-medium text-slate-900">{c.name}</span>
              {c.reasons.length > 0 && <span className="text-red-800"> — {c.reasons.join("; ")}</span>}
              <button type="button" className="ml-2 text-xs text-red-700 underline" disabled={removeCase.isPending}
                onClick={() => removeCase.mutate(c.case_id)}>Remove case</button>
            </li>
          ))}
        </ul>
      )}
      {(state === "failed" || state === "unchecked") && cases.length > 0 && (
        <div className="mt-3 border-t border-slate-100 pt-2">
          <label className="block text-xs font-medium text-slate-800">
            Allow this version anyway (records a reason in the audit log)
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why this version may be used despite failed checks"
              className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <button
            type="button"
            disabled={override.isPending || reason.trim().length < 8}
            onClick={() =>
              override.mutate(
                { versionId, reason: reason.trim() },
                {
                  onSuccess: () => toast.success("Override recorded — scenarios may use this version"),
                  onError: (error) => toast.error(formatApiError(error)),
                },
              )
            }
            className="mt-2 rounded-md border border-amber-700 px-3 py-1 text-xs text-amber-900 disabled:opacity-60"
          >
            Override and allow use
          </button>
        </div>
      )}
    </section>
  );
}
