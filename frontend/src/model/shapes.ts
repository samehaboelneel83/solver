/**
 * Starting shapes for a new rule or goal: the patterns most models are made
 * of, filled in from what this model already declares, so a person composes
 * from something whole and then reshapes it in the boxes -- rather than
 * starting from `0 <= 0`.
 *
 * Every shape is a well-formed IR tree over declared names (checked by
 * `blockCheck`); a shape that needs something the model lacks is not offered,
 * and says what it needs.
 */
import { fillIndices, freeIndexName, seedForSet, type Binding, type Constraint, type ModelContext, type ObjectiveTerm, type Term } from "./terms";

export type RuleShape = "cap_total" | "cap_each" | "cover_each" | "cap_linked" | "cap_when_chosen" | "cover_within_reach" | "total_per_item" | "rest_between";
export type GoalShape = "count" | "cost";

/** The decision a shape is built on: the first that is a number and (when asked) over at least
 * `sets` sets -- so a shape for "a decision over two sets" finds base[yard, truck] even when a
 * yes/no open[yard] was declared first. */
function decision(context: ModelContext, sets = 0): { name: string; index: string[] } | null {
  const found = Object.entries(context.variables).find(([, spec]) => spec.domain !== "interval" && spec.index.length >= sets);
  return found ? { name: found[0], index: found[1].index } : null;
}

/** How much data looks like 0/1 "within reach" (made by the map's "0/1 within"), not a distance. */
function reachLike(name: string, spec: { index: string[] }): number {
  const words = /reach|within|cover|near|can|ok|flag|allowed|serves/i.test(name) ? 2 : 0;
  const far = /dist|min|km|time|cost|price|minutes|metres|meters/i.test(name) ? -2 : 0;
  const zero = (spec as { default?: number | string }).default;
  return words + far + (zero === undefined || Number(zero) === 0 ? 1 : 0);
}

/**
 * A decision over one set that a relationship reaches, and the walk to it:
 * for a relationship from a set to itself (a hierarchy) down from each item
 * to everything under it; otherwise from each item at the other end.
 */
function linked(context: ModelContext): { name: string; set: string; rel: string; anchorSet: string; end: "from" | "to"; loops: boolean } | null {
  for (const [name, spec] of Object.entries(context.variables)) {
    if (spec.domain === "interval" || spec.index.length !== 1) continue;
    const set = spec.index[0];
    // A hierarchy first: "everything under each item" is the walk most models mean.
    const rels = [...context.relationships].sort((a, b) => Number(!!b.hierarchy) - Number(!!a.hierarchy));
    for (const rel of rels) {
      if (rel.to === set) return { name, set, rel: rel.name, anchorSet: rel.from, end: "from", loops: rel.from === rel.to };
      if (rel.from === set) return { name, set, rel: rel.name, anchorSet: rel.to, end: "to", loops: false };
    }
  }
  return null;
}

/** One binding per set, with fresh letters. */
function bindingsFor(sets: string[], outer: Binding[] = []): Binding[] {
  const out: Binding[] = [];
  for (const set of sets) out.push({ index: freeIndexName([...outer, ...out], seedForSet(set)), set });
  return out;
}

/** Data read over the bound sets (all of its index among them), at the bound letters. */
function dataOver(context: ModelContext, bound: Binding[]): Term | null {
  const sets = bound.map((b) => b.set);
  // The data that matches the most of these sets: cost[e, d] before demand[d].
  const found = Object.entries(context.parameters)
    .filter(([, spec]) => spec.index.length > 0 && spec.index.every((s) => sets.includes(s)))
    .sort(([, a], [, b]) => b.index.length - a.index.length)[0];
  if (!found) return null;
  return { par: found[0], index: fillIndices(found[1].index.length, found[1].index, bound) };
}

/**
 * Improvement plan 4.3, "capacity only when chosen": a yes/no decision over one set (open[yard]) and
 * another decision that set indexes (station[yard, truck]). Each item's total is at most its capacity
 * times its yes/no -- nothing goes to a closed site. The capacity is the item's first number field,
 * else data over that set, else 10 for the person to change.
 */
function whenChosen(context: ModelContext): { flag: string; set: string; amount: { name: string; index: string[] } } | null {
  for (const [flag, spec] of Object.entries(context.variables)) {
    if (spec.domain !== "binary" || spec.index.length !== 1) continue;
    const set = spec.index[0];
    const amount = Object.entries(context.variables).find(([name, other]) =>
      name !== flag && other.domain !== "interval" && other.index.length >= 2 && other.index.includes(set));
    if (amount) return { flag, set, amount: { name: amount[0], index: amount[1].index } };
  }
  return null;
}

/**
 * Improvement plan 4.3, "cover from within reach": a decision over the sets that serve (yards,
 * depots, nurses), and either 0/1 data reach[server, item] (made by "From the map → within") or a
 * relationship between the two kinds. Each item needs at least one chosen within its reach.
 */
