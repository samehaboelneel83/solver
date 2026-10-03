/**
 * Three more recipes (benchmark, October 2026, G3d): each writes the decisions, rules and goals a
 * common kind of model needs into the draft from one short form, to read and change like any other.
 *
 * - selection: choose projects within a budget for the most value (a knapsack);
 * - network: which depots to open and what each ships to each customer -- capacity, one supplier per
 *   customer, shortage at a penalty, a fleet by vehicle type;
 * - phasing: which project to start in which period, within each period's budget, sooner worth more.
 * - flow: trips between zones routed over the roads, within capacity (widened within a budget), least time.
 * - inventory: how much of each product to order each period (at each location), within storage, least cost.
 */
import type { Binding, Constraint, ObjectiveTerm, Term } from "./terms";
import type { FormDraft } from "./draftIr";
import { say } from "./coverageRecipe";

type Variables = FormDraft["variables"];

function free(name: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  if (!used.has(name)) return name;
  for (let n = 2; ; n++) if (!used.has(`${name}_${n}`)) return `${name}_${n}`;
}

const attr = (of: string, name: string): Term => ({ attr: { of, name } }) as Term;
const v = (name: string, index: string[]): Term => ({ var: name, index }) as Term;
const k = (value: number): Term => ({ const: value }) as Term;
const mul = (a: Term, b: Term): Term => ({ mul: [a, b] }) as Term;
const sum = (of: Term, ...over: [string, string][]): Term => ({ sum: of, over: over.map(([index, set]) => ({ index, set })) }) as Term;
const each = (...over: [string, string][]) => over.map(([index, set]) => ({ index, set }));

/** The names a recipe must not reuse, and a helper that hands out fresh ones. */
function namer(draft: FormDraft) {
  const taken = new Set([...Object.keys(draft.variables), ...Object.keys(draft.parameters), ...draft.constraints.map((c) => c.id),
    ...draft.objective.terms.map((t) => t.id)]);
  return (name: string) => {
    const got = free(name, taken);
    taken.add(got);
    return got;
  };
}

function rule(id: string, note: string, left: Term, relation: "<=" | ">=" | "=", right: Term, forall?: Binding[]): Constraint {
  return { id, note, ...(forall ? { forall } : {}), left, relation, right, severity: "hard" } as Constraint;
}

// --- selection under a budget --------------------------------------------------------------------

export type SelectionRecipe = {
  /** The kind of record chosen from (projects). */
  items: string;
  /** A number field of an item: what choosing it is worth. */
  value: string;
  /** A number field of an item: what it costs. */
  cost: string;
  budget: number;
  /** At least / at most this many chosen. */
  atLeast?: number;
  atMost?: number;
  /** A yes/no field: items with it set are always chosen. */
  mustHave?: string;
  /** A yes/no field: items with it set are never chosen (blocked by construction). */
  never?: string;
  /** At most so many of those whose field holds a value: "at most 8 parking projects". */
  perType?: { field: string; value: string; atMost: number }[];
  /** At least one chosen for every record of a kind the items link to: "every district at least one". */
  atLeastOnePer?: { kind: string; link: string };
};

