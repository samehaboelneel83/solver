/**
 * Describe it -> a first draft (benchmark, October 2026, G3c): from a person's own description and
 * the workspace's kinds, fields and data values, the recipe their words call for, filled in -- which
 * kind is chosen from, which field is the cost, the budget they wrote -- each choice with the reason
 * for it, and what is still missing. Offline and by words, like `lib/describeProblem.ts`; it writes
 * nothing until the person says so, and what it writes is an ordinary draft to read and change.
 */
import { applyCoverage, type CoverageRecipe } from "./coverageRecipe";
import type { FormDraft } from "./draftIr";
import { applyAllocation, applyNetwork, applyPhasing, applySelection, type AllocationRecipe, type NetworkRecipe, type PhasingRecipe,
  type SelectionRecipe } from "./recipes";

export type Kind = { name: string; role?: string; attributes: { name: string; data_type: string }[] };
export type Data = { name: string; index: string[] };
export type Recipe = "coverage" | "selection" | "network" | "phasing" | "allocation";

export type Proposal = {
  recipe: Recipe;
  title: string;
  /** Each choice made, and why: "projects are chosen from project — you wrote “projects”". */
  choices: string[];
  /** What the words and the workspace did not give; the draft is written only when this is empty. */
  missing: string[];
  apply: ((draft: FormDraft) => FormDraft) | null;
};

const TITLES: Record<Recipe, string> = {
  coverage: "Choose places to open so others are within reach",
  selection: "Choose projects within a budget",
  network: "A supply network: open, ship, deliver",
  phasing: "Start projects over periods within each period's budget",
  allocation: "Share each one out among options (land among crops)",
};

const SIGNALS: Record<Recipe, RegExp> = {
  coverage: /\b(cover\w*|within|reach\w*|minutes?|response|nearby|closest|serve every|hotspots?)\b/g,
  selection: /\b(projects?|portfolio|select\w*|invest\w*|proposals?|candidates?|fund\w*|shortlist\w*|options?)\b/g,
  network: /\b(ship\w*|deliver\w*|supply|suppl(y|ier)s?|warehouses?|depots?|customers?|stores?|flows?|transport\w*|distribut\w*|trucks?|fleet|vehicles?)\b/g,
  phasing: /\b(years?|yearly|annual\w*|quarters?|periods?|phas\w*|over time|month\w*|multi-?year|horizon)\b/g,
  // Benchmark re-test, October 2026: crop planning matched no recipe.
  allocation: /\b(allocat\w*|crops?|plant\w*|feddans?|hectares?|acres?|land|grow\w*|share\w* (out|of)|split|mix|irrigat\w*|sow\w*|area to)\b/g,
};

const words = (name: string) => name.toLowerCase().split(/_+/).filter(Boolean);
const plural = (w: string) => (w.endsWith("y") ? [w, `${w.slice(0, -1)}ies`] : w.endsWith("s") ? [w] : [w, `${w}s`, `${w}es`]);

