import { isName } from "../ir/contract";
import { variableNameProblem, type VariableSpec } from "./declarations";
import type { FormDraft } from "./draftIr";
import type { Binding, Term } from "./terms";

export type ParameterUse = { name: string; dimensions: number[] };
export type GuidedCommand =
  | { kind: "variable"; name: string; domain: "binary" | "integer" | "continuous"; index: string[]; lower: string; upper: string }
  | { kind: "rule"; name: string; decision: string; separate: number[]; relation: "<=" | "=" | ">="; limit: string; limitParameter?: ParameterUse; coefficient?: ParameterUse; preference: boolean; penalty: string; note: string }
  | { kind: "objective"; name: string; decision: string; sense: "minimize" | "maximize"; weight: string; coefficient?: ParameterUse };

export function parameterTerm(draft: FormDraft, use: ParameterUse, decision: string, allowed: number[]): Term {
  const parameter = draft.parameters[use.name];
  const variable = draft.variables[decision];
  if (!parameter || "entity" in parameter) throw new Error("Choose a declared numeric parameter from the Parameters section below.");
  if (!variable || use.dimensions.length !== parameter.index.length) throw new Error("Map every parameter dimension to the decision.");
  if (parameter.index.some((set, i) => !draft.sets.includes(set) || !allowed.includes(use.dimensions[i]) || variable.index[use.dimensions[i]] !== set)) {
    throw new Error("Each parameter dimension must match an available decision dimension. A rule limit can use only dimensions kept separate.");
  }
  return { par: use.name, index: use.dimensions.map(i => `i${i + 1}`) };
}

function number(text: string, label: string): number {
  if (!text.trim() || !Number.isFinite(Number(text))) throw new Error(`${label} must be a number.`);
  return Number(text);
}

function id(name: string, taken: string[]) {
  if (!isName(name)) throw new Error("Use a name starting with a letter, followed by lower-case letters, digits or underscores.");
  if (taken.includes(name)) throw new Error(`There is already an item called ${name}. Choose another name.`);
}

function decisionExpression(draft: FormDraft, name: string, separate: number[] = [], coefficient?: ParameterUse): { term: Term; forall: Binding[] } {
  const spec = draft.variables[name];
  if (!spec || spec.domain === "interval") throw new Error("Choose an existing numeric or yes/no decision.");
  if (spec.index.some(set => !draft.sets.includes(set))) throw new Error("This decision references a missing set. Repair its declaration first.");
  if (new Set(separate).size !== separate.length || separate.some(i => !Number.isInteger(i) || i < 0 || i >= spec.index.length)) throw new Error("The decision dimensions changed. Choose the scope again.");
  const bindings = spec.index.map((set, i) => ({ index: `i${i + 1}`, set }));
  const over = bindings.filter((_, i) => !separate.includes(i));
  const variable: Term = { var: name, index: bindings.map(b => b.index) };
  const ref: Term = coefficient ? { mul: [parameterTerm(draft, coefficient, name, bindings.map((_, i) => i)), variable] } : variable;
  return { term: over.length ? { sum: ref, over } : ref, forall: bindings.filter((_, i) => separate.includes(i)) };
}

/** Apply to the latest shared draft, preserving existing declarations and rules. */
export function applyGuidedCommand(draft: FormDraft, command: GuidedCommand, availableSets: string[]): FormDraft {
  if (command.kind === "variable") {
    const problem = variableNameProblem(command.name, [...draft.sets, ...Object.keys(draft.parameters), ...Object.keys(draft.variables)]);
    if (problem) throw new Error(problem);
    if (command.index.some(set => !availableSets.includes(set))) throw new Error("Choose sets that exist in this domain.");
    const spec: VariableSpec = { domain: command.domain, index: [...command.index] };
    if (command.domain !== "binary") {
      if (command.lower.trim()) spec.lower = number(command.lower, "Minimum");
      if (command.upper.trim()) spec.upper = number(command.upper, "Maximum");
      if (spec.lower !== undefined && spec.upper !== undefined && spec.lower > spec.upper) throw new Error("Minimum must not exceed maximum.");
      if (command.domain === "integer" && [spec.lower, spec.upper].some(value => value !== undefined && !Number.isSafeInteger(value))) throw new Error("Whole-number decisions need whole-number bounds.");
    }
    return { ...draft, sets: [...new Set([...draft.sets, ...command.index])], variables: { ...draft.variables, [command.name]: spec } };
  }
  if (command.kind === "rule") {
    id(command.name, draft.constraints.map(rule => rule.id));
    const { term, forall } = decisionExpression(draft, command.decision, command.separate, command.coefficient);
    const limit: Term = command.limitParameter
      ? parameterTerm(draft, command.limitParameter, command.decision, command.separate)
      : { const: number(command.limit, "Limit") };
    const penalty = command.preference ? number(command.penalty, "Penalty") : undefined;
    if (penalty !== undefined && (!Number.isSafeInteger(penalty) || penalty < 1)) throw new Error("Penalty must be a positive whole number.");
    return { ...draft, constraints: [...draft.constraints, {
      id: command.name, ...(command.note.trim() ? { note: command.note.trim() } : {}),
      ...(forall.length ? { forall } : {}), left: term, relation: command.relation, right: limit,
      ...(penalty === undefined ? { severity: "hard" as const } : { severity: "soft" as const, weight: penalty }),
    }] };
  }
  id(command.name, draft.objective.terms.map(term => term.id));
  if (draft.objective.terms.length && draft.objective.sense !== command.sense) throw new Error("The objective direction changed. Review the existing objective before adding a term.");
  const weight = number(command.weight, "Weight");
  if (!Number.isSafeInteger(weight) || weight <= 0) throw new Error("Weight must be a positive whole number.");
  const { term } = decisionExpression(draft, command.decision, [], command.coefficient);
  return { ...draft, objective: { ...draft.objective, sense: command.sense,
    terms: [...draft.objective.terms, { id: command.name, weight, expression: term }] } };
}
