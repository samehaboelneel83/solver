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
  /** Never leave out a place this needy: every one whose number field is at least this is covered. */
  mustCover?: { field: string; atLeast: number };
  /** Seats: a covered place's people (number fields multiplied) are seated at open sites within reach,
   * none holding more than its capacity field -- not merely "a site is near". Only with !coverAll. */
  seats?: { capacity: string; demand: string[]; /** The share of them that needs a seat at once, 0..1 (else all). */ share?: number };
  /** Never open a site linked to one of these (in an outage area), unless its yes/no field says it copes. */
  avoid?: { rel: string; end: "from" | "to"; kind: string; unless?: string };
  /** Each open site needs one of these (a team, a crew, a vehicle). */
  staff?: {
    kind: string;
    /** A number field of a staff record: the most sites one may serve. */
    capacity?: string;
    /** A number field of a site: how many it needs when open (else one). */
    needs?: string;
    /** Only sites that what it is linked to reaches: the link (team -> hospital) and 0/1 data over that kind and the sites. */
    via?: { rel: string; end: "from" | "to"; kind: string; reach: string; reachIndex: string[] };
  };
};

function free(name: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  if (!used.has(name)) return name;
  for (let n = 2; ; n++) if (!used.has(`${name}_${n}`)) return `${name}_${n}`;
}

/** A name as words, for the notes a person reads: candidate_site -> candidate site. */
export const say = (name: string) => name.replace(/_/g, " ");

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
      id: free("every_place_covered", taken), note: `every ${say(r.places)} has an open ${say(r.sites)} within reach`,
      forall: [{ index: p, set: r.places }], left: reached, relation: ">=", right: { const: 1 } as Term, severity: "hard",
    } as Constraint);
    terms.push({ id: free(r.cost ? "cost" : "sites_open", taken), weight: 1, expression: costOf } as ObjectiveTerm);
  } else {
    variables[covered] = { index: [r.places], domain: "binary" } as FormDraft["variables"][string];
    constraints.push({
      id: free("covered_needs_open", taken), note: `a ${say(r.places)} counts as covered only with an open ${say(r.sites)} within reach`,
      forall: [{ index: p, set: r.places }], left: { var: covered, index: [p] } as Term, relation: "<=", right: reached, severity: "hard",
    } as Constraint);
    const worth: Term = r.weights.length
      ? ({ mul: [product(r.weights.map((w) => attr(p, w))), { var: covered, index: [p] }] } as Term)
      : ({ var: covered, index: [p] } as Term);
    terms.push({ id: free("covered_worth", taken), weight: 1, expression: { sum: worth, over: [{ index: p, set: r.places }] } as Term } as ObjectiveTerm);
    terms.push({ id: free(r.cost ? "cost" : "sites_open", taken), weight: 1, expression: { mul: [{ const: -1 }, costOf] } as Term } as ObjectiveTerm);
  }
  if (r.mustCover && !r.coverAll && Number.isFinite(r.mustCover.atLeast)) {
    const m = r.mustCover;
    constraints.push({
      id: free("must_cover", [...taken, ...constraints.map((c) => c.id)]),
      note: `every ${say(r.places)} with ${say(m.field)} of ${m.atLeast} or more is covered`,
      forall: [{ index: p, set: r.places, where: [{ attr: m.field, op: ">=", value: m.atLeast }] }],
      left: { var: covered, index: [p] } as Term, relation: ">=", right: { const: 1 } as Term, severity: "hard",
    } as Constraint);
  }
  if (r.budget !== undefined && Number.isFinite(r.budget)) {
    constraints.push({
      id: free("budget", [...taken, ...constraints.map((c) => c.id)]), note: `the open ${say(r.sites)} cost at most ${r.budget}`,
      left: costOf, relation: "<=", right: { const: r.budget } as Term, severity: "hard",
    } as Constraint);
  }
  if (r.seats && !r.coverAll && r.seats.demand.length) {
    const seat = free("seated", [...taken, ...Object.keys(variables), ...constraints.map((c) => c.id)]);
    variables[seat] = { index: [r.places, r.sites], domain: "continuous", lower: 0 } as FormDraft["variables"][string];
    const cell: Term = { var: seat, index: [p, s] } as Term;
    const share = r.seats.share !== undefined && r.seats.share > 0 && r.seats.share < 1 ? r.seats.share : null;
    const people = product([...r.seats.demand.map((f) => attr(p, f)), ...(share !== null ? [{ const: share } as Term] : [])]);
    const ids = () => [...taken, seat, ...Object.keys(variables), ...constraints.map((c) => c.id)];
    const who = r.seats.demand.map(say).join(" × ") + (share !== null ? ` (${Math.round(share * 1000) / 10}% of them at once)` : "");
    constraints.push({
      id: free("seats_for_covered", ids()), note: `a covered ${say(r.places)} has seats for all its ${who}`,
      forall: [{ index: p, set: r.places }], left: { sum: cell, over: [{ index: s, set: r.sites }] } as Term, relation: ">=",
      right: { mul: [people, { var: covered, index: [p] }] } as Term, severity: "hard",
    } as Constraint);
    constraints.push({
      id: free("seats_within_reach", ids()), note: `people are seated only at ${say(r.sites)} within reach`,
      forall: [{ index: p, set: r.places }, { index: s, set: r.sites }], left: cell, relation: "<=",
      right: { mul: [people, reachCell] } as Term, severity: "hard",
    } as Constraint);
    constraints.push({
      id: free("seats_capacity", ids()), note: `an open ${say(r.sites)} seats at most its ${say(r.seats.capacity)}, a closed one none`,
      forall: [{ index: s, set: r.sites }], left: { sum: cell, over: [{ index: p, set: r.places }] } as Term, relation: "<=",
      right: { mul: [attr(s, r.seats.capacity), opened] } as Term, severity: "hard",
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
      id: free(st.needs ? "staff_per_open_site" : "one_per_open_site", ids()),
      note: st.needs ? `each open ${say(r.sites)} has as many ${say(st.kind)} as its ${say(st.needs)}, a closed one none` : `each open ${say(r.sites)} has one ${say(st.kind)}, a closed one none`,
      forall: [{ index: s, set: r.sites }], left: { sum: cell, over: [{ index: t, set: st.kind }] } as Term, relation: "=",
      right: (st.needs ? { mul: [attr(s, st.needs), opened] } : opened) as Term, severity: "hard",
    } as Constraint);
    if (st.capacity) {
      constraints.push({
        id: free("staff_capacity", ids()), note: `a ${say(st.kind)} serves at most its ${say(st.capacity)}`,
        forall: [{ index: t, set: st.kind }], left: { sum: cell, over: [{ index: s, set: r.sites }] } as Term, relation: "<=",
        right: attr(t, st.capacity), severity: "hard",
      } as Constraint);
    }
    if (st.via) {
      const h = "h";
      const near: Term = { par: st.via.reach, index: st.via.reachIndex.map((k) => (k === r.sites ? s : h)) } as Term;
      constraints.push({
        id: free("staff_reach", ids()), note: `a ${say(st.kind)} serves only ${say(r.sites)} its ${say(st.via.rel)} reaches`,
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
      note: `no ${say(r.sites)} linked to a ${say(av.kind)} is opened${av.unless ? ` unless its ${say(av.unless)}` : ""}`,
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
