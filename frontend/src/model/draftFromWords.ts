/**
 * Describe it -> a first draft (benchmark, October 2026, G3c): from a person's own description and
 * the workspace's kinds, fields and data values, the recipe their words call for, filled in -- which
 * kind is chosen from, which field is the cost, the budget they wrote -- each choice with the reason
 * for it, and what is still missing. Offline and by words, like `lib/describeProblem.ts`; it writes
 * nothing until the person says so, and what it writes is an ordinary draft to read and change.
 */
import { applyCoverage, type CoverageRecipe } from "./coverageRecipe";
import type { FormDraft } from "./draftIr";
import { applyAllocation, applyAssignment, applyFlow, applyInventory, applyNetwork, applyPhasing, applySelection, endsOf, type AllocationRecipe, type AssignmentRecipe, type FlowRecipe, type InventoryRecipe, type Link,
  type NetworkRecipe, type PhasingRecipe, type SelectionRecipe } from "./recipes";

export type Kind = { name: string; role?: string; attributes: { name: string; data_type: string; enum_values?: string[] | null }[] };
export type Data = { name: string; index: string[] };
export type Recipe = "coverage" | "selection" | "network" | "phasing" | "allocation" | "flow" | "inventory" | "assignment";

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
  flow: "Traffic: route the trips between zones over the roads",
  inventory: "Stock: how much of each product to order each period",
  assignment: "Each place served by its nearest open site: least response time",
};

