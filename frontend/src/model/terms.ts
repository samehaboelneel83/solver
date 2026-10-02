/**
 * The arithmetic half of a model, and the vocabulary an editor needs to
 * offer it.
 *
 * **Why this is not react-querybuilder.** That library builds a boolean
 * condition tree: field, operator, value, joined by and/or. It is exactly
 * right for a binding's `where` filter, and `whereFilter.ts` uses it for
 * that. But `8 * sum(assign[e,d,s] over d, s) <= hours_per_week[e]` is not a
 * condition tree — it is arithmetic over bound indices, and there is no
 * field/operator/value shape that says it. Forcing it into one would
 * produce an editor that cannot express the model the platform already
 * solves.
 *
 * So: react-querybuilder for every filter, this for every term, and the two
 * meet inside a binding.
 */

import { ARITHMETIC_ATTR_TYPES } from "../ir";
import { cellText } from "../lib/irBlocks/catalogue";
import type { PathCombination, Relation, Severity, TermKind, TraversalDepth } from "../ir";

export type IrFilter = { attr: string; op: string; value: unknown };
/** "This or that": filters of which any one holding is enough, one level deep. */
export type FilterGroup = { any: IrFilter[] };
/** One entry of a `where`: a filter, or a group of them. */
export type WhereEntry = IrFilter | FilterGroup;

export const isGroup = (entry: WhereEntry): entry is FilterGroup => "any" in entry;

/** How far a walk goes: from `min` to `max` steps, no `max` for no limit. */
export type Steps = { min: number; max?: number };

/**
 * A traversal. `from`/`to` name the end the **anchor** sits at, so the
 * index being bound takes the other one -- which is why exactly one of
 * them (or `both`, either end) is ever present. `depth` or `steps` say how
 * far; `where` narrows the links walked, `on` to the links valid that day.
 */
export type Via = {
  rel: string;
  from?: string;
  to?: string;
  both?: string;
  depth?: TraversalDepth;
  steps?: Steps;
  where?: WhereEntry[];
  on?: string;
  as?: string;
};
export type Binding = { index: string; set: string; where?: WhereEntry[]; via?: Via };

/**
 * The binding moved to another set, keeping what still fits it: a condition
 * on an attribute the new set also has (of the same type), and a walk the
 * new set can still be reached by from the same item. Whatever does not fit
 * is dropped -- the caller can offer to undo.
 */
export function rebindSet(binding: Binding, set: string, context: ModelContext, earlier: Binding[]): Binding {
  const next: Binding = { index: binding.index, set };
  const attrs = context.attributes[set] ?? [];
  const oldAttrs = context.attributes[binding.set] ?? [];
  const fits = (f: IrFilter) => {
    const now = attrs.find((a) => a.name === f.attr);
    return !!now && now.data_type === oldAttrs.find((a) => a.name === f.attr)?.data_type;
  };
  const where = (binding.where ?? []).filter((entry) => (isGroup(entry) ? entry.any.every(fits) : fits(entry)));
  if (where.length) next.where = where;
  const walk = viaOf(binding);
  if (walk && walksAvailable(context, set, earlier).some((o) => o.rel === walk.rel && o.anchorEnd === walk.anchorEnd && o.anchors.includes(walk.anchor))) {
    next.via = binding.via;
  }
  return next;
}

/** Whether moving a binding dropped any of its conditions or its walk. */
export function lost(before: Binding, after: Binding): boolean {
  return (before.where?.length ?? 0) > (after.where?.length ?? 0) || (!!before.via && !after.via);
}

/** The binding with these conditions, or with none (no empty `where` left behind). */
export function withWhere(binding: Binding, where: WhereEntry[] | undefined): Binding {
  const { where: _old, ...rest } = binding;
  return where && where.length > 0 ? { ...rest, where } : rest;
}

