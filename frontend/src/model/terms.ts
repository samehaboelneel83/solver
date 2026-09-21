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
  | { mul: [Term, Term] };

export type Constraint = {
  id: string;
  note?: string;
  forall?: Binding[];
  left: Term;
  relation: Relation;
  right: Term;
  severity: Severity;
  penalty?: number;
};

export type ObjectiveTerm = { id: string; weight: number; expression: Term };

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
};

export function termKind(term: Term): TermKind {
  if ("const" in term) return "const";
  if ("par" in term) return "par";
  if ("var" in term) return "var";
  if ("attr" in term) return "attr";
  if ("sum" in term) return "sum";
  if ("add" in term) return "add";
  return "mul";
}

/** A new term of the chosen kind, filled in as far as the context allows so
 * the editor never shows a control with nothing in it. */
export function emptyTerm(kind: TermKind, context: ModelContext, bound: Binding[]): Term {
  const firstSet = context.sets[0] ?? "";
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
      return {
        sum: { const: 1 },
        over: [{ index: freeIndexName(bound), set: firstSet }],
      };
    case "add":
      return { add: [{ const: 0 }, { const: 0 }] };
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
      const anchors = bound.filter((b) => b.set === anchorSet).map((b) => b.index);
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

  function fromTerm(term: Term) {
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
export function describeTerm(term: Term): string {
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
    default: {
      const t = term as { mul: [Term, Term] };
      return `${describeTerm(t.mul[0])} × ${describeTerm(t.mul[1])}`;
    }
  }
}

/** Does this term mention a variable? The contract refuses a product of two
 * that do, so the editor can say it before the server does. */
export function mentionsVariable(term: Term): boolean {
  switch (termKind(term)) {
    case "var":
      return true;
    case "sum":
      return mentionsVariable((term as { sum: Term }).sum);
    case "add":
      return (term as { add: Term[] }).add.some(mentionsVariable);
    case "mul":
      return (term as { mul: [Term, Term] }).mul.some(mentionsVariable);
    default:
      return false;
  }
}
