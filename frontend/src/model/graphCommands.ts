/**
 * Editing a model from its graph (Epic UX, U-2): typed connections, deletion that
 * removes exactly what depends on the deleted part, and renaming that follows every
 * reference. Pure functions over the forms' draft, so the graph, the keyboard and
 * the forms all make the same edit -- and every refusal says why in the planner's words.
 */
import { isName } from "../ir/contract";
import type { ModelPart } from "../lib/modelGraph";
import { referencesOf, strandedBy } from "./declarations";
import type { FormDraft } from "./draftIr";
import type { Binding, Constraint, Term } from "./terms";

export type PartRef = { part: ModelPart; name: string };

/** What connecting one card to another means -- one meaning per pair of kinds. */
export type Connection =
  | { kind: "index"; set: string; variable: string }
  | { kind: "for-each"; set: string; rule: string }
  | { kind: "use-in-rule"; source: PartRef; rule: string; coefficient: number }
  | { kind: "use-in-objective"; variable: string; coefficient: number };

export type ConnectionKind = Connection["kind"];

/** The connection a drag from `source` to `target` makes, or why none does. */
export function connectionFor(source: PartRef, target: PartRef): { kind: ConnectionKind; says: string } | { refused: string } {
  const s = source.part;
  const t = target.part;
  if (s === "sets" && t === "variables") return { kind: "index", says: `${target.name} gets one value for each ${source.name}` };
  if (s === "sets" && t === "rules") return { kind: "for-each", says: `${target.name} holds for each ${source.name}` };
  if (s === "variables" && t === "rules") return { kind: "use-in-rule", says: `${source.name} is counted in ${target.name}` };
  if (s === "parameters" && t === "rules") return { kind: "use-in-rule", says: `${source.name} becomes part of ${target.name}'s limit` };
  if (s === "variables" && t === "objective") return { kind: "use-in-objective", says: `${source.name} is counted in the goal` };
  if (s === "sets" && t === "parameters") {
    return { refused: `A parameter's index comes from the domain's data (${target.name} is defined there), so it is not changed here.` };
  }
  if (s === "parameters" && t === "objective") {
    return { refused: `${source.name} is data: on its own it does not change the goal. Connect a decision to the goal, with ${source.name} as its coefficient in the rule editor.` };
  }
  if (t === "sets") return { refused: "A set is an entity type of the domain; nothing flows into it." };
  if (s === "rules" || s === "objective") return { refused: "Rules and the goal are where connections end; connect a set, decision or parameter to them." };
  return { refused: `There is no connection from a ${singular(s)} to a ${singular(t)}.` };
}

function singular(part: ModelPart): string {
  return { sets: "set", variables: "decision", parameters: "parameter", rules: "rule", objective: "goal" }[part];
}

/** A name not in `taken`, from `base`: `base`, `base_2`, … */
function fresh(base: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  if (!used.has(base)) return base;
  for (let n = 2; ; n += 1) if (!used.has(`${base}_${n}`)) return `${base}_${n}`;
}

function bindingNames(rule: Constraint, term?: Term): Set<string> {
  const names = new Set((rule.forall ?? []).map((b) => b.index));
  const walk = (t: unknown) => {
    if (!t || typeof t !== "object") return;
    const over = (t as { over?: Binding[] }).over;
    if (Array.isArray(over)) over.forEach((b) => names.add(b.index));
    Object.values(t as object).forEach(walk);
  };
  walk(rule.left);
  walk(rule.right);
  walk(term);
  return names;
}

/** `coefficient × name[…]`, each dimension bound to the rule's own `for each` where the sets agree, summed otherwise. */
function referenceIn(rule: Constraint | null, kind: "var" | "par", name: string, index: string[], coefficient: number): Term {
  const bound = [...(rule?.forall ?? [])];
  const taken = rule ? bindingNames(rule) : new Set<string>();
  const summed: Binding[] = [];
  const subscripts = index.map((set) => {
    const at = bound.findIndex((b) => b.set === set);
    if (at >= 0) {
      const [binding] = bound.splice(at, 1);
      return binding.index;
    }
    const letter = fresh(set.charAt(0) || "i", taken);
    taken.add(letter);
    summed.push({ index: letter, set });
    return letter;
  });
  const ref = (kind === "var" ? { var: name, index: subscripts } : { par: name, index: subscripts }) as Term;
  const scaled: Term = coefficient === 1 ? ref : { mul: [{ const: coefficient }, ref] };
  return summed.length ? { sum: scaled, over: summed } : scaled;
}