export type Term =
  | { const: number }
  | { par: string; index: string[] }
  | { var: string; index: string[] }
  | { attr: { of: string; name: string; along?: PathCombination } }
  | { sum: Term; over: Binding[] }
  | { add: Term[] }
  | { mul: [Term, Term] }
  | { pwl: { var: string; index: string[] }; points: [number, number][] }
  | { fn: string; of: Term }
  /** A declared predictor (a trained model) applied to its inputs, in order
   * (version 2, Epic ML). */
  | { predict: string; of: Term[] };

export type Constraint = {
  id: string;
  note?: string;
  forall?: Binding[];
  /** Absent on a version that predates the IR contract — an id and a note
   * with nothing to solve. The editor must not assume these are present. */
  left?: Term;
  relation?: Relation;
  right?: Term;
  severity?: Severity;
  weight?: number;
  /** The rule holds only while this yes-or-no decision is `is` (version 2). */
  when?: When;
  /** It may fail in at most this share of a stochastic solve's sampled futures (version 2, queue R8). */
  chance?: { epsilon: number };
  /** A scheduling rule (version 2) in place of left/relation/right. Kept
   * and shown by the editor, not yet built in it. */
  no_overlap?: SchedulingBody;
  cumulative?: SchedulingBody & { demand: Term; capacity: Term };
  /** Each group's units one connected piece (version 2), in place of
   * left/relation/right. */
  connected?: ConnectedBody;
  /** Vehicles round the stops from a depot (version 2, queue R15b), in place
   * of left/relation/right. */
  route?: RouteBody;
};

export type RouteBody = {
  visit: { var: string; index: string[] };
  vehicles: { index: string; set: string };
  stops: { index: string; set: string };
  depot: string;
  demand?: string;
  capacity?: string;
  /** Time windows (queue R15c): a parameter over [stop, stop], and stop attributes. */
  travel?: string;
  earliest?: string;
  latest?: string;
  service?: string;
};

/** `every stop visited once by vehicle from depot, stop demand within vehicle capacity`, or null for any other rule. */
export function describeRoute(rule: { route?: unknown }): string | null {
  const r = rule.route as Partial<RouteBody> | undefined;
  if (!r) return null;
  const load = r.demand && r.capacity ? `, ${r.demand} within ${r.vehicles?.set || "vehicle"} ${r.capacity}` : "";
  const windows = r.travel
    ? `, arriving between ${r.earliest || "0"} and ${r.latest || "any time"} after ${r.travel}${r.service ? ` and ${r.service} at each` : ""}`
    : "";
  return `every ${r.stops?.set || "stop"} but ${r.depot || "?"} visited once by a ${r.vehicles?.set || "vehicle"} from ${r.depot || "?"} and back${load}${windows}`;
}

/** The binary variables a route rule can read: indexed [vehicles, stops, stops]. */
export function routeChoices(context: ModelContext): { variable: string; vehicles: string; stops: string }[] {
  return Object.entries(context.variables)
    .filter(([, v]) => v.domain === "binary" && v.index.length === 3 && v.index[1] === v.index[2] && v.index[0] !== v.index[1])
    .map(([variable, v]) => ({ variable, vehicles: v.index[0], stops: v.index[1] }));
}

/** The body for one choice: indices named after their sets, the next stop after the stop. */
export function routeBody(choice: { variable: string; vehicles: string; stops: string }, depot: string, load?: { demand: string; capacity: string }): RouteBody {
  const v = seedForSet(choice.vehicles);
  let i = seedForSet(choice.stops);
  if (i === v) i = `${i}2`;
  return {
    visit: { var: choice.variable, index: [v, i, `${i}_next`] },
    vehicles: { index: v, set: choice.vehicles },
    stops: { index: i, set: choice.stops },
    depot,
    ...(load ? load : {}),
  };
}

/** A new route rule over the first admissible variable, or null when there is none. */
export function newRouteRule(id: string, context: ModelContext): Constraint | null {
  const choice = routeChoices(context)[0];
  if (!choice) return null;
  return { id, route: routeBody(choice, "depot"), severity: "hard" } as Constraint;
}

export type ConnectedBody = {
  assign: { var: string; index: string[] };
  units: { index: string; set: string };
  groups: { index: string; set: string };
  via: string;
  empty?: "forbidden" | "allowed";
};

