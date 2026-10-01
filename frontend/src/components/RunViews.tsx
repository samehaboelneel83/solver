import { useId, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { NO_BASEMAP, useBasemaps } from "../hooks/useBasemaps";
import { fitView, tileUrl } from "../lib/tiles";
import { getRunPlaces, type Run, type RunPlaces } from "../api/v1";
import {
  cellKey,
  defaultAxes,
  formatAmount,
  ganttBars,
  gridOf,
  mapMarks,
  membersOf,
  rowPosition,
  timelineBars,
  type Bar,
  shade,
  VIEW_LABELS,
  viewsFor,
  type Shape,
  type ViewKind,
} from "../lib/runViews";
import { naturalOrders } from "../lib/naturalOrder";

/** Colours for the members drawn inside a grid's cells (people in a roster): one each, the same on every run. */
const PALETTE = ["#2563eb", "#d97706", "#059669", "#9333ea", "#ca8a04", "#dc2626", "#0891b2", "#64748b"];
function colourOf(key: string): string {
  let h = 0;
  for (const c of key) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

export type Entry = { index: string[]; value: number | null };

/**
 * Every decision of a run, each drawn the way its shape reads (queue R17): a
 * roster as a grid with people inside the cells, amounts as a heat matrix,
 * bars or a line, a yes/no over one set as the set with its chosen members
 * marked -- the plain list one click away. Nothing to configure.
 */
export default function RunViews({ run }: { run: Run }) {
  // An interval is never in `assignments` (its start and end are): it is drawn beside them.
  const names = [...new Set([...Object.keys(run.assignments ?? {}), ...Object.keys(run.intervals ?? {})])];
  // Where the located sets' members stood (queue R17b), once per run; nothing to map is `{}`.
  const places = useQuery({
    queryKey: ["run-places", run.id],
    queryFn: () => getRunPlaces(run.id),
    enabled: names.length > 0 && run.id !== undefined,
    retry: false,
    staleTime: Infinity,
  });
  if (names.length === 0) return null;
  return (
    <div className="space-y-6">
      {names.map((variable) => (
        <DecisionView key={variable} run={run} variable={variable} places={places.data ?? {}} />
      ))}
    </div>
  );
}

function DecisionView({ run, variable, places }: { run: Run; variable: string; places: RunPlaces }) {
  const sets = run.index_sets.variables[variable] ?? [];
  const kind = run.variable_kinds?.[variable] ?? "binary";
  const amounts = run.amounts?.[variable];
  // An interval has no amounts of its own: its start and end decisions carry them (queue R17b).
  const parts = kind === "interval" ? run.intervals?.[variable] : undefined;
  const hasAmounts = parts ? Boolean(parts.start && parts.end && run.amounts) : amounts !== undefined && run.amounts !== null;
  const shape: Shape = { sets, kind, roles: run.set_roles ?? {}, hasAmounts, located: Object.keys(places) };
  const bars: Bar[] = useMemo(() => {
    if (!parts?.start || !parts.end) return [];
    const read = (name: string) => (run.amounts?.[name] ?? []).map((a) => ({ index: a.index, value: Number(a.value) }));
    const present = parts.presence ? (run.assignments?.[parts.presence] ?? []) : null;
    return ganttBars(read(parts.start), read(parts.end), present, rowPosition(shape));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parts, run.amounts, run.assignments]);
  const entries: Entry[] = useMemo(
    () =>
      kind === "interval"
        ? bars.map((b) => ({ index: [b.row, ...b.label], value: b.end - b.start }))
        : kind === "binary" || !amounts
          ? (run.assignments?.[variable] ?? []).map((index) => ({ index, value: null }))
          : amounts.map((a) => ({ index: a.index, value: Number(a.value) })),
    [amounts, bars, kind, run.assignments, variable],
  );
  return (
    <ShapedView
      name={variable}
      shape={shape}
      entries={entries}
      bars={bars}
      order={naturalOrders(run.set_order ?? {})}
      labels={run.labels}
      places={places}
      count={kind === "binary" ? `${entries.length} chosen` : `${entries.length} non-zero`}
    />
  );
}

/**
 * One table of numbers or choices, drawn the way its shape reads -- an answer's decision, or
 * (queue R17b) an input: a parameter's cells, over the same sets. The view is chosen from the
 * shape, every other that fits is one tab away.
 */
export function ShapedView({ name: title, shape, entries, bars = [], order, labels, places, count, empty = "Nothing chosen." }: {
  name: string;
  shape: Shape;
  entries: Entry[];
  bars?: Bar[];
  order: Record<string, string[]>;
  labels: Record<string, Record<string, string>>;
  places: RunPlaces;
  count: string;
  empty?: string;
}) {
  const id = useId();
  const sets = shape.sets;
  const views = viewsFor(shape);
  const [chosenView, setView] = useState<ViewKind | null>(null);
  // The places arrive after the first draw; the default is recomputed until a view is picked.
  const view = chosenView && views.includes(chosenView) ? chosenView : views[0];
  const name = (set: string | undefined, key: string) => (set ? labels[set]?.[key] : undefined) ?? key;
  const members = (position: number) => membersOf(sets[position], order, entries.map((e) => e.index[position]));

  return (
    <section aria-labelledby={`${id}-title`} className="rounded-md border border-slate-200 bg-white">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-3 py-2">
        <h3 id={`${id}-title`} className="text-sm font-semibold text-slate-900">
          <span className="font-mono">{title}</span>
          {sets.length > 0 && <span className="font-normal text-slate-500"> [{sets.join(", ")}]</span>}
          <span className="ml-2 font-normal text-slate-500">{count}</span>
        </h3>
        {views.length > 1 && (
          <div role="tablist" aria-label={`How to draw ${title}`} className="inline-flex overflow-hidden rounded border border-slate-300 text-xs">
            {views.map((v) => (
              <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
                      className={view === v ? "bg-slate-900 px-2 py-1 text-white" : "px-2 py-1 text-slate-600 hover:bg-slate-100"}>
                {VIEW_LABELS[v]}
              </button>
            ))}
          </div>
        )}
      </header>
      <div className="overflow-x-auto p-3">
        {entries.length === 0 ? (
          <p className="text-sm text-slate-500">{empty}</p>
        ) : view === "map" ? (
          <MapView marks={mapMarks(sets, entries, places)} name={name} />
        ) : view === "gantt" ? (
          <GanttView bars={bars} rowSet={sets[rowPosition(shape)]} labelSets={sets.filter((_, i) => i !== rowPosition(shape))} name={name} unit="" />
        ) : view === "timeline" ? (
          <TimelineView shape={shape} entries={entries} members={members} name={name} />
        ) : view === "grid" ? (
          <GridView shape={shape} entries={entries} members={members} name={name} />
        ) : view === "heat" ? (
          <HeatView shape={shape} entries={entries} members={members} name={name} />
        ) : view === "panels" ? (
          <PanelsView shape={shape} entries={entries} members={members} name={name} />
        ) : view === "bars" ? (
          <BarsView sets={sets} entries={entries} members={members(0)} name={name} />
        ) : view === "line" ? (
          <LineView sets={sets} entries={entries} members={members(0)} name={name} />
        ) : view === "chosen" ? (
          <ChosenView set={sets[0]} entries={entries} members={members(0)} name={name} />
        ) : view === "value" ? (
          <p className="text-2xl font-semibold tabular-nums text-slate-900">{formatAmount(entries[0].value ?? 1)}</p>
        ) : (
          <ListView sets={sets} entries={entries} name={name} />
        )}
      </div>
    </section>
  );
}

type Namer = (set: string | undefined, key: string) => string;

/** Rows, columns and what is inside chosen by the reader; the defaults read a roster as a roster. */
function useAxes(shape: Shape) {
  const [axes, setAxes] = useState(() => defaultAxes(shape));
  const n = shape.sets.length;
  const choose = (which: "rows" | "cols", position: number) => {
    const other = which === "rows" ? axes.cols : axes.rows;
    const next = which === "rows" ? { rows: position, cols: other === position ? axes.rows : other } : { rows: other === position ? axes.cols : other, cols: position };
    setAxes({ ...next, inside: [...Array(n).keys()].filter((i) => i !== next.rows && i !== next.cols) });
  };
  return { axes, choose };
}

function AxisPicker({ shape, axes, choose }: { shape: Shape; axes: { rows: number; cols: number }; choose: (w: "rows" | "cols", p: number) => void }) {
  const id = useId();
  if (shape.sets.length < 2) return null;
  const select = (which: "rows" | "cols", label: string) => (
    <label htmlFor={`${id}-${which}`} className="flex items-center gap-1">
      {label}
      <select id={`${id}-${which}`} className="rounded border border-slate-300 px-1 py-0.5" value={which === "rows" ? axes.rows : axes.cols}
              onChange={(event) => choose(which, Number(event.target.value))}>
        {shape.sets.map((set, i) => <option key={`${set}-${i}`} value={i}>{set}{shape.sets.indexOf(set) !== i ? ` (${i + 1})` : ""}</option>)}
      </select>
    </label>
  );
  return (
    <div className="mb-2 flex flex-wrap gap-3 text-xs text-slate-600">
      {select("rows", "Down")}
      {select("cols", "Across")}
    </div>
  );
}

function GridView({ shape, entries, members, name }: { shape: Shape; entries: Entry[]; members: (p: number) => string[]; name: Namer }) {
  const { axes, choose } = useAxes(shape);
  const cells = gridOf(entries, axes);
  const rows = members(axes.rows);
  const cols = axes.cols >= 0 ? members(axes.cols) : [""];
  const insideSets = axes.inside.map((i) => shape.sets[i]);
  // One colour per member in the set's own order, so the first eight people never share one.
  const colours = new Map((axes.inside.length > 0 ? members(axes.inside[0]) : []).map((m, k) => [m, PALETTE[k % PALETTE.length]]));
  return (
    <div>
      <AxisPicker shape={shape} axes={axes} choose={choose} />
      <table className="border-separate border-spacing-1 text-xs">
        <thead>
          <tr>
            <th />
            {cols.map((c) => <th key={c} scope="col" className="px-1 text-left font-medium text-slate-500">{name(shape.sets[axes.cols], c)}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r}>
              <th scope="row" className="whitespace-nowrap pr-2 text-left font-medium text-slate-600">{name(shape.sets[axes.rows], r)}</th>
              {cols.map((c) => {
                const cell = cells.get(cellKey(r, c));
                return (
                  <td key={c} className="min-w-[4.5rem] rounded bg-slate-50 p-1 align-top">
                    {cell && insideSets.length === 0 && <span aria-label="chosen" className="font-semibold text-emerald-700">✓</span>}
                    {cell && insideSets.length > 0 && (
                      <div className="flex flex-wrap gap-0.5">
                        {cell.inside.map((keys) => {
                          const label = keys.map((k, j) => name(insideSets[j], k)).join(" · ");
                          return (
                            <span key={keys.join("\u0001")} className="rounded px-1 py-0.5 text-[11px] font-medium text-white"
                                  style={{ background: colours.get(keys[0]) ?? colourOf(keys.join("\u0001")) }}>{label}</span>
                          );
                        })}
                      </div>
                    )}
                    {cell && insideSets.length > 0 && <div className="mt-0.5 text-right text-[10px] text-slate-400">{cell.inside.length}</div>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HeatTable({ shape, axes, entries, members, name, largest }: {
  shape: Shape; axes: { rows: number; cols: number; inside: number[] }; entries: Entry[]; members: (p: number) => string[]; name: Namer; largest: number;
}) {
  const cells = gridOf(entries, axes);
  const rows = members(axes.rows);
  const cols = members(axes.cols);
  return (
    <table className="border-separate border-spacing-0.5 text-xs tabular-nums">
      <thead>
        <tr>
          <th />
          {cols.map((c) => <th key={c} scope="col" className="px-1 font-medium text-slate-500">{name(shape.sets[axes.cols], c)}</th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r}>
            <th scope="row" className="whitespace-nowrap pr-2 text-left font-medium text-slate-600">{name(shape.sets[axes.rows], r)}</th>
            {cols.map((c) => {
              const value = cells.get(cellKey(r, c))?.value ?? null;
              const s = shade(value, largest);
              return (
                <td key={c} className="min-w-[3rem] rounded px-1 py-1 text-center"
                    style={{ background: value === null ? "rgb(248 250 252)" : `rgba(234, 88, 12, ${0.12 + s * 0.78})`, color: s > 0.55 ? "white" : "rgb(15 23 42)" }}>
                  {value === null ? "" : formatAmount(value)}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HeatView({ shape, entries, members, name }: { shape: Shape; entries: Entry[]; members: (p: number) => string[]; name: Namer }) {
  const { axes, choose } = useAxes(shape);
  const largest = Math.max(0, ...[...gridOf(entries, axes).values()].map((c) => Math.abs(c.value ?? 0)));
  return (
    <div>
      <AxisPicker shape={shape} axes={axes} choose={choose} />
      <HeatTable shape={shape} axes={axes} entries={entries} members={members} name={name} largest={largest} />
      {axes.inside.length > 0 && <p className="mt-1 text-xs text-slate-500">Each cell sums over {axes.inside.map((i) => shape.sets[i]).join(", ")}.</p>}
    </div>
  );
}

/** One heat matrix per member of the remaining set, all on one scale. */
function PanelsView({ shape, entries, members, name }: { shape: Shape; entries: Entry[]; members: (p: number) => string[]; name: Namer }) {
  const { axes, choose } = useAxes(shape);
  const panel = axes.inside[0];
  const largest = Math.max(0, ...entries.map((e) => Math.abs(e.value ?? 0)));
  const rest = { ...axes, inside: axes.inside.slice(1) };
  return (
    <div>
      <AxisPicker shape={shape} axes={axes} choose={choose} />
      <div className="flex flex-wrap gap-4">
        {members(panel).map((m) => (
          <figure key={m}>
            <figcaption className="mb-1 text-xs font-semibold text-slate-700">{shape.sets[panel]}: {name(shape.sets[panel], m)}</figcaption>
            <HeatTable shape={shape} axes={rest} entries={entries.filter((e) => e.index[panel] === m)} members={members} name={name} largest={largest} />
          </figure>
        ))}
      </div>
    </div>
  );
}

function BarsView({ sets, entries, members, name }: { sets: string[]; entries: Entry[]; members: string[]; name: Namer }) {
  const value = new Map(entries.map((e) => [e.index[0], e.value ?? 0]));
  const largest = Math.max(1e-9, ...[...value.values()].map(Math.abs));
  return (
    <ul className="space-y-1 text-xs tabular-nums">
      {members.map((m) => {
        const v = value.get(m) ?? 0;
        return (
          <li key={m} className="flex items-center gap-2">
            <span className="w-32 shrink-0 truncate text-slate-600">{name(sets[0], m)}</span>
            <span className="h-3 rounded bg-blue-600" style={{ width: `${(Math.abs(v) / largest) * 60}%`, minWidth: v ? 2 : 0 }} />
            <span className="text-slate-700">{formatAmount(v)}</span>
          </li>
        );
      })}
    </ul>
  );
}

function LineView({ sets, entries, members, name }: { sets: string[]; entries: Entry[]; members: string[]; name: Namer }) {
  const value = new Map(entries.map((e) => [e.index[0], e.value ?? 0]));
  const points = members.map((m) => value.get(m) ?? 0);
  const W = Math.max(240, members.length * 36), H = 140, left = 44, bottom = 22;
  const top = Math.max(1e-9, ...points), low = Math.min(0, ...points);
  const x = (i: number) => left + (members.length === 1 ? 0 : (i * (W - left - 8)) / (members.length - 1));
  const y = (v: number) => 8 + (1 - (v - low) / (top - low || 1)) * (H - bottom - 8);
  const every = Math.ceil(members.length / 12);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} role="img" aria-label={`${sets[0]} over time`} className="text-slate-500">
      {[low, top].map((v) => (
        <g key={v}>
          <line x1={left} x2={W - 8} y1={y(v)} y2={y(v)} stroke="rgb(226 232 240)" />
          <text x={left - 4} y={y(v) + 3} textAnchor="end" fontSize="10" fill="currentColor">{formatAmount(v)}</text>
        </g>
      ))}
      <polyline points={points.map((v, i) => `${x(i)},${y(v)}`).join(" ")} fill="none" stroke="rgb(var(--accent-600))" strokeWidth="2" />
      {points.map((v, i) => <circle key={members[i]} cx={x(i)} cy={y(v)} r="2.5" fill="rgb(var(--accent-600))"><title>{`${name(sets[0], members[i])}: ${formatAmount(v)}`}</title></circle>)}
      {members.map((m, i) => i % every === 0 && (
        <text key={m} x={x(i)} y={H - 6} textAnchor="middle" fontSize="10" fill="currentColor">{name(sets[0], m)}</text>
      ))}
    </svg>
  );
}

function ChosenView({ set, entries, members, name }: { set: string; entries: Entry[]; members: string[]; name: Namer }) {
  const chosen = new Set(entries.map((e) => e.index[0]));
  return (
    <ul className="flex flex-wrap gap-1.5 text-xs">
      {members.map((m) => (
        <li key={m} className={chosen.has(m) ? "rounded bg-emerald-600 px-2 py-1 font-medium text-white" : "rounded border border-slate-200 px-2 py-1 text-slate-400"}
            aria-label={chosen.has(m) ? `${name(set, m)} (chosen)` : name(set, m)}>
          {name(set, m)}
        </li>
      ))}
    </ul>
  );
}

function ListView({ sets, entries, name }: { sets: string[]; entries: Entry[]; name: Namer }) {
  return (
    <ul className="flex flex-wrap gap-2">
      {entries.map((e) => (
        <li key={e.index.join("\u0001")} className="rounded border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-700">
          {e.index.map((k, i) => name(sets[i], k)).join(" · ")}
          {e.value !== null && <span className="ml-1 font-semibold tabular-nums">= {formatAmount(e.value)}</span>}
        </li>
      ))}
    </ul>
  );
}

/**
 * A Gantt chart (queue R17b): one row per member of the row set, each bar from its start to its
 * end on a shared axis, labelled with the rest of its index. Plain SVG.
 */
export function GanttView({ bars, rowSet, labelSets, name, unit, slots }: {
  bars: Bar[]; rowSet: string | undefined; labelSets: string[]; name: Namer; unit: string;
  /** For a timeline: the time set's members, one per unit of the axis. */
  slots?: { set: string; members: string[] };
}) {
  const rows = [...new Set(bars.map((b) => b.row))];
  const low = slots ? 0 : Math.min(0, ...bars.map((b) => b.start));
  const high = slots ? slots.members.length : Math.max(1, ...bars.map((b) => b.end));
  const left = 120, right = 16, band = 26, top = 22;
  const width = Math.max(480, left + right + (slots ? slots.members.length * 56 : 480));
  const x = (v: number) => left + ((v - low) / (high - low || 1)) * (width - left - right);
  const ticks = slots
    ? slots.members.map((m, i) => ({ at: i + 0.5, text: name(slots.set, m) }))
    : niceTicks(low, high).map((t) => ({ at: t, text: formatAmount(t) }));
  return (
    <svg role="img" aria-label={`Gantt chart of ${bars.length} bars over ${rows.length} rows`} width={width}
         height={top + rows.length * band + 8} className="text-slate-500">
      {ticks.map((t) => (
        <g key={`${t.at}`}>
          <line x1={x(t.at)} x2={x(t.at)} y1={top - 4} y2={top + rows.length * band} stroke="currentColor" strokeOpacity={0.15} />
          <text x={x(t.at)} y={12} textAnchor="middle" fontSize={10} fill="currentColor">{t.text}{unit}</text>
        </g>
      ))}
      {rows.map((row, r) => (
        <g key={row}>
          <text x={left - 8} y={top + r * band + band / 2 + 4} textAnchor="end" fontSize={11} className="fill-slate-700">
            {name(rowSet, row)}
          </text>
          {bars.filter((b) => b.row === row).map((b, k) => {
            const label = b.label.map((key, j) => name(labelSets[j], key)).join(" · ");
            const w = Math.max(2, x(b.end) - x(b.start));
            return (
              <g key={k}>
                <rect x={x(b.start)} y={top + r * band + 4} width={w} height={band - 8} rx={3}
                      fill={colourOf(b.label.join("\u0001") || row)}>
                  <title>{`${name(rowSet, row)}${label ? ` · ${label}` : ""}: ${slots ? `${slots.members[b.start]} to ${slots.members[b.end - 1]}` : `${formatAmount(b.start)} to ${formatAmount(b.end)}`}`}</title>
                </rect>
                {w > 36 && label && (
                  <text x={x(b.start) + 4} y={top + r * band + band / 2 + 4} fontSize={10} fill="white">{label}</text>
                )}
              </g>
            );
          })}
        </g>
      ))}
    </svg>
  );
}

/** A yes/no answer over a time set as a timeline: the chosen slots of each row member, runs of
 * consecutive slots as one bar. */
function TimelineView({ shape, entries, members, name }: { shape: Shape; entries: Entry[]; members: (p: number) => string[]; name: Namer }) {
  const time = shape.sets.findIndex((s) => shape.roles[s] === "time");
  const row = rowPosition(shape) === time ? (time === 0 ? 1 : 0) : rowPosition(shape);
  const slots = members(time);
  const bars = timelineBars(entries.map((e) => e.index), time, row, slots);
  const labelSets = shape.sets.filter((_, i) => i !== time && i !== row);
  return <GanttView bars={bars} rowSet={shape.sets[row]} labelSets={labelSets} name={name} unit="" slots={{ set: shape.sets[time], members: slots }} />;
}

/** About six round ticks between low and high. */
function niceTicks(low: number, high: number): number[] {
  const span = high - low || 1;
  const raw = span / 6;
  const step = [1, 2, 5, 10].map((m) => m * 10 ** Math.floor(Math.log10(raw))).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let t = Math.ceil(low / step) * step; t <= high + 1e-9; t += step) out.push(Number(t.toPrecision(12)));
  return out;
}

/**
 * An answer on a map (queue R17b): every placed member as a point, the chosen ones filled and
 * sized by amount; a line for each tuple between two located sets -- a site serving a customer,
 * a flow, a route's leg -- coloured by what the rest of its index says (the vehicle). Plain SVG,
 * a degree of longitude shortened by the cosine of the latitude.
 */
export function MapView({ marks, name }: { marks: ReturnType<typeof mapMarks>; name: Namer }) {
  // The domain's basemaps (spatial.tiles_index), the same choice the districting map offers.
  const { basemaps, chosen: basemap, choose } = useBasemaps();
  const all = [...marks.points.map((p) => p.at), ...marks.lines.flatMap((l) => [l.from, l.to])];
  if (all.length === 0) return <p className="text-sm text-slate-500">Nothing here has a place to draw.</p>;
  const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const degrees = Math.abs(minY) <= 90 && Math.abs(maxY) <= 90 && Math.abs(minX) <= 180 && Math.abs(maxX) <= 180;
  const squash = degrees ? Math.cos((((minY + maxY) / 2) * Math.PI) / 180) : 1;
  const W = 640, H = 420, pad = 24;
  const spanX = Math.max((maxX - minX) * squash, 1e-9), spanY = Math.max(maxY - minY, 1e-9);
  const k = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
  // Over a basemap the frame is Web Mercator, so the marks sit on the imagery; else a plain frame.
  const view = basemap && degrees
    ? fitView({ west: minX - 1e-4, south: minY - 1e-4, east: maxX + 1e-4, north: maxY + 1e-4 }, W - 2 * pad, H - 2 * pad, basemap)
    : null;
  const at = (p: [number, number]): [number, number] => {
    if (view) {
      const [x, y] = view.project(p[0], p[1]);
      return [x + pad, y + pad];
    }
    return [
      pad + (p[0] - minX) * squash * k + (W - 2 * pad - spanX * k) / 2,
      H - pad - (p[1] - minY) * k - (H - 2 * pad - spanY * k) / 2,
    ];
  };
  const biggest = Math.max(1, ...marks.lines.map((l) => Math.abs(l.value ?? 1)), ...marks.points.map((p) => Math.abs(p.value ?? 1)));
  const chosen = marks.points.filter((p) => p.chosen).length;
  // Each located set its own colour, so a site and the customers it serves read apart.
  const setsDrawn = [...new Set(marks.points.map((p) => p.set))];
  const SET_FILL = [["#059669", "#065f46"], ["#d97706", "#92400e"], ["#7c3aed", "#5b21b6"]];
  const fillOf = (set: string) => SET_FILL[setsDrawn.indexOf(set) % SET_FILL.length];
  return (
    <figure>
    {basemaps.length > 0 && degrees && (
      <label className="mb-1 flex items-center gap-2 text-xs text-slate-600">
        Background
        <select className="rounded border border-slate-300 px-1 py-0.5 text-xs" value={basemap?.id ?? NO_BASEMAP}
                onChange={(event) => choose(event.target.value)}>
          <option value={NO_BASEMAP}>none</option>
          {basemaps.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
      </label>
    )}
    {setsDrawn.length > 1 && (
      <figcaption className="mb-1 flex gap-3 text-xs text-slate-600">
        {setsDrawn.map((set) => (
          <span key={set} className="inline-flex items-center gap-1">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: fillOf(set)[0] }} />
            {set}
          </span>
        ))}
      </figcaption>
    )}
    <svg role="img" aria-label={`Map of ${chosen} chosen of ${marks.points.length} places and ${marks.lines.length} lines`}
         width={W} height={H} className="rounded bg-slate-50">
      {view && basemap && view.tiles.map((tile) => (
        <image key={`${tile.z}/${tile.x}/${tile.y}/${tile.left}`} href={tileUrl(basemap.url, tile)} x={tile.left + pad} y={tile.top + pad}
               width={tile.size + 0.5} height={tile.size + 0.5} preserveAspectRatio="none" />
      ))}
      {marks.lines.map((l, i) => {
        const [x1, y1] = at(l.from), [x2, y2] = at(l.to);
        return (
          <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={l.group ? colourOf(l.group) : "#2563eb"} strokeOpacity={0.75}
                strokeWidth={l.value === null ? 1.5 : 1 + (4 * Math.abs(l.value)) / biggest}>
            <title>{`${l.label}${l.group ? ` (${l.group})` : ""}${l.value === null ? "" : `: ${formatAmount(l.value)}`}`}</title>
          </line>
        );
      })}
      {marks.points.map((p) => {
        const [x, y] = at(p.at);
        const r = p.chosen ? 4 + (p.value === null ? 2 : (5 * Math.abs(p.value)) / biggest) : 3;
        return (
          <circle key={`${p.set}-${p.key}`} cx={x} cy={y} r={r} fill={p.chosen ? fillOf(p.set)[0] : "white"}
                  stroke={p.chosen ? fillOf(p.set)[1] : "#94a3b8"} strokeWidth={1.2}>
            <title>{`${name(p.set, p.key)}${p.chosen ? " (chosen)" : ""}${p.value === null ? "" : `: ${formatAmount(p.value)}`}`}</title>
          </circle>
        );
      })}
    </svg>
    </figure>
  );
}
