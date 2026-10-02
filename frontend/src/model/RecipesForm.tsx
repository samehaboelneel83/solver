import { useState, type ReactNode } from "react";
import type { FormDraft } from "./draftIr";
import { applyNetwork, applyPhasing, applySelection } from "./recipes";

type Kind = { name: string; attributes: { name: string; data_type: string }[] };
type Data = { name: string; index: string[] };
type Which = "selection" | "network" | "phasing";

const SELECT = "ml-1 rounded border border-slate-300 bg-white px-2 py-1 text-sm";
const numbers = (kind: Kind | undefined) =>
  (kind?.attributes ?? []).filter((a) => a.data_type === "integer" || a.data_type === "number").map((a) => a.name);
const yesNo = (kind: Kind | undefined) => (kind?.attributes ?? []).filter((a) => a.data_type === "boolean").map((a) => a.name);
const toNumber = (text: string) => (text.trim() === "" ? undefined : Number(text.replace(/,/g, "")));

function Pick({ label, value, onChange, options, optional }: {
  label: string; value: string; onChange: (v: string) => void; options: string[]; optional?: boolean;
}) {
  return (
    <label className="text-xs text-slate-700">{label}
      <select aria-label={label} className={SELECT} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{optional ? "none" : "choose…"}</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-end gap-3">{children}</div>;
}

/**
 * Three more recipes (benchmark, October 2026): projects within a budget, a supply network, and
 * projects phased over periods -- each writes its decisions, rules and goals into the draft.
 */
export default function RecipesForm({ kinds, data, onApply }: {
  kinds: Kind[];
  data: Data[];
  onApply: (edit: (draft: FormDraft) => FormDraft) => void;
}) {
  const [which, setWhich] = useState<Which>("selection");
  const [f, setF] = useState<Record<string, string>>({});
  const [done, setDone] = useState<string | null>(null);
  const set = (key: string) => (value: string) => { setF({ ...f, [key]: value }); setDone(null); };
  const kind = (key: string) => kinds.find((k) => k.name === f[key]);
  const names = kinds.map((k) => k.name);
  const get = (key: string) => f[key] ?? "";

  let ready: boolean;
  let apply: (draft: FormDraft) => FormDraft;
  let body: ReactNode;
  if (which === "selection") {
    const budget = toNumber(get("budget"));
    const atMost = toNumber(get("atMost"));
    ready = !!(f.items && f.value && f.cost && budget !== undefined && Number.isFinite(budget));
    apply = (d) => applySelection(d, { items: f.items, value: f.value, cost: f.cost, budget: budget!,
      ...(atMost !== undefined && Number.isFinite(atMost) ? { atMost } : {}), ...(f.mustHave ? { mustHave: f.mustHave } : {}) });
    body = (
      <Row>
        <Pick label="Choose among" value={get("items")} onChange={set("items")} options={names} />
        <Pick label="Worth" value={get("value")} onChange={set("value")} options={numbers(kind("items"))} />
        <Pick label="Cost" value={get("cost")} onChange={set("cost")} options={numbers(kind("items"))} />
        <label className="text-xs text-slate-700">Budget
          <input aria-label="Budget" className={`${SELECT} w-28`} inputMode="decimal" value={get("budget")} onChange={(e) => set("budget")(e.target.value)} />
        </label>
        <label className="text-xs text-slate-700">At most
          <input aria-label="At most" className={`${SELECT} w-16`} inputMode="numeric" value={get("atMost")} onChange={(e) => set("atMost")(e.target.value)} />
        </label>
        <Pick label="Always chosen when" value={get("mustHave")} onChange={set("mustHave")} options={yesNo(kind("items"))} optional />
      </Row>
    );
  } else if (which === "network") {
    const costs = data.filter((d) => d.index.length === 2 && f.sources && f.customers && d.index.includes(f.sources) && d.index.includes(f.customers));
    const unit = costs.find((d) => d.name === f.unitCost) ?? costs[0];
    const penalty = toNumber(get("penalty"));
    ready = !!(f.sources && f.customers && f.sources !== f.customers && f.demand && unit);
    const fleet = kind("fleet");
    apply = (d) => applyNetwork(d, { sources: f.sources, customers: f.customers, demand: f.demand, unitCost: unit!.name, unitCostIndex: unit!.index,
      ...(f.capacity ? { capacity: f.capacity } : {}), ...(f.openCost ? { openCost: f.openCost } : {}),
      ...(f.single === "yes" ? { singleSource: true } : {}),
      ...(penalty !== undefined && Number.isFinite(penalty) ? { shortagePenalty: penalty } : {}),
      ...(fleet && f.load && f.price ? { fleet: { kind: fleet.name, capacity: f.load, cost: f.price } } : {}) });
    body = (
      <>
        <Row>
          <Pick label="Ship from" value={get("sources")} onChange={set("sources")} options={names} />
          <Pick label="To" value={get("customers")} onChange={set("customers")} options={names} />
          <Pick label="Each needs" value={get("demand")} onChange={set("demand")} options={numbers(kind("customers"))} />
          <Pick label="Cost a unit" value={unit?.name ?? ""} onChange={set("unitCost")} options={costs.map((d) => d.name)} />
        </Row>
        {f.sources && f.customers && costs.length === 0 && (
          <p className="text-xs text-amber-800">No data value is indexed by both {f.sources} and {f.customers}: make one (a distance from the map, or uploaded) first.</p>
        )}
        <Row>
          <Pick label="Capacity" value={get("capacity")} onChange={set("capacity")} options={numbers(kind("sources"))} optional />
          <Pick label="Opening cost" value={get("openCost")} onChange={set("openCost")} options={numbers(kind("sources"))} optional />
          <Pick label="One supplier each" value={get("single")} onChange={set("single")} options={["yes"]} optional />
          <label className="text-xs text-slate-700">Shortage allowed, a unit costs
            <input aria-label="Shortage cost" className={`${SELECT} w-24`} inputMode="decimal" value={get("penalty")} onChange={(e) => set("penalty")(e.target.value)} />
          </label>
        </Row>
        <Row>
          <Pick label="Vehicles by type" value={get("fleet")} onChange={set("fleet")} options={names} optional />
          {fleet && <Pick label="Each carries" value={get("load")} onChange={set("load")} options={numbers(fleet)} />}
          {fleet && <Pick label="Each costs" value={get("price")} onChange={set("price")} options={numbers(fleet)} />}
        </Row>
      </>
    );
  } else {
    ready = !!(f.items && f.periods && f.items !== f.periods && f.value && f.cost && f.budget);
    apply = (d) => applyPhasing(d, { items: f.items, periods: f.periods, value: f.value, cost: f.cost, budget: f.budget,
      ...(f.weight ? { weight: f.weight } : {}), ...(f.all === "yes" ? { all: true } : {}) });
    body = (
      <>
        <Row>
          <Pick label="Start" value={get("items")} onChange={set("items")} options={names} />
          <Pick label="In" value={get("periods")} onChange={set("periods")} options={names} />
          <Pick label="Worth" value={get("value")} onChange={set("value")} options={numbers(kind("items"))} />
          <Pick label="Cost" value={get("cost")} onChange={set("cost")} options={numbers(kind("items"))} />
        </Row>
        <Row>
          <Pick label="Each period's budget" value={get("budget")} onChange={set("budget")} options={numbers(kind("periods"))} />
          <Pick label="Sooner counts" value={get("weight")} onChange={set("weight")} options={numbers(kind("periods"))} optional />
          <Pick label="Every one started" value={get("all")} onChange={set("all")} options={["yes"]} optional />
        </Row>
      </>
    );
  }

  return (
    <details className="mb-6 rounded-md border border-sky-200 bg-sky-50 p-3">
      <summary className="cursor-pointer text-sm font-semibold text-sky-900">
        More recipes: projects within a budget, a supply network, projects over years
      </summary>
      <form aria-label="More recipes" className="mt-3 space-y-3 text-sm text-slate-800"
        onSubmit={(e) => {
          e.preventDefault();
          if (!ready) return;
          onApply(apply);
          setDone("Written into the model below: read and change it like any other part.");
        }}>
        <div role="radiogroup" aria-label="Recipe" className="flex flex-wrap gap-3 text-xs">
          {([["selection", "Choose projects within a budget"], ["network", "Supply network: open, ship, fleet"],
            ["phasing", "Phase projects over periods"]] as [Which, string][]).map(([w, words]) => (
            <label key={w}><input type="radio" checked={which === w} onChange={() => { setWhich(w); setF({}); setDone(null); }} /> {words}</label>
          ))}
        </div>
        {body}
        <button type="submit" disabled={!ready} className="rounded-md bg-sky-800 px-3 py-1.5 text-white disabled:opacity-60">Write it into the model</button>
        {done && <p role="status" className="text-green-800">{done}</p>}
      </form>
    </details>
  );
}
