/**
 * The coverage recipe (user trial, P2): "choose which places to open so the others are within reach,
 * within a budget, the most important covered first" -- the decisions, rules and goals such a model
 * needs, written into the draft from one short form instead of seven equations.
 */
import type { Constraint, ObjectiveTerm, Term } from "./terms";
import type { FormDraft } from "./draftIr";

export type CoverageRecipe = {
  /** The kind of record chosen from (sites). */
  sites: string;
  /** The kind of record to be covered (zones). */
  places: string;
  /** 0/1 data over both kinds, 1 where a site reaches a place, in either index order. */
  reach: string;
  reachIndex: string[];
  /** A number field of a site: what opening it costs. */
  cost?: string;
  /** The most the open sites may cost together. */
  budget?: number;
  /** Number fields of a place multiplied into how much covering it is worth (population, vulnerability). */
  weights: string[];
  /** Every place must be covered (the goal is then the least cost) -- else cover the most worth. */
  coverAll: boolean;
  /** Never open a site linked to one of these (in an outage area), unless its yes/no field says it copes. */
  avoid?: { rel: string; end: "from" | "to"; kind: string; unless?: string };
  /** Each open site needs one of these (a team, a crew, a vehicle). */
  staff?: {
    kind: string;
    /** A number field of a staff record: the most sites one may serve. */
    capacity?: string;
    /** Only sites that what it is linked to reaches: the link (team -> hospital) and 0/1 data over that kind and the sites. */
    via?: { rel: string; end: "from" | "to"; kind: string; reach: string; reachIndex: string[] };
  };
};

function free(name: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  if (!used.has(name)) return name;
  for (let n = 2; ; n++) if (!used.has(`${name}_${n}`)) return `${name}_${n}`;
}

const attr = (of: string, name: string): Term => ({ attr: { of, name } }) as Term;
const product = (terms: Term[]): Term => terms.reduce((a, b) => ({ mul: [a, b] }) as Term);