function plus(existing: Term | undefined, term: Term): Term {
  if (!existing || ("const" in existing && existing.const === 0)) return term;
  return { add: [...("add" in existing ? existing.add : [existing]), term] };
}

function ruleNamed(draft: FormDraft, id: string): Constraint {
  const rule = draft.constraints.find((r) => r.id === id);
  if (!rule) throw new Error(`There is no rule called ${id}.`);
  if (rule.no_overlap || rule.cumulative || rule.connected || rule.route) {
    throw new Error(`${id} is a scheduling, route or connection rule; its parts are set in its own editor.`);
  }
  return rule;
}

/** The draft with `connection` made. Throws an Error saying why when it cannot be. */
export function connect(draft: FormDraft, connection: Connection): FormDraft {
  if (connection.kind === "index") {
    const spec = draft.variables[connection.variable];
    if (!spec) throw new Error(`There is no decision called ${connection.variable}.`);
    if (spec.domain === "interval") throw new Error(`${connection.variable} is a task (an interval); its sets come from its start and end.`);
    if (!draft.sets.includes(connection.set)) throw new Error(`${connection.set} is not a set of this model.`);
    if (spec.index.includes(connection.set)) throw new Error(`${connection.variable} already has one value for each ${connection.set}.`);
    const uses = strandedBy({ kind: "variable", name: connection.variable }, draft.constraints, draft.objective.terms, draft.variables);
    if (uses.length) {
      throw new Error(`${connection.variable} is used by ${uses.join(", ")}; adding a dimension would change every one of those uses. Add it before using the decision, or edit those rules.`);
    }
    return { ...draft, variables: { ...draft.variables, [connection.variable]: { ...spec, index: [...spec.index, connection.set] } } };
  }
  if (connection.kind === "for-each") {
    const rule = ruleNamed(draft, connection.rule);
    if (!draft.sets.includes(connection.set)) throw new Error(`${connection.set} is not a set of this model.`);
    const index = fresh(connection.set.charAt(0) || "i", bindingNames(rule));
    const next: Constraint = { ...rule, forall: [...(rule.forall ?? []), { index, set: connection.set }] };
    return { ...draft, constraints: draft.constraints.map((r) => (r.id === rule.id ? next : r)) };
  }
  const coefficient = connection.coefficient;
  if (!Number.isFinite(coefficient) || coefficient === 0) throw new Error("The coefficient must be a number other than 0.");
  if (connection.kind === "use-in-rule") {
    const rule = ruleNamed(draft, connection.rule);
    const { part, name } = connection.source;
    if (part === "variables") {
      const spec = draft.variables[name];
      if (!spec) throw new Error(`There is no decision called ${name}.`);
      if (spec.domain === "interval") throw new Error(`${name} is a task (an interval); a rule counts its start, end or presence instead.`);
      const next: Constraint = { ...rule, left: plus(rule.left, referenceIn(rule, "var", name, spec.index, coefficient)),
        relation: rule.relation ?? "<=", right: rule.right ?? { const: 0 } };
      return { ...draft, constraints: draft.constraints.map((r) => (r.id === rule.id ? next : r)) };
    }
    if (part === "parameters") {
      const spec = draft.parameters[name];
      if (!spec) throw new Error(`There is no parameter called ${name}.`);
      const next: Constraint = { ...rule, left: rule.left ?? { const: 0 }, relation: rule.relation ?? "<=",
        right: plus(rule.right, referenceIn(rule, "par", name, spec.index, coefficient)) };
      return { ...draft, constraints: draft.constraints.map((r) => (r.id === rule.id ? next : r)) };
    }
    throw new Error("Only a decision or a parameter is counted in a rule.");
  }
  const spec = draft.variables[connection.variable];
  if (!spec) throw new Error(`There is no decision called ${connection.variable}.`);
  if (spec.domain === "interval") throw new Error(`${connection.variable} is a task (an interval); the goal counts its start or end instead.`);
  const id = fresh(`${connection.variable}_term`, draft.objective.terms.map((t) => t.id));
  const expression = referenceIn(null, "var", connection.variable, spec.index, coefficient);
  return { ...draft, objective: { ...draft.objective, terms: [...draft.objective.terms, { id, weight: 1, expression }] } };
}

