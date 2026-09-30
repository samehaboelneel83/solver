/**
 * The hierarchical check behind the Boxes and Sentence views
 * (docs/design/nested-blocks.md, "The validation engine").
 *
 * Every part of a rule or goal is checked on its own -- a number, a decision,
 * a piece of data first, then the operations that combine them, the totals
 * over sets, the comparison, the rule -- and a problem is reported with the
 * path from the rule down to the part that has it: "left side › term 2 ›
 * hours[q]: “q” is not bound here". A box shows its own problems, and says
 * how many its parts hold, so a problem deep inside is visible at every level
 * above it without repeating it there.
 *
 * It is the editor's early, local reading. The server's contract check
 * (app/ir/validate.py, mirrored in src/ir/validate.ts) stays the judge at
 * Publish; nothing here lets through what that refuses.
 */
import { FUNCTIONS } from "../ir";
import { opsFor, OP_WORDS } from "./whereWords";
import { arithmeticAttributes, degree, type Binding, type Constraint, type ModelContext, type Term } from "./terms";

/** Where in the hierarchy a problem sits (the design's validation levels). */
export type Level = "primitive" | "operation" | "aggregation" | "comparison" | "rule";

export type Problem = {
  /** From the rule (or goal) down to the part, in the words the boxes use. */
  path: string[];
  level: Level;
  message: string;
};

function isBound(name: string, bound: Binding[]): Binding | undefined {
  for (let i = bound.length - 1; i >= 0; i -= 1) {
    if (bound[i].index === name) return bound[i];
  }
  return undefined;
}

/** An index cell is a bound name, or a parameter read at bound names (next_day[d]). */
function checkCells(owner: string, cells: unknown[], bound: Binding[], path: string[], out: Problem[]) {
  for (const cell of cells) {
    if (typeof cell === "string") {
      if (!cell) out.push({ path, level: "primitive", message: `${owner} has an empty index` });
      else if (!isBound(cell, bound)) {
        out.push({ path, level: "primitive", message: `“${cell}” is not bound here: add it to a “for each” or to a total` });
      }
    } else if (cell && typeof cell === "object" && "index" in cell) {
      checkCells(owner, (cell as { index: unknown[] }).index, bound, path, out);
    }
  }
}

function arity(owner: string, declared: string[] | undefined, given: unknown[], path: string[], out: Problem[]) {
  if (declared && declared.length !== given.length) {
    out.push({
      path,
      level: "primitive",
      message: `${owner} takes ${declared.length} ${declared.length === 1 ? "index" : "indices"}${declared.length ? ` (${declared.join(", ")})` : ""}, not ${given.length}`,
    });
  }
}

/** Every problem in a term and its parts, each with its path below `path`. */
export function checkTerm(term: Term, context: ModelContext, bound: Binding[], path: string[] = []): Problem[] {
  const out: Problem[] = [];
  const at = (label: string) => [...path, label];
  if ("const" in term) {
    if (!Number.isFinite(term.const)) out.push({ path, level: "primitive", message: "a number is needed here" });
  } else if ("var" in term) {
    const spec = context.variables[term.var];
    if (!term.var) out.push({ path, level: "primitive", message: "choose which decision" });
    else if (!spec) out.push({ path, level: "primitive", message: `“${term.var}” is not a decision of this model` });
    else if (spec.domain === "interval") {
      out.push({ path, level: "primitive", message: `“${term.var}” is a time span, not a number to calculate with` });
    }
    arity(term.var || "The decision", spec?.index, term.index, path, out);
    checkCells(term.var, term.index, bound, path, out);
  } else if ("par" in term) {
    const spec = context.parameters[term.par];
    if (!term.par) out.push({ path, level: "primitive", message: "choose which data" });
    else if (!spec) out.push({ path, level: "primitive", message: `“${term.par}” is not data this model has` });
    arity(term.par || "The data", spec?.index, term.index, path, out);
    checkCells(term.par, term.index, bound, path, out);
  } else if ("attr" in term) {
    const binding = isBound(term.attr.of, bound);
    if (!term.attr.along) {
      if (!binding) out.push({ path, level: "primitive", message: `“${term.attr.of || "?"}” is not bound here` });
      else if (!arithmeticAttributes(context, binding.set).some((a) => a.name === term.attr.name)) {
        out.push({ path, level: "primitive", message: `${binding.set} has no number called “${term.attr.name || "?"}”` });
      }
    }
  } else if ("sum" in term) {
    if (term.over.length === 0) {
      out.push({ path, level: "aggregation", message: "a total says what it runs over" });
    }
    const seen = new Set<string>();
    for (const binding of term.over) {
      if (!context.sets.includes(binding.set)) {
        out.push({ path, level: "aggregation", message: `“${binding.set || "?"}” is not a set of this model` });
      }
      if (!/^[a-z][a-z0-9_]*$/.test(binding.index)) {
        out.push({ path, level: "aggregation", message: `“${binding.index}” is not a usable name for each item` });
      } else if (seen.has(binding.index) || isBound(binding.index, bound)) {
        out.push({ path, level: "aggregation", message: `“${binding.index}” already names something here; pick another letter` });
      }
      seen.add(binding.index);
      for (const message of checkWhere(binding, context)) out.push({ path, level: "aggregation", message });
    }
    out.push(...checkTerm(term.sum, context, [...bound, ...term.over], at("what is totalled")));
  } else if ("add" in term) {
    if (term.add.length < 2) out.push({ path, level: "operation", message: "adding needs at least two terms" });
    term.add.forEach((part, i) => out.push(...checkTerm(part, context, bound, at(`term ${i + 1}`))));
  } else if ("mul" in term) {
    term.mul.forEach((part, i) => out.push(...checkTerm(part, context, bound, at(`factor ${i + 1}`))));
    if (degree(term) > 2) {
      out.push({ path, level: "operation", message: "this multiplies more than two decisions together, which no solver here takes" });
    }
  } else if ("fn" in term) {
    if (!(term.fn in FUNCTIONS)) out.push({ path, level: "operation", message: `“${term.fn}” is not a function the platform knows` });
    out.push(...checkTerm(term.of, context, bound, at(`${term.fn} of`)));
  } else if ("predict" in term) {
    const spec = context.predictors?.[term.predict];
    if (!term.predict) out.push({ path, level: "operation", message: "choose which trained model" });
    else if (context.predictors && !spec) {
      out.push({ path, level: "operation", message: `“${term.predict}” is not a trained model this problem declares` });
    } else if (spec && spec.inputs !== term.of.length) {
      out.push({ path, level: "operation", message: `${term.predict} reads ${spec.inputs} inputs, not ${term.of.length}` });
    }
    term.of.forEach((input, i) => out.push(...checkTerm(input, context, bound, at(`input ${i + 1}`))));
  }
  return out;
}