/** The draft with the recipe's decisions, rules and goals added; what is already there is kept. */
export function applyCoverage(draft: FormDraft, r: CoverageRecipe): FormDraft {
  const names = [...Object.keys(draft.variables), ...draft.constraints.map((c) => c.id), ...draft.objective.terms.map((t) => t.id)];
  const open = free("open", names);
  const covered = free("covered", [...names, open]);
  const s = "s", p = "p";
  const reachCell: Term = { par: r.reach, index: r.reachIndex[0] === r.places ? [p, s] : [s, p] } as Term;
  const opened: Term = { var: open, index: [s] } as Term;
  const reached: Term = { sum: { mul: [reachCell, opened] }, over: [{ index: s, set: r.sites }] } as Term;
  const costOf = r.cost ? ({ sum: { mul: [attr(s, r.cost), opened] }, over: [{ index: s, set: r.sites }] } as Term)
    : ({ sum: opened, over: [{ index: s, set: r.sites }] } as Term);

  const variables = { ...draft.variables, [open]: { index: [r.sites], domain: "binary" } } as FormDraft["variables"];
  const constraints: Constraint[] = [...draft.constraints];
  const terms: ObjectiveTerm[] = [];
  const taken = [...names, open, covered];
  if (r.coverAll) {
    constraints.push({
      id: free("every_place_covered", taken), note: `every ${r.places} has an open ${r.sites} within reach`,
      forall: [{ index: p, set: r.places }], left: reached, relation: ">=", right: { const: 1 } as Term, severity: "hard",
    } as Constraint);
    terms.push({ id: free(r.cost ? "cost" : "sites_open", taken), weight: 1, expression: costOf } as ObjectiveTerm);
  } else {
    variables[covered] = { index: [r.places], domain: "binary" } as FormDraft["variables"][string];
    constraints.push({
      id: free("covered_needs_open", taken), note: `a ${r.places} counts as covered only with an open ${r.sites} within reach`,
      forall: [{ index: p, set: r.places }], left: { var: covered, index: [p] } as Term, relation: "<=", right: reached, severity: "hard",
    } as Constraint);
    const worth: Term = r.weights.length
      ? ({ mul: [product(r.weights.map((w) => attr(p, w))), { var: covered, index: [p] }] } as Term)
      : ({ var: covered, index: [p] } as Term);
    terms.push({ id: free("covered_worth", taken), weight: 1, expression: { sum: worth, over: [{ index: p, set: r.places }] } as Term } as ObjectiveTerm);
    terms.push({ id: free(r.cost ? "cost" : "sites_open", taken), weight: 1, expression: { mul: [{ const: -1 }, costOf] } as Term } as ObjectiveTerm);
  }
  if (r.budget !== undefined && Number.isFinite(r.budget)) {
    constraints.push({
      id: free("budget", [...taken, ...constraints.map((c) => c.id)]), note: `the open ${r.sites} cost at most ${r.budget}`,
      left: costOf, relation: "<=", right: { const: r.budget } as Term, severity: "hard",
    } as Constraint);
  }
  const staffSets: string[] = [];
  if (r.staff) {
    const st = r.staff;
    const assign = free("assign", [...taken, ...constraints.map((c) => c.id)]);
    const t = "t";
    const cell: Term = { var: assign, index: [t, s] } as Term;
    variables[assign] = { index: [st.kind, r.sites], domain: "binary" } as FormDraft["variables"][string];
    const ids = () => [...taken, assign, ...constraints.map((c) => c.id)];
    constraints.push({
      id: free("one_per_open_site", ids()), note: `each open ${r.sites} has one ${st.kind}, a closed one none`,
      forall: [{ index: s, set: r.sites }], left: { sum: cell, over: [{ index: t, set: st.kind }] } as Term, relation: "=",
      right: { var: open, index: [s] } as Term, severity: "hard",
    } as Constraint);
    if (st.capacity) {
      constraints.push({
        id: free("staff_capacity", ids()), note: `a ${st.kind} serves at most its ${st.capacity}`,
        forall: [{ index: t, set: st.kind }], left: { sum: cell, over: [{ index: s, set: r.sites }] } as Term, relation: "<=",
        right: attr(t, st.capacity), severity: "hard",
      } as Constraint);
    }
    if (st.via) {
      const h = "h";
      const near: Term = { par: st.via.reach, index: st.via.reachIndex.map((k) => (k === r.sites ? s : h)) } as Term;
      constraints.push({
        id: free("staff_reach", ids()), note: `a ${st.kind} serves only ${r.sites} its ${st.via.rel} reaches`,
        forall: [{ index: t, set: st.kind }, { index: s, set: r.sites }], left: cell, relation: "<=",
        right: { sum: near, over: [{ index: h, set: st.via.kind, via: { rel: st.via.rel, [st.via.end]: t } }] } as Term, severity: "hard",
      } as Constraint);
      staffSets.push(st.via.kind);
    }
    staffSets.push(st.kind);
  }
  if (r.avoid) {
    const av = r.avoid;
    const a = "a";
    constraints.push({
      id: free("avoid_" + av.kind, [...taken, ...Object.keys(variables), ...constraints.map((c) => c.id)]),
      note: `no ${r.sites} linked to a ${av.kind} is opened${av.unless ? ` unless its ${av.unless}` : ""}`,
      forall: [{ index: s, set: r.sites, ...(av.unless ? { where: [{ attr: av.unless, op: "=", value: false }] } : {}) }],
      left: { sum: opened, over: [{ index: a, set: av.kind, via: { rel: av.rel, [av.end]: s } }] } as Term,
      relation: "<=", right: { const: 0 } as Term, severity: "hard",
    } as Constraint);
    staffSets.push(av.kind);
  }
  const reachData = r.staff?.via ? { [r.staff.via.reach]: draft.parameters[r.staff.via.reach] ?? { index: r.staff.via.reachIndex } } : {};
  return {
    ...draft,
    sets: [...new Set([...draft.sets, r.sites, r.places, ...staffSets])],
    parameters: { ...draft.parameters, [r.reach]: draft.parameters[r.reach] ?? { index: r.reachIndex }, ...reachData },
    variables,
    constraints,
    // Goals in order: cover the most worth first, then spend the least -- or, covering all, the least cost.
    objective: r.coverAll
      ? { sense: "minimize", mode: "weighted", terms }
      : { sense: "maximize", mode: "lex", terms },
  };
}