export function applySelection(draft: FormDraft, r: SelectionRecipe): FormDraft {
  const name = namer(draft);
  const pick = name("choose");
  const i = "i";
  const chosen = v(pick, [i]);
  const constraints = [...draft.constraints,
    rule(name("budget"), `the chosen ${say(r.items)} cost at most ${r.budget}`, sum(mul(attr(i, r.cost), chosen), [i, r.items]), "<=", k(r.budget))];
  if (r.atLeast !== undefined && Number.isFinite(r.atLeast)) {
    constraints.push(rule(name("at_least_chosen"), `at least ${r.atLeast} ${say(r.items)} are chosen`, sum(chosen, [i, r.items]), ">=", k(r.atLeast)));
  }
  if (r.atMost !== undefined && Number.isFinite(r.atMost)) {
    constraints.push(rule(name("at_most_chosen"), `at most ${r.atMost} ${say(r.items)} are chosen`, sum(chosen, [i, r.items]), "<=", k(r.atMost)));
  }
  if (r.mustHave) {
    constraints.push({ ...rule(name("must_have"), `every ${say(r.items)} marked ${say(r.mustHave)} is chosen`, chosen, ">=", k(1)),
      forall: [{ index: i, set: r.items, where: [{ attr: r.mustHave, op: "=", value: true }] }] } as Constraint);
  }
  if (r.never) {
    constraints.push({ ...rule(name("never_chosen"), `no ${say(r.items)} marked ${say(r.never)} is chosen`, chosen, "<=", k(0)),
      forall: [{ index: i, set: r.items, where: [{ attr: r.never, op: "=", value: true }] }] } as Constraint);
  }
  for (const t of r.perType ?? []) {
    constraints.push(rule(name(`at_most_${t.value.toLowerCase().replace(/[^a-z0-9]+/g, "_")}`), `at most ${t.atMost} ${say(r.items)} with ${say(t.field)} ${t.value} are chosen`,
      { sum: chosen, over: [{ index: i, set: r.items, where: [{ attr: t.field, op: "=", value: t.value }] }] } as Term, "<=", k(t.atMost)));
  }
  if (r.atLeastOnePer) {
    const d = "d";
    constraints.push(rule(name(`one_per_${r.atLeastOnePer.kind}`), `every ${say(r.atLeastOnePer.kind)} has at least one ${say(r.items)} chosen`,
      { sum: chosen, over: [{ index: i, set: r.items, via: { rel: r.atLeastOnePer.link, to: d } }] } as Term, ">=", k(1),
      each([d, r.atLeastOnePer.kind])));
  }
  return {
    ...draft,
    sets: [...new Set([...draft.sets, r.items, ...(r.atLeastOnePer ? [r.atLeastOnePer.kind] : [])])],
    variables: { ...draft.variables, [pick]: { index: [r.items], domain: "binary" } } as Variables,
    constraints,
    objective: { sense: "maximize", mode: "weighted", terms: [
      { id: name("value_chosen"), weight: 1, expression: sum(mul(attr(i, r.value), chosen), [i, r.items]) } as ObjectiveTerm] },
  };
}

// --- network design ------------------------------------------------------------------------------

export type NetworkRecipe = {
  /** Where goods come from (depots), and who needs them (customers). */
  sources: string;
  customers: string;
  /** A number field of a customer: how much it needs. */
  demand: string;
  /** Data over both kinds, in either order: what one unit costs from a source to a customer. */
  unitCost: string;
  unitCostIndex: string[];
  /** A number field of a source: the most it ships. */
  capacity?: string;
  /** A number field of a source: what opening it costs; with it, sources are opened or not. */
  openCost?: string;
  /** Each customer is served by one source only. */
  singleSource?: boolean;
  /** Demand may go unmet at this cost a unit, instead of the model having no answer; or at a number
   * field of the customer's (a penalty per unit), when it has one. */
  shortagePenalty?: number;
  shortageField?: string;
  /** Vehicles by type, bought per source: a number field each of their capacity and their cost. */
  fleet?: { kind: string; capacity: string; cost: string };
};