/** `each zone is one connected piece of cell over adjacent`, or null for
 * any other rule. */
export function describeConnected(rule: { connected?: unknown }): string | null {
  const c = rule.connected as Partial<ConnectedBody> | undefined;
  if (!c) return null;
  const empty = c.empty === "allowed" ? " (or empty)" : "";
  return `each ${c.groups?.set || "group"} is one connected piece of ${c.units?.set || "units"}${empty} over ${c.via || "?"}`;
}

/** The binary variables a connected rule can read -- indexed by exactly two
 * sets, the first joined to itself by a relationship -- with those
 * relationships. */
export function connectedChoices(context: ModelContext): { variable: string; units: string; groups: string; vias: string[] }[] {
  return Object.entries(context.variables)
    .filter(([, v]) => v.domain === "binary" && v.index.length === 2 && v.index[0] !== v.index[1])
    .map(([variable, v]) => ({
      variable,
      units: v.index[0],
      groups: v.index[1],
      vias: context.relationships.filter((r) => r.from === v.index[0] && r.to === v.index[0]).map((r) => r.name),
    }));
}

/** The body for one choice: the indices named after their sets, never the same name twice. */
export function connectedBody(
  choice: { variable: string; units: string; groups: string },
  via: string,
  empty: "forbidden" | "allowed" = "forbidden"
): ConnectedBody {
  const u = seedForSet(choice.units);
  let z = seedForSet(choice.groups);
  if (z === u) z = `${z}2`;
  return {
    assign: { var: choice.variable, index: [u, z] },
    units: { index: u, set: choice.units },
    groups: { index: z, set: choice.groups },
    via,
    empty,
  };
}

/** A new connected rule over the first admissible variable and relationship, or null when there is none. */
export function newConnectedRule(id: string, context: ModelContext): Constraint | null {
  const choice = connectedChoices(context).find((c) => c.vias.length > 0);
  if (!choice) return null;
  return { id, connected: connectedBody(choice, choice.vias[0]), severity: "hard" } as Constraint;
}

export type When = { var: string; index: string[]; is?: 0 | 1 };

/** `only while open[f] is yes`, or null for an unconditional rule. */
export function describeWhen(when: { var?: string; index?: string[]; is?: number } | undefined): string | null {
  if (!when?.var) return null;
  return `only while ${when.var}[${(when.index ?? []).join(", ")}] is ${when.is === 0 ? "no" : "yes"}`;
}

export type SchedulingBody = { interval: { var: string; index: string[] }; over: Binding[] };

/** Which scheduling rule a constraint is, if it is one. */
export function schedulingKind(rule: {
  no_overlap?: unknown;
  cumulative?: unknown;
}): "no_overlap" | "cumulative" | null {
  if (rule.no_overlap !== undefined) return "no_overlap";
  if (rule.cumulative !== undefined) return "cumulative";
  return null;
}

/** A one-line reading of a scheduling rule, or null for any other:
 * `no two of task[j] (j in job) overlap`. */
export function describeSchedule(rule: { no_overlap?: unknown; cumulative?: unknown }): string | null {
  const kind = schedulingKind(rule);
  if (kind === null) return null;
  const body = rule[kind] as SchedulingBody & { demand?: Term; capacity?: Term };
  const of = `${body.interval?.var ?? "?"}[${(body.interval?.index ?? []).join(", ")}]`;
  const over = (body.over ?? []).map(describeBinding).join(", ");
  if (kind === "no_overlap") return `no two of ${of} (${over}) overlap`;
  return (
    `${of} (${over}), each taking ${describeTerm(body.demand)}, ` +
    `stay within ${describeTerm(body.capacity)} at every moment`
  );
}

export type ObjectiveTerm = { id: string; weight: number; expression?: Term };

