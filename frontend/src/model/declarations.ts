/**
 * What a model declares before it can say anything: its sets, the domain
 * parameters it reads, and the variables a solver decides.
 *
 * **Two of the three are not free text, and that is the point.**
 *
 * - A **set** is an entity type of the domain. `snapshot_dataset()` resolves
 *   every name against `entity_type`, so a set the domain does not have is a
 *   model that cannot be frozen — refused at submit (and, before this
 *   editor, a 500 much later).
 * - A **parameter** is a `parameter_def` of the domain, and its index is
 *   `index_type_ids` **in order** — `demand[day, shift]` is not
 *   `demand[shift, day]`. So the editor offers the domain's parameters and
 *   derives the index; typing one would be an invitation to get the order
 *   wrong in a way only a wrong answer would reveal.
 * - A **variable** is the model's own: the editor names it, and only its
 *   index has to line up with declared sets.
 *
 * Changing a declaration can strand a term that referred to it, so
 * `strandedBy` reports what would break *before* the change is made rather
 * than leaving the server to refuse the publish.
 */

import { NAME_PATTERN } from "../ir/contract";
import type { Constraint, ObjectiveTerm, Term } from "./terms";
import { termKind } from "./terms";

export type EntityTypeRef = { id: number | string; name: string };
export type ParameterDefRef = { id: number | string; name: string; index_type_ids: (number | string)[] };

export type ParameterDeclaration = { name: string; index: string[] };
export type VariableDeclaration = { name: string; index: string[]; domain: "binary" | "integer" };

const NAME_RE = new RegExp(NAME_PATTERN);

/** The domain's parameters, with their index read back as set names. A
 * parameter whose index names a type the model has not declared as a set is
 * offered with that position blank, so the gap is visible rather than
 * silently mis-ordered. */
export function parameterOptions(
  parameters: readonly ParameterDefRef[],
  entityTypes: readonly EntityTypeRef[]
): ParameterDeclaration[] {
  const nameOf = new Map(entityTypes.map((t) => [String(t.id), t.name]));
  return parameters.map((parameter) => ({
    name: parameter.name,
    index: parameter.index_type_ids.map((id) => nameOf.get(String(id)) ?? ""),
  }));
}

/** Whether a parameter can be declared: every position of its index must be
 * a set the model declares, or terms could not subscript it. */
export function parameterIsUsable(
  parameter: ParameterDeclaration,
  sets: readonly string[]
): { usable: boolean; reason?: string } {
  const missing = parameter.index.filter((set) => set === "" || !sets.includes(set));
  if (missing.length === 0) return { usable: true };
  const named = missing.filter(Boolean);
  return {
    usable: false,
    reason: named.length
      ? `${parameter.name} is indexed by ${named.join(" and ")}, which ${
          named.length > 1 ? "are not sets" : "is not a set"
        } of this model yet.`
      : `${parameter.name} is indexed by an entity type this model does not declare.`,
  };
}

export function variableNameProblem(name: string, taken: readonly string[]): string | null {
  if (name === "") return "A variable needs a name.";
  if (!NAME_RE.test(name)) {
    return "A name starts with a letter and uses lower-case letters, digits and underscores.";
  }
  if (taken.includes(name)) return `There is already something called ${name}.`;
  return null;
}

/** Every set, parameter and variable a term mentions. */
export function referencesOf(term: Term, found = { sets: new Set<string>(), names: new Set<string>() }) {
  switch (termKind(term)) {
    case "par":
      found.names.add((term as { par: string }).par);
      break;
    case "var":
      found.names.add((term as { var: string }).var);
      break;
    case "sum": {
      const t = term as { sum: Term; over: { set: string }[] };
      t.over.forEach((binding) => found.sets.add(binding.set));
      referencesOf(t.sum, found);
      break;
    }
    case "add":
      (term as { add: Term[] }).add.forEach((part) => referencesOf(part, found));
      break;
    case "mul":
      (term as { mul: [Term, Term] }).mul.forEach((part) => referencesOf(part, found));
      break;
    default:
      break;
  }
  return found;
}

/**
 * What would be left dangling by removing a declaration — reported before the
 * removal, naming the rules that would break. Publishing a model whose terms
 * refer to something it no longer declares is refused by the server; being
 * told which rule, here, is the difference between a fixable mistake and a
 * puzzle.
 */
export function strandedBy(
  removal: { kind: "set" | "parameter" | "variable"; name: string },
  constraints: readonly Constraint[],
  objectiveTerms: readonly ObjectiveTerm[]
): string[] {
  const broken: string[] = [];

  const mentions = (term: Term): boolean => {
    const { sets, names } = referencesOf(term);
    return removal.kind === "set" ? sets.has(removal.name) : names.has(removal.name);
  };

  for (const constraint of constraints) {
    const inBindings =
      removal.kind === "set" && (constraint.forall ?? []).some((b) => b.set === removal.name);
    if (inBindings || mentions(constraint.left) || mentions(constraint.right)) {
      broken.push(constraint.id);
    }
  }
  for (const term of objectiveTerms) {
    if (mentions(term.expression)) broken.push(term.id);
  }
  return broken;
}