export function applyNetwork(draft: FormDraft, r: NetworkRecipe): FormDraft {
  const name = namer(draft);
  const s = "s", c = "c";
  const ship = name("ship");
  const variables = { ...draft.variables, [ship]: { index: [r.sources, r.customers], domain: "continuous", lower: 0 } } as Variables;
  const flow = v(ship, [s, c]);
  const unit: Term = { par: r.unitCost, index: r.unitCostIndex[0] === r.customers ? [c, s] : [s, c] } as Term;
  const constraints = [...draft.constraints];
  const terms: ObjectiveTerm[] = [];
  const needs = attr(c, r.demand);

  let open: string | null = null;
  if (r.openCost) {
    open = name("open");
    variables[open] = { index: [r.sources], domain: "binary" } as Variables[string];
    terms.push({ id: name("opening_cost"), weight: 1, expression: sum(mul(attr(s, r.openCost), v(open, [s])), [s, r.sources]) } as ObjectiveTerm);
  }
  let short: string | null = null;
  if (r.shortageField || (r.shortagePenalty !== undefined && Number.isFinite(r.shortagePenalty))) {
    short = name("short");
    variables[short] = { index: [r.customers], domain: "continuous", lower: 0 } as Variables[string];
  }
  const served: Term = short ? ({ add: [sum(flow, [s, r.sources]), v(short, [c])] } as Term) : sum(flow, [s, r.sources]);
  constraints.push(rule(name("demand_met"), short
    ? `each ${say(r.customers)} gets its ${say(r.demand)}, or the rest counts as short`
    : `each ${say(r.customers)} gets its ${say(r.demand)}`, served, ">=", needs, each([c, r.customers])));
  if (r.singleSource) {
    const assign = name("served_by");
    variables[assign] = { index: [r.sources, r.customers], domain: "binary" } as Variables[string];
    constraints.push(rule(name("one_source_each"), `each ${say(r.customers)} is served by one ${say(r.sources)}`,
      sum(v(assign, [s, c]), [s, r.sources]), "=", k(1), each([c, r.customers])));
    constraints.push(rule(name("ship_only_if_served"), `a ${say(r.sources)} ships to a ${say(r.customers)} only if it serves it`,
      flow, "<=", mul(needs, v(assign, [s, c])), each([s, r.sources], [c, r.customers])));
    if (open) {
      constraints.push(rule(name("serve_only_if_open"), `only an open ${say(r.sources)} serves`,
        v(assign, [s, c]), "<=", v(open, [s]), each([s, r.sources], [c, r.customers])));
    }
  }
  if (r.capacity) {
    const most = attr(s, r.capacity);
    constraints.push(rule(name("source_capacity"), open ? `an open ${say(r.sources)} ships at most its ${say(r.capacity)}, a closed one nothing`
      : `a ${say(r.sources)} ships at most its ${say(r.capacity)}`, sum(flow, [c, r.customers]), "<=", open ? mul(most, v(open, [s])) : most,
    each([s, r.sources])));
  } else if (open && !r.singleSource) {
    constraints.push(rule(name("ship_only_if_open"), `only an open ${say(r.sources)} ships`, flow, "<=", mul(needs, v(open, [s])),
      each([s, r.sources], [c, r.customers])));
  }
  const sets = [r.sources, r.customers];
  if (r.fleet) {
    const f = r.fleet, t = "t";
    const trucks = name("vehicles");
    variables[trucks] = { index: [r.sources, f.kind], domain: "integer", lower: 0 } as Variables[string];
    constraints.push(rule(name("fleet_carries"), `what a ${say(r.sources)} ships fits in its ${say(f.kind)}s`,
      sum(flow, [c, r.customers]), "<=", sum(mul(attr(t, f.capacity), v(trucks, [s, t])), [t, f.kind]), each([s, r.sources])));
    terms.push({ id: name("fleet_cost"), weight: 1, expression: sum(mul(attr(t, f.cost), v(trucks, [s, t])), [s, r.sources], [t, f.kind]) } as ObjectiveTerm);
    sets.push(f.kind);
  }
  terms.unshift({ id: name("shipping_cost"), weight: 1, expression: sum(mul(unit, flow), [s, r.sources], [c, r.customers]) } as ObjectiveTerm);
  // The price is in the goal's equation, weight 1, to read and change there (benchmark round 4: a hidden
  // weight of 15000 on this goal was found late and counted twice).
  if (short) terms.push({ id: name("shortage"), weight: 1,
    expression: sum(mul(r.shortageField ? attr(c, r.shortageField) : k(r.shortagePenalty!), v(short, [c])), [c, r.customers]) } as ObjectiveTerm);
  return {
    ...draft,
    sets: [...new Set([...draft.sets, ...sets])],
    parameters: { ...draft.parameters, [r.unitCost]: draft.parameters[r.unitCost] ?? { index: r.unitCostIndex } },
    variables,
    constraints,
    objective: { sense: "minimize", mode: "weighted", terms },
  };
}

// --- phasing over periods ------------------------------------------------------------------------

export type PhasingRecipe = {
  /** What is started (projects) and when (years, quarters). */
  items: string;
  periods: string;
  /** A number field of an item: what it is worth once started. */
  value: string;
  /** A number field of an item: what it costs in the period it starts. */
  cost: string;
  /** A number field of a period: what may be spent in it. */
  budget: string;
  /** A number field of a period: how much a start in it counts (3, 2, 1: sooner is better). */
  weight?: string;
  /** Every item is started in some period (else: those worth it). */
  all?: boolean;
};

export function applyPhasing(draft: FormDraft, r: PhasingRecipe): FormDraft {
  const name = namer(draft);
  const i = "i", t = "t";
  const start = name("start");
  const cell = v(start, [i, t]);
  const constraints = [...draft.constraints,
    rule(name("start_once"), r.all ? `each ${say(r.items)} starts in one ${say(r.periods)}` : `each ${say(r.items)} starts at most once`,
      sum(cell, [t, r.periods]), r.all ? "=" : "<=", k(1), each([i, r.items])),
    rule(name("period_budget"), `what starts in a ${say(r.periods)} costs at most its ${say(r.budget)}`,
      sum(mul(attr(i, r.cost), cell), [i, r.items]), "<=", attr(t, r.budget), each([t, r.periods])),
  ];
  const worth = r.weight ? mul(mul(attr(i, r.value), attr(t, r.weight)), cell) : mul(attr(i, r.value), cell);
  return {
    ...draft,
    sets: [...new Set([...draft.sets, r.items, r.periods])],
    variables: { ...draft.variables, [start]: { index: [r.items, r.periods], domain: "binary" } } as Variables,
    constraints,
    objective: { sense: "maximize", mode: "weighted", terms: [
      { id: name(r.weight ? "value_sooner" : "value_started"), weight: 1, expression: sum(worth, [i, r.items], [t, r.periods]) } as ObjectiveTerm] },
  };
}

