import { useState } from "react";
import { applyCoverage, say, type CoverageRecipe } from "./coverageRecipe";
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
export default function CoverageRecipeForm({ kinds, data, links = [], onApply }: {
  kinds: Kind[];
  /** The domain's parameters, each with the kinds it is indexed by. */
  data: Data[];
  /** The domain's relationship types between kinds: a team's hospital, a van's depot. */
  links?: { name: string; from: string; to: string }[];
  onApply: (edit: (draft: FormDraft) => FormDraft) => void;
}) {
  const [sites, setSites] = useState("");
  const [places, setPlaces] = useState("");
  const [cost, setCost] = useState("");
  const [budget, setBudget] = useState("");
  const [weights, setWeights] = useState<string[]>([]);
  const [coverAll, setCoverAll] = useState(false);
  const [avoidLink, setAvoidLink] = useState("");
  const [avoidUnless, setAvoidUnless] = useState("");
  const siteLinks = links.flatMap((l): { rel: string; end: "from" | "to"; kind: string }[] =>
    l.from === sites && l.to !== sites ? [{ rel: l.name, end: "from", kind: l.to }]
      : l.to === sites && l.from !== sites ? [{ rel: l.name, end: "to", kind: l.from }] : []);
  const avoid = siteLinks.find((l) => l.rel === avoidLink) ?? null;
  const [staffKind, setStaffKind] = useState("");
  const [staffCap, setStaffCap] = useState("");
  const [staffNeeds, setStaffNeeds] = useState("");
  const [seatCap, setSeatCap] = useState("");
  const [seatDemand, setSeatDemand] = useState<string[]>([]);
  const [mustField, setMustField] = useState("");
  const [mustAtLeast, setMustAtLeast] = useState("");
  const [seatShare, setSeatShare] = useState("100");
  const [staffLink, setStaffLink] = useState("");
  const [staffReach, setStaffReach] = useState("");
  // A link from the staff kind to another kind (team -> hospital), read from either end.
  type StaffLink = { rel: string; end: "from" | "to"; kind: string };
  const staffLinks = links.flatMap((l): StaffLink[] =>
    l.from === staffKind && l.to !== staffKind ? [{ rel: l.name, end: "from" as const, kind: l.to }]
      : l.to === staffKind && l.from !== staffKind ? [{ rel: l.name, end: "to" as const, kind: l.from }] : []);
  const link = staffLinks.find((l) => l.rel === staffLink) ?? null;
  const linkReach = link ? data.filter((d) => d.index.length === 2 && d.index.includes(link.kind) && d.index.includes(sites) && link.kind !== sites) : [];
  const viaReach = linkReach.find((d) => d.name === staffReach) ?? linkReach[0];
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
            ...(avoid ? { avoid: { ...avoid, ...(avoidUnless ? { unless: avoidUnless } : {}) } } : {}),
            ...(!coverAll && mustField && mustAtLeast.trim() !== "" && Number.isFinite(Number(mustAtLeast))
              ? { mustCover: { field: mustField, atLeast: Number(mustAtLeast) } } : {}),
            ...(!coverAll && seatCap && seatDemand.length ? { seats: { capacity: seatCap, demand: seatDemand,
              ...(Number(seatShare) > 0 && Number(seatShare) < 100 ? { share: Number(seatShare) / 100 } : {}) } } : {}),
            ...(staffKind ? { staff: {
              kind: staffKind, ...(staffCap ? { capacity: staffCap } : {}), ...(staffNeeds ? { needs: staffNeeds } : {}),
              ...(link && viaReach ? { via: { rel: link.rel, end: link.end, kind: link.kind, reach: viaReach.name, reachIndex: viaReach.index } } : {}),
            } } : {}),
          };
          onApply((draft) => applyCoverage(draft, recipe));
        }}
      >
        <div className="flex flex-wrap items-center gap-2">
          Open some
          <select aria-label="Kind to open" className={SELECT} value={sites} onChange={(e) => { setSites(e.target.value); setCost(""); }}>
            <option value="">kind…</option>
            {kinds.map((k) => <option key={k.name} value={k.name}>{say(k.name)}</option>)}
          </select>
          so that each
          <select aria-label="Kind to cover" className={SELECT} value={places} onChange={(e) => { setPlaces(e.target.value); setWeights([]); }}>
            <option value="">kind…</option>
            {kinds.filter((k) => k.name !== sites).map((k) => <option key={k.name} value={k.name}>{say(k.name)}</option>)}
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
        {siteLinks.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-sky-200 pt-2">
            Never open one linked by
            <select aria-label="Avoid link" className={SELECT} value={avoidLink} onChange={(e) => setAvoidLink(e.target.value)}>
              <option value="">(no such rule)</option>
              {siteLinks.map((l) => <option key={l.rel} value={l.rel}>{l.rel} (to a {l.kind})</option>)}
            </select>
            {avoid && (
              <>
                unless its
                <select aria-label="Avoid unless" className={SELECT} value={avoidUnless} onChange={(e) => setAvoidUnless(e.target.value)}>
                  <option value="">(no exception)</option>
                  {(kinds.find((k) => k.name === sites)?.attributes ?? []).filter((a) => a.data_type === "boolean")
                    .map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
                </select>
                is yes
              </>
            )}
          </div>
        )}
        {!coverAll && numberFields(placeKind).length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-sky-200 pt-2">
            Never leave out a {places ? say(places) : "place"} whose
            <select aria-label="Must-cover field" className={SELECT} value={mustField} onChange={(e) => setMustField(e.target.value)}>
              <option value="">(no such rule)</option>
              {numberFields(placeKind).map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            {mustField && (
              <>
                is at least
                <input aria-label="Must-cover from" inputMode="decimal" className={`${SELECT} w-20`} value={mustAtLeast} onChange={(e) => setMustAtLeast(e.target.value)} />
                <span className="text-xs text-slate-500">(if the budget cannot reach them all, the answer says so)</span>
              </>
            )}
          </div>
        )}
        {!coverAll && numberFields(siteKind).length > 0 && numberFields(placeKind).length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-sky-200 pt-2">
            Count a {places || "place"} covered only if its
            {numberFields(placeKind).map((f) => (
              <label key={f} className="flex items-center gap-1">
                <input type="checkbox" checked={seatDemand.includes(f)}
                  onChange={(e) => setSeatDemand(e.target.checked ? [...seatDemand, f] : seatDemand.filter((d) => d !== f))} /> {f}
              </label>
            ))}
            <span className="text-xs text-slate-500">(multiplied: the people)</span>
            — of whom
            <input aria-label="Share needing a seat" inputMode="decimal" className={`${SELECT} w-16`} value={seatShare} onChange={(e) => setSeatShare(e.target.value)} />
            % at once — find seats at open ones within reach, each holding at most its
            <select aria-label="Seats field" className={SELECT} value={seatCap} onChange={(e) => setSeatCap(e.target.value)}>
              <option value="">(no seat limit)</option>
              {numberFields(siteKind).map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2 border-t border-sky-200 pt-2">
          Each open one needs
          <select aria-label="Staff needed" className={SELECT} value={staffNeeds} onChange={(e) => setStaffNeeds(e.target.value)} disabled={!staffKind}>
            <option value="">one</option>
            {numberFields(siteKind).map((f) => <option key={f} value={f}>as many as its {f}</option>)}
          </select>
          <select aria-label="Staff kind" className={SELECT} value={staffKind}
            onChange={(e) => { setStaffKind(e.target.value); setStaffCap(""); setStaffLink(""); setStaffReach(""); }}>
            <option value="">(nobody: leave out)</option>
            {kinds.filter((k) => k.name !== sites && k.name !== places).map((k) => <option key={k.name} value={k.name}>{say(k.name)}</option>)}
          </select>
          {staffKind && (
            <>
              , serving at most its
              <select aria-label="Staff capacity field" className={SELECT} value={staffCap} onChange={(e) => setStaffCap(e.target.value)}>
                <option value="">(no limit)</option>
                {numberFields(kinds.find((k) => k.name === staffKind)).map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
              {staffLinks.length > 0 && (
                <>
                  , and only {sites || "sites"} its
                  <select aria-label="Staff link" className={SELECT} value={staffLink} onChange={(e) => setStaffLink(e.target.value)}>
                    <option value="">(any {sites || "site"})</option>
                    {staffLinks.map((l) => <option key={l.rel} value={l.rel}>{l.rel} ({l.kind})</option>)}
                  </select>
                  {link && (
                    <>
                      reaches, by
                      <select aria-label="Staff reach data" className={SELECT} value={viaReach?.name ?? ""} onChange={(e) => setStaffReach(e.target.value)} disabled={!linkReach.length}>
                        {linkReach.length === 0 && <option value="">no 0/1 data over {link.kind} and {sites} yet</option>}
                        {linkReach.map((d) => <option key={d.name} value={d.name}>{d.name}[{d.index.join(", ")}]</option>)}
                      </select>
                    </>
                  )}
                </>
              )}
            </>
          )}
        </div>
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
