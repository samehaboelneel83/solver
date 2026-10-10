import { useMutation } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";

type Used = { non_zero: number; cells: number; chosen?: string[] };
type Trial = { status: string; objective?: number | null; solver?: string; seconds?: number; why?: string;
  used?: Record<string, Used> };
type Checked = { refusal: { code: string; loc: (string | number)[]; message: string } | null; readback: string[]; trial?: Trial };

/** The trial in one sentence, with the warnings a person needs before publishing. */
function trialWords(trial: Trial): string {
  if (["not compiled", "skipped", "no solver", "failed", "no answer"].includes(trial.status)) {
    return `Not trial-solved (${trial.status}${trial.why ? `: ${trial.why}` : ""}).`;
  }
  const goal = typeof trial.objective === "number" ? `, goal ${trial.objective.toLocaleString("en-US")}` : "";
  const used = Object.entries(trial.used ?? {}).map(([name, u]) =>
    `${name} used in ${u.non_zero.toLocaleString("en-US")} of ${u.cells.toLocaleString("en-US")}${u.chosen?.length ? ` (${u.chosen.join(", ")})` : ""}`);
  let words = `Trial on this domain's data (solved once for up to ${trial.seconds ?? 15} s, nothing kept): ${trial.status}${goal}`
    + (used.length ? `; ${used.join("; ")}` : "") + ".";
  if (trial.status === "infeasible") words += " No answer exists with these rules and this data.";
  else if (used.length && Object.values(trial.used ?? {}).every((u) => !u.non_zero)) words += " It chooses or makes nothing.";
  return words;
}

/**
 * The draft read back in the platform's own words, and solved once on the domain's data -- what `check_spec`
 * gives the Assistant before it proposes a plan, here for anyone editing a model (owner, 9 October 2026).
 */
export function DraftCheck({ problemId, ir }: { problemId: number; ir: Record<string, unknown> | null }) {
  const check = useMutation({
    mutationFn: (trial: boolean) => apiFetch<Checked>(`/api/v1/problems/${problemId}/draft-check`, {
      method: "POST", body: JSON.stringify({ ir, trial }),
    }),
  });
  return (
    <section aria-labelledby="draft-check" className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
      <h3 id="draft-check" className="font-semibold text-slate-900">Read it back and try it</h3>
      <p className="text-sm text-slate-600">
        The platform reads the draft back in words -- which records each rule ranges over, what each decision is,
        what the goal adds up -- so you can compare it with what you meant; a trial solves it once on this domain's
        data before anything is published.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" className="rounded border px-3 py-1.5 text-sm disabled:opacity-50" disabled={!ir || check.isPending}
          onClick={() => check.mutate(false)}>Read it back</button>
        <button type="button" className="rounded bg-blue-700 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          disabled={!ir || check.isPending} onClick={() => check.mutate(true)}>
          {check.isPending ? "Checking…" : "Read it back and trial-solve"}</button>
      </div>
      {check.isError && <p role="alert" className="mt-2 text-sm text-red-700">{formatApiError(check.error)}</p>}
      {check.data && (
        <div className="mt-3 space-y-2 text-sm" aria-live="polite">
          {check.data.refusal && <p role="alert" className="text-red-700">
            Not publishable yet: {check.data.refusal.message}{" "}
            <span className="font-mono text-xs">[{check.data.refusal.code} at {check.data.refusal.loc.join(" / ")}]</span></p>}
          <ul aria-label="As built" className="list-none space-y-0.5 font-mono text-xs">
            {check.data.readback.filter((line) => line.trim()).map((line, n) => <li key={n}>{line}</li>)}
          </ul>
          {check.data.trial && <p role="status" className={check.data.trial.status === "infeasible" ? "text-red-700" : ""}>
            {trialWords(check.data.trial)}</p>}
        </div>
      )}
    </section>
  );
}