// --- allocation of an amount among options ---------------------------------------------------------

export type AllocationRecipe = {
  /** What is shared out (parcels), and among what (crops). */
  items: string;
  options: string;
  /** A number field of an item: how much of it there is (feddan); all of it, or at most. */
  size: string;
  /** What a unit given to an option is worth: a number field of the option, data over both, or fields of
   * the option multiplied, less another (yield × price − cost per feddan). */
  worth: { field: string } | { data: string; index: string[] } | { product: string[]; less?: string };
  /** What a unit of an option uses of a shared resource (water per feddan), and how much there is. */
  use?: { field: string; limit: number };
  /** 0/1 data over both: where an option may go at all (suitable soil, rotation). */
  allowed?: { data: string; index: string[] };
  /** Number fields of an option: its least and most share of everything, 0..1. */
  minShare?: string;
  maxShare?: string;
  /** Number fields of an option: its least and most in all, in the items' size units (min_area_feddan). */
  minAmount?: string;
  maxAmount?: string;
  /** Every unit of every item is given out (else at most). */
  all?: boolean;
};

export function applyAllocation(draft: FormDraft, r: AllocationRecipe): FormDraft {
  const name = namer(draft);
  const i = "i", o = "o";
  const give = name("amount");
  const cell = v(give, [i, o]);
  const w = r.worth;
  const product: Term | null = "product" in w ? w.product.map((f) => attr(o, f)).reduce((a, b) => mul(a, b)) : null;
  const worth: Term = "field" in w ? attr(o, w.field)
    : "data" in w ? ({ par: w.data, index: w.index[0] === r.items ? [i, o] : [o, i] } as Term)
      : w.less ? ({ add: [product!, mul(k(-1), attr(o, w.less))] } as Term) : product!;
  const everything: Term = sum(attr(i, r.size), [i, r.items]);
  const constraints: Constraint[] = [...draft.constraints,
    rule(name("size_of_each"), r.all ? `all of each ${say(r.items)}'s ${say(r.size)} is given out` : `each ${say(r.items)} gives out at most its ${say(r.size)}`,
      sum(cell, [o, r.options]), r.all ? "=" : "<=", attr(i, r.size), each([i, r.items]))];
  if (r.use) {
    constraints.push(rule(name("shared_limit"), `what is given out uses at most ${r.use.limit} of ${say(r.use.field)}`,
      sum(mul(attr(o, r.use.field), cell), [i, r.items], [o, r.options]), "<=", k(r.use.limit)));
  }
  if (r.allowed) {
    const ok: Term = { par: r.allowed.data, index: r.allowed.index[0] === r.items ? [i, o] : [o, i] } as Term;
    constraints.push(rule(name("only_where_allowed"), `a ${say(r.options)} goes only where ${say(r.allowed.data)} allows it`,
      cell, "<=", mul(attr(i, r.size), ok), each([i, r.items], [o, r.options])));
  }
  // A share is of the land that can hold the option, when only some can (benchmark round 4: a least
  // share of all the land, for a crop most land cannot hold, could not be met).
  const whole: Term = r.allowed ? sum(mul(attr(i, r.size), { par: r.allowed.data, index: r.allowed.index[0] === r.items ? [i, o] : [o, i] } as Term), [i, r.items]) : everything;
  const ofWhole = r.allowed ? `of the ${say(r.size)} that can hold it` : "of the whole";
  if (r.minShare) {
    constraints.push(rule(name("least_share"), `each ${say(r.options)} gets at least its ${say(r.minShare)} ${ofWhole}`,
      sum(cell, [i, r.items]), ">=", mul(attr(o, r.minShare), whole), each([o, r.options])));
  }
  if (r.maxShare) {
    constraints.push(rule(name("most_share"), `each ${say(r.options)} gets at most its ${say(r.maxShare)} ${ofWhole}`,
      sum(cell, [i, r.items]), "<=", mul(attr(o, r.maxShare), whole), each([o, r.options])));
  }
  if (r.minAmount) {
    constraints.push(rule(name("least_amount"), `each ${say(r.options)} gets at least its ${say(r.minAmount)} in all`,
      sum(cell, [i, r.items]), ">=", attr(o, r.minAmount), each([o, r.options])));
  }
  if (r.maxAmount) {
    constraints.push(rule(name("most_amount"), `each ${say(r.options)} gets at most its ${say(r.maxAmount)} in all`,
      sum(cell, [i, r.items]), "<=", attr(o, r.maxAmount), each([o, r.options])));
  }
  const data: FormDraft["parameters"] = { ...draft.parameters };
  for (const d of [("data" in w ? w : null), r.allowed ?? null]) {
    if (d) data[d.data] = draft.parameters[d.data] ?? { index: d.index };
  }
  return {
    ...draft,
    sets: [...new Set([...draft.sets, r.items, r.options])],
    parameters: data,
    variables: { ...draft.variables, [give]: { index: [r.items, r.options], domain: "continuous", lower: 0 } } as Variables,
    constraints,
    objective: { sense: "maximize", mode: "weighted", terms: [
      { id: name("worth"), weight: 1, expression: sum(mul(worth, cell), [i, r.items], [o, r.options]) } as ObjectiveTerm] },
  };
}

