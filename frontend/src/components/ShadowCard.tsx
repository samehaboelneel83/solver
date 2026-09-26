import { formatApiError } from "../api/errors";
import { useShadowReport, type Id } from "../api/v1";

/**
 * Candidate versions shadowed beside this problem's real runs (queue R31).
 */
export default function ShadowCard({ problemId }: { problemId: Id }) {
  const report = useShadowReport(problemId);
  if (!report.data) return null;
  const { candidates } = report.data;
  return (
    <section aria-label="Shadow runs" className="mb-4 rounded-md border border-slate-200 bg-white p-3 text-sm">
      <h3 className="font-semibold text-slate-900">Shadow runs</h3>
      {candidates.length === 0 ? (
        <p className="mt-1 text-xs text-slate-600">
          No shadowed twins yet. Set <code className="font-mono">shadow.version</code> and{" "}
          <code className="font-mono">shadow.rate</code> on this problem to compare a candidate beside live plans.
        </p>
      ) : (
        <ul className="mt-2 space-y-2">
          {candidates.map((c) => (
            <li key={c.model_version_id} className="rounded border border-slate-100 bg-slate-50 p-2 text-xs">
              <p className="font-medium text-slate-900">
                Version id {c.model_version_id}: {c.compared} compared,{" "}
                {c.share_at_least_as_good === null
                  ? "no share yet"
                  : `${Math.round(c.share_at_least_as_good * 100)}% at least as good`}
                {c.median_time_ratio != null && ` · median time ×${c.median_time_ratio}`}
              </p>
              {c.recent.length > 0 && (
                <ul className="mt-1 space-y-0.5 text-slate-700">
                  {c.recent.slice(0, 5).map((r) => (
                    <li key={r.shadow_run}>
                      real {r.real_run} ↔ shadow {r.shadow_run}
                      {r.verdict?.delta != null && ` · Δ ${r.verdict.delta}`}
                      {r.verdict?.at_least_as_good === true && " · good"}
                      {r.verdict?.at_least_as_good === false && " · worse"}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      {report.isError && <p className="mt-1 text-xs text-red-700">{formatApiError(report.error)}</p>}
    </section>
  );
}
