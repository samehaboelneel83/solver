import { useState } from "react";
import type { FormDraft } from "./draftIr";
import { keptWords, proposeDraft, type Data, type Kind, type Recipe } from "./draftFromWords";
import type { Link } from "./recipes";

const RECIPES: [Recipe, string][] = [["coverage", "places within reach"], ["selection", "projects within a budget"],
  ["network", "a supply network"], ["phasing", "projects over periods"], ["allocation", "land among crops"], ["flow", "traffic over roads"]];

/**
 * Describe the problem, get a first draft (benchmark, October 2026, G3c): the recipe the words call
 * for, filled in from this workspace's kinds, fields and data, each choice with its reason -- and
 * what is still missing. Written into the model only when asked.
 */
export default function DescribeToDraft({ kinds, data, links = [], onApply, startOpen = false, domainId }: {
  kinds: Kind[]; data: Data[]; links?: Link[]; onApply: (edit: (draft: FormDraft) => FormDraft) => void; startOpen?: boolean;
  /** The words typed on the Start page for this workspace start the box. */
  domainId?: number | string;
}) {
  const [text, setText] = useState(() => keptWords(domainId));
  const [only, setOnly] = useState<Recipe | "">("");
  const [done, setDone] = useState(false);
  const proposal = proposeDraft(text, kinds, data, only || undefined, links);
  return (
    <details className="mb-6 rounded-md border border-violet-200 bg-violet-50 p-3" open={startOpen || undefined}>
      <summary className="cursor-pointer text-sm font-semibold text-violet-900">Describe the problem in words, and get a first draft</summary>
      <div className="mt-3 space-y-2 text-sm text-slate-800">
        <textarea aria-label="The problem in words" className="h-20 w-full rounded border border-slate-300 px-2 py-1"
          value={text} onChange={(e) => { setText(e.target.value); setDone(false); }}
          placeholder="e.g. Choose up to 5 projects within a budget of 2 million, the most benefit first" />
        {text.trim().length >= 12 && !proposal && (
          <p className="text-slate-600">Nothing in those words matched a recipe yet: say what is chosen, and what limits it.</p>
        )}
        {proposal && (
          <section aria-label="The proposed draft" className="rounded border border-violet-200 bg-white p-3">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <h3 className="font-semibold text-slate-900">{proposal.title}</h3>
              <label className="text-xs text-slate-600">not this? read it as
                <select aria-label="Read it as" className="ml-1 rounded border border-slate-300 px-1 py-0.5 text-xs"
                  value={only} onChange={(e) => { setOnly(e.target.value as Recipe | ""); setDone(false); }}>
                  <option value="">the best fit</option>
                  {RECIPES.map(([r, words]) => <option key={r} value={r}>{words}</option>)}
                </select>
              </label>
            </div>
            <ul className="list-disc pl-5 text-xs text-slate-700">{proposal.choices.slice(1).map((c) => <li key={c}>{c}</li>)}</ul>
            {proposal.missing.length > 0 && (
              <div role="note" className="mt-2 text-xs text-amber-800">
                Still needed before it can be written:
                <ul className="list-disc pl-5">{proposal.missing.map((m) => <li key={m}>{m}</li>)}</ul>
              </div>
            )}
            <button type="button" disabled={!proposal.apply} className="mt-2 rounded-md bg-violet-800 px-3 py-1.5 text-white disabled:opacity-60"
              onClick={() => { if (proposal.apply) { onApply(proposal.apply); setDone(true); } }}>
              Write this draft into the model
            </button>
            {done && <p role="status" className="mt-1 text-green-800">Written below: its decisions, rules and goals are ordinary parts of the model to read and change.</p>}
          </section>
        )}
      </div>
    </details>
  );
}