// --- traffic over a road network -----------------------------------------------------------------

export type FlowRecipe = {
  /** Where trips start and end (zones, junctions), and the roads between them. */
  nodes: string;
  arcs: string;
  /** Relationships from a road to the node it starts at and to the one it ends at. */
  startsAt: string;
  endsAt: string;
  /** Data over two nodes, origin first: how many trips go from one to the other. */
  trips: string;
  /** A number field of a road: how long it takes. */
  time: string;
  /** A number field of a road: the most it carries. */
  capacity?: string;
  /** Roads may be widened: a number field each of the capacity added and what it costs, within a budget. */
  upgrade?: { added: string; cost: string; budget: number };
};

/** A relationship between two kinds, by name. */
export type Link = { name: string; from: string; to: string };

/** Of the links from a road to a node, the one its name says it starts at (from, start, origin), and the one it ends at. */
export function endsOf(links: Link[]): { startsAt?: string; endsAt?: string } {
  const start = links.find((l) => /(^|_)(from|start\w*|origin|source|tail)($|_)/.test(l.name));
  const end = links.find((l) => l !== start && /(^|_)(to|end\w*|dest\w*|target|head)($|_)/.test(l.name));
  return { startsAt: start?.name, endsAt: end?.name };
}

/**
 * Every trip goes from its origin to its destination over the roads, each road within its capacity,
 * for the least total travel time. The flow is kept apart by origin, so each origin's trips are
 * followed to where they end: at every other node, what of an origin's traffic comes in less what
 * goes out is the trips from that origin ending there. The origin's own balance follows.
 */
export function applyFlow(draft: FormDraft, r: FlowRecipe): FormDraft {
  const name = namer(draft);
  const a = "a", o = "o", n = "n";
  const flow = name("flow");
  const onRoad = v(flow, [a, o]);
  const along = (rel: string): Term => ({ sum: onRoad, over: [{ index: a, set: r.arcs, via: { rel, to: n } }] }) as Term;
  const variables = { ...draft.variables, [flow]: { index: [r.arcs, r.nodes], domain: "continuous", lower: 0 } } as Variables;
  const constraints: Constraint[] = [...draft.constraints,
    rule(name("trips_arrive"), `at every ${say(r.nodes)}, the traffic from each origin that stays there is the ${say(r.trips)} ending there`,
      { add: [along(r.endsAt), mul(k(-1), along(r.startsAt))] } as Term, "=", { par: r.trips, index: [o, n] } as Term,
      [{ index: o, set: r.nodes }, { index: n, set: r.nodes, where: [{ index: o, op: "!=" }] }])];
  if (r.capacity) {
    let most: Term = attr(a, r.capacity);
    if (r.upgrade) {
      const widen = name("upgrade");
      variables[widen] = { index: [r.arcs], domain: "binary" } as Variables[string];
      most = { add: [most, mul(attr(a, r.upgrade.added), v(widen, [a]))] } as Term;
      constraints.push(rule(name("upgrade_budget"), `the ${say(r.arcs)}s upgraded cost at most ${r.upgrade.budget}`,
        sum(mul(attr(a, r.upgrade.cost), v(widen, [a])), [a, r.arcs]), "<=", k(r.upgrade.budget)));
    }
    constraints.push(rule(name("road_capacity"), r.upgrade ? `each ${say(r.arcs)} carries at most its ${say(r.capacity)}, more if upgraded`
      : `each ${say(r.arcs)} carries at most its ${say(r.capacity)}`, sum(onRoad, [o, r.nodes]), "<=", most, each([a, r.arcs])));
  }
  return {
    ...draft,
    sets: [...new Set([...draft.sets, r.nodes, r.arcs])],
    parameters: { ...draft.parameters, [r.trips]: draft.parameters[r.trips] ?? { index: [r.nodes, r.nodes] } },
    variables,
    constraints,
    objective: { sense: "minimize", mode: "weighted", terms: [
      { id: name("travel_time"), weight: 1, expression: sum(mul(attr(a, r.time), onRoad), [a, r.arcs], [o, r.nodes]) } as ObjectiveTerm] },
  };
}

