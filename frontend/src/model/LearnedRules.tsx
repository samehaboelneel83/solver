import { useState } from "react";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";

/** One rule every past plan kept and the model does not say (app.solve.learn). */
export type LearnedRule = {
  id: string;
  decision: string;
  by: string[];
  over: string[];
  direction: "most" | "least";
  bound: number;
  model_allows: number | null;
  plans: number;
  says: string;
  rule: Record<string, unknown> & { id: string };
};

type Learned = { plans: number; rules: LearnedRule[]; says: string; source: string; runs: number[] };

/**
 * Rules learnt from past plans: what every approved plan (or every answer) kept that the model does not say,
 * each ready to add. Nothing is added unasked -- a planner reads each one.
 */
export default function LearnedRules({
  problemId,
  taken,
  onAdd,
}: {
  problemId: number;
  /** Rule ids the model already has: a learnt rule is added under a free one. */
  taken: string[];
  onAdd: (rule: Record<string, unknown>) => void;
}) {
  const [source, setSource] = useState<"approved" | "answered">("approved");
  const [found, setFound] = useState<Learned | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<string[]>([]);

  async function learn() {
    setBusy(true);
    setError(null);
    try {
      setFound(await apiFetch<Learned>(`/api/v1/problems/${problemId}/learned-rules?source=${source}`));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  function add(learnt: LearnedRule) {
    let id = learnt.rule.id;
    for (let n = 2; taken.includes(id); n += 1) id = `${learnt.rule.id}_${n}`;
    onAdd({ ...learnt.rule, id });
    setAdded((current) => [...current, learnt.id]);
  }

  return (
    <details className="mt-4 rounded-md border border-slate-200 p-3 text-sm">
      <summary className="cursor-pointer font-medium text-slate-800">Rules your past plans kept</summary>
      <p className="mt-2 text-slate-600">
        Finds limits every past plan stayed within that the model does not say -- nobody over three days, never
        fewer than two a shift -- so its answers stop breaking them. Each one is a rule you can add; nothing is
        added by itself.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <label className="inline-flex items-center gap-1">
          Learn from
          <select className="rounded border border-slate-300 px-1 py-0.5" value={source}
            onChange={(e) => setSource(e.target.value as "approved" | "answered")}>
            <option value="approved">the plans people approved</option>
            <option value="answered">this problem&rsquo;s recent answers</option>
          </select>
        </label>
        <button type="button" onClick={() => void learn()} disabled={busy}
          className="rounded border border-blue-600 px-3 py-1 text-blue-700 hover:bg-blue-50 disabled:opacity-60">
          {busy ? "Learning…" : "Learn rules"}
        </button>
      </div>
      {error && <p role="alert" className="mt-2 text-red-600">{error}</p>}
      {found && (
        <div className="mt-3">
          <p className="text-slate-700">{found.says}</p>
          <ul className="mt-2 space-y-2">
            {found.rules.map((learnt) => (
              <li key={learnt.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-200 px-3 py-2">
                <span className="text-slate-800">{learnt.says}</span>
                {added.includes(learnt.id) ? (
                  <span className="text-xs text-green-800">Added to the draft</span>
                ) : (
                  <button type="button" onClick={() => add(learnt)}
                    className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50">
                    Add as a rule
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </details>
  );
}