/** What the editor knows about the domain it is writing a model for. */
export type ModelContext = {
  /** Entity type names the IR declares as sets, in IR order. */
  sets: string[];
  /** Set name -> entity type id, for the filter catalogue. */
  setIds: Record<string, number>;
  /** Set name -> its attributes. */
  /** `enum_values`: the choices a list-of-choices attribute takes. */
  attributes: Record<string, { name: string; data_type: string; enum_values?: string[] | null }[]>;
  variables: Record<string, { index: string[]; domain: string }>;
  parameters: Record<string, { index: string[] }>;
  /** The relationship types the IR declares, with the entity types each
   * joins -- which is what decides whether a walk is offered at all. */
  /** `hierarchy`: a tree read from parent (the from end) to child, so a walk goes "below" or "above". */
  relationships: { name: string; from: string; to: string; hierarchy?: boolean; attributes?: { name: string; data_type: string }[] }[];
  /** The trained models the IR declares (Epic ML), with how many inputs each reads. */
  predictors?: Record<string, { inputs: number }>;
};

export const TERM_LABELS: Record<TermKind, string> = {
  const: "a number",
  par: "a parameter",
  var: "a variable",
  attr: "an attribute",
  sum: "a sum over a set",
  add: "several terms added",
  mul: "one term times another",
  pwl: "a piecewise curve of a variable",
  fn: "a function (log, exp, …) of a term",
  predict: "a trained model's prediction",
};

export function termKind(term: Term): TermKind {
  if ("const" in term) return "const";
  if ("par" in term) return "par";
  if ("var" in term) return "var";
  if ("attr" in term) return "attr";
  if ("sum" in term) return "sum";
  if ("add" in term) return "add";
  if ("pwl" in term) return "pwl";
  if ("fn" in term) return "fn";
  if ("predict" in term) return "predict";
  return "mul";
}

/** A new term of the chosen kind, filled in as far as the context allows so
 * the editor never shows a control with nothing in it. */
export function emptyTerm(kind: TermKind, context: ModelContext, bound: Binding[]): Term {
  switch (kind) {
    case "const":
      return { const: 0 };
    case "par": {
      const name = Object.keys(context.parameters)[0] ?? "";
      const arity = context.parameters[name]?.index.length ?? 0;
      return { par: name, index: fillIndices(arity, context.parameters[name]?.index ?? [], bound) };
    }
    case "var": {
      // An interval is not a number to read (its start and end are).
      const name = Object.keys(context.variables).find((n) => context.variables[n].domain !== "interval") ?? "";
      const arity = context.variables[name]?.index.length ?? 0;
      return { var: name, index: fillIndices(arity, context.variables[name]?.index ?? [], bound) };
    }
    case "attr": {
      const binding = bound[0];
      const attrs = binding ? arithmeticAttributes(context, binding.set) : [];
      return { attr: { of: binding?.index ?? "", name: attrs[0]?.name ?? "" } };
    }
    case "sum":
      // Defence: the kind picker hides sum when there is no set, but a
      // caller that forces one still must not invent an empty-set binding.
      if (context.sets.length === 0) {
        return { const: 0 };
      }
      return {
        sum: { const: 1 },
        over: [nextBinding(bound, context)],
      };
    case "add":
      return { add: [{ const: 0 }, { const: 0 }] };
    case "pwl": {
      // A straight line through two points: a curve with nothing bent yet.
      const name =
        Object.keys(context.variables).find((n) => ["integer", "continuous"].includes(context.variables[n].domain)) ?? "";
      const arity = context.variables[name]?.index.length ?? 0;
      return {
        pwl: { var: name, index: fillIndices(arity, context.variables[name]?.index ?? [], bound) },
        points: [
          [0, 0],
          [1, 1],
        ],
      };
    }
    case "fn": {
      // Of a decision when there is one: a function of data is only a number.
      const numeric = Object.keys(context.variables).some((n) => context.variables[n].domain !== "interval");
      return { fn: "exp", of: numeric ? emptyTerm("var", context, bound) : { const: 0 } };
    }
    case "predict":
      // A prediction names a predictor the model declares; the editor keeps
      // one it is given and does not mint one (the kind picker hides it).
      return { predict: "", of: [{ const: 0 }] };
    default:
      return { mul: [{ const: 1 }, { const: 0 }] };
  }
}

