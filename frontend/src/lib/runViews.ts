/**
 * Which view draws a decision, and the layout each view needs (queue R17).
 *
 * The view is chosen from the decision's shape -- how many sets index it,
 * what role each set plays in the domain (time, agent, location...), and
 * whether it is a yes/no choice or an amount -- so a new model is drawn well
 * without anyone configuring it. Every view is also offered by name, and the
 * plain list is always there. Pure functions: the components only draw.
 */

export type ViewKind = "grid" | "heat" | "panels" | "bars" | "line" | "chosen" | "value" | "list";

export type Shape = {
  /** The set each index position names, in order. */
  sets: string[];
  /** binary, integer, continuous or interval. */
  kind: string;
  /** Set -> the domain's role for its entity type (time, agent, location, resource, org...). */
  roles: Record<string, string>;
  /** False for runs recorded before amounts were kept: an amount then has no value to draw. */
  hasAmounts: boolean;
};

export const VIEW_LABELS: Record<ViewKind, string> = {
  grid: "Grid",
  heat: "Heat matrix",
  panels: "Small multiples",
  bars: "Bars",
  line: "Line",
  chosen: "Chosen set",
  value: "Value",
  list: "List",
};

/** The default view first, then the others that fit. */
export function viewsFor(shape: Shape): ViewKind[] {
  const n = shape.sets.length;
  const yesNo = shape.kind === "binary";
  if (shape.kind === "interval") return ["list"];
  if (!yesNo && !shape.hasAmounts) return ["list"];
  if (n === 0) return ["value", "list"];
  if (yesNo) {
    if (n === 1) return ["chosen", "list"];
    return ["grid", "list"];
  }
  if (n === 1) {
    const time = shape.roles[shape.sets[0]] === "time";
    return time ? ["line", "bars", "list"] : ["bars", "line", "list"];
  }
  if (n === 2) return ["heat", "grid", "list"];
  return ["panels", "heat", "grid", "list"];
}

/**
 * Which positions go across, down and inside a grid, by default.
 *
 * A roster (person x day x shift, yes/no) reads best with time across, the
 * slot down and the people inside each cell: the agent set goes inside, the
 * time set across. Otherwise the second set goes across and the first down,
 * and anything left goes inside.
 */
export function defaultAxes(shape: Shape): { rows: number; cols: number; inside: number[] } {
  const n = shape.sets.length;
  const positions = [...Array(n).keys()];
  if (n === 1) return { rows: 0, cols: -1, inside: [] };
  const role = (i: number) => shape.roles[shape.sets[i]];
  const agent = n >= 3 ? positions.find((i) => role(i) === "agent") : undefined;
  const rest = positions.filter((i) => i !== agent);
  const time = rest.find((i) => role(i) === "time");
  const cols = time ?? rest[rest.length - 1];
  const rows = rest.find((i) => i !== cols) ?? positions.find((i) => i !== cols)!;
  const inside = positions.filter((i) => i !== rows && i !== cols);
  return { rows, cols, inside };
}

/** A set's members in order: the dataset's order where known, then any met in the answer. */
export function membersOf(set: string, order: Record<string, string[]>, seen: string[]): string[] {
  const known = order[set] ?? [];
  const extra = [...new Set(seen)].filter((key) => !known.includes(key)).sort();
  return [...known, ...extra];
}

export type GridCell = { inside: string[][]; value: number | null };

/**
 * The grid: rows x columns, each cell holding the tuples' remaining positions
 * (a yes/no answer) or the sum of their amounts.
 */
export function gridOf(
  tuples: { index: string[]; value: number | null }[],
  axes: { rows: number; cols: number; inside: number[] },
): Map<string, GridCell> {
  const cells = new Map<string, GridCell>();
  for (const t of tuples) {
    const key = `${t.index[axes.rows]}\u0001${axes.cols >= 0 ? t.index[axes.cols] : ""}`;
    const cell = cells.get(key) ?? { inside: [], value: null };
    cell.inside.push(axes.inside.map((i) => t.index[i]));
    if (t.value !== null) cell.value = (cell.value ?? 0) + t.value;
    cells.set(key, cell);
  }
  return cells;
}

export const cellKey = (row: string, col: string) => `${row}\u0001${col}`;

/** Shade from 0 to 1 by magnitude, the largest cell darkest; 0 for no value. */
export function shade(value: number | null, largest: number): number {
  if (value === null || largest <= 0) return 0;
  return Math.min(1, Math.abs(value) / largest);
}

const NUMBERS = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 });

/** A number as a planner reads it: whole numbers plain, others to three significant figures. Western
 * digits and grouping whatever the browser's locale, like the rest of the interface (an Arabic
 * locale gave ٤٠ for 40). */
export function formatAmount(value: number): string {
  return NUMBERS.format(Number.isInteger(value) ? value : Number(value.toPrecision(3)));
}