// --- inventory over periods ----------------------------------------------------------------------

export type InventoryRecipe = {
  /** What is stocked (products), over what periods, and, if more than one, where (stores, warehouses). */
  products: string;
  periods: string;
  locations?: string;
  /** Data over the product, the period and the location if any, in any order: how much is needed. */
  demand: { data: string; index: string[] };
  /** What is on hand at the start: a number field of the product, or data over product and location. */
  initial?: { field: string } | { data: string; index: string[] };
  /** Number fields of a product: what a unit costs to order, and to hold for a period. */
  unitCost?: string;
  holdCost?: string;
  /** The most ordered of a product in one period: a number field of the product. */
  orderMax?: string;
  /** What fits in store: a number field of the location, or a number; a product's size, if it is not 1. */
  storage?: { capacity: string | number; size?: string };
  /** Demand may go unmet (lost sales) at this cost a unit, instead of the model having no answer; or at
   * a number field of the product's (a penalty per unit), when it has one. */
  shortagePenalty?: number;
  shortageField?: string;
};

/**
 * How much of each product to order in each period (at each location), so that what is on hand
 * meets what is needed, within storage, for the least cost of ordering and holding. Stock at the end
 * of a period is what was there at the start, plus all ordered so far, less all needed so far: the
 * periods are read in the order of their keys (2026-01, 2026-02, ... or w01, w02, ...).
 */
