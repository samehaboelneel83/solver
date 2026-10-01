/**
 * The ready examples (templates) in plain words, for "Start a problem"
 * (simplification plan, phase 3). Keyed by the template's name; one not
 * listed here is shown by its name alone.
 */
export type ExampleWords = { title: string; says: string };

export const EXAMPLES: Record<string, ExampleWords> = {
  weekly_rota: {
    title: "Weekly staff rota",
    says: "Put people on shifts across a week, covering what each shift needs without anyone working too much.",
  },
  feed_blend: {
    title: "Cheapest feed blend",
    says: "Mix 100 kg of feed from three ingredients at the lowest cost, with enough protein and not too much fibre.",
  },
  load_balance: {
    title: "Share work evenly",
    says: "Split 120 hours of work across four people as evenly as each one's capacity allows.",
  },
  workshop: {
    title: "Workshop schedule",
    says: "Order three jobs through cutting and then welding so that everything is finished as early as possible.",
  },
  region_partitioning: {
    title: "Split an area into zones",
    says: "Cut a map into four connected zones with balanced populations, each as compact as it can be.",
  },
  facility_coverage: {
    title: "Where to open sites",
    says: "Choose which sites to open and who each one serves, so every customer is in reach at the least cost.",
  },
  emergency_coverage: {
    title: "Cover places at risk",
    says: "Choose where to keep response units so places at risk are within reach on the map, the critical ones twice, most risk first and then the least cost.",
  },
  cairo_university_lectures: {
    title: "Lecture timetable",
    says: "Put university sections into days, times and rooms with no clashes, keeping to room sizes and preferring mornings.",
  },
};

export function exampleWords(name: string): ExampleWords {
  return EXAMPLES[name] ?? { title: name.replace(/_/g, " "), says: "" };
}
