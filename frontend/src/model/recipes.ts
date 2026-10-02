/**
 * Three more recipes (benchmark, October 2026, G3d): each writes the decisions, rules and goals a
 * common kind of model needs into the draft from one short form, to read and change like any other.
 *
 * - selection: choose projects within a budget for the most value (a knapsack);
 * - network: which depots to open and what each ships to each customer -- capacity, one supplier per
 *   customer, shortage at a penalty, a fleet by vehicle type;
 * - phasing: which project to start in which period, within each period's budget, sooner worth more.
 */
import type { Constraint, ObjectiveTerm, Term } from "./terms";
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

function rule(id: string, note: string, left: Term, relation: "<=" | ">=" | "=", right: Term, forall?: ReturnType<typeof each>): Constraint {
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
  return {
    ...draft,
    sets: [...new Set([...draft.sets, r.items])],
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
  /** Demand may go unmet at this cost a unit, instead of the model having no answer. */
  shortagePenalty?: number;
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
  if (r.shortagePenalty !== undefined && Number.isFinite(r.shortagePenalty)) {
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
  if (short) terms.push({ id: name("shortage"), weight: r.shortagePenalty!, expression: sum(v(short, [c]), [c, r.customers]) } as ObjectiveTerm);
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
  /** What a unit given to an option is worth: a number field of the option, or data over both. */
  worth: { field: string } | { data: string; index: string[] };
  /** What a unit of an option uses of a shared resource (water per feddan), and how much there is. */
  use?: { field: string; limit: number };
  /** 0/1 data over both: where an option may go at all (suitable soil, rotation). */
  allowed?: { data: string; index: string[] };
  /** Number fields of an option: its least and most share of everything, 0..1. */
  minShare?: string;
  maxShare?: string;
  /** Every unit of every item is given out (else at most). */
  all?: boolean;
};

export function applyAllocation(draft: FormDraft, r: AllocationRecipe): FormDraft {
  const name = namer(draft);
  const i = "i", o = "o";
  const give = name("amount");
  const cell = v(give, [i, o]);
  const worth: Term = "field" in r.worth ? attr(o, r.worth.field)
    : ({ par: r.worth.data, index: r.worth.index[0] === r.items ? [i, o] : [o, i] } as Term);
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
  if (r.minShare) {
    constraints.push(rule(name("least_share"), `each ${say(r.options)} gets at least its ${say(r.minShare)} of the whole`,
      sum(cell, [i, r.items]), ">=", mul(attr(o, r.minShare), everything), each([o, r.options])));
  }
  if (r.maxShare) {
    constraints.push(rule(name("most_share"), `each ${say(r.options)} gets at most its ${say(r.maxShare)} of the whole`,
      sum(cell, [i, r.items]), "<=", mul(attr(o, r.maxShare), everything), each([o, r.options])));
  }
  const data: FormDraft["parameters"] = { ...draft.parameters };
  for (const d of [("data" in r.worth ? r.worth : null), r.allowed ?? null]) {
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