// -- deletion -------------------------------------------------------------------

/** What deleting a part does, shown before it is done. */
export type DeletionPlan = {
  target: PartRef;
  /** Rules and goal terms that go with it: they cannot stand without it. */
  removes: string[];
  /** Rules and goal terms that stay, losing only the part of them that read it. */
  trims: string[];
  /** Why it cannot be deleted from here, when it cannot. */
  refused?: string;
};

function mentions(term: Term | undefined, name: string): boolean {
  return term != null && referencesOf(term).names.has(name);
}

/** `term` without its summands that read `name`; null when nothing is left. */
function without(term: Term | undefined, name: string): Term | null | undefined {
  if (term == null) return term;
  if (!mentions(term, name)) return term;
  if ("add" in term) {
    const kept = term.add.map((part) => without(part, name)).filter((part): part is Term => part != null);
    return kept.length === 0 ? null : kept.length === 1 ? kept[0] : { add: kept };
  }
  if ("sum" in term) {
    const inner = without(term.sum, name);
    return inner == null ? null : { ...term, sum: inner };
  }
  return null;
}

function readsADecision(term: Term | null | undefined, draft: FormDraft, removed: string): boolean {
  if (term == null) return false;
  const { names } = referencesOf(term);
  return [...names].some((n) => n !== removed && n in draft.variables);
}

type Outcome = { rules: Map<string, Constraint | null>; terms: Map<string, FormDraft["objective"]["terms"][number] | null> };

function outcomeOf(draft: FormDraft, target: PartRef): Outcome | { refused: string } {
  const rules = new Map<string, Constraint | null>();
  const terms = new Map<string, FormDraft["objective"]["terms"][number] | null>();
  const { part, name } = target;
  if (part === "rules") {
    rules.set(name, null);
    return { rules, terms };
  }
  if (part === "objective") {
    draft.objective.terms.forEach((t) => terms.set(t.id, null));
    return { rules, terms };
  }
  if (part === "sets") {
    const holders = [
      ...Object.entries(draft.variables).filter(([, s]) => s.index.includes(name)).map(([n]) => n),
      ...Object.entries(draft.parameters).filter(([, s]) => s.index.includes(name) || (s as { entity?: string }).entity === name).map(([n]) => n),
    ];
    if (holders.length) return { refused: `${holders.join(", ")} ${holders.length > 1 ? "are" : "is"} indexed by ${name}; delete or re-index ${holders.length > 1 ? "them" : "it"} first.` };
    for (const id of strandedBy({ kind: "set", name }, draft.constraints, draft.objective.terms)) {
      if (draft.constraints.some((r) => r.id === id)) rules.set(id, null);
      else terms.set(id, null);
    }
    return { rules, terms };
  }
  const intervals = Object.entries(draft.variables).filter(([n, s]) => n !== name && s.domain === "interval" &&
    [s.start, s.end, s.presence, typeof s.size === "string" ? s.size : undefined].includes(name)).map(([n]) => n);
  if (intervals.length) return { refused: `${name} is part of the task ${intervals.join(", ")}; delete the task first.` };
  for (const rule of draft.constraints) {
    const body = rule.no_overlap ?? rule.cumulative;
    const structural = rule.when?.var === name || rule.connected?.assign.var === name || rule.route?.visit.var === name ||
      body?.interval.var === name || mentions(rule.cumulative?.demand, name) || mentions(rule.cumulative?.capacity, name);
    if (structural) {
      rules.set(rule.id, null);
      continue;
    }
    if (!mentions(rule.left, name) && !mentions(rule.right, name)) continue;
    const left = without(rule.left, name);
    const right = without(rule.right, name);
    // A rule with no decision left in it constrains nothing: it goes too.
    if (!readsADecision(left, draft, name) && !readsADecision(right, draft, name)) {
      rules.set(rule.id, null);
      continue;
    }
    rules.set(rule.id, { ...rule, left: left ?? { const: 0 }, right: right ?? { const: 0 } });
  }
  for (const term of draft.objective.terms) {
    if (!mentions(term.expression, name)) continue;
    const kept = without(term.expression, name);
    terms.set(term.id, kept == null || !readsADecision(kept, draft, name) ? null : { ...term, expression: kept });
  }
  return { rules, terms };
}