function withinReach(context: ModelContext): { name: string; index: string[]; server: string; item: string; par?: string; rel?: { name: string; end: "from" | "to" } } | null {
  for (const [name, spec] of Object.entries(context.variables)) {
    if (spec.domain === "interval" || !spec.index.length) continue;
    // The data most like 0/1 reach first: reach[yard, hotspot] before drive_min[yard, hotspot].
    const pars = Object.entries(context.parameters).sort(([n1, p1], [n2, p2]) => reachLike(n2, p2) - reachLike(n1, p1));
    for (const [par, p] of pars) {
      if (p.index.length !== 2) continue;
      const [a, b] = p.index;
      if (spec.index.includes(a) && !spec.index.includes(b)) return { name, index: spec.index, server: a, item: b, par };
    }
    for (const rel of context.relationships) {
      if (spec.index.includes(rel.from) && !spec.index.includes(rel.to)) return { name, index: spec.index, server: rel.from, item: rel.to, rel: { name: rel.name, end: "to" } };
      if (spec.index.includes(rel.to) && !spec.index.includes(rel.from)) return { name, index: spec.index, server: rel.to, item: rel.from, rel: { name: rel.name, end: "from" } };
    }
  }
  return null;
}

/**
 * Improvement plan 5.2, workforce rules: a decision over (who, slot) and a relationship from the slot
 * kind to itself -- "too_close", made by Data values → From times -- so nobody takes two slots that
 * overlap or leave too little rest.
 */
function restPair(context: ModelContext): { name: string; index: string[]; slot: string; rel: string } | null {
  for (const rel of context.relationships) {
    if (rel.from !== rel.to) continue;
    const found = Object.entries(context.variables).find(([, spec]) =>
      spec.domain === "binary" && spec.index.length >= 2 && spec.index.filter((s) => s === rel.from).length === 1);
    if (found) return { name: found[0], index: found[1].index, slot: rel.from, rel: rel.name };
  }
  return null;
}

export const RULE_SHAPES: { shape: RuleShape; title: string; needs: (context: ModelContext) => string | null }[] = [
  {
    shape: "cap_total",
    title: "A total is at most a limit",
    needs: (c) => (decision(c) ? null : "a decision"),
  },
  {
    shape: "cap_each",
    title: "For each item, a decision is at most its limit",
    needs: (c) => (decision(c)?.index.length ? null : "a decision over a set"),
  },
  {
    shape: "cover_each",
    title: "For each item, a total covers what is needed",
    needs: (c) => (decision(c, 2) ? null : "a decision over two sets"),
  },
  {
    shape: "cap_linked",
    title: "For each item, a total over what is linked to it is at most a limit",
    needs: (c) => (linked(c) ? null : "a decision over a set that a relationship reaches"),
  },
  {
    shape: "cap_when_chosen",
    title: "For each item, at most its capacity -- and nothing unless it is chosen",
    needs: (c) => (whenChosen(c) ? null : "a yes/no decision over a set, and another decision over that set and more"),
  },
  {
    shape: "cover_within_reach",
    title: "For each item, at least one chosen from those within its reach",
    needs: (c) => (withinReach(c) ? null : "a decision, and 0/1 reach data -- tick it under “Data this model reads” -- or a relationship to the items it covers"),
  },
  {
    shape: "total_per_item",
    title: "For each item, its total over the rest is at most its own limit (hours, shifts, load)",
    needs: (c) => (decision(c, 2) ? null : "a decision over two sets"),
  },
  {
    shape: "rest_between",
    title: "Nobody takes two slots that are too close (rest between shifts, no overlaps)",
    needs: (c) => (restPair(c) ? null : "a yes/no decision over who and when, and a too-close link between slots (Data values → From times)"),
  },
];

