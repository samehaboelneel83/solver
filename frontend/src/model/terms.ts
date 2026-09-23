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
import type { Relation, Severity, TermKind, TraversalDepth } from "../ir";

export type IrFilter = { attr: string; op: string; value: unknown };

/**
 * A traversal. `from`/`to` name the end the **anchor** sits at, so the
 * index being bound takes the other one -- which is why exactly one of
 * them is ever present.
 */
export type Via = { rel: string; from?: string; to?: string; depth?: TraversalDepth };
export type Binding = { index: string; set: string; where?: IrFilter[]; via?: Via };

export type Term =
  | { const: number }
  | { par: string; index: string[] }
  | { var: string; index: string[] }
  | { attr: { of: string; name: string } }
  | { sum: Term; over: Binding[] }
  | { add: Term[] }
  | { mul: [Term, Term] }
  | { pwl: { var: string; index: string[] }; points: [number, number][] };

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
};

export type ObjectiveTerm = { id: string; weight: number; expression?: Term };

/** What the editor knows about the domain it is writing a model for. */
export type ModelContext = {
  /** Entity type names the IR declares as sets, in IR order. */
  sets: string[];
  /** Set name -> entity type id, for the filter catalogue. */
  setIds: Record<string, number>;
  /** Set name -> its attributes. */
  attributes: Record<string, { name: string; data_type: string }[]>;
  variables: Record<string, { index: string[]; domain: string }>;
  parameters: Record<string, { index: string[] }>;
  /** The relationship types the IR declares, with the entity types each
   * joins -- which is what decides whether a walk is offered at all. */
  relationships: { name: string; from: string; to: string }[];
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
};

export function termKind(term: Term): TermKind {
  if ("const" in term) return "const";
  if ("par" in term) return "par";
  if ("var" in term) return "var";
  if ("attr" in term) return "attr";
  if ("sum" in term) return "sum";
  if ("add" in term) return "add";
  if ("pwl" in term) return "pwl";
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
      const name = Object.keys(context.variables)[0] ?? "";
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
      const name = Object.keys(context.variables)[0] ?? "";
      const arity = context.variables[name]?.index.length ?? 0;
      return {
        pwl: { var: name, index: fillIndices(arity, context.variables[name]?.index ?? [], bound) },
        points: [
          [0, 0],
          [1, 1],
        ],
      };
    }
    default:
      return { mul: [{ const: 1 }, { const: 0 }] };
  }
}

/** The attributes arithmetic admits, which is `integer` and `number`
 * since migration 0015 (contract §7). Reading a `number` is how a model
 * becomes continuous, and that is now a decision the platform records
 * rather than one it refuses. */
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
export function walksAvailable(context: ModelContext, set: string, bound: Binding[]) {
  const offers: { rel: string; anchorEnd: "from" | "to"; anchors: string[]; loops: boolean }[] = [];
  for (const rel of context.relationships) {
    for (const anchorEnd of ["from", "to"] as const) {
      const boundEnd = anchorEnd === "from" ? rel.to : rel.from;
      const anchorSet = anchorEnd === "from" ? rel.from : rel.to;
      if (boundEnd !== set) continue;
      const anchors = uniqueByIndex(bound.filter((b) => b.set === anchorSet)).map((b) => b.index);
      if (anchors.length === 0) continue;
      offers.push({ rel: rel.name, anchorEnd, anchors, loops: rel.from === rel.to });
    }
  }
  return offers;
}

/** `reports_to:from` -- one select carries both, because a self-joining
 * type offers the same name at both ends and the pair is what identifies
 * the walk. */
export function walkKey(rel: string, anchorEnd: "from" | "to") {
  return `${rel}:${anchorEnd}`;
}

export function viaOf(binding: Binding): { rel: string; anchorEnd: "from" | "to"; anchor: string } | null {
  const via = binding.via;
  if (!via) return null;
  const anchorEnd = via.from !== undefined ? "from" : "to";
  return { rel: via.rel, anchorEnd, anchor: (via.from ?? via.to) as string };
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

function fillIndices(arity: number, wantedSets: string[], bound: Binding[]): string[] {
  return Array.from({ length: arity }, (_, position) => {
    const set = wantedSets[position];
    return bound.find((b) => b.set === set)?.index ?? "";
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
      return `${t.par}[${t.index.join(", ")}]`;
    }
    case "var": {
      const t = term as { var: string; index: string[] };
      return `${t.var}[${t.index.join(", ")}]`;
    }
    case "attr": {
      const t = term as { attr: { of: string; name: string } };
      return `${t.attr.name}[${t.attr.of}]`;
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