/** The words of the text that name the kind: its name, its last word, or their plurals. */
function mentions(text: string, kind: Kind): string | null {
  const ws = words(kind.name);
  const forms = [ws.join(" "), ws.join("_"), ws[ws.length - 1]].flatMap(plural);
  for (const f of forms) {
    const m = text.match(new RegExp(`\\b${f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i"));
    if (m) return m[0];
  }
  return null;
}

const numeric = (k: Kind | undefined) =>
  (k?.attributes ?? []).filter((a) => a.data_type === "number" || a.data_type === "integer").map((a) => a.name);

/** The first field of a kind whose name fits, and the words that made it fit. */
function field(k: Kind | undefined, pattern: RegExp, of: (k: Kind | undefined) => string[] = numeric): string | undefined {
  return of(k).find((n) => pattern.test(n));
}

/** A number in the text after the first of these words found, in this order: "a budget of 2.5 million", "at most 3". */
function amount(text: string, leads: string[]): number | undefined {
  for (const lead of leads) {
    const m = text.match(new RegExp(`\\b(?:${lead})\\b[^0-9.]{0,24}([0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(k|thousand|m|million|bn|billion)?\\b`, "i"));
    if (!m) continue;
    const scale = { k: 1e3, thousand: 1e3, m: 1e6, million: 1e6, bn: 1e9, billion: 1e9 }[(m[2] ?? "").toLowerCase() as "k"] ?? 1;
    const n = Number(m[1].replace(/,/g, "")) * scale;
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

/** A budget typed in pounds against costs kept in millions or thousands (`cost_megp`, `capex_m`):
 * in the costs' units, said (benchmark re-test, October 2026: 150 million against costs in mEGP). */
function inUnitsOf(budget: number | undefined, cost: string | undefined, choices: string[]): number | undefined {
  if (budget === undefined || !cost) return budget;
  const scale = /(^|_)(m|mn|megp|musd|million|millions)($|_)|megp|_m$/i.test(cost) ? 1e6
    : /(^|_)(k|kegp|thousand|thousands)($|_)|kegp|_k$/i.test(cost) ? 1e3 : 1;
  if (scale === 1 || budget < scale) return budget;
  choices.push(`Budget in the costs' units: ${budget / scale} (${cost} is in ${scale === 1e6 ? "millions" : "thousands"})`);
  return budget / scale;
}

/** The kind the text names that best fits a part: by its name, else its role or fields. */
function pick(text: string, kinds: Kind[], fit: RegExp, also: (k: Kind) => boolean = () => true, not: string[] = []):
  { kind: Kind; why: string } | null {
  const free = kinds.filter((k) => !not.includes(k.name) && also(k));
  for (const k of free) {
    const said = mentions(text, k);
    if (said && fit.test(k.name)) return { kind: k, why: `you wrote “${said}”` };
  }
  for (const k of free) {
    const said = mentions(text, k);
    if (said) return { kind: k, why: `you wrote “${said}”` };
  }
  const named = free.find((k) => fit.test(k.name));
  return named ? { kind: named, why: `the workspace has ${named.name}` } : null;
}

/** The recipe the words call for, best first; none below two signals unless it is the only one. */
export function recipeFor(text: string): { recipe: Recipe; said: string[] }[] {
  const found = (Object.keys(SIGNALS) as Recipe[]).map((recipe) => ({
    recipe, said: [...new Set((text.toLowerCase().match(SIGNALS[recipe]) ?? []))],
  })).filter((r) => r.said.length > 0);
  // Phasing is selection over time: years and projects together is phasing.
  return found.sort((a, b) => b.said.length - a.said.length || (a.recipe === "phasing" ? -1 : 1));
}

export function proposeDraft(text: string, kinds: Kind[], data: Data[], only?: Recipe): Proposal | null {
  if (text.trim().length < 12 || !kinds.length) return null;
  const ranked = recipeFor(text);
  const best = only ? ranked.find((r) => r.recipe === only) ?? { recipe: only, said: [] } : ranked[0];
  if (!best) return null;
  const said = best.said.slice(0, 3).map((w) => `“${w}”`).join(", ");
  const choices: string[] = [said ? `${TITLES[best.recipe]} — you wrote ${said}` : TITLES[best.recipe]];
  const missing: string[] = [];
  const need = <T,>(value: T | undefined | null, what: string): T | undefined => {
    if (value === undefined || value === null || value === "") missing.push(what);
    return value ?? undefined;
  };
  const note = (what: string, value: string | number | undefined, why: string) => {
    if (value !== undefined) choices.push(`${what}: ${value} — ${why}`);
  };

  if (best.recipe === "selection" || best.recipe === "phasing") {
    const time = (k: Kind) => k.role === "time" || /year|period|quarter|month|phase|season/.test(k.name);
    const items = pick(text, kinds, /project|option|proposal|candidate|investment|initiative|asset/, (k) => !time(k) && numeric(k).length >= 2);
    const value = field(items?.kind, /benefit|value|score|return|npv|worth|impact|priority|gain/);
    const cost = field(items?.kind, /cost|capex|price|spend|invest|amount/);
    note("Chosen from", items?.kind.name, items?.why ?? "");
    note("Worth", value, "its name");
    note("Cost", cost, "its name");
    need(items, "a kind of record to choose from, with a number field for its worth and one for its cost");
    if (items) {
      need(value, `a number field of ${items.kind.name} for what one is worth (benefit, value, score)`);
      need(cost, `a number field of ${items.kind.name} for what one costs`);
    }
    if (best.recipe === "phasing") {
      const periods = pick(text, kinds, /year|period|quarter|month|phase/, time, items ? [items.kind.name] : []);
      const budget = field(periods?.kind, /budget|cap|limit|spend|fund/);
      const weight = field(periods?.kind, /weight|discount|factor|priority/);
      note("Periods", periods?.kind.name, periods?.why ?? "");
      note("Each period's budget", budget, "its name");
      note("Sooner counts by", weight, "its name");
      need(periods, "a kind of record for the periods (years, quarters), with a budget field");
      if (periods) need(budget, `a number field of ${periods.kind.name} for what may be spent in it`);
      const all = /\b(every|all) (project|one)s? (is |are |must be )?(started|built|done)\b/i.test(text);
      if (all) choices.push("Every one is started — you wrote it");
      const recipe = missing.length ? null : ({ items: items!.kind.name, periods: periods!.kind.name, value: value!, cost: cost!, budget: budget!,
        ...(weight ? { weight } : {}), ...(all ? { all } : {}) } satisfies PhasingRecipe);
      return { recipe: "phasing", title: TITLES.phasing, choices, missing, apply: recipe ? (d) => applyPhasing(d, recipe) : null };
    }
    const budget = inUnitsOf(amount(text, ["budget", "spend", "afford", "invest"]), cost, choices);
    const atMost = amount(text, ["at most", "no more than", "up to", "maximum of", "max"]);
    note("Budget", budget, "the number you wrote");
    need(budget, "the budget: write it, e.g. “a budget of 2 million”");
    const most = atMost !== undefined && atMost !== budget && atMost < 1000 ? atMost : undefined;
    note("At most chosen", most, "the number you wrote");
    const mustHave = items ? field(items.kind, /committed|must|mandatory|required|locked/, (k) => (k?.attributes ?? []).filter((a) => a.data_type === "boolean").map((a) => a.name)) : undefined;
    note("Always chosen when", mustHave, "its name");
    const recipe = missing.length ? null : ({ items: items!.kind.name, value: value!, cost: cost!, budget: budget!,
      ...(most !== undefined ? { atMost: most } : {}), ...(mustHave ? { mustHave } : {}) } satisfies SelectionRecipe);
    return { recipe: "selection", title: TITLES.selection, choices, missing, apply: recipe ? (d) => applySelection(d, recipe) : null };
  }

  if (best.recipe === "allocation") {
    const options = pick(text, kinds, /crop|option|product|use|activit|treatment|variet/);
    const items = pick(text, kinds, /parcel|field|plot|farm|land|area|block|zone|site/, (k) => numeric(k).length > 0,
      options ? [options.kind.name] : []);
    note("Shared out", items?.kind.name, items?.why ?? "");
    note("Among", options?.kind.name, options?.why ?? "");
    need(items, "a kind of record to share out (parcels), with a number field for its size");
    need(options, "a kind of record to share among (crops)");
    const size = field(items?.kind, /area|size|feddan|hectare|acre|capacity|amount|ha$/) ?? numeric(items?.kind)[0];
    note("Its size", size, "its name");
    if (items) need(size, `a number field of ${items.kind.name} for how much of it there is`);
    // Worth: data over both (yield × price per parcel and crop) before a field of the option (profit per unit).
    const over = data.filter((d) => d.index.length === 2 && items && options && d.index.includes(items.kind.name) && d.index.includes(options.kind.name));
    const worthData = over.find((d) => /profit|margin|worth|value|return|revenue|yield|income/.test(d.name));
    const worthField = field(options?.kind, /profit|margin|worth|value|return|revenue|price|income/);
    note("Worth a unit", worthData?.name ?? worthField, worthData ? "data over both kinds" : "its name");
    if (items && options) need(worthData ?? worthField, `what a unit of ${options.kind.name} is worth: a number field (profit) or data over ${items.kind.name} and ${options.kind.name}`);
    const allowed = over.find((d) => d !== worthData && /suit|allow|ok|rotation|can|fit|eligible/.test(d.name));
    note("Only where", allowed?.name, "0/1 data over both kinds");
    const useField = field(options?.kind, /water|use|need|requirement|labou?r|m3|input/);
    const limit = amount(text, ["water", "limit", "budget", "quota", "at most", "no more than"]);
    if (useField && limit !== undefined) choices.push(`Shared limit: ${useField} up to ${limit} — its name and the number you wrote`);
    const minShare = field(options?.kind, /min.*share|share.*min|min_?pct|min_?frac|least/);
    const maxShare = field(options?.kind, /max.*share|share.*max|max_?pct|max_?frac|most/);
    note("Least share", minShare, "its name");
    note("Most share", maxShare, "its name");
    const all = /\b(all|every|whole|entire) (the )?(land|area|feddans?|parcels?)\b/i.test(text);
    if (all) choices.push("All of it given out — you wrote it");
    const recipe = missing.length ? null : ({ items: items!.kind.name, options: options!.kind.name, size: size!,
      worth: worthData ? { data: worthData.name, index: worthData.index } : { field: worthField! },
      ...(useField && limit !== undefined ? { use: { field: useField, limit } } : {}),
      ...(allowed ? { allowed: { data: allowed.name, index: allowed.index } } : {}),
      ...(minShare ? { minShare } : {}), ...(maxShare ? { maxShare } : {}), ...(all ? { all } : {}) } satisfies AllocationRecipe);
    return { recipe: "allocation", title: TITLES.allocation, choices, missing, apply: recipe ? (d) => applyAllocation(d, recipe) : null };
  }

  if (best.recipe === "network") {
    const sources = pick(text, kinds, /depot|warehouse|plant|factory|hub|supplier|dc|origin|source|mill/);
    const customers = pick(text, kinds, /customer|store|shop|client|retailer|outlet|destination|market|clinic|site|demand/,
      (k) => numeric(k).length > 0, sources ? [sources.kind.name] : []);
    note("Ship from", sources?.kind.name, sources?.why ?? "");
    note("To", customers?.kind.name, customers?.why ?? "");
    need(sources, "a kind of record goods come from (depots, warehouses)");
    need(customers, "a kind of record that needs them, with a number field for how much");
    const demand = field(customers?.kind, /demand|need|order|qty|quantity|volume|amount/) ?? numeric(customers?.kind)[0];
    note("Each needs", demand, "its name");
    if (customers) need(demand, `a number field of ${customers.kind.name} for how much it needs`);
    const both = data.filter((d) => d.index.length === 2 && sources && customers && d.index.includes(sources.kind.name) && d.index.includes(customers.kind.name));
    const unit = both.find((d) => /cost|price|rate|tariff/.test(d.name)) ?? both.find((d) => /dist|km|time|min/.test(d.name)) ?? both[0];
    note("Cost a unit", unit?.name, "data over both kinds");
    if (sources && customers) need(unit, `a data value over ${sources.kind.name} and ${customers.kind.name}: a cost, a distance or a travel time`);
    const capacity = field(sources?.kind, /capacity|cap|supply|max|limit|throughput/);
    const openCost = /\b(open|close|which (depot|warehouse|site)s?|fixed)\w*/i.test(text) ? field(sources?.kind, /fixed|open|setup|rent|overhead/) : undefined;
    note("Capacity", capacity, "its name");
    note("Opening cost", openCost, "you asked which to open");
    const single = /\b(single[- ]sourc\w*|one (depot|warehouse|supplier|source)|only one (depot|warehouse|supplier|source)|a single (depot|warehouse|supplier))\b/i.test(text);
    if (single) choices.push("One supplier each — you wrote it");
    const shortage = /\b(short\w*|unmet|stock-?outs?|penalt\w*|lost sales?)\b/i.test(text) ? amount(text, ["penalty", "lost sales?", "costs?"]) ?? 1000 : undefined;
    note("Shortage allowed, a unit costs", shortage, "you wrote of shortage");
    const fleetKind = /\b(fleet|vehicle|truck|van|lorr)\w*/i.test(text)
      ? kinds.find((k) => /vehicle|truck|van|fleet|lorry/.test(k.name) && k.name !== sources?.kind.name && k.name !== customers?.kind.name) : undefined;
    const load = field(fleetKind, /capacity|load|payload|size/);
    const price = field(fleetKind, /cost|price|rate|rent/);
    if (fleetKind && load && price) choices.push(`Vehicles by type: ${fleetKind.name}, each carries ${load}, costs ${price} — you wrote of a fleet`);
    const recipe = missing.length ? null : ({ sources: sources!.kind.name, customers: customers!.kind.name, demand: demand!, unitCost: unit!.name,
      unitCostIndex: unit!.index, ...(capacity ? { capacity } : {}), ...(openCost ? { openCost } : {}), ...(single ? { singleSource: true } : {}),
      ...(shortage !== undefined ? { shortagePenalty: shortage } : {}),
      ...(fleetKind && load && price ? { fleet: { kind: fleetKind.name, capacity: load, cost: price } } : {}) } satisfies NetworkRecipe);
    return { recipe: "network", title: TITLES.network, choices, missing, apply: recipe ? (d) => applyNetwork(d, recipe) : null };
  }

  const sites = pick(text, kinds, /site|depot|centre|center|station|clinic|candidate|facilit|yard|shelter|base|hospital/);
  // What is covered is what the 0/1 reach data joins the sites to, when there is such data: a word
  // alone took "restricted zones" for it (benchmark re-test, October 2026).
  const reachable = sites ? data.filter((d) => d.index.length === 2 && d.index.includes(sites.kind.name)
    && d.index.some((k) => k !== sites.kind.name) && /within|reach|cover|near|minutes|min\b/.test(d.name)) : [];
  const reachKinds = [...new Set(reachable.map((d) => d.index.find((k) => k !== sites!.kind.name)!))];
  const named = pick(text, kinds, /zone|area|district|place|neighbou?rhood|village|hotspot|block|tract|community|demand|household|town|cit/,
    (k) => reachKinds.length === 0 || reachKinds.includes(k.name), sites ? [sites.kind.name] : []);
  const fromData = !named && reachKinds.length === 1 ? kinds.find((k) => k.name === reachKinds[0]) : undefined;
  const places = named ?? (fromData ? { kind: fromData, why: "the reach data joins the sites to it" } : null);
  note("Open", sites?.kind.name, sites?.why ?? "");
  note("Cover", places?.kind.name, places?.why ?? "");
  need(sites, "a kind of record to open (sites, centres)");
  need(places, "a kind of record to cover (zones, areas)");
  const reachData = data.filter((d) => d.index.length === 2 && sites && places && d.index.includes(sites.kind.name) && d.index.includes(places.kind.name));
  const reach = reachData.find((d) => /within|reach|cover|near/.test(d.name)) ?? reachData[0];
  note("Within reach by", reach?.name, "0/1 data over both kinds");
  if (sites && places) need(reach, `0/1 data over ${sites.kind.name} and ${places.kind.name}: who is within reach (Data values → From the map → within)`);
  const cost = field(sites?.kind, /cost|price|rent|capex/);
  const budget = inUnitsOf(amount(text, ["budget", "spend", "afford"]), cost, choices);
  const weights = numeric(places?.kind).filter((n) => /population|people|vulnerab|risk|demand|weight|households?|elderly/.test(n));
  const coverAll = /\b(every|all|each) (\w+ ){0,2}(is |are |must be |should be )?(covered|served|reached)\b/i.test(text) && budget === undefined;
  note("Cost", cost, "its name");
  note("Budget", budget, "the number you wrote");
  if (weights.length) choices.push(`Worth covering: ${weights.join(" × ")} — their names`);
  if (coverAll) choices.push("Every one covered, at the least cost — you wrote it");
  // Capacity as well as reach: sites with a capacity seat the people of the places they cover
  // (benchmark re-test, October 2026: coverage with capacity was left out of the draft).
  const capacity = /\b(capacit\w*|seats?|beds?|units? per|how many)\b/i.test(text) || field(sites?.kind, /capacity|seats|beds/) ? field(sites?.kind, /capacity|seats|beds|max_units|units/) : undefined;
  const people = numeric(places?.kind).filter((n) => /population|people|demand|calls|patients|households?/.test(n)).slice(0, 1);
  const seats = !coverAll && capacity && people.length ? { capacity, demand: people } : undefined;
  if (seats) choices.push(`Each open ${sites!.kind.name} serves at most its ${capacity}, of the ${people[0]} it covers — their names`);
  const recipe = missing.length ? null : ({ sites: sites!.kind.name, places: places!.kind.name, reach: reach!.name, reachIndex: reach!.index,
    ...(cost ? { cost } : {}), ...(budget !== undefined ? { budget } : {}), weights, coverAll, ...(seats ? { seats } : {}) } satisfies CoverageRecipe);
  return { recipe: "coverage", title: TITLES.coverage, choices, missing, apply: recipe ? (d) => applyCoverage(d, recipe) : null };
}

/** The words typed on the Start page, kept per workspace so the model editor's "Describe" box starts
 * from them (benchmark re-test, October 2026: they were typed twice). */
const WORDS_KEY = (domainId: number | string) => `solver_problem_words:${domainId}`;
export function keepWords(domainId: number | string | null | undefined, text: string): void {
  if (domainId == null) return;
  try {
    if (text.trim()) localStorage.setItem(WORDS_KEY(domainId), text);
  } catch {
    /* kept for this page only */
  }
}
export function keptWords(domainId: number | string | null | undefined): string {
  if (domainId == null) return "";
  try {
    return localStorage.getItem(WORDS_KEY(domainId)) ?? "";
  } catch {
    return "";
  }
}