/** The conditions on one binding ("only some of them"), against its set's attributes. */
export function checkWhere(binding: Binding, context: ModelContext): string[] {
  const attributes = context.attributes[binding.set];
  if (!attributes || !binding.where) return [];
  const out: string[] = [];
  for (const filter of binding.where) {
    const attribute = attributes.find((a) => a.name === filter.attr);
    if (!attribute) {
      out.push(`${binding.set} has nothing called “${filter.attr || "?"}” to compare`);
      continue;
    }
    if (!opsFor(attribute.data_type).includes(filter.op)) {
      out.push(`${filter.attr} cannot be compared with “${OP_WORDS[filter.op] ?? filter.op}”`);
    } else if (filter.op === "in" || filter.op === "notIn") {
      if (!Array.isArray(filter.value) || filter.value.length === 0) out.push(`“${filter.attr} ${OP_WORDS[filter.op]}” needs at least one value`);
    } else if ((attribute.data_type === "number" || attribute.data_type === "integer") && typeof filter.value !== "number") {
      out.push(`${filter.attr} is a number, so compare it with a number`);
    }
  }
  return out;
}

/** A rule: what it runs over, both sides, and what the comparison as a whole asks. */
export function checkRule(rule: Constraint, context: ModelContext): Problem[] {
  const out: Problem[] = [];
  const forall = rule.forall ?? [];
  forall.forEach((binding, i) => {
    if (!context.sets.includes(binding.set)) {
      out.push({ path: ["for each"], level: "rule", message: `“${binding.set || "?"}” is not a set of this model` });
    }
    if (forall.findIndex((other) => other.index === binding.index) !== i) {
      out.push({ path: ["for each"], level: "rule", message: `“${binding.index}” is used twice; each item needs its own letter` });
    }
    for (const message of checkWhere(binding, context)) out.push({ path: ["for each"], level: "rule", message });
  });
  if (rule.left == null || rule.right == null) {
    out.push({ path: [], level: "rule", message: "the rule does not compare anything yet" });
    return out;
  }
  if (rule.relation && !["<=", "=", ">="].includes(rule.relation)) {
    out.push({ path: ["comparison"], level: "comparison", message: "a rule is “at most”, “exactly” or “at least”" });
  }
  out.push(...checkTerm(rule.left, context, forall, ["left side"]));
  out.push(...checkTerm(rule.right, context, forall, ["right side"]));
  if (degree(rule.left) + degree(rule.right) === 0) {
    out.push({
      path: ["comparison"],
      level: "comparison",
      message: "neither side reads a decision, so nothing the solver chooses can keep or break this rule",
    });
  }
  return out;
}

/** A goal term's expression. */
export function checkGoal(expression: Term, context: ModelContext): Problem[] {
  const out = checkTerm(expression, context, [], []);
  if (degree(expression) === 0) {
    out.push({ path: [], level: "comparison", message: "the goal reads no decision, so no plan can make it better or worse" });
  }
  return out;
}

/** The problems at exactly `path`, and how many sit below it. */
export function problemsAt(problems: Problem[], path: string[]): { own: Problem[]; inside: number } {
  const starts = (p: Problem) => path.every((step, i) => p.path[i] === step);
  const under = problems.filter(starts);
  const own = under.filter((p) => p.path.length === path.length);
  return { own, inside: under.length - own.length };
}

/** A problem in plain words, with where it is. */
export function explain(problem: Problem): string {
  const where = problem.path.length ? `${problem.path.join(" › ")}: ` : "";
  return `${where}${problem.message.charAt(0).toUpperCase()}${problem.message.slice(1)}.`;
}
