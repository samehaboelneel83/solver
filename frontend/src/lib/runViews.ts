/**
 * Which view draws a decision, and the layout each view needs (queue R17).
 *
 * The view is chosen from the decision's shape -- how many sets index it,
 * what role each set plays in the domain (time, agent, location...), and
 * whether it is a yes/no choice or an amount -- so a new model is drawn well
 * without anyone configuring it. Every view is also offered by name, and the
 * plain list is always there. Pure functions: the components only draw.
 */

export type ViewKind = "grid" | "heat" | "panels" | "bars" | "line" | "chosen" | "value" | "list" | "gantt" | "timeline";

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
  gantt: "Gantt",
  timeline: "Timeline",
};

/** The default view first, then the others that fit. */
export function viewsFor(shape: Shape): ViewKind[] {
  const n = shape.sets.length;
  const yesNo = shape.kind === "binary";
  // An interval is drawn from its start and end amounts (queue R17b).
  if (shape.kind === "interval") return shape.hasAmounts ? ["gantt", "list"] : ["list"];
  if (!yesNo && !shape.hasAmounts) return ["list"];
  if (n === 0) return ["value", "list"];
  if (yesNo) {
    if (n === 1) return ["chosen", "list"];
    // Over a time set, the same answer reads as bars through time: who works which days.
    const overTime = shape.sets.some((s) => shape.roles[s] === "time");
    return overTime ? ["grid", "timeline", "list"] : ["grid", "list"];
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

/** The index position a Gantt or timeline draws one row per member of: the person, machine
 * or place (agent, resource, location), else the first position that is not time. */
export function rowPosition(shape: Shape): number {
  const role = (i: number) => shape.roles[shape.sets[i]];
  const positions = [...shape.sets.keys()];
  return (
    positions.find((i) => ["agent", "resource", "location"].includes(role(i))) ??
    positions.find((i) => role(i) !== "time") ??
    0
  );
}

export type Bar = { row: string; label: string[]; start: number; end: number };

/**
 * An interval decision's bars: each instance from its start to its end amount (an amount
 * the answer does not list is 0), only the present ones when it is optional.
 */
export function ganttBars(
  starts: { index: string[]; value: number }[],
  ends: { index: string[]; value: number }[],
  present: string[][] | null,
  row: number,
): Bar[] {
  const key = (index: string[]) => index.join("\u0001");
  const at = new Map<string, { index: string[]; start: number; end: number }>();
  for (const s of starts) at.set(key(s.index), { index: s.index, start: s.value, end: 0 });
  for (const e of ends) at.set(key(e.index), { index: e.index, start: at.get(key(e.index))?.start ?? 0, end: e.value });
  if (present) for (const p of present) if (!at.has(key(p))) at.set(key(p), { index: p, start: 0, end: 0 });
  const kept = present ? new Set(present.map(key)) : null;
  return [...at.values()]
    .filter((b) => (kept ? kept.has(key(b.index)) : true) && b.end >= b.start)
    .map((b) => ({ row: b.index[row] ?? "", label: b.index.filter((_, i) => i !== row), start: b.start, end: b.end }))
    .sort((a, b) => a.row.localeCompare(b.row) || a.start - b.start);
}

/**
 * A yes/no answer over a time set as bars: each row member's chosen time slots, the
 * consecutive ones (in the set's own order) merged into one bar per run of days, per value
 * of the remaining positions. `start`/`end` are slot positions, end exclusive.
 */
export function timelineBars(tuples: string[][], time: number, row: number, slots: string[]): Bar[] {
  const where = new Map(slots.map((s, i) => [s, i]));
  const groups = new Map<string, { row: string; label: string[]; at: number[] }>();
  for (const t of tuples) {
    const label = t.filter((_, i) => i !== time && i !== row);
    const k = `${t[row]}\u0001${label.join("\u0001")}`;
    const g = groups.get(k) ?? { row: t[row], label, at: [] };
    const i = where.get(t[time]);
    if (i !== undefined) g.at.push(i);
    groups.set(k, g);
  }
  const bars: Bar[] = [];
  for (const g of groups.values()) {
    const at = [...new Set(g.at)].sort((a, b) => a - b);
    let from = 0;
    for (let i = 1; i <= at.length; i += 1) {
      if (i === at.length || at[i] !== at[i - 1] + 1) {
        if (at.length) bars.push({ row: g.row, label: g.label, start: at[from], end: at[i - 1] + 1 });
        from = i;
      }
    }
  }
  return bars.sort((a, b) => a.row.localeCompare(b.row) || a.start - b.start);
}
