/**
 * "Describe it in words" (improvement plan 5.6): from a person's own description of their problem,
 * the closest ready examples and the tools their words call for -- offline, by words that signal a
 * kind of model, so it works on an install with no outside service, and every suggestion says why.
 * It never builds or publishes anything: it points at where to start.
 */
export type Suggestion = { kind: "example" | "tool"; key: string; title: string; why: string; where: string; score: number };

type Signal = { words: RegExp; key: string; title: string; where: string; kind: "example" | "tool" };

const SIGNALS: Signal[] = [
  { kind: "example", key: "heatwave_cooling", title: "Cooling centres in a heatwave", where: "Start a problem → From a ready example",
    words: /\b(heat\w*|cool\w*|shelter\w*|seat\w*|vulnerab\w*|elderly|older|over-?65s?|outage\w*|generator\w*|power cut\w*)\b/gi },
  { kind: "example", key: "emergency_coverage", title: "Cover places at risk", where: "Start a problem → From a ready example",
    words: /\b(risk|emergenc\w*|respon\w*|ambulance\w*|fire|flood\w*|hotspot\w*|backup|critical|incident\w*)\b/gi },
  { kind: "example", key: "facility_coverage", title: "Where to open sites", where: "Start a problem → From a ready example",
    words: /\b(open|site|sites|depot|depots|warehouse|yard|yards|clinic|station|stations|facilit\w*|locat\w*|pre-?position\w*|place|placing)\b/gi },
  { kind: "example", key: "weekly_rota", title: "Weekly staff rota", where: "Start a problem → From a ready example",
    words: /\b(shift|shifts|roster\w*|rota|staff\w*|crew|crews|nurse\w*|operator\w*|driver\w*|employee\w*|workforce)\b/gi },
  { kind: "example", key: "feed_blend", title: "Cheapest feed blend", where: "Start a problem → From a ready example",
    words: /\b(blend\w*|mix|mixture|recipe|ingredient\w*|diet|nutrient\w*|feed)\b/gi },
  { kind: "example", key: "region_partitioning", title: "Split an area into zones", where: "Start a problem → From a ready example",
    words: /\b(zone|zones|territor\w*|district\w*|partition\w*|split|region\w*|compact|contiguous)\b/gi },
  { kind: "example", key: "workshop", title: "Workshop schedule", where: "Start a problem → From a ready example",
    words: /\b(job|jobs|machine\w*|sequence|order|makespan|finish|deadline\w*|schedul\w*)\b/gi },
  { kind: "example", key: "load_balance", title: "Share work evenly", where: "Start a problem → From a ready example",
    words: /\b(even\w*|balanc\w*|fair\w*|share|workload)\b/gi },
  { kind: "example", key: "cairo_university_lectures", title: "Lecture timetable", where: "Start a problem → From a ready example",
    words: /\b(timetable|lecture\w*|class|classes|room|rooms|course\w*|section\w*|teacher\w*|instructor\w*)\b/gi },
  { kind: "tool", key: "map_layers", title: "Bring your places in from a map file", where: "Map data → Import, then Use in models",
    words: /\b(map|gis|geojson|shapefile|dxf|cad|kml|coordinates?|lat\w*|lon\w*|polygon\w*|layer\w*)\b/gi },
  { kind: "tool", key: "within", title: "Who is within reach (km or minutes)", where: "Data values → From the map → within",
    words: /\b(within|reach|minutes?|drive|driving|travel|cover\w*|response time|nearby)\b/gi },
  { kind: "tool", key: "distance", title: "Distances or travel times between places", where: "Data values → From the map → distance",
    words: /\b(distance\w*|km|kilomet\w*|metres?|meters?|nearest|closest|route\w*|road\w*)\b/gi },
  { kind: "tool", key: "inside", title: "Which area each place is in", where: "Data values → From the map → inside",
    words: /\b(inside|in which|belongs?|district\w*|zone\w*|area\w*|neighbou?rhood\w*)\b/gi },
  { kind: "tool", key: "rest", title: "Rest between shifts, no overlaps", where: "Data values → From times, then the rule shape \"Nobody takes two slots that are too close\"",
    words: /\b(rest|overlap\w*|back-to-back|consecutive|between shifts|hours? off)\b/gi },
  { kind: "tool", key: "capacity", title: "Capacity only when a site is chosen", where: "Model → Start a rule from a shape → at most its capacity",
    words: /\b(capacit\w*|max(imum)?|at most|limit\w*|size)\b/gi },
  { kind: "tool", key: "goals_in_order", title: "Goals in order (first this, then that)", where: "Model → What to make best → this order",
    words: /\b(then|first|priorit\w*|most important|before cost)\b/gi },
  { kind: "tool", key: "futures", title: "Plan for several forecasts", where: "Model → a parameter's values are → named futures",
    words: /\b(forecast\w*|uncertain\w*|weather|rain\w*|demand may|scenario\w*|what if|worst case)\b/gi },
];

/** The examples and tools a description calls for, best first, each with the words that called it. */
export function suggest(description: string, available: string[] = []): Suggestion[] {
  const text = description.toLowerCase();
  if (text.trim().length < 12) return [];
  const out: Suggestion[] = [];
  for (const signal of SIGNALS) {
    if (signal.kind === "example" && available.length && !available.includes(signal.key)) continue;
    const found = [...new Set((text.match(signal.words) ?? []).map((w) => w.toLowerCase()))];
    if (!found.length) continue;
    out.push({ kind: signal.kind, key: signal.key, title: signal.title, where: signal.where, score: found.length,
               why: `you wrote ${found.slice(0, 4).map((w) => `“${w}”`).join(", ")}` });
  }
  const examples = out.filter((s) => s.kind === "example").sort((a, b) => b.score - a.score).slice(0, 2);
  const tools = out.filter((s) => s.kind === "tool").sort((a, b) => b.score - a.score);
  return [...examples, ...tools];
}
