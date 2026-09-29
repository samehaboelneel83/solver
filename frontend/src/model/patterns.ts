/**
 * Scheduling and routing patterns for the guided forms (Epic UX, U-3).
 *
 * Each pattern is one planner-level request -- "each job is a task of a given
 * length", "a machine does one job at a time", "vehicles visit every stop" --
 * turned into the declarations and rules the IR needs, whole: a pattern never
 * leaves the draft half-built, and a request it cannot serve is refused with the
 * reason before anything changes.
 */
import { isName } from "../ir/contract";
import type { VariableSpec } from "./declarations";
import type { FormDraft } from "./draftIr";
import { connectedBody, routeBody, seedForSet, type Binding, type Constraint, type Term } from "./terms";

/** A number, or a parameter read with the dimensions of what it sizes. */
export type Amount = { const: number } | { parameter: string };

export type PatternCommand =
  | { kind: "task"; name: string; index: string[]; size: Amount; horizon: number; optional: boolean }
  | { kind: "one_at_a_time"; name: string; task: string; resource: number[] }
  | { kind: "shared_capacity"; name: string; task: string; resource: number[]; demand: Amount; capacity: Amount }
  | { kind: "routes"; name: string; vehicles: string; stops: string; depot: string;
      load?: { demand: string; capacity: string }; travel?: string }
  | { kind: "regions"; name: string; units: string; groups: string; via: string; everyUnitOnce: boolean; allowEmpty: boolean };

export type PatternKind = PatternCommand["kind"];

/** The catalogue, in the order the guided form offers it. */
export const PATTERNS: { kind: PatternKind; label: string; says: string }[] = [
  { kind: "task", label: "Task with a duration", says: "Each item is a task that starts, lasts and ends -- optionally only if it is done at all." },
  { kind: "one_at_a_time", label: "One at a time", says: "A resource (a machine, a room, a person) does one task at a time." },
  { kind: "shared_capacity", label: "Shared capacity", says: "Tasks running together never use more than a resource has." },
  { kind: "routes", label: "Vehicle routes", says: "Vehicles leave a depot, visit every stop once and come back." },
  { kind: "regions", label: "Connected regions", says: "Each group is one connected piece: a territory, a district, a zone." },
];

function taken(draft: FormDraft): Set<string> {
  return new Set([...draft.sets, ...Object.keys(draft.parameters), ...Object.keys(draft.variables)]);
}

function checkName(name: string, used: Set<string>, what = "name") {
  if (!isName(name)) throw new Error(`The ${what} starts with a letter and uses lower-case letters, digits and underscores.`);
  if (used.has(name)) throw new Error(`There is already something called ${name}. Choose another ${what}.`);
}

function checkRuleId(draft: FormDraft, id: string) {
  if (!isName(id)) throw new Error("The rule name starts with a letter and uses lower-case letters, digits and underscores.");
  if (draft.constraints.some((rule) => rule.id === id)) throw new Error(`There is already a rule called ${id}.`);
}

function fresh(stem: string, used: Set<string>): string {
  let candidate = stem;
  for (let n = 2; used.has(candidate); n += 1) candidate = `${stem}_${n}`;
  used.add(candidate);
  return candidate;
}

/** Index names for `sets`, one per set, never the same twice. */
function indexNames(sets: string[]): string[] {
  const used = new Set<string>();
  return sets.map((set) => fresh(seedForSet(set), used));
}

function interval(draft: FormDraft, name: string): VariableSpec {
  const spec = draft.variables[name];
  if (!spec || spec.domain !== "interval") throw new Error("Choose a task (made with the Task with a duration pattern).");
  return spec;
}

/** An amount read at the dimensions `sets`, bound to `indices`; a parameter must be indexed exactly by those sets. */
function amount(draft: FormDraft, value: Amount, sets: string[], indices: string[], what: string): Term {
  if ("const" in value) {
    if (!Number.isFinite(value.const) || value.const < 0) throw new Error(`The ${what} is a number of at least 0.`);
    return { const: value.const };
  }
  const spec = draft.parameters[value.parameter];
  if (!spec) throw new Error(`Choose a parameter for the ${what}.`);
  if (spec.index.join("|") !== sets.join("|")) {
    const want = sets.length ? `one number for each ${sets.join(" and ")}` : "one number";
    throw new Error(`The ${what} parameter must hold ${want}; ${value.parameter} is indexed by ${spec.index.join(", ") || "nothing"}.`);
  }
  return { par: value.parameter, index: indices };
}

function split(spec: VariableSpec, resource: number[]) {
  if (new Set(resource).size !== resource.length || resource.some((i) => i < 0 || i >= spec.index.length)) {
    throw new Error("The task's dimensions changed. Choose the resource again.");
  }
  if (resource.length === spec.index.length) throw new Error("Leave at least one dimension as the tasks that share the resource.");
  const names = indexNames(spec.index);
  const bindings: Binding[] = spec.index.map((set, i) => ({ index: names[i], set }));
  return {
    names,
    forall: bindings.filter((_, i) => resource.includes(i)),
    over: bindings.filter((_, i) => !resource.includes(i)),
    resourceSets: resource.map((i) => spec.index[i]),
    resourceNames: resource.map((i) => names[i]),
  };
}