/** The attributes arithmetic admits, which is `integer` and `number`
 * since migration 0015 (contract §7). Reading a `number` is how a model
 * becomes continuous, and that is now a decision the platform records
 * rather than one it refuses. */
/** The edges the bindings in scope name with `as` (queue R19), each with the
 * walk it belongs to -- what an `attr of` an edge may read. */
export function edgesInScope(bound: Binding[]): { name: string; rel: string; path: boolean }[] {
  return bound
    .filter((b) => b.via?.as)
    .map((b) => ({ name: b.via!.as as string, rel: b.via!.rel, path: !singleStep(b.via!) }));
}

/** Whether a walk takes exactly one step, so a link it names is one link rather than a path. */
export function singleStep(via: Via): boolean {
  if (via.steps) return via.steps.min === 1 && via.steps.max === 1;
  return (via.depth ?? "one") === "one";
}

/** The numbers a relationship type declares for its edges. */
export function edgeAttributes(context: ModelContext, rel: string) {
  return (context.relationships.find((r) => r.name === rel)?.attributes ?? []).filter((a) =>
    (ARITHMETIC_ATTR_TYPES as readonly string[]).includes(a.data_type)
  );
}

export function arithmeticAttributes(context: ModelContext, set: string) {
  return (context.attributes[set] ?? []).filter((a) =>
    (ARITHMETIC_ATTR_TYPES as readonly string[]).includes(a.data_type)
  );
}

/**
 * The walks this binding could make: every relationship type with an end
 * of the binding's own set, paired with an already-bound index sitting at
 * the other end.
 *
 * Both halves of the offer are checked here, so the editor cannot compose
 * a `via` the validator would refuse -- `binding_via_endpoint_mismatch`
 * and `binding_via_anchor_not_bound` are unreachable from this UI.
 */
export type WalkEnd = "from" | "to" | "both";

export function walksAvailable(context: ModelContext, set: string, bound: Binding[]) {
  const offers: { rel: string; anchorEnd: WalkEnd; anchors: string[]; loops: boolean }[] = [];
  for (const rel of context.relationships) {
    for (const anchorEnd of ["from", "to"] as const) {
      const boundEnd = anchorEnd === "from" ? rel.to : rel.from;
      const anchorSet = anchorEnd === "from" ? rel.from : rel.to;
      if (boundEnd !== set) continue;
      const anchors = uniqueByIndex(bound.filter((b) => b.set === anchorSet)).map((b) => b.index);
      if (anchors.length === 0) continue;
      offers.push({ rel: rel.name, anchorEnd, anchors, loops: rel.from === rel.to });
    }
    // A relationship from a set to itself can also be walked either way.
    if (rel.from === rel.to && rel.to === set) {
      const anchors = uniqueByIndex(bound.filter((b) => b.set === set)).map((b) => b.index);
      if (anchors.length > 0) offers.push({ rel: rel.name, anchorEnd: "both", anchors, loops: true });
    }
  }
  return offers;
}

/** `reports_to:from` -- one select carries both, because a self-joining
 * type offers the same name at both ends and the pair is what identifies
 * the walk. */
export function walkKey(rel: string, anchorEnd: WalkEnd) {
  return `${rel}:${anchorEnd}`;
}

export function viaOf(binding: Binding): { rel: string; anchorEnd: WalkEnd; anchor: string } | null {
  const via = binding.via;
  if (!via) return null;
  const anchorEnd: WalkEnd = via.from !== undefined ? "from" : via.both !== undefined ? "both" : "to";
  return { rel: via.rel, anchorEnd, anchor: (via.from ?? via.both ?? via.to) as string };
}

/** Indices bound at a point in the tree: the constraint's `forall` plus
 * every enclosing `sum`'s `over`. */
export function boundIndices(outer: Binding[], added: Binding[] = []): Binding[] {
  return [...outer, ...added];
}

/** Keep the first binding of each index name. A sum that rebinds a set
 * already bound outside would otherwise list `d` twice in the index
 * picker, which is the same choice twice and a duplicate React key. */