export function planDeletion(draft: FormDraft, target: PartRef): DeletionPlan {
  const outcome = outcomeOf(draft, target);
  if ("refused" in outcome) return { target, removes: [], trims: [], refused: outcome.refused };
  const removes: string[] = [];
  const trims: string[] = [];
  for (const [id, next] of [...outcome.rules, ...outcome.terms]) (next === null ? removes : trims).push(id);
  return { target, removes: target.part === "rules" || target.part === "objective" ? removes.filter((id) => id !== target.name) : removes, trims };
}

/** The draft with `target` deleted, and with exactly the rules and goal terms its plan names changed. */
export function applyDeletion(draft: FormDraft, target: PartRef): FormDraft {
  const outcome = outcomeOf(draft, target);
  if ("refused" in outcome) throw new Error(outcome.refused);
  const constraints = draft.constraints.flatMap((rule) => {
    if (!outcome.rules.has(rule.id)) return [rule];
    const next = outcome.rules.get(rule.id);
    return next ? [next] : [];
  });
  const terms = draft.objective.terms.flatMap((term) => {
    if (!outcome.terms.has(term.id)) return [term];
    const next = outcome.terms.get(term.id);
    return next ? [next] : [];
  });
  const next: FormDraft = { ...draft, constraints, objective: { ...draft.objective, terms } };
  if (target.part === "variables") {
    const { [target.name]: _gone, ...variables } = draft.variables;
    return { ...next, variables };
  }
  if (target.part === "parameters") {
    const { [target.name]: _gone, ...parameters } = draft.parameters;
    return { ...next, parameters };
  }
  if (target.part === "sets") return { ...next, sets: draft.sets.filter((s) => s !== target.name) };
  return next;
}

// -- renaming ---------------------------------------------------------------------

/** Every value under one of `keys` equal to `from`, replaced by `to`, anywhere in `value`. */
function renamed<T>(value: T, keys: Set<string>, from: string, to: string): T {
  if (Array.isArray(value)) return value.map((item) => renamed(item, keys, from, to)) as T;
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([key, inner]) => [
    key, keys.has(key) && inner === from ? to : renamed(inner, keys, from, to),
  ])) as T;
}

/**
 * The draft with a part renamed and every reference to it following: a decision's
 * uses in rules and the goal, as a rule's switch and a task's parts; a rule's or
 * goal term's id. Sets and parameters are named by the domain's data, not here.
 */
export function rename(draft: FormDraft, target: PartRef, to: string): FormDraft {
  const from = target.name;
  if (to === from) return draft;
  if (!isName(to)) throw new Error("A name starts with a letter and uses lower-case letters, digits and underscores.");
  if (target.part === "rules") {
    if (draft.constraints.some((r) => r.id === to)) throw new Error(`There is already a rule called ${to}.`);
    return { ...draft, constraints: draft.constraints.map((r) => (r.id === from ? { ...r, id: to } : r)) };
  }
  if (target.part === "objective") {
    if (draft.objective.terms.some((t) => t.id === to)) throw new Error(`There is already a goal term called ${to}.`);
    return { ...draft, objective: { ...draft.objective, terms: draft.objective.terms.map((t) => (t.id === from ? { ...t, id: to } : t)) } };
  }
  const declared = [...draft.sets, ...Object.keys(draft.parameters), ...Object.keys(draft.variables)];
  if (declared.includes(to)) throw new Error(`There is already something called ${to}.`);
  if (target.part === "variables") {
    const keys = new Set(["var"]);
    const variables = Object.fromEntries(Object.entries(draft.variables).map(([name, spec]) => {
      const next = { ...spec };
      for (const field of ["start", "end", "presence", "size"] as const) if (next[field] === from) (next as Record<string, unknown>)[field] = to;
      return [name === from ? to : name, next];
    }));
    return { ...draft, variables, constraints: renamed(draft.constraints, keys, from, to),
      objective: { ...draft.objective, terms: renamed(draft.objective.terms, keys, from, to) } };
  }
  // A set is an entity type and a parameter a parameter of the domain, both by name:
  // renaming either here would point the model at other data.
  throw new Error(target.part === "sets"
    ? "A set is named by its entity type; rename the type on the domain's Record types page."
    : "A parameter is named by the domain's parameter; rename it on the domain's Parameters page.");
}