/** Apply a pattern to the latest draft. Throws an Error saying why when it cannot. */
export function applyPattern(draft: FormDraft, command: PatternCommand, availableSets: string[]): FormDraft {
  const used = taken(draft);
  if (command.kind === "task") {
    checkName(command.name, used);
    if (command.index.some((set) => !availableSets.includes(set))) throw new Error("Choose sets that exist in this domain.");
    if (!Number.isSafeInteger(command.horizon) || command.horizon < 1) throw new Error("The horizon is a whole number of time steps, at least 1.");
    if ("const" in command.size && !Number.isSafeInteger(command.size.const)) throw new Error("A duration is a whole number of time steps.");
    const sets = [...new Set([...draft.sets, ...command.index])];
    const size: number | string = "const" in command.size ? command.size.const : command.size.parameter;
    amount({ ...draft, sets }, command.size, command.index, indexNames(command.index), "duration");
    const start = fresh(`${command.name}_start`, used);
    const end = fresh(`${command.name}_end`, used);
    const part: VariableSpec = { index: command.index, domain: "integer", lower: 0, upper: command.horizon };
    const variables: Record<string, VariableSpec> = { ...draft.variables, [start]: part, [end]: part };
    let presence: string | undefined;
    if (command.optional) {
      presence = fresh(`${command.name}_done`, used);
      variables[presence] = { index: command.index, domain: "binary" };
    }
    variables[command.name] = { index: command.index, domain: "interval", start, end, size, ...(presence ? { presence } : {}) };
    return { ...draft, sets, variables };
  }
  if (command.kind === "one_at_a_time" || command.kind === "shared_capacity") {
    checkRuleId(draft, command.name);
    const spec = interval(draft, command.task);
    const { names, forall, over, resourceSets, resourceNames } = split(spec, command.resource);
    const body = { interval: { var: command.task, index: names }, over };
    const rule: Constraint = command.kind === "one_at_a_time"
      ? { id: command.name, severity: "hard", ...(forall.length ? { forall } : {}), no_overlap: body }
      : { id: command.name, severity: "hard", ...(forall.length ? { forall } : {}), cumulative: {
          ...body,
          demand: amount(draft, command.demand, spec.index, names, "demand"),
          capacity: amount(draft, command.capacity, resourceSets, resourceNames, "capacity"),
        } };
    return { ...draft, constraints: [...draft.constraints, rule] };
  }
  if (command.kind === "routes") {
    checkRuleId(draft, command.name);
    for (const set of [command.vehicles, command.stops]) {
      if (!availableSets.includes(set)) throw new Error("Choose sets that exist in this domain.");
    }
    if (command.vehicles === command.stops) throw new Error("Vehicles and stops are two different sets.");
    if (!command.depot.trim()) throw new Error("Name the depot: the key of the stop the vehicles start from.");
    const visit = fresh(`${command.name}_visit`, used);
    const sets = [...new Set([...draft.sets, command.vehicles, command.stops])];
    const variables = { ...draft.variables, [visit]: { index: [command.vehicles, command.stops, command.stops], domain: "binary" as const } };
    const body = routeBody({ variable: visit, vehicles: command.vehicles, stops: command.stops }, command.depot.trim(), command.load);
    let terms = draft.objective.terms;
    if (command.travel) {
      const spec = draft.parameters[command.travel];
      if (!spec || spec.index.join("|") !== `${command.stops}|${command.stops}`) {
        throw new Error(`The travel cost is a parameter with one number for each pair of ${command.stops}.`);
      }
      if (draft.objective.terms.length && draft.objective.sense !== "minimize") throw new Error("Travel is minimised; the goal already maximises. Review the goal first.");
      const [v, i, j] = body.visit.index;
      const id = fresh(`${command.name}_travel`, new Set(draft.objective.terms.map((t) => t.id)));
      const expression: Term = { sum: { mul: [{ par: command.travel, index: [i, j] }, { var: visit, index: [v, i, j] }] },
        over: [{ index: v, set: command.vehicles }, { index: i, set: command.stops }, { index: j, set: command.stops }] };
      terms = [...terms, { id, weight: 1, expression }];
    }
    return { ...draft, sets, variables, constraints: [...draft.constraints, { id: command.name, severity: "hard", route: body } as Constraint],
      objective: { ...draft.objective, ...(command.travel ? { sense: "minimize" } : {}), terms } };
  }
  // regions
  checkRuleId(draft, command.name);
  for (const set of [command.units, command.groups]) if (!availableSets.includes(set)) throw new Error("Choose sets that exist in this domain.");
  if (command.units === command.groups) throw new Error("Units and groups are two different sets.");
  if (!command.via) throw new Error(`Choose the relationship that says which ${command.units} are next to each other.`);
  const assign = fresh(`${command.name}_in`, used);
  const sets = [...new Set([...draft.sets, command.units, command.groups])];
  const variables = { ...draft.variables, [assign]: { index: [command.units, command.groups], domain: "binary" as const } };
  const body = connectedBody({ variable: assign, units: command.units, groups: command.groups }, command.via,
    command.allowEmpty ? "allowed" : "forbidden");
  const rules: Constraint[] = [{ id: command.name, severity: "hard", connected: body } as Constraint];
  if (command.everyUnitOnce) {
    const [u, z] = body.assign.index;
    rules.push({ id: fresh(`${command.name}_each_once`, new Set(draft.constraints.map((r) => r.id))), severity: "hard",
      forall: [{ index: u, set: command.units }], relation: "=", right: { const: 1 },
      left: { sum: { var: assign, index: [u, z] }, over: [{ index: z, set: command.groups }] } });
  }
  return { ...draft, sets, variables, constraints: [...draft.constraints, ...rules] };
}

/** The tasks a scheduling pattern can use: every interval, with its dimensions. */
export function tasksOf(draft: FormDraft): { name: string; index: string[] }[] {
  return Object.entries(draft.variables).filter(([, spec]) => spec.domain === "interval").map(([name, spec]) => ({ name, index: spec.index }));
}