export function uniqueByIndex(bound: Binding[]): Binding[] {
  const seen = new Set<string>();
  return bound.filter((binding) => {
    if (seen.has(binding.index)) return false;
    seen.add(binding.index);
    return true;
  });
}

export function fillIndices(arity: number, wantedSets: string[], bound: Binding[]): string[] {
  // Two cells of one set take two different names when there are two (cc_km[c, c2], not
  // cc_km[c, c] -- benchmark, October 2026); with one, both read it.
  const used = new Set<Binding>();
  return Array.from({ length: arity }, (_, position) => {
    const set = wantedSets[position];
    const found = bound.find((b) => b.set === set && !used.has(b)) ?? bound.find((b) => b.set === set);
    if (found) used.add(found);
    return found?.index ?? "";
  });
}

/** `e`, then `e2`, `e3`… — a name not already bound. */
export function freeIndexName(bound: Binding[], seed = "i"): string {
  const taken = new Set(bound.map((b) => b.index));
  if (!taken.has(seed)) return seed;
  for (let n = 2; n < 100; n += 1) {
    if (!taken.has(`${seed}${n}`)) return `${seed}${n}`;
  }
  return `${seed}_`;
}

/** Drop UI-only fields and empty optionals so a binding matches the contract. */
export function cleanBinding(binding: Binding & { problems?: string[] }): Binding {
  const next: Binding = { index: binding.index, set: binding.set };
  if (binding.where && binding.where.length > 0) next.where = binding.where;
  if (binding.via) next.via = binding.via;
  return next;
}

/** Walk a term and clean every binding it ranges over. */
export function cleanTerm(term: Term): Term {
  if ("sum" in term) {
    return { sum: cleanTerm(term.sum), over: term.over.map(cleanBinding) };
  }
  if ("add" in term) {
    return { add: term.add.map(cleanTerm) };
  }
  if ("mul" in term) {
    return { mul: [cleanTerm(term.mul[0]), cleanTerm(term.mul[1])] };
  }
  return term;
}

export function seedForSet(set: string): string {
  return /^[a-z]/.test(set) ? set[0] : "i";
}

/** True when the index is still the name `nextBinding` would have chosen
 * for this set (`e`, `e2`, …), so changing the set may rename it. A name
 * the person typed (`person`) is left alone. */
export function isGeneratedIndex(index: string, set: string): boolean {
  const seed = seedForSet(set);
  return index === seed || new RegExp(`^${seed}\\d+$`).test(index);
}

/** The next binding to add: a set not already ranged over, named after
 * that set (`e` for employee). When every set is already bound, reuse the
 * first one with a free name (`e2`) rather than a generic `i`. */
export function nextBinding(bound: Binding[], context: ModelContext): Binding {
  const used = new Set(bound.map((b) => b.set));
  const set = context.sets.find((name) => !used.has(name)) ?? context.sets[0] ?? "";
  return { index: freeIndexName(bound, seedForSet(set)), set };
}

/** The next free `c_1` / `o_2` style id among those already taken. */
export function freeNumberedId(prefix: string, taken: string[]): string {
  const used = new Set(taken);
  for (let n = 1; n < 1000; n += 1) {
    const id = `${prefix}${n}`;
    if (!used.has(id)) return id;
  }
  return `${prefix}${taken.length + 1}`;
}

/**
 * Every relationship type a model actually walks, sorted, for the IR's
 * `relationships` declaration.
 *
 * Walks the whole tree because a `via` can be nested arbitrarily deep
 * inside a sum. Sorted so that two drafts holding the same walks produce
 * the same document, and therefore the same `ir_hash` -- an order that
 * followed the editing history would mint a new version for no change.
 */
