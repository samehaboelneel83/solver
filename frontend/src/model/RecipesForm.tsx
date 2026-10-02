import { useState, type ReactNode } from "react";
import type { FormDraft } from "./draftIr";
import { applyAllocation, applyFlow, applyInventory, endsOf, type Link, applyNetwork, applyPhasing, applySelection } from "./recipes";

type Kind = { name: string; attributes: { name: string; data_type: string }[] };
type Data = { name: string; index: string[] };
type Which = "selection" | "network" | "phasing" | "allocation" | "flow" | "inventory";

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
 * More recipes (benchmark, October 2026): projects within a budget, a supply network, projects
 * phased over periods, land among crops, traffic over roads, stock over periods -- each writes its
 * decisions, rules and goals into the draft.
 */
export default function RecipesForm({ kinds, data, links = [], onApply }: {
  kinds: Kind[];
  data: Data[];
  /** Relationships between kinds: a road's start and end for traffic. */
  links?: Link[];
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
  } else if (which === "allocation") {
    // Land among crops (benchmark re-test, October 2026).
    const over = data.filter((d) => d.index.length === 2 && f.items && f.options && d.index.includes(f.items) && d.index.includes(f.options));
    const worthData = over.find((d) => d.name === f.worth);
    const allowed = over.find((d) => d.name === f.allowed);
    const limit = toNumber(get("limit"));
    ready = !!(f.items && f.options && f.items !== f.options && f.size && f.worth);
    apply = (d) => applyAllocation(d, { items: f.items, options: f.options, size: f.size,
      worth: worthData ? { data: worthData.name, index: worthData.index } : { field: f.worth },
      ...(f.use && limit !== undefined && Number.isFinite(limit) ? { use: { field: f.use, limit } } : {}),
      ...(allowed ? { allowed: { data: allowed.name, index: allowed.index } } : {}),
      ...(f.minShare ? { minShare: f.minShare } : {}), ...(f.maxShare ? { maxShare: f.maxShare } : {}),
      ...(f.all === "yes" ? { all: true } : {}) });
    body = (
      <>
        <Row>
          <Pick label="Share out each" value={get("items")} onChange={set("items")} options={names} />
          <Pick label="Among" value={get("options")} onChange={set("options")} options={names} />
          <Pick label="Its size" value={get("size")} onChange={set("size")} options={numbers(kind("items"))} />
          <Pick label="A unit is worth" value={get("worth")} onChange={set("worth")} options={[...numbers(kind("options")), ...over.map((d) => d.name)]} />
        </Row>
        <Row>
          <Pick label="Uses" value={get("use")} onChange={set("use")} options={numbers(kind("options"))} optional />
          <label className="text-xs text-slate-700">up to
            <input aria-label="Shared limit" className={`${SELECT} w-28`} inputMode="decimal" value={get("limit")} onChange={(e) => set("limit")(e.target.value)} />
          </label>
          <Pick label="Only where" value={get("allowed")} onChange={set("allowed")} options={over.map((d) => d.name)} optional />
          <Pick label="Least share" value={get("minShare")} onChange={set("minShare")} options={numbers(kind("options"))} optional />
          <Pick label="Most share" value={get("maxShare")} onChange={set("maxShare")} options={numbers(kind("options"))} optional />
          <Pick label="All of it given out" value={get("all")} onChange={set("all")} options={["yes"]} optional />
        </Row>
      </>
    );
  } else if (which === "flow") {
    // Traffic: a table of trips between zones over the roads (benchmark re-test, October 2026).
    const ends = links.filter((l) => f.arcs && f.nodes && l.from === f.arcs && l.to === f.nodes);
    const guess = endsOf(ends);
    const startsAt = f.startsAt || guess.startsAt || "";
    const endsAt = f.endsAt || guess.endsAt || "";
    const trips = data.filter((d) => f.nodes && d.index.length === 2 && d.index[0] === f.nodes && d.index[1] === f.nodes);
    const budget = toNumber(get("budget"));
    const widen = !!(f.capacity && f.added && f.widenCost && budget !== undefined && Number.isFinite(budget));
    ready = !!(f.nodes && f.arcs && f.nodes !== f.arcs && startsAt && endsAt && startsAt !== endsAt && f.trips && f.time);
    apply = (d) => applyFlow(d, { nodes: f.nodes, arcs: f.arcs, startsAt, endsAt, trips: f.trips, time: f.time,
      ...(f.capacity ? { capacity: f.capacity } : {}), ...(widen ? { upgrade: { added: f.added, cost: f.widenCost, budget: budget! } } : {}) });
    body = (
      <>
        <Row>
          <Pick label="Trips between" value={get("nodes")} onChange={set("nodes")} options={names} />
          <Pick label="Over" value={get("arcs")} onChange={set("arcs")} options={names} />
          <Pick label="A road starts at" value={startsAt} onChange={set("startsAt")} options={ends.map((l) => l.name)} />
          <Pick label="and ends at" value={endsAt} onChange={set("endsAt")} options={ends.map((l) => l.name)} />
        </Row>
        {f.nodes && f.arcs && ends.length < 2 && (
          <p className="text-xs text-amber-800">A {f.arcs} needs two links to {f.nodes}: where it starts and where it ends (Records → link records on a matching field).</p>
        )}
        <Row>
          <Pick label="How many trips" value={get("trips")} onChange={set("trips")} options={trips.map((d) => d.name)} />
          <Pick label="Time on a road" value={get("time")} onChange={set("time")} options={numbers(kind("arcs"))} />
          <Pick label="Capacity" value={get("capacity")} onChange={set("capacity")} options={numbers(kind("arcs"))} optional />
        </Row>
        {f.nodes && trips.length === 0 && (
          <p className="text-xs text-amber-800">No data value is indexed by {f.nodes} twice (origin, destination): upload the trips table as one first.</p>
        )}
        {f.capacity && (
          <Row>
            <Pick label="Widening adds" value={get("added")} onChange={set("added")} options={numbers(kind("arcs"))} optional />
            <Pick label="Widening costs" value={get("widenCost")} onChange={set("widenCost")} options={numbers(kind("arcs"))} optional />
            <label className="text-xs text-slate-700">Widening budget
              <input aria-label="Widening budget" className={`${SELECT} w-28`} inputMode="decimal" value={get("budget")} onChange={(e) => set("budget")(e.target.value)} />
            </label>
          </Row>
        )}
      </>
    );
  } else if (which === "inventory") {
    // Stock per product over periods, at each location (benchmark re-test, October 2026).
    const shape = [f.products, f.periods, ...(f.locations ? [f.locations] : [])];
    const needed = data.filter((d) => f.products && f.periods && d.index.length === shape.length && shape.every((k) => d.index.includes(k)));
    const demand = needed.find((d) => d.name === f.demand) ?? needed[0];
    const startData = data.filter((d) => f.locations && d.index.length === 2 && d.index.includes(f.products) && d.index.includes(f.locations));
    const start = startData.find((d) => d.name === f.initial);
    const room = toNumber(get("room"));
    const penalty = toNumber(get("penalty"));
    ready = !!(f.products && f.periods && new Set(shape).size === shape.length && demand);
    apply = (d) => applyInventory(d, { products: f.products, periods: f.periods, ...(f.locations ? { locations: f.locations } : {}),
      demand: { data: demand!.name, index: demand!.index },
      ...(start ? { initial: { data: start.name, index: start.index } } : f.initial ? { initial: { field: f.initial } } : {}),
      ...(f.unitCost ? { unitCost: f.unitCost } : {}), ...(f.holdCost ? { holdCost: f.holdCost } : {}), ...(f.orderMax ? { orderMax: f.orderMax } : {}),
      ...(f.locations && f.capacity ? { storage: { capacity: f.capacity, ...(f.size ? { size: f.size } : {}) } }
        : room !== undefined && Number.isFinite(room) ? { storage: { capacity: room, ...(f.size ? { size: f.size } : {}) } } : {}),
      ...(penalty !== undefined && Number.isFinite(penalty) ? { shortagePenalty: penalty } : {}) });
    body = (
      <>
        <Row>
          <Pick label="Stock of" value={get("products")} onChange={set("products")} options={names} />
          <Pick label="Each" value={get("periods")} onChange={set("periods")} options={names} />
          <Pick label="At each" value={get("locations")} onChange={set("locations")} options={names} optional />
          <Pick label="Needed" value={demand?.name ?? ""} onChange={set("demand")} options={needed.map((d) => d.name)} />
        </Row>
        {f.products && f.periods && needed.length === 0 && (
          <p className="text-xs text-amber-800">No data value is indexed by {shape.join(", ")}: upload what is needed (a forecast) as one first.</p>
        )}
        <Row>
          <Pick label="On hand at the start" value={get("initial")} onChange={set("initial")} options={[...numbers(kind("products")), ...startData.map((d) => d.name)]} optional />
          <Pick label="Cost to order a unit" value={get("unitCost")} onChange={set("unitCost")} options={numbers(kind("products"))} optional />
          <Pick label="Cost to hold a unit" value={get("holdCost")} onChange={set("holdCost")} options={numbers(kind("products"))} optional />
          <Pick label="Most ordered at once" value={get("orderMax")} onChange={set("orderMax")} options={numbers(kind("products"))} optional />
        </Row>
        <Row>
          {f.locations
            ? <Pick label="Room in store" value={get("capacity")} onChange={set("capacity")} options={numbers(kind("locations"))} optional />
            : <label className="text-xs text-slate-700">Room in store
              <input aria-label="Room in store" className={`${SELECT} w-24`} inputMode="decimal" value={get("room")} onChange={(e) => set("room")(e.target.value)} />
            </label>}
          <Pick label="A unit takes" value={get("size")} onChange={set("size")} options={numbers(kind("products"))} optional />
          <label className="text-xs text-slate-700">Lost sales allowed, a unit costs
            <input aria-label="Lost sale cost" className={`${SELECT} w-24`} inputMode="decimal" value={get("penalty")} onChange={(e) => set("penalty")(e.target.value)} />
          </label>
        </Row>
      </>
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
        More recipes: projects within a budget, a supply network, projects over years, land among crops, traffic over roads, stock over periods
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
            ["phasing", "Phase projects over periods"], ["allocation", "Share land among crops"],
            ["flow", "Traffic: trips over the roads"], ["inventory", "Stock: order each period"]] as [Which, string][]).map(([w, words]) => (
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
