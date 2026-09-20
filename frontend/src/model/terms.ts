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

import type { Relation, Severity, TermKind } from "../ir";

export type IrFilter = { attr: string; op: string; value: unknown };
export type Binding = { index: string; set: string; where?: IrFilter[] };

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
  /** Set name -> its attributes. Arithmetic admits `integer` only. */
  attributes: Record<string, { name: string; data_type: string }[]>;
  variables: Record<string, { index: string[]; domain: string }>;
  parameters: Record<string, { index: string[] }>;
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
      const attrs = binding ? integerAttributes(context, binding.set) : [];
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

/** Only `integer` attributes are arithmetic (contract §7): admitting
 * `number` would make a model continuous without anyone deciding to. */
export function integerAttributes(context: ModelContext, set: string) {
  return (context.attributes[set] ?? []).filter((a) => a.data_type === "integer");
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
      return `sum(${describeTerm(t.sum)} over ${t.over.map((b) => `${b.index} in ${b.set}`).join(", ")})`;
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
