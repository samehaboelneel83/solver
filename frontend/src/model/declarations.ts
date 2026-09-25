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

import { NAME_PATTERN, type VariableDomain } from "../ir/contract";
import type { Constraint, ObjectiveTerm, Term } from "./terms";
import { termKind } from "./terms";

export type EntityTypeRef = { id: number | string; name: string };
export type ParameterDefRef = {
  id: number | string;
  name: string;
  index_type_ids: (number | string)[];
  /** Queue R20b: its values are entities of this type. */
  value_type_id?: number | string | null;
};

/** `entity`: the set its values are entities of (queue R20b), declared with it. */
export type ParameterDeclaration = { name: string; index: string[]; entity?: string; id?: number | string };
/** How a parameter's values may be wrong (IR version 2): each within a
 * fraction of itself, at most `gamma` of a rule's cells at once (all when
 * absent) -- or one value per scenario. What a robust solve reads. */
export type Uncertainty = { kind: "interval"; deviation: number; gamma?: number } | { kind: "scenarios" };

export type ParameterSpec = { index: string[]; uncertainty?: Uncertainty };

/** `within 10% of each value, at most 2 at once`, or null when exact. */
export function describeUncertainty(uncertainty: Uncertainty | undefined): string | null {
  if (!uncertainty) return null;
  if (uncertainty.kind === "scenarios") return "one value per scenario";
  const share = `within ${Number((uncertainty.deviation * 100).toPrecision(6))}% of each value`;
  return uncertainty.gamma === undefined ? share : `${share}, at most ${uncertainty.gamma} at once`;
}

export type VariableSpec = {
  index: string[];
  domain: VariableDomain;
  lower?: number;
  upper?: number;
  /** An interval's parts (version 2): kept as published, not built here yet. */
  start?: string;
  end?: string;
  size?: number | string;
  presence?: string;
  /** When it is decided (version 2): 1 now, 2 once the uncertain data is known. */
  stage?: 1 | 2;
};
export type VariableDeclaration = { name: string } & VariableSpec;

/** A binary variable's bounds are fixed at 0 and 1 — drop any that were typed. */
export function withDomain(spec: VariableSpec, domain: VariableDomain): VariableSpec {
  if (domain === "interval") {
    // Its start, end, size and presence are what it is; it has no bounds.
    const next: VariableSpec = { index: spec.index, domain };
    for (const key of ["start", "end", "size", "presence"] as const) {
      if (spec[key] !== undefined) (next as Record<string, unknown>)[key] = spec[key];
    }
    return next;
  }
  if (domain === "binary") {
    return { index: spec.index, domain };
  }
  const next: VariableSpec = { index: spec.index, domain };
  if (spec.lower !== undefined) next.lower = spec.lower;
  if (spec.upper !== undefined) next.upper = spec.upper;
  return next;
}

/** Drop empty optionals and binary bounds so the published declaration matches the contract. */
export function cleanVariable(spec: VariableSpec): VariableSpec {
  return withStage(withDomain(spec, spec.domain), spec.stage);
}

/** A stage kept or dropped (an interval has none: its start and end carry it). */
export function withStage(spec: VariableSpec, stage: 1 | 2 | undefined): VariableSpec {
  const { stage: _previous, ...rest } = spec;
  return stage !== undefined && spec.domain !== "interval" ? { ...rest, stage } : rest;
}

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
    id: parameter.id,
    name: parameter.name,
    index: parameter.index_type_ids.map((id) => nameOf.get(String(id)) ?? ""),
    ...(parameter.value_type_id != null ? { entity: nameOf.get(String(parameter.value_type_id)) ?? "" } : {}),
  }));
}

/** Whether a parameter can be declared: every position of its index must be
 * a set the model declares, or terms could not subscript it. */
export function parameterIsUsable(
  parameter: ParameterDeclaration,
  sets: readonly string[]
): { usable: boolean; reason?: string } {
  const missing = [...parameter.index, ...(parameter.entity !== undefined ? [parameter.entity] : [])].filter(
    (set) => set === "" || !sets.includes(set)
  );
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
export function referencesOf(
  term: Term | undefined,
  found = { sets: new Set<string>(), names: new Set<string>() }
) {
  if (term == null) return found;
  switch (termKind(term)) {
    case "par":
      found.names.add((term as { par: string }).par);
      break;
    case "var":
      found.names.add((term as { var: string }).var);
      break;
    case "pwl":
      found.names.add((term as { pwl: { var: string } }).pwl.var);
      break;
    case "fn":
      referencesOf((term as { of: Term }).of, found);
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
  objectiveTerms: readonly ObjectiveTerm[],
  variables: Readonly<Record<string, VariableSpec>> = {}
): string[] {
  const broken: string[] = [];

  const mentions = (term: Term | undefined): boolean => {
    if (term == null) return false;
    const { sets, names } = referencesOf(term);
    return removal.kind === "set" ? sets.has(removal.name) : names.has(removal.name);
  };
  const ranges = (bindings: readonly { set: string }[] | undefined) =>
    removal.kind === "set" && (bindings ?? []).some((b) => b.set === removal.name);
  const isNamed = (name: string | undefined) => removal.kind !== "set" && name === removal.name;

  for (const constraint of constraints) {
    const schedule = constraint.no_overlap ?? constraint.cumulative;
    if (
      ranges(constraint.forall) ||
      mentions(constraint.left) ||
      mentions(constraint.right) ||
      // The switch of a conditional rule, and a scheduling rule's intervals,
      // the sets it ranges over, and what it counts.
      isNamed(constraint.when?.var) ||
      (constraint.connected !== undefined &&
        (isNamed(constraint.connected.assign.var) ||
          ranges([constraint.connected.units, constraint.connected.groups]))) ||
      (schedule !== undefined &&
        (isNamed(schedule.interval.var) ||
          ranges(schedule.over) ||
          mentions(constraint.cumulative?.demand) ||
          mentions(constraint.cumulative?.capacity)))
    ) {
      broken.push(constraint.id);
    }
  }
  for (const term of objectiveTerms) {
    if (mentions(term.expression)) broken.push(term.id);
  }
  // An interval is built from other declarations: its start and end, its
  // presence, and a size read from a parameter.
  for (const [name, spec] of Object.entries(variables)) {
    if (spec.domain !== "interval") continue;
    const parts = [spec.start, spec.end, spec.presence, typeof spec.size === "string" ? spec.size : undefined];
    if (parts.some(isNamed)) broken.push(name);
  }
  return broken;
}
