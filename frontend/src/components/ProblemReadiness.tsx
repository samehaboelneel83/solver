import { Link, useParams } from "react-router-dom";
import { useProblemRuns, useScenarios, useVersions, type Id } from "../api/v1";

/**
 * Short readiness checklist for a problem (OAAS N07 / proposal §4).
 * Each step links to the ordinary page; it is not a second editor.
 */
export default function ProblemReadiness({ problemId }: { problemId: Id }) {
  const versions = useVersions(problemId, { limit: 1, offset: 0 });
  const scenarios = useScenarios(problemId, { limit: 1, offset: 0 });
  const runs = useProblemRuns(problemId);
  const { domainId } = useParams();
  const href = (page: string) => domainId
    ? `/domains/${domainId}/problems/${problemId}/${page}`
    : `/${page}?problem=${problemId}`;
  const hasVersion = (versions.data?.items.length ?? 0) > 0;
  const hasScenario = (scenarios.data?.items.length ?? 0) > 0;
  const loading = versions.isLoading || scenarios.isLoading;

  const steps = [
    {
      done: hasVersion,
      label: "Publish a model version",
      href: href("model"),
    },
    {
      done: hasScenario,
      label: "Create a scenario",
      href: href("scenarios"),
    },
    {
      // Ticked once any scenario has a run (operator trial F10).
      done: (runs.data?.total ?? 0) > 0,
      label: "Run and review a result",
      href: href("runs"),
      optionalUntil: !hasScenario,
    },
  ];

  if (versions.isError || scenarios.isError) {
    return <div role="alert" className="mb-4 text-sm">Readiness could not be checked.
      <button type="button" className="p-2 text-blue-700 underline" onClick={() => { void versions.refetch(); void scenarios.refetch(); }}>Retry</button>
    </div>;
  }
  if (loading) {
    return <p className="mb-4 text-sm text-slate-500">Checking readiness…</p>;
  }

  // Once most steps are done the list is only in the way (operator trial F13): one line, or nothing.
  const done = steps.filter((step) => step.done).length;
  const next = steps.find((step) => !step.done);
  if (!next) return null;
  if (done >= 2) {
    return (
      <p aria-label="Problem readiness" role="note" className="mb-3 text-sm text-slate-600">
        {done} of {steps.length} steps done. Next:{" "}
        <Link to={next.href} className="font-medium text-blue-700 underline">{next.label}</Link>
      </p>
    );
  }

  return (
    <section aria-label="Problem readiness" className="mb-6 rounded-md border border-slate-200 bg-slate-50 p-4">
      <h2 className="mb-1 text-sm font-semibold text-slate-900">Continue this problem</h2>
      <p className="mb-3 text-xs text-slate-600">Next incomplete steps. Experienced users can skip ahead.</p>
      <ol className="space-y-2 text-sm">
        {steps.map((step) => (
          <li key={step.label} className="flex items-center gap-2">
            <span
              aria-hidden
              className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs ${
                step.done ? "bg-green-100 text-green-800" : "bg-white text-slate-500 ring-1 ring-slate-300"
              }`}
            >
              {step.done ? "✓" : "·"}
            </span>
            {step.done ? (
              <span className="text-slate-600 line-through">{step.label}</span>
            ) : (
              <Link to={step.href} className="font-medium text-blue-700 underline">
                {step.label}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