export function declaredRelationships(
  constraints: Constraint[],
  objectiveTerms: ObjectiveTerm[]
): string[] {
  const found = new Set<string>();

  function fromBindings(bindings: Binding[] | undefined) {
    for (const binding of bindings ?? []) {
      if (binding.via) found.add(binding.via.rel);
    }
  }

  function fromTerm(term: Term | undefined) {
    if (term == null) return;
    switch (termKind(term)) {
      case "sum": {
        const t = term as { sum: Term; over: Binding[] };
        fromBindings(t.over);
        fromTerm(t.sum);
        return;
      }
      case "add":
        (term as { add: Term[] }).add.forEach(fromTerm);
        return;
      case "mul":
        (term as { mul: [Term, Term] }).mul.forEach(fromTerm);
        return;
      default:
        return;
    }
  }

  for (const constraint of constraints) {
    fromBindings(constraint.forall);
    fromTerm(constraint.left);
    fromTerm(constraint.right);
    fromBindings(constraint.no_overlap?.over);
    fromBindings(constraint.cumulative?.over);
    if (constraint.connected?.via) found.add(constraint.connected.via);
  }
  for (const term of objectiveTerms) fromTerm(term.expression);

  return [...found].sort();
}

/** `e in employee` or, for a walk, `sub in unit via reports_to from u`. */
export function describeBinding(binding: Binding): string {
  const walk = viaOf(binding);
  if (!walk) return `${binding.index} in ${binding.set}`;
  const depth = binding.via?.depth ?? "one";
  const reach = depth === "one" ? "" : depth === "any" ? ", any depth" : ", any depth or itself";
  return `${binding.index} in ${binding.set} via ${walk.rel} ${walk.anchorEnd} ${walk.anchor}${reach}`;
}

/** A one-line reading of a term, for a summary row: `sum(assign[e,d,s])`. */
export function describeTerm(term: Term | undefined | null): string {
  if (term == null) return "(not yet expressed)";
  switch (termKind(term)) {
    case "const":
      return String((term as { const: number }).const);
    case "par": {
      const t = term as { par: string; index: string[] };
      return `${t.par}[${t.index.map(cellText).join(", ")}]`;
    }
    case "var": {
      const t = term as { var: string; index: string[] };
      return `${t.var}[${t.index.map(cellText).join(", ")}]`;
    }
    case "attr": {
      const t = term as { attr: { of: string; name: string; along?: string } };
      return t.attr.along ? `${t.attr.along} of ${t.attr.name} along ${t.attr.of}` : `${t.attr.name}[${t.attr.of}]`;
    }
    case "sum": {
      const t = term as { sum: Term; over: Binding[] };
      return `sum(${describeTerm(t.sum)} over ${t.over.map(describeBinding).join(", ")})`;
    }
    case "add":
      return (term as { add: Term[] }).add.map(describeTerm).join(" + ");
    case "pwl": {
      const t = term as { pwl: { var: string; index: string[] }; points: [number, number][] };
      return `curve(${t.pwl.var}[${t.pwl.index.join(", ")}], ${t.points.length} points)`;
    }
    case "fn": {
      const t = term as { fn: string; of: Term };
      return `${t.fn}(${describeTerm(t.of)})`;
    }
    case "predict": {
      const t = term as { predict: string; of: Term[] };
      return `predict ${t.predict}(${t.of.map(describeTerm).join(", ")})`;
    }
    default: {
      const t = term as { mul: [Term, Term] };
      return `${describeTerm(t.mul[0])} × ${describeTerm(t.mul[1])}`;
    }
  }
}

/** How many decisions this term multiplies together: 0 for a number, 1 for
 * a linear term, 2 for a quadratic one. The contract allows two at most in a
 * rule or a weighted goal, so the editor can say so before the server does. */
export function degree(term: Term): number {
  switch (termKind(term)) {
    case "var":
    case "pwl":
      return 1;
    case "fn":
      // It stands for a decision of its own when its argument reads one.
      return degree((term as { of: Term }).of) ? 1 : 0;
    case "predict":
      // Likewise a prediction, when any input reads one.
      return (term as { of: Term[] }).of.some((input) => degree(input) > 0) ? 1 : 0;
    case "sum":
      return degree((term as { sum: Term }).sum);
    case "add":
      return Math.max(0, ...(term as { add: Term[] }).add.map(degree));
    case "mul":
      return (term as { mul: [Term, Term] }).mul.reduce((total, factor) => total + degree(factor), 0);
    default:
      return 0;
  }
}