export function applyInventory(draft: FormDraft, r: InventoryRecipe): FormDraft {
  const name = namer(draft);
  const p = "p", l = "l", t = "t", s = "s";
  const kindIndex: Record<string, string> = { [r.products]: p, [r.periods]: t, ...(r.locations ? { [r.locations]: l } : {}) };
  const at = (index: string[], period = t) => index.map((kind) => (kind === r.periods ? period : kindIndex[kind] ?? kind));
  const where = (period: string): string[] => [p, ...(r.locations ? [l] : []), period];
  const shape = [r.products, ...(r.locations ? [r.locations] : []), r.periods];
  const order = name("order"), stock = name("stock");
  const variables = { ...draft.variables,
    [order]: { index: shape, domain: "continuous", lower: 0 },
    [stock]: { index: shape, domain: "continuous", lower: 0 } } as Variables;
  const upTo = (of: Term): Term => ({ sum: of, over: [{ index: s, set: r.periods, where: [{ index: t, op: "<=" }] }] }) as Term;
  const parts: Term[] = [];
  if (r.initial) parts.push("field" in r.initial ? attr(p, r.initial.field) : ({ par: r.initial.data, index: at(r.initial.index) } as Term));
  parts.push(upTo(v(order, where(s))));
  let short: string | null = null;
  if (r.shortageField || (r.shortagePenalty !== undefined && Number.isFinite(r.shortagePenalty))) {
    short = name("short");
    variables[short] = { index: shape, domain: "continuous", lower: 0 } as Variables[string];
    parts.push(upTo(v(short, where(s))));
  }
  parts.push(mul(k(-1), upTo({ par: r.demand.data, index: at(r.demand.index, s) } as Term)));
  const every = each([p, r.products], ...(r.locations ? [[l, r.locations] as [string, string]] : []), [t, r.periods]);
  const here = r.locations ? ` at each ${say(r.locations)}` : "";
  const constraints: Constraint[] = [...draft.constraints,
    rule(name("stock_balance"), `the ${say(r.products)} in stock${here} at the end of a ${say(r.periods)} is what was there at the start, `
      + `plus all ordered${short ? " and all short" : ""} so far, less all needed so far`, v(stock, where(t)), "=", { add: parts } as Term, every)];
  if (r.orderMax) {
    constraints.push(rule(name("order_limit"), `at most its ${say(r.orderMax)} of a ${say(r.products)} is ordered in a ${say(r.periods)}`,
      v(order, where(t)), "<=", attr(p, r.orderMax), every));
  }
  if (r.storage) {
    const cap: Term = typeof r.storage.capacity === "number" ? k(r.storage.capacity) : attr(r.locations ? l : t, r.storage.capacity);
    const held = r.storage.size ? mul(attr(p, r.storage.size), v(stock, where(t))) : v(stock, where(t));
    constraints.push(rule(name("storage"), `what is in stock${here} fits its ${typeof r.storage.capacity === "number" ? r.storage.capacity : say(r.storage.capacity)}`,
      sum(held, [p, r.products]), "<=", cap, each(...(r.locations ? [[l, r.locations] as [string, string]] : []), [t, r.periods])));
  }
  const over: [string, string][] = [[p, r.products], ...(r.locations ? [[l, r.locations] as [string, string]] : []), [t, r.periods]];
  const terms: ObjectiveTerm[] = [];
  if (r.unitCost) terms.push({ id: name("ordering_cost"), weight: 1, expression: sum(mul(attr(p, r.unitCost), v(order, where(t))), ...over) } as ObjectiveTerm);
  if (r.holdCost) terms.push({ id: name("holding_cost"), weight: 1, expression: sum(mul(attr(p, r.holdCost), v(stock, where(t))), ...over) } as ObjectiveTerm);
  if (short) terms.push({ id: name("lost_sales"), weight: 1,
    expression: sum(mul(r.shortageField ? attr(p, r.shortageField) : k(r.shortagePenalty!), v(short, where(t))), ...over) } as ObjectiveTerm);
  // With no costs at all, the least stock held is the goal.
  if (!terms.length) terms.push({ id: name("stock_held"), weight: 1, expression: sum(v(stock, where(t)), ...over) } as ObjectiveTerm);
  const data: FormDraft["parameters"] = { ...draft.parameters, [r.demand.data]: draft.parameters[r.demand.data] ?? { index: r.demand.index } };
  if (r.initial && "data" in r.initial) data[r.initial.data] = draft.parameters[r.initial.data] ?? { index: r.initial.index };
  return {
    ...draft,
    sets: [...new Set([...draft.sets, ...shape])],
    parameters: data,
    variables,
    constraints,
    objective: { sense: "minimize", mode: "weighted", terms },
  };
}

// --- vehicle routes -----------------------------------------------------------------------------

export type RouteRecipe = {
  /** Who drives (trucks) and where they go (stops, the depots among them). */
  vehicles: string;
  stops: string;
  /** Data over two stops: the distance or time from one to the next. */
  travel: string;
  /** Where every vehicle starts and ends: one stop for all, a field of each vehicle naming its own, or a
   * relationship linking each vehicle to its own (placed there by an earlier plan). */
  depot: { one: string } | { field: string } | { link: string };
  /** A number field of a stop (what is dropped there) and of a vehicle (what it carries). */
  load?: { demand: string; capacity: string };
};

/**
 * Every stop but the depots visited once, by vehicles that leave their depot and come back, each
 * within what it carries, for the least travel (benchmark round 3: route rules were "under Expert",
 * and not found there without a decision to build them on).
 */
export function applyRoutes(draft: FormDraft, r: RouteRecipe): FormDraft {
  const name = namer(draft);
  const visit = name("visit");
  const t = "v", i = "i", j = "j";
  const home = "one" in r.depot ? { depot: r.depot.one } : "field" in r.depot ? { depot_of: r.depot.field } : { depot_by: r.depot.link };
  const constraints: Constraint[] = [...draft.constraints, {
    id: name("routes"), note: `every ${say(r.stops)} is visited once, by a ${say(r.vehicles)} from its depot and back`,
    route: { visit: { var: visit, index: [t, i, j] }, vehicles: { index: t, set: r.vehicles }, stops: { index: i, set: r.stops },
      ...home, ...(r.load ? { demand: r.load.demand, capacity: r.load.capacity } : {}) },
    severity: "hard",
  } as Constraint];
  return {
    ...draft,
    sets: [...new Set([...draft.sets, r.vehicles, r.stops])],
    parameters: { ...draft.parameters, [r.travel]: draft.parameters[r.travel] ?? { index: [r.stops, r.stops] } },
    variables: { ...draft.variables, [visit]: { index: [r.vehicles, r.stops, r.stops], domain: "binary" } } as Variables,
    constraints,
    objective: { sense: "minimize", mode: "weighted", terms: [{ id: name("travel"), weight: 1,
      expression: sum(mul({ par: r.travel, index: [i, j] } as Term, v(visit, [t, i, j])), [t, r.vehicles], [i, r.stops], [j, r.stops]) } as ObjectiveTerm] },
  };
}

