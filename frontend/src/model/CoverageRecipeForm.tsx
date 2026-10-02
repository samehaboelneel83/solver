import { useState } from "react";
import { applyCoverage, type CoverageRecipe } from "./coverageRecipe";
import type { FormDraft } from "./draftIr";

type Kind = { name: string; attributes: { name: string; data_type: string }[] };
type Data = { name: string; index: string[] };

const SELECT = "rounded border border-slate-300 bg-white px-2 py-1 text-sm";
const numberFields = (kind: Kind | undefined) =>
  (kind?.attributes ?? []).filter((a) => a.data_type === "integer" || a.data_type === "number").map((a) => a.name);

/**
 * "Where to open, so the rest is covered" in one form (user trial): which kind is opened, which is
 * covered, the 0/1 reach data between them, a cost and a budget, and what makes a place worth
 * covering. Applying it writes the decisions, the rules and the goals into the draft, to read and
 * change like any other.
 */
export default function CoverageRecipeForm({ kinds, data, onApply }: {
  kinds: Kind[];
  /** The domain's parameters, each with the kinds it is indexed by. */
  data: Data[];
  onApply: (edit: (draft: FormDraft) => FormDraft) => void;
}) {
  const [sites, setSites] = useState("");
  const [places, setPlaces] = useState("");
  const [cost, setCost] = useState("");
  const [budget, setBudget] = useState("");
  const [weights, setWeights] = useState<string[]>([]);
  const [coverAll, setCoverAll] = useState(false);
  const reachOptions = data.filter((d) => d.index.length === 2 && sites && places && d.index.includes(sites) && d.index.includes(places) && sites !== places);
  const [reachChoice, setReachChoice] = useState("");
  const reach = reachOptions.find((d) => d.name === reachChoice) ?? reachOptions[0];
  const siteKind = kinds.find((k) => k.name === sites);
  const placeKind = kinds.find((k) => k.name === places);
  const budgetNumber = budget.trim() === "" ? undefined : Number(budget.replace(/,/g, ""));
  const ready = !!sites && !!places && !!reach && (budgetNumber === undefined || Number.isFinite(budgetNumber));

  return (
    <details className="mb-6 rounded-md border border-sky-200 bg-sky-50 p-3">
      <summary className="cursor-pointer text-sm font-semibold text-sky-900">
        Recipe: choose places to open so others are within reach (cooling centres, depots, clinics…)
      </summary>
      <form
        aria-label="Coverage recipe"
        className="mt-3 space-y-3 text-sm text-slate-800"
        onSubmit={(event) => {
          event.preventDefault();
          if (!ready || !reach) return;
          const recipe: CoverageRecipe = {
            sites, places, reach: reach.name, reachIndex: reach.index,
            ...(cost ? { cost } : {}), ...(budgetNumber !== undefined ? { budget: budgetNumber } : {}),
            weights, coverAll,
          };
          onApply((draft) => applyCoverage(draft, recipe));
        }}
      >
        <div className="flex flex-wrap items-center gap-2">
          Open some
          <select aria-label="Kind to open" className={SELECT} value={sites} onChange={(e) => { setSites(e.target.value); setCost(""); }}>
            <option value="">kind…</option>
            {kinds.map((k) => <option key={k.name} value={k.name}>{k.name}</option>)}
          </select>
          so that each
          <select aria-label="Kind to cover" className={SELECT} value={places} onChange={(e) => { setPlaces(e.target.value); setWeights([]); }}>
            <option value="">kind…</option>
            {kinds.filter((k) => k.name !== sites).map((k) => <option key={k.name} value={k.name}>{k.name}</option>)}
          </select>
          has one within reach, by
          <select aria-label="Reach data" className={SELECT} value={reach?.name ?? ""} onChange={(e) => setReachChoice(e.target.value)} disabled={!reachOptions.length}>
            {reachOptions.length === 0 && <option value="">no 0/1 data over both yet</option>}
            {reachOptions.map((d) => <option key={d.name} value={d.name}>{d.name}[{d.index.join(", ")}]</option>)}
          </select>
        </div>
        {sites && places && reachOptions.length === 0 && (
          <p className="text-xs text-amber-800">
            First make 0/1 reach data between {places} and {sites}: Map data → Compute from the map → “a 0/1 within parameter”.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          Opening one costs its
          <select aria-label="Cost field" className={SELECT} value={cost} onChange={(e) => setCost(e.target.value)}>
            <option value="">(count the sites)</option>
            {numberFields(siteKind).map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
          ; all together at most
          <input aria-label="Budget" inputMode="decimal" className={`${SELECT} w-28`} placeholder="no limit" value={budget} onChange={(e) => setBudget(e.target.value)} />
        </div>
        <fieldset className="flex flex-wrap items-center gap-3">
          <legend className="sr-only">What to cover</legend>
          <label className="flex items-center gap-1">
            <input type="radio" name="cover" checked={!coverAll} onChange={() => setCoverAll(false)} /> cover the most, worth
          </label>
          {numberFields(placeKind).map((f) => (
            <label key={f} className={`flex items-center gap-1 ${coverAll ? "opacity-50" : ""}`}>
              <input type="checkbox" disabled={coverAll} checked={weights.includes(f)}
                onChange={(e) => setWeights(e.target.checked ? [...weights, f] : weights.filter((w) => w !== f))} /> {f}
            </label>
          ))}
          <span className="text-xs text-slate-500">(multiplied; none ticked: each counts 1), then spend the least</span>
          <label className="flex items-center gap-1">
            <input type="radio" name="cover" checked={coverAll} onChange={() => setCoverAll(true)} /> cover every one, at the least cost
          </label>
        </fieldset>
        <div className="flex items-center gap-3">
          <button type="submit" disabled={!ready} className="rounded-md bg-sky-700 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
            Write these rules and goals
          </button>
          <span className="text-xs text-slate-600">They are added to the draft below, to read and change; the goals replace any there.</span>
        </div>
      </form>
    </details>
  );
}