export function ruleFromShape(shape: RuleShape, id: string, context: ModelContext): Constraint {
  const d = decision(context);
  if (!d) throw new Error("This model has no decision to build a rule on yet.");
  if (shape === "cap_each") {
    const forall = bindingsFor(d.index);
    return {
      id,
      forall,
      left: { var: d.name, index: forall.map((b) => b.index) },
      relation: "<=",
      right: dataOver(context, forall) ?? { const: 1 },
      severity: "hard",
    };
  }
  const two = decision(context, 2);
  if (shape === "total_per_item" && two) {
    const d = two;
    // "For each operator o: sum(work[o, b] for b in time_block) <= o's max_shifts."
    const forall = bindingsFor([d.index[0]]);
    const over = bindingsFor(d.index.slice(1), forall);
    const letters = new Map([...forall, ...over].map((b) => [b.set, b.index]));
    const field = (context.attributes[d.index[0]] ?? []).find((a) => a.data_type === "integer" || a.data_type === "number");
    const limit: Term = field ? { attr: { of: forall[0].index, name: field.name } } : dataOver(context, forall) ?? { const: 5 };
    return {
      id, forall,
      left: { sum: { var: d.name, index: d.index.map((set) => letters.get(set) ?? "") }, over },
      relation: "<=", right: limit, severity: "hard",
    };
  }
  const rest = shape === "rest_between" ? restPair(context) : null;
  if (rest) {
    // "For each operator o, slot a, and slot b too close after a: work[o, a] + work[o, b] <= 1."
    const others = bindingsFor(rest.index.filter((set) => set !== rest.slot));
    const [first] = bindingsFor([rest.slot], others);
    const second = { ...bindingsFor([rest.slot], [...others, first])[0], via: { rel: rest.rel, from: first.index } };
    const forall = [...others, first, second];
    const at = (slot: string): Term => ({ var: rest.name, index: rest.index.map((set) => (set === rest.slot ? slot : others.find((b) => b.set === set)?.index ?? "")) });
    return { id, forall, left: { add: [at(first.index), at(second.index)] }, relation: "<=", right: { const: 1 }, severity: "hard" };
  }
  const chosen = shape === "cap_when_chosen" ? whenChosen(context) : null;
  if (chosen) {
    // "For each yard y: sum(station[y, t] for t in truck) <= y's max_trucks * open[y]."
    const forall = bindingsFor([chosen.set]);
    const over = bindingsFor(chosen.amount.index.filter((set) => set !== chosen.set), forall);
    const letters = new Map([...forall, ...over].map((b) => [b.set, b.index]));
    const field = (context.attributes[chosen.set] ?? []).find((a) => a.data_type === "integer" || a.data_type === "number");
    const capacity: Term = field ? { attr: { of: forall[0].index, name: field.name } } : dataOver(context, forall) ?? { const: 10 };
    return {
      id,
      forall,
      left: { sum: { var: chosen.amount.name, index: chosen.amount.index.map((set) => letters.get(set) ?? "") }, over },
      relation: "<=",
      right: { mul: [capacity, { var: chosen.flag, index: [forall[0].index] }] },
      severity: "hard",
    };
  }
  const reach = shape === "cover_within_reach" ? withinReach(context) : null;
  if (reach) {
    // "For each hotspot h: sum(reach[y, h] * station[y, t] for y in yard, t in truck) >= 1."
    const forall = bindingsFor([reach.item]);
    const over = bindingsFor(reach.index, forall);
    const letters = new Map([...forall, ...over].map((b) => [b.set, b.index]));
    const read: Term = { var: reach.name, index: reach.index.map((set) => letters.get(set) ?? "") };
    if (reach.par) {
      const near: Term = { par: reach.par, index: [letters.get(reach.server) ?? "", forall[0].index] };
      return { id, forall, left: { sum: { mul: [near, read] }, over }, relation: ">=", right: { const: 1 }, severity: "hard" };
    }
    const walked = over.map((b) => (b.set === reach.server && reach.rel ? { ...b, via: { rel: reach.rel.name, [reach.rel.end]: forall[0].index } } : b));
    return { id, forall, left: { sum: read, over: walked }, relation: ">=", right: { const: 1 }, severity: "hard" };
  }
  const link = shape === "cap_linked" ? linked(context) : null;
  if (link) {
    // "For each manager m, the total of pick over everyone under m is at most 1."
    const forall = bindingsFor([link.anchorSet]);
    const [reached] = bindingsFor([link.set], forall);
    const via = { rel: link.rel, [link.end]: forall[0].index, ...(link.loops ? { depth: "any" as const } : {}) };
    return {
      id,
      forall,
      left: { sum: { var: link.name, index: [reached.index] }, over: [{ ...reached, via }] },
      relation: "<=",
      right: { const: 1 },
      severity: "hard",
    };
  }
  if (shape === "cover_each" && two) {
    const d = two;
    // Checked once per item of the set that has a need to cover (demand[day]), totalled over the rest.
    const each = d.index.find((set) => Object.values(context.parameters).some((p) => p.index.length === 1 && p.index[0] === set)) ?? d.index[0];
    const forall = bindingsFor([each]);
    const over = bindingsFor(d.index.filter((set) => set !== each), forall);
    const letters = new Map([...forall, ...over].map((b) => [b.set, b.index]));
    return {
      id,
      forall,
      left: { sum: { var: d.name, index: d.index.map((set) => letters.get(set) ?? "") }, over },
      relation: ">=",
      right: dataOver(context, forall) ?? { const: 1 },
      severity: "hard",
    };
  }
  const over = bindingsFor(d.index);
  const read: Term = { var: d.name, index: over.map((b) => b.index) };
  return {
    id,
    left: over.length ? { sum: read, over } : read,
    relation: "<=",
    right: { const: 10 },
    severity: "hard",
  };
}

export const GOAL_SHAPES: { shape: GoalShape; title: string; needs: (context: ModelContext) => string | null }[] = [
  { shape: "count", title: "The total of a decision", needs: (c) => (decision(c) ? null : "a decision") },
  { shape: "cost", title: "A cost: data times a decision, totalled", needs: (c) => (decision(c) ? null : "a decision") },
];

export function goalFromShape(shape: GoalShape, id: string, context: ModelContext): ObjectiveTerm {
  const d = decision(context);
  if (!d) throw new Error("This model has no decision to count yet.");
  const over = bindingsFor(d.index);
  const read: Term = { var: d.name, index: over.map((b) => b.index) };
  const body: Term = shape === "cost" ? { mul: [dataOver(context, over) ?? { const: 1 }, read] } : read;
  return { id, weight: 1, expression: over.length ? { sum: body, over } : body };
}