// --- each place served by its nearest open site: least response time --------------------------------

export type AssignmentRecipe = {
  /** Where help comes from (stations, bases) and who needs it (districts, towns). */
  sites: string;
  places: string;
  /** Data over both kinds, either order: the minutes (or km) from a site to a place. */
  time: { data: string; index: string[] };
  /** A number field of a place: how much its time counts (calls, incidents, people); else 1 each. */
  weight?: string;
  /** How many sites are open, or what opening costs (a number field of a site) within a budget. */
  open?: { count: number } | { cost: string; budget: number };
  /** A yes/no field of a site: those set are open already and stay open. */
  existing?: string;
  /** No place is served from further than this, in the time's unit. */
  within?: number;
  /** A number field of a site: the most it serves, counted in the weight. */
  capacity?: string;
};

/**
 * Which sites to open and which open site serves each place, for the least response time weighted by
 * demand (a p-median): each place served by exactly one open site, never further than `within`
 * (benchmark round 4: coverage counted who is within reach; nothing sent each place to one site).
 */
export function applyAssignment(draft: FormDraft, r: AssignmentRecipe): FormDraft {
  const name = namer(draft);
  const s = "s", p = "p";
  const open = name("open"), serve = name("serves");
  const cell = v(serve, [s, p]);
  const minutes: Term = { par: r.time.data, index: r.time.index[0] === r.places ? [p, s] : [s, p] } as Term;
  const weight = (t: Term) => (r.weight ? mul(attr(p, r.weight), t) : t);
  const constraints: Constraint[] = [...draft.constraints,
    rule(name("one_site_each"), `each ${say(r.places)} is served by one open ${say(r.sites)}`, sum(cell, [s, r.sites]), "=", k(1), each([p, r.places])),
    rule(name("only_from_open"), `only an open ${say(r.sites)} serves`, cell, "<=", v(open, [s]), each([s, r.sites], [p, r.places]))];
  if (r.within !== undefined && Number.isFinite(r.within)) {
    constraints.push(rule(name("within_reach"), `no ${say(r.places)} is served from further than ${r.within}`,
      mul(minutes, cell), "<=", k(r.within), each([s, r.sites], [p, r.places])));
  }
  if (r.open && "count" in r.open) {
    constraints.push(rule(name("sites_open"), `${r.open.count} ${say(r.sites)}s are open`, sum(v(open, [s]), [s, r.sites]), "=", k(r.open.count)));
  } else if (r.open) {
    constraints.push(rule(name("budget"), `the open ${say(r.sites)}s cost at most ${r.open.budget}`,
      sum(mul(attr(s, r.open.cost), v(open, [s])), [s, r.sites]), "<=", k(r.open.budget)));
  }
  if (r.existing) {
    constraints.push({ ...rule(name("existing_stay_open"), `every ${say(r.sites)} marked ${say(r.existing)} stays open`, v(open, [s]), "=", k(1)),
      forall: [{ index: s, set: r.sites, where: [{ attr: r.existing, op: "=", value: true }] }] } as Constraint);
  }
  if (r.capacity) {
    constraints.push(rule(name("site_capacity"), `an open ${say(r.sites)} serves at most its ${say(r.capacity)}`,
      sum(weight(cell), [p, r.places]), "<=", mul(attr(s, r.capacity), v(open, [s])), each([s, r.sites])));
  }
  return {
    ...draft,
    sets: [...new Set([...draft.sets, r.sites, r.places])],
    parameters: { ...draft.parameters, [r.time.data]: draft.parameters[r.time.data] ?? { index: r.time.index } },
    variables: { ...draft.variables, [open]: { index: [r.sites], domain: "binary" }, [serve]: { index: [r.sites, r.places], domain: "binary" } } as Variables,
    constraints,
    objective: { sense: "minimize", mode: "weighted", terms: [{ id: name("response_time"), weight: 1,
      expression: sum(weight(mul(minutes, cell)), [s, r.sites], [p, r.places]) } as ObjectiveTerm] },
  };
}
