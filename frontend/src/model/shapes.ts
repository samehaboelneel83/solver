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

export type RuleShape = "cap_total" | "cap_each" | "cover_each";
export type GoalShape = "count" | "cost";

/** The decision a shape is built on: the first one that is a number. */
function decision(context: ModelContext): { name: string; index: string[] } | null {
  const found = Object.entries(context.variables).find(([, spec]) => spec.domain !== "interval");
  return found ? { name: found[0], index: found[1].index } : null;
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
    needs: (c) => ((decision(c)?.index.length ?? 0) >= 2 ? null : "a decision over two sets"),
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
  if (shape === "cover_each" && d.index.length >= 2) {
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