const SIGNALS: Record<Recipe, RegExp> = {
  coverage: /\b(cover\w*|within|reach\w*|minutes?|response|nearby|closest|serve every|hotspots?)\b/g,
  selection: /\b(projects?|portfolio|select\w*|invest\w*|proposals?|candidates?|fund\w*|shortlist\w*|options?)\b/g,
  network: /\b(ship\w*|deliver\w*|supply|suppl(y|ier)s?|warehouses?|depots?|customers?|stores?|flows?|transport\w*|distribut\w*|trucks?|fleet|vehicles?)\b/g,
  phasing: /\b(years?|yearly|annual\w*|quarters?|periods?|phas\w*|over time|month\w*|multi-?year|horizon)\b/g,
  // Benchmark re-test, October 2026: crop planning matched no recipe.
  allocation: /\b(allocat\w*|crops?|plant\w*|feddans?|hectares?|acres?|land|grow\w*|share\w* (out|of)|split|mix|irrigat\w*|sow\w*|area to)\b/g,
  // Benchmark re-test, October 2026: a trips table over a road network matched no recipe.
  flow: /\b(traffic|congest\w*|trips?|commut\w*|junctions?|intersections?|roads?|od matrix|origin-destination|lanes?|widen\w*|travel times?)\b/g,
  // Benchmark re-test, October 2026: stock per product over periods matched no recipe.
  // Benchmark round 4: "minimise response time" had no recipe; coverage was used in its place.
  assignment: /\b(response times?|respond\w*|nearest|closest|p-?median|assign\w* (each|every)|minimi[sz]e (the )?(total |average |mean )?(travel |response |driving )?(time|minutes|distance)|weighted (time|distance|minutes))\b/g,
  inventory: /\b(inventor\w*|stock\w*|reorder\w*|replenish\w*|holding|safety stock|skus?|lost sales?|backorders?|on hand|order quantit\w*|forecasts?|products?)\b/g,
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

/** The first field of a kind whose name fits: at the start of the name or of one of its words, so
 * "rent" does not fit `current_inventory_t` (benchmark round 4: it was taken as the opening cost). */
function field(k: Kind | undefined, pattern: RegExp, of: (k: Kind | undefined) => string[] = numeric): string | undefined {
  const flags = pattern.flags.replace("g", "");
  const atWord = new RegExp(`(?:^|_)(?:${pattern.source})`, flags);
  return of(k).find((n) => atWord.test(n));
}

/** A number field of a kind the text names whole ("veh_hours_saved_per_day", or with spaces), not one of `not`. */
function namedField(k: Kind | undefined, text: string, not: RegExp = /$^/): string | undefined {
  return numeric(k).filter((n) => !not.test(n))
    .find((n) => new RegExp(`(^|[^a-z0-9_])${n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/_/g, "[_ ]")}($|[^a-z0-9_])`, "i").test(text));
}

/** A number in the text after the first of these words found, in this order: "a budget of 2.5 million", "at most 3". */
function amount(text: string, leads: string[]): number | undefined {
  for (const lead of leads) {
    // "150000 kEGP", "2.5 mUSD": a scale written onto the currency counts too (benchmark round 3: read as 150).
    const m = text.match(new RegExp(`\\b(?:${lead})\\b[^0-9.]{0,24}([0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(k|thousand|m|mn|million|bn|billion)?(?:egp|usd|eur|gbp|le|sar|aed)?\\b`, "i"));
    if (!m) continue;
    const scale = { k: 1e3, thousand: 1e3, m: 1e6, mn: 1e6, million: 1e6, bn: 1e9, billion: 1e9 }[(m[2] ?? "").toLowerCase() as "k"] ?? 1;
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

/** "at most 8 parking projects": the word before the items is a value of one of their fields -- a list
 * field holding it, else a text field for the type (type, category, kind, class, group). */
function limitsPerType(text: string, items: Kind): { field: string; value: string; atMost: number; said: string }[] {
  const nouns = [...new Set([...words(items.name), ...words(items.name).flatMap(plural), "ones", "of them"])].join("|");
  const found: { field: string; value: string; atMost: number; said: string }[] = [];
  const pattern = new RegExp(`\\b(?:at most|no more than|up to|maximum of|max)\\s+([0-9]+)\\s+([a-z][a-z-]*)\\s+(?:${nouns})\\b`, "gi");
  for (const m of text.matchAll(pattern)) {
    const word = m[2].toLowerCase();
    const listed = items.attributes.find((a) => (a.enum_values ?? []).some((x) => x.toLowerCase() === word));
    const typed = items.attributes.find((a) => a.data_type === "text" && /(^|_)(type|category|kind|class|group|sort)($|_)/.test(a.name));
    const f = listed ?? typed;
    if (!f) continue;
    const value = listed ? listed.enum_values!.find((x) => x.toLowerCase() === word)! : word;
    found.push({ field: f.name, value, atMost: Number(m[1]), said: m[0] });
  }
  return found;
}

/** "every district gets at least one", "at least one project in each district": the kind, and the link
 * from the items to it when there is one. */
function onePer(text: string, items: Kind, kinds: Kind[], links: Link[]):
  { kind: string; said: string; link?: string } | null {
  const m = text.match(/\b(?:every|each)\s+([a-z_]+)\b[^.;]{0,40}\bat least (?:one|1)\b/i)
    ?? text.match(/\bat least (?:one|1)\b[^.;]{0,40}\b(?:in|for|per|of) (?:every|each)\s+([a-z_]+)\b/i);
  if (!m) return null;
  const word = m[1].toLowerCase();
  const kind = kinds.find((k) => k.name !== items.name && [words(k.name).join("_"), words(k.name).join(" "), words(k.name).at(-1)!]
    .flatMap(plural).includes(word));
  if (!kind) return null;
  const link = links.find((l) => l.from === items.name && l.to === kind.name);
  return { kind: kind.name, said: m[0], link: link?.name };
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
  // Asking for the least response time, or the nearest site, is assignment whatever else is said: "within
  // 15 minutes" alone was read as coverage (benchmark round 4).
  const first = found.find((r) => r.recipe === "assignment");
  return found.sort((a, b) => (first ? Number(b === first) - Number(a === first) : 0)
    || b.said.length - a.said.length || (a.recipe === "phasing" ? -1 : 1));
}

export function proposeDraft(text: string, kinds: Kind[], data: Data[], only?: Recipe, links: Link[] = []): Proposal | null {
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
    // A field the words name whole is the worth (benchmark round 4: benefit_per_megp was taken when
    // veh_hours_saved_per_day was written).
    const costLike = /(^|_)(cost|capex|price|spend|invest|amount|budget)/;
    const value = namedField(items?.kind, text, costLike) ?? field(items?.kind, /benefit|value|score|return|npv|worth|impact|priority|gain/);
    const cost = numeric(items?.kind).filter((n) => costLike.test(n)).find((n) => namedField(items?.kind, text) === n
      || new RegExp(`\\b${n.replace(/_/g, "[_ ]")}\\b`, "i").test(text)) ?? field(items?.kind, /cost|capex|price|spend|invest|amount/);
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
    // "at most 8 parking projects": a limit on those of one type, not on all (benchmark round 4).
    const perType = items ? limitsPerType(text, items.kind) : [];
    for (const t of perType) choices.push(`At most ${t.atMost} with ${t.field} = ${t.value} — you wrote “${t.said}”`);
    const atMost = amount(perType.reduce((left, t) => left.replace(t.said, " "), text), ["at most", "no more than", "up to", "maximum of", "max"]);
    note("Budget", budget, "the number you wrote");
    need(budget, "the budget: write it, e.g. “a budget of 2 million”");
    const most = atMost !== undefined && atMost !== budget && atMost < 1000 ? atMost : undefined;
    note("At most chosen", most, "the number you wrote");
    // "every district gets at least one project": one or more chosen per record linked to (benchmark round 4).
    const per = items ? onePer(text, items.kind, kinds, links) : null;
    if (per?.link) choices.push(`At least one in every ${per.kind} — you wrote “${per.said}”; through ${per.link}`);
    if (per && !per.link) choices.push(`Not added: at least one in every ${per.kind} — you wrote “${per.said}”, but no ${items!.kind.name} is linked to a ${per.kind}; link them under Records → Compute and join, then describe it again`);
    const flags = (k: Kind | undefined) => (k?.attributes ?? []).filter((a) => a.data_type === "boolean").map((a) => a.name);
    // Whole words: "blocked" is not "locked" (benchmark round 3: blocked projects were made a must).
    const named = (n: string) => new RegExp(`\\b${n.replace(/_/g, "[_ ]")}\\b`, "i").test(text) || words(n).some((w) => w.length > 3 && new RegExp(`\\b${w}`, "i").test(text));
    const never = items ? flags(items.kind).find((n) => /(^|_)(blocked|block|excluded?|forbidden|banned|closed|restricted|not_allowed|infeasible)(_|$)/.test(n)
      || (named(n) && /\b(never|cannot|can't|can not|not be|must not|no)\b[^.;]{0,50}\b(chosen|selected|funded|picked|built)\b/i.test(text))) : undefined;
    const mustHave = items ? flags(items.kind).find((n) => n !== never && /(^|_)(committed|must|mandatory|required|locked)(_|$)/.test(n)) : undefined;
    note("Always chosen when", mustHave, "its name");
    note("Never chosen when", never, "its name and your words");
    const recipe = missing.length ? null : ({ items: items!.kind.name, value: value!, cost: cost!, budget: budget!,
      ...(most !== undefined ? { atMost: most } : {}), ...(mustHave ? { mustHave } : {}), ...(never ? { never } : {}),
      ...(perType.length ? { perType: perType.map(({ field: f, value: x, atMost: n }) => ({ field: f, value: x, atMost: n })) } : {}),
      ...(per?.link ? { atLeastOnePer: { kind: per.kind, link: per.link } } : {}) } satisfies SelectionRecipe);
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
    // Profit per unit area when the option has it; else yield × price, less the cost per unit area
    // (benchmark round 3: price per tonne was taken as worth per feddan).
    const profitField = field(options?.kind, /profit|margin|worth|net|return|income/);
    const yieldField = field(options?.kind, /yield|t_per|ton|tonnes?_per|production|output/);
    const priceField = field(options?.kind, /price|revenue|value/);
    const costField = field(options?.kind, /cost|expense/);
    const built = !worthData && !profitField && yieldField && priceField ? { product: [yieldField, priceField], ...(costField ? { less: costField } : {}) } : undefined;
    const worthField = profitField ?? (built ? undefined : priceField);
    note("Worth a unit", worthData?.name ?? worthField ?? (built ? `${yieldField} × ${priceField}${costField ? ` − ${costField}` : ""}` : undefined),
      worthData ? "data over both kinds" : built ? "their names: yield times price, less cost" : "its name");
    if (items && options) need(worthData ?? worthField ?? (built ? "built" : undefined), `what a unit of ${options.kind.name} is worth: a number field (profit) or data over ${items.kind.name} and ${options.kind.name}`);
    const allowed = over.find((d) => d !== worthData && /suit|allow|ok|rotation|can|fit|eligible/.test(d.name));
    note("Only where", allowed?.name, "0/1 data over both kinds");
    const useField = field(options?.kind, /water|use|need|requirement|labou?r|m3|input/);
    const limit = amount(text, ["water", "limit", "budget", "quota", "at most", "no more than"]);
    if (useField && limit !== undefined) choices.push(`Shared limit: ${useField} up to ${limit} — its name and the number you wrote`);
    // Each item draws from the source it links to (a canal intake, a well), up to the source's capacity.
    const sourceLink = useField && items ? links.find((l) => l.from === items.kind.name && l.to !== options?.kind.name
      && /water|source|intake|well|canal|pump|supply/.test(`${l.to} ${l.name}`)) : undefined;
    const sourceKind = sourceLink ? kinds.find((k) => k.name === sourceLink.to) : undefined;
    const sourceCap = field(sourceKind, /capacity|cap|supply|allocation|quota|available|m3|limit/);
    const useBySource = useField && sourceLink && sourceCap ? { field: useField, kind: sourceLink.to, link: sourceLink.name, capacity: sourceCap } : undefined;
    if (useBySource) choices.push(`Each ${sourceLink!.to} supplies at most its ${sourceCap}, to the ${items!.kind.name}s linked by ${sourceLink!.name} — their names`);
    // A share by its name (share, pct, frac); any other least or most is an amount in the size's units
    // (benchmark round 4: min_area_feddan was written as a share of all the land).
    const minShare = field(options?.kind, /min\w*(share|pct|frac|percent)|(share|pct|frac|percent)\w*min|least\w*(share|pct|frac)/);
    const maxShare = field(options?.kind, /max\w*(share|pct|frac|percent)|(share|pct|frac|percent)\w*max|most\w*(share|pct|frac)/);
    const minAmount = minShare ? undefined : field(options?.kind, /min(imum)?($|_)|least/);
    const maxAmount = maxShare ? undefined : field(options?.kind, /max(imum)?($|_)|most/);
    note("Least share", minShare, "its name");
    note("Most share", maxShare, "its name");
    note("Least in all", minAmount, "its name");
    note("Most in all", maxAmount, "its name");
    const all = /\b(all|every|whole|entire) (the )?(land|area|feddans?|parcels?)\b/i.test(text);
    if (all) choices.push("All of it given out — you wrote it");
    const recipe = missing.length ? null : ({ items: items!.kind.name, options: options!.kind.name, size: size!,
      worth: worthData ? { data: worthData.name, index: worthData.index } : built ?? { field: worthField! },
      ...(useField && limit !== undefined ? { use: { field: useField, limit } } : {}), ...(useBySource ? { useBySource } : {}),
      ...(allowed ? { allowed: { data: allowed.name, index: allowed.index } } : {}),
      ...(minShare ? { minShare } : {}), ...(maxShare ? { maxShare } : {}), ...(minAmount ? { minAmount } : {}), ...(maxAmount ? { maxAmount } : {}),
      ...(all ? { all } : {}) } satisfies AllocationRecipe);
    return { recipe: "allocation", title: TITLES.allocation, choices, missing, apply: recipe ? (d) => applyAllocation(d, recipe) : null };
  }

  if (best.recipe === "assignment") {
    const sites = pick(text, kinds, /site|depot|centre|center|station|clinic|candidate|facilit|yard|base|hospital|warehouse/);
    const timed = (d: Data) => /(^|_)(min|mins|minutes|km|time|dist|distance|tt|travel|drive)($|_)/.test(d.name);
    const fromTimes = sites ? [...new Set(data.filter((d) => d.index.length === 2 && d.index.includes(sites.kind.name) && timed(d))
      .map((d) => d.index.find((k) => k !== sites.kind.name)!))] : [];
    const places = pick(text, kinds, /zone|area|district|place|town|village|cell|community|customer|neighbou?rhood|cit/,
      (k) => fromTimes.length === 0 || fromTimes.includes(k.name), sites ? [sites.kind.name] : []);
    note("Open", sites?.kind.name, sites?.why ?? "");
    note("Serving each", places?.kind.name, places?.why ?? "");
    need(sites, "a kind of record to open (stations, bases)");
    need(places, "a kind of record each served by one (districts, towns)");
    const both = data.filter((d) => sites && places && d.index.length === 2 && d.index.includes(sites.kind.name) && d.index.includes(places.kind.name));
    const time = both.find(timed) ?? both[0];
    note("Minutes between", time?.name, "data over both kinds");
    if (sites && places) need(time, `travel times or distances over ${sites.kind.name} and ${places.kind.name} (Data values → Compute from the map)`);
    const named = numeric(places?.kind).filter((n) => new RegExp(`\\b${n.replace(/_/g, "[_ ]")}\\b`, "i").test(text));
    const weight = named[0] ?? numeric(places?.kind).find((n) => /incident|calls?|demand|population|people|patients|households?/.test(n));
    note("Each counts by", weight, named.length ? "you wrote it" : "its name");
    const cost = field(sites?.kind, /cost|price|rent|capex/);
    const budget = cost ? inUnitsOf(amount(text, ["budget", "spend", "afford"]), cost, choices) : undefined;
    const count = amount(text, ["open", "at most", "up to", "choose", "build"]);
    const open = cost && budget !== undefined ? { cost, budget } : count !== undefined && Number.isInteger(count) && count > 0 && count < 1000 ? { count } : undefined;
    if (open) choices.push("count" in open ? `${open.count} open — the number you wrote` : `Opening costs ${open.cost}, within ${open.budget}`);
    const existing = (sites?.kind.attributes ?? []).find((a) => a.data_type === "boolean" && /existing|current|already|open_now|operating/.test(a.name))?.name;
    note("Open already", existing, "its name");
    // Only a number written with its minutes or km is a reach: "within a budget of 400M" is not
    // (benchmark round 5: the budget was read as a distance).
    const within = text.match(/\b(?:within|no more than|never more than|not more than|more than|at most|under)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:-\s*)?(?:min|mins|minutes|km|kilomet\w*)\b/i);
    const reach = within ? Number(within[1]) : undefined;
    note("Never further than", reach, "the number you wrote");
    const capacity = /\bcapacit/i.test(text) ? field(sites?.kind, /capacity|beds|max|units/) : undefined;
    note("Serves at most", capacity, "you wrote of capacity");
    const recipe = missing.length ? null : ({ sites: sites!.kind.name, places: places!.kind.name, time: { data: time!.name, index: time!.index },
      ...(weight ? { weight } : {}), ...(open ? { open } : {}), ...(existing ? { existing } : {}), ...(reach !== undefined ? { within: reach } : {}),
      ...(capacity ? { capacity } : {}) } satisfies AssignmentRecipe);
    return { recipe: "assignment", title: TITLES.assignment, choices, missing, apply: recipe ? (d) => applyAssignment(d, recipe) : null };
  }

  if (best.recipe === "flow") {
    const square = (k: Kind) => data.some((d) => d.index.length === 2 && d.index[0] === k.name && d.index[1] === k.name);
    const twoLinks = (arc: string, node: string) => links.filter((l) => l.from === arc && l.to === node).length >= 2;
    const nodes = pick(text, kinds, /zone|junction|intersection|node|district|area|taz|centroid|place/,
      (k) => square(k) || kinds.some((a) => twoLinks(a.name, k.name)));
    const arcs = pick(text, kinds, /road|link|street|segment|arc|edge|lane|route/, (k) => !!nodes && twoLinks(k.name, nodes.kind.name),
      nodes ? [nodes.kind.name] : []);
    note("Trips between", nodes?.kind.name, nodes?.why ?? "");
    note("Over", arcs?.kind.name, arcs?.why ?? "");
    need(nodes, "a kind of record trips go between (zones, junctions)");
    // Roads that hold their ends as codes are one step away (benchmark round 3: the recipe found nothing).
    const codes = nodes ? kinds.filter((k) => k.name !== nodes.kind.name && k.attributes.filter((a) => a.data_type === "text"
      && /(^|_)(from|to|start|end|origin|dest\w*|source|target|a|b|u|v)(_|$)/.test(a.name)).length >= 2) : [];
    if (nodes) need(arcs, `a kind of record for the roads, each linked twice to ${nodes.kind.name}: where it starts and where it ends${codes.length
      ? ` -- ${codes[0].name} holds them as codes: link them under Records → Compute and join → Link records by a code they hold, once for each end (name the links from_… and to_…)`
      : ""}`);
    const { startsAt, endsAt } = nodes && arcs ? endsOf(links.filter((l) => l.from === arcs.kind.name && l.to === nodes.kind.name)) : {};
    if (startsAt && endsAt) choices.push(`A road starts at ${startsAt} and ends at ${endsAt} — their names`);
    if (nodes && arcs) need(startsAt && endsAt ? startsAt : undefined, `which link of ${arcs.kind.name} is where it starts and which where it ends: name them from_… and to_…`);
    const square2 = data.filter((d) => nodes && d.index.length === 2 && d.index[0] === nodes.kind.name && d.index[1] === nodes.kind.name);
    const trips = square2.find((d) => /trip|od|demand|flow|volume|journey/.test(d.name)) ?? square2[0];
    note("How many trips", trips?.name, "data over two of them, origin first");
    if (nodes) need(trips, `a data value over ${nodes.kind.name} twice (origin, destination): how many trips go from one to the other`);
    const time = field(arcs?.kind, /time|minutes|min\b|travel|duration|length|km|dist/);
    note("Time on a road", time, "its name");
    if (arcs) need(time, `a number field of ${arcs.kind.name} for how long it takes`);
    const capacity = field(arcs?.kind, /capacity|cap\b|_cap|max|throughput/);
    note("Capacity", capacity, "its name");
    const added = /\b(widen\w*|upgrad\w*|expan\w*|add\w* lanes?|new lanes?)\b/i.test(text) ? field(arcs?.kind, /extra|added|widen|upgrade|new_cap|more/) : undefined;
    const cost = added ? field(arcs?.kind, /cost|price|capex/) : undefined;
    const budget = added && cost ? inUnitsOf(amount(text, ["budget", "spend", "afford"]), cost, choices) : undefined;
    const upgrade = capacity && added && cost && budget !== undefined ? { added, cost, budget } : undefined;
    if (upgrade) choices.push(`Roads may be widened by ${added} at ${cost}, within ${budget} — you wrote of widening`);
    // "travel time grows as a road fills", "congestion": the BPR curve in place of a hard limit (benchmark round 4).
    const congestion = !!capacity && /\b(congest\w*|bpr|volume[- ]delay|(grows?|rises?|increases?|slows?)\b[^.;]{0,30}\b(fills?|full|busy|load\w*|volume)|as (a |the )?roads? fills?)\b/i.test(text);
    if (congestion) choices.push("Time grows as a road fills (time × (1 + 0.15 (load/capacity)⁴)), in place of a hard limit — you wrote of congestion");
    const recipe = missing.length ? null : ({ nodes: nodes!.kind.name, arcs: arcs!.kind.name, startsAt: startsAt!, endsAt: endsAt!, trips: trips!.name,
      time: time!, ...(capacity ? { capacity } : {}), ...(upgrade ? { upgrade } : {}), ...(congestion ? { congestion: {} } : {}) } satisfies FlowRecipe);
    return { recipe: "flow", title: TITLES.flow, choices, missing, apply: recipe ? (d) => applyFlow(d, recipe) : null };
  }

  if (best.recipe === "inventory") {
    const time = (k: Kind) => k.role === "time" || /week|month|period|day|quarter|year|season/.test(k.name);
    const periods = pick(text, kinds, /week|month|period|day|quarter|year/, time);
    const products = pick(text, kinds, /product|item|sku|part|material|good|article/, (k) => !time(k), periods ? [periods.kind.name] : []);
    note("Stock of", products?.kind.name, products?.why ?? "");
    note("Each", periods?.kind.name, periods?.why ?? "");
    need(products, "a kind of record for what is stocked (products)");
    need(periods, "a kind of record for the periods (weeks, months)");
    // What is needed: data over the product and the period, and a location when it has one.
    const over = data.filter((d) => products && periods && d.index.includes(products.kind.name) && d.index.includes(periods.kind.name)
      && d.index.length <= 3 && new Set(d.index).size === d.index.length);
    const demand = over.find((d) => /demand|forecast|sales|need|order|requirement/.test(d.name)) ?? over[0];
    note("Needed", demand?.name, "data over both kinds");
    if (products && periods) need(demand, `a data value over ${products.kind.name} and ${periods.kind.name}: how much is needed (a forecast)`);
    const where = demand?.index.find((k) => k !== products?.kind.name && k !== periods?.kind.name);
    const locations = where ? kinds.find((k) => k.name === where) : undefined;
    note("At each", locations?.name, "the data is kept per one");
    const startData = locations ? data.find((d) => d.index.length === 2 && d.index.includes(products!.kind.name) && d.index.includes(locations.name)
      && /on_?hand|initial|opening|start|stock/.test(d.name)) : undefined;
    const startField = field(products?.kind, /on_?hand|initial|opening|start|stock/);
    note("On hand at the start", startData?.name ?? startField, "its name");
    const unitCost = numeric(products?.kind).find((n) => /cost|price/.test(n) && !/hold|carry|storage|order_?fixed/.test(n));
    const holdCost = field(products?.kind, /hold|carry|storage_cost/);
    const orderMax = field(products?.kind, /max_?order|order_?max|max_?qty|supply_?limit|max_per/);
    note("Cost to order a unit", unitCost, "its name");
    note("Cost to hold a unit", holdCost, "its name");
    note("Most ordered at once", orderMax, "its name");
    const room = locations ? field(locations, /capacity|space|room|storage/) : amount(text, ["storage", "room for", "space for", "capacity"]);
    const size = field(products?.kind, /size|volume|space|pallets?|m3/);
    note("Room in store", room, locations ? "its name" : "the number you wrote");
    note("A unit takes", room !== undefined ? size : undefined, "its name");
    const shortage = /\b(lost sales?|short\w*|stock-?outs?|unmet|backorders?|penalt\w*)\b/i.test(text) ? amount(text, ["penalty", "lost sales?", "costs?"]) ?? 1000 : undefined;
    const shortageField = shortage !== undefined ? field(products?.kind, /penalt|shortage|stockout|lost/) : undefined;
    note("Lost sales allowed, a unit costs", shortageField ?? shortage, shortageField ? "its name; the price is in the lost sales goal's equation" : "you wrote of shortage; the price is in the lost sales goal's equation, to change there");
    const recipe = missing.length ? null : ({ products: products!.kind.name, periods: periods!.kind.name, ...(locations ? { locations: locations.name } : {}),
      demand: { data: demand!.name, index: demand!.index },
      ...(startData ? { initial: { data: startData.name, index: startData.index } } : startField ? { initial: { field: startField } } : {}),
      ...(unitCost ? { unitCost } : {}), ...(holdCost ? { holdCost } : {}), ...(orderMax ? { orderMax } : {}),
      ...(room !== undefined ? { storage: { capacity: room, ...(size ? { size } : {}) } } : {}),
      ...(shortage !== undefined ? { shortagePenalty: shortage } : {}), ...(shortageField ? { shortageField } : {}) } satisfies InventoryRecipe);
    return { recipe: "inventory", title: TITLES.inventory, choices, missing, apply: recipe ? (d) => applyInventory(d, recipe) : null };
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
    // A cost field of the source the words name first (benchmark round 4: fixed_cost_egp_yr was written,
    // current_inventory_t taken).
    const openCost = /\b(open|close|which (depot|warehouse|site)s?|fixed)\w*/i.test(text)
      ? namedField(sources?.kind, text, /capacit|inventor|stock|supply|demand/) ?? field(sources?.kind, /fixed|open|setup|rent|overhead/) : undefined;
    note("Capacity", capacity, "its name");
    note("Opening cost", openCost, "you asked which to open");
    const single = /\b(single[- ]sourc\w*|one (depot|warehouse|supplier|source)|only one (depot|warehouse|supplier|source)|a single (depot|warehouse|supplier))\b/i.test(text);
    if (single) choices.push("One supplier each — you wrote it");
    const shortage = /\b(short\w*|unmet|stock-?outs?|penalt\w*|lost sales?)\b/i.test(text) ? amount(text, ["penalty", "lost sales?", "costs?"]) ?? 1000 : undefined;
    const shortageField = shortage !== undefined ? field(customers?.kind, /penalt|shortage|unmet|lost/) : undefined;
    note("Shortage allowed, a unit costs", shortageField ?? shortage, shortageField ? `its name; the price is in the shortage goal's equation` : "you wrote of shortage; the price is in the shortage goal's equation, to change there");
    const fleetKind = /\b(fleet|vehicle|truck|van|lorr)\w*/i.test(text)
      ? kinds.find((k) => /vehicle|truck|van|fleet|lorry/.test(k.name) && k.name !== sources?.kind.name && k.name !== customers?.kind.name) : undefined;
    const load = field(fleetKind, /capacity|load|payload|size/);
    const price = field(fleetKind, /cost|price|rate|rent/);
    if (fleetKind && load && price) choices.push(`Vehicles by type: ${fleetKind.name}, each carries ${load}, costs ${price} — you wrote of a fleet`);
    // How many vehicles there are, and how long a delivery may take (benchmark round 5: both typed by hand).
    const availableField = field(fleetKind, /avail|count|number|fleet_size|units|owned|how_many/);
    const available = availableField !== load && availableField !== price ? availableField : undefined;
    const fleetMost = (() => {
      const m = text.match(/\b(?:fleet of|at most|no more than|up to|only|have)\s+(\d+)\s+(?:\w+\s+)?(?:vehicles?|trucks?|vans?|lorr(?:y|ies))\b/i)
        ?? text.match(/\b(\d+)\s+(?:vehicles?|trucks?|vans?|lorr(?:y|ies))\s+(?:in all|in total|available)\b/i);
      return m ? Number(m[1]) : undefined;
    })();
    if (fleetKind && load && price && available) choices.push(`No more ${fleetKind.name}s than its ${available} — its name`);
    else if (fleetKind && load && price && fleetMost !== undefined) choices.push(`At most ${fleetMost} vehicles in all — the number you wrote`);
    const hours = text.match(/\b(?:within|in at most|in no more than|no more than|at most|under)\s+([0-9]+(?:\.[0-9]+)?)\s*(h|hrs?|hours?|min|mins|minutes)\b/i);
    const timeData = hours ? both.find((d) => (/^h/i.test(hours[2]) ? /(^|_)(h|hrs?|hours?|time|tt|travel|duration)($|_)/ : /(^|_)(min|mins|minutes|time|tt|travel|duration)($|_)/).test(d.name)) : undefined;
    const deliveryLimit = hours && timeData ? { data: timeData.name, index: timeData.index, most: Number(hours[1]) } : undefined;
    if (deliveryLimit) choices.push(`Nothing goes where ${timeData!.name} is over ${deliveryLimit.most} — the limit you wrote`);
    const recipe = missing.length ? null : ({ sources: sources!.kind.name, customers: customers!.kind.name, demand: demand!, unitCost: unit!.name,
      unitCostIndex: unit!.index, ...(capacity ? { capacity } : {}), ...(openCost ? { openCost } : {}), ...(single ? { singleSource: true } : {}),
      ...(shortage !== undefined ? { shortagePenalty: shortage } : {}), ...(shortageField ? { shortageField } : {}),
      ...(fleetKind && load && price ? { fleet: { kind: fleetKind.name, capacity: load, cost: price,
        ...(available ? { available } : fleetMost !== undefined ? { most: fleetMost } : {}) } } : {}),
      ...(deliveryLimit ? { deliveryLimit } : {}) } satisfies NetworkRecipe);
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
  // Travel times and distances are not who is within reach (benchmark round 3: minutes were read as 0/1).
  const measured = (name: string) => /(^|_)(min|mins|minutes|km|m|metres|meters|time|dist|distance|tt|secs?|hours?|hrs?)($|_)/.test(name)
    && !/within|reach|cover|flag|ok|_01|yes/.test(name);
  const reach = reachData.find((d) => /within|reach|cover|near/.test(d.name) && !measured(d.name)) ?? reachData.find((d) => !measured(d.name));
  const times = reachData.filter((d) => measured(d.name));
  note("Within reach by", reach?.name, "0/1 data over both kinds");
  if (sites && places) need(reach, times.length
    ? `0/1 data over ${sites.kind.name} and ${places.kind.name} saying who is within reach: ${times[0].name} holds travel times or distances, not yes/no -- make the 0/1 data from it with Data values → From the map → within`
    : `0/1 data over ${sites.kind.name} and ${places.kind.name}: who is within reach (Data values → From the map → within)`);
  const cost = field(sites?.kind, /cost|price|rent|capex/);
  const budget = inUnitsOf(amount(text, ["budget", "spend", "afford"]), cost, choices);
  // A field the words name ("weight coverage by incident_count") before one whose name sounds right
  // (benchmark round 3: population was used where incidents were asked for).
  const namedFields = numeric(places?.kind).filter((n) => new RegExp(`\\b${n.replace(/_/g, "[_ ]")}\\b`, "i").test(text));
  const weights = namedFields.length ? namedFields.filter((n) => !/capacit|cost|price/.test(n))
    : numeric(places?.kind).filter((n) => /population|people|vulnerab|risk|demand|weight|households?|elderly/.test(n));
  const coverAll = /\b(every|all|each) (\w+ ){0,2}(is |are |must be |should be )?(covered|served|reached)\b/i.test(text) && budget === undefined;
  note("Cost", cost, "its name");
  note("Budget", budget, "the number you wrote");
  if (weights.length) choices.push(`Worth covering: ${weights.join(" × ")} — their names`);
  if (coverAll) choices.push("Every one covered, at the least cost — you wrote it");
  // Capacity as well as reach: sites with a capacity seat the people of the places they cover
  // (benchmark re-test, October 2026: coverage with capacity was left out of the draft).
  const capacity = /\b(capacit\w*|seats?|beds?|units? per|how many)\b/i.test(text) || field(sites?.kind, /capacity|seats|beds/) ? field(sites?.kind, /capacity|seats|beds|max_units|units/) : undefined;
  const people = numeric(places?.kind).filter((n) => /population|people|demand|calls|patients|households?/.test(n)).slice(0, 1);
  // "Serves at most capacity_units population centres": the capacity counts places, not people
  // (benchmark round 3: it was read as seats for the population).
  const placeWords = places ? [...new Set([...words(places.kind.name), "places", "centres", "centers", "towns", "zones", "districts", "areas", "villages"])] : [];
  const countsPlaces = !!capacity && placeWords.some((w) => new RegExp(`\\b(at most|up to|no more than|serves?|serving|cover)\\b[^.;]{0,40}\\b${w}s?\\b`, "i").test(text))
    && !/\b(seats?|beds?|people|persons|patients)\b/i.test(text);
  const seats = coverAll || !capacity ? undefined : countsPlaces ? { capacity, demand: [] as string[] } : people.length ? { capacity, demand: people } : undefined;
  if (seats) choices.push(seats.demand.length ? `Each open ${sites!.kind.name} serves at most its ${capacity}, of the ${people[0]} it covers — their names`
    : `Each open ${sites!.kind.name} serves at most its ${capacity} ${places!.kind.name}s, each served by one — you wrote it`);
  // "At most 8 bases open", "no more than 5 sites" (benchmark round 5: the limit was typed by hand).
  const siteWords = sites ? [...new Set([...words(sites.kind.name), ...words(sites.kind.name).flatMap(plural), "sites", "bases", "stations", "centres", "centers", "depots"])] : [];
  const maxOpen = sites ? (() => {
    const m = text.match(new RegExp(`\\b(?:at most|no more than|up to|maximum of|max|open)\\s+(\\d+)\\s+(?:new\\s+)?(?:${siteWords.join("|")})\\b`, "i"));
    return m ? Number(m[1]) : undefined;
  })() : undefined;
  if (maxOpen !== undefined) choices.push(`At most ${maxOpen} ${sites!.kind.name}s open — the number you wrote`);
  // "Covered twice", "at least two bases within reach" (benchmark round 5: double coverage was typed by hand).
  const twice = /\b(covered|cover(ed)? (each|every) \w+) twice\b|\bdouble[- ]cover\w*|\bbackup cover\w*/i.test(text) ? 2
    : (() => {
      const m = text.match(new RegExp(`\\bat least (two|three|2|3) (?:open\\s+)?(?:${siteWords.join("|")})\\b`, "i"));
      return m ? ({ two: 2, three: 3 } as Record<string, number>)[m[1].toLowerCase()] ?? Number(m[1]) : undefined;
    })();
  if (twice) choices.push(`Covered means ${twice} open ${sites?.kind.name ?? "site"}s within reach — you wrote it`);
  const recipe = missing.length ? null : ({ sites: sites!.kind.name, places: places!.kind.name, reach: reach!.name, reachIndex: reach!.index,
    ...(cost ? { cost } : {}), ...(budget !== undefined ? { budget } : {}), weights, coverAll, ...(seats ? { seats } : {}),
    ...(maxOpen !== undefined ? { maxOpen } : {}), ...(twice ? { times: twice } : {}) } satisfies CoverageRecipe);
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

/** The words for one problem: its own, else the workspace's Start-page words, which it then takes --
 * a later problem in the workspace starts empty (benchmark round 3: one problem's words were offered
 * to the next). */
const PROBLEM_WORDS_KEY = (problemId: number | string) => `solver_problem_words:problem:${problemId}`;
export function wordsFor(domainId: number | string | null | undefined, problemId: number | string | null | undefined): string {
  if (problemId == null) return keptWords(domainId);
  try {
    const own = localStorage.getItem(PROBLEM_WORDS_KEY(problemId));
    if (own !== null) return own;
    const shared = keptWords(domainId);
    if (shared && domainId != null) {
      localStorage.setItem(PROBLEM_WORDS_KEY(problemId), shared);
      localStorage.removeItem(WORDS_KEY(domainId));
    }
    return shared;
  } catch {
    return keptWords(domainId);
  }
}
export function keepProblemWords(problemId: number | string | null | undefined, text: string): void {
  if (problemId == null) return;
  try {
    localStorage.setItem(PROBLEM_WORDS_KEY(problemId), text);
  } catch {
    /* kept for this page only */
  }
}
