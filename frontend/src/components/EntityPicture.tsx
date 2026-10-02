import { useEntities, type EntityType } from "../api/v1";
import { formatAmount } from "../lib/runViews";
import { MapView } from "./RunViews";
import { binsOf } from "./SpreadView";

type Point = [number, number];

/** Where a stored shape stands: a point as given, a polygon at the middle of its outer ring. */
export function placeOf(value: unknown): Point | null {
  const shape = value as { type?: string; coordinates?: unknown } | null;
  if (!shape || typeof shape !== "object") return null;
  if (shape.type === "Point" && Array.isArray(shape.coordinates)) return shape.coordinates.slice(0, 2) as Point;
  if (shape.type === "LineString" && Array.isArray(shape.coordinates) && shape.coordinates.length) {
    // A road or a canal stands at its middle point.
    return (shape.coordinates as Point[])[Math.floor((shape.coordinates.length - 1) / 2)].slice(0, 2) as Point;
  }
  const ring =
    shape.type === "Polygon" ? (shape.coordinates as Point[][])?.[0]
    : shape.type === "MultiPolygon" ? (shape.coordinates as Point[][][])?.[0]?.[0]
    : null;
  if (!ring?.length) return null;
  const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
  return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
}

/**
 * A type's entities as a picture (queue R17b's input views): how each number attribute spreads
 * across them, and -- when they have a place -- where they are. Read from the first 500.
 */
export default function EntityPicture({ type }: { type: EntityType }) {
  const list = useEntities(type.id, { limit: 500 });
  const items = list.data?.items ?? [];
  if (items.length === 0) return null;
  const numbers = type.attributes.filter((a) => a.data_type === "integer" || a.data_type === "number");
  const shapes = type.attributes.filter((a) => a.data_type === "geometry");
  // A time set with dates (queue R17c): its members on a calendar.
  const dated = type.role === "time" ? type.attributes.find((a) => a.data_type === "date") : undefined;
  const days = dated
    ? items.flatMap((e) => {
        const d = e.attrs?.[dated.name];
        return typeof d === "string" && /^\d{4}-\d{2}-\d{2}$/.test(d) ? [{ date: d, key: e.key, label: e.label ?? e.key }] : [];
      })
    : [];
  const points = shapes.length
    ? items.flatMap((e) => {
        const at = placeOf(e.attrs?.[shapes[0].name]);
        return at ? [{ set: type.name, key: e.key, at, chosen: true, value: null }] : [];
      })
    : [];
  if (numbers.length === 0 && points.length === 0 && days.length === 0) return null;
  return (
    <section aria-label={`${type.name} at a glance`} className="mt-6 rounded-md border border-slate-200 bg-white p-3">
      <h3 className="mb-2 text-sm font-semibold text-slate-900">
        {type.name} at a glance
        {list.data && list.data.total > items.length && (
          <span className="ml-2 font-normal text-slate-500">(the first {items.length} of {list.data.total})</span>
        )}
      </h3>
      <div className="flex flex-wrap gap-4">
        {numbers.map((a) => {
          const values = items.map((e) => e.attrs?.[a.name]).filter((v): v is number => typeof v === "number");
          return <Histogram key={a.name} name={a.name} unit={a.unit} values={values} of={items.length} />;
        })}
      </div>
      {days.length > 0 && <CalendarView days={days} by={dated!.name} />}
      {points.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 text-xs text-slate-600">Where they are ({points.length} placed, by {shapes[0].name})</p>
          <MapView marks={{ points, lines: [] }} name={(_, key) => items.find((e) => e.key === key)?.label ?? key} />
        </div>
      )}
    </section>
  );
}

function Histogram({ name, unit, values, of }: { name: string; unit: string | null; values: number[]; of: number }) {
  const bins = binsOf(values, 10);
  const W = 220, H = 90, bottom = 16;
  const tallest = Math.max(1, ...bins.map((b) => b.n));
  const w = bins.length ? W / bins.length : W;
  const low = bins[0]?.from, high = bins[bins.length - 1]?.to;
  return (
    <figure className="w-[220px]">
      <figcaption className="mb-1 text-xs text-slate-700">
        <span className="font-mono">{name}</span>
        {unit ? ` (${unit})` : ""}
        <span className="text-slate-500"> · {values.length} of {of} set</span>
      </figcaption>
      {values.length === 0 ? (
        <p className="text-xs text-slate-500">No values yet.</p>
      ) : (
        <svg role="img" aria-label={`${name} spread over ${values.length} entities`} width={W} height={H}>
          {bins.map((b, i) => {
            const h = ((H - bottom) * b.n) / tallest;
            return (
              <rect key={i} x={i * w + 1} y={H - bottom - h} width={Math.max(1, w - 2)} height={h} fill="#64748b">
                <title>{`${b.n}: ${formatAmount(b.from)} to ${formatAmount(b.to)}`}</title>
              </rect>
            );
          })}
          <text x={0} y={H - 3} fontSize={10} className="fill-slate-500">{formatAmount(low)}</text>
          <text x={W} y={H - 3} fontSize={10} textAnchor="end" className="fill-slate-500">{formatAmount(high)}</text>
        </svg>
      )}
    </figure>
  );
}

/** Each month the dates fall in, Monday first, the dated members marked with their key. */
export function CalendarView({ days, by }: { days: { date: string; key: string; label: string }[]; by: string }) {
  const onDate = new Map<string, { key: string; label: string }[]>();
  for (const d of days) onDate.set(d.date, [...(onDate.get(d.date) ?? []), d]);
  const months = [...new Set(days.map((d) => d.date.slice(0, 7)))].sort().slice(0, 12);
  return (
    <div className="mt-3">
      <p className="mb-1 text-xs text-slate-600">On the calendar ({days.length} dated, by {by})</p>
      <div className="flex flex-wrap gap-4">
        {months.map((month) => {
          const [y, m] = month.split("-").map(Number);
          const first = new Date(Date.UTC(y, m - 1, 1));
          const length = new Date(Date.UTC(y, m, 0)).getUTCDate();
          const lead = (first.getUTCDay() + 6) % 7;
          const cells = [...Array(lead).fill(null), ...Array.from({ length }, (_, i) => i + 1)];
          return (
            <table key={month} aria-label={`Calendar ${month}`} className="text-center text-[11px]">
              <caption className="text-left text-xs font-medium text-slate-700">
                {first.toLocaleString("en-US", { month: "long", year: "numeric", timeZone: "UTC" })}
              </caption>
              <thead>
                <tr>{["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <th key={i} scope="col" className="w-7 font-normal text-slate-400">{d}</th>)}</tr>
              </thead>
              <tbody>
                {Array.from({ length: Math.ceil(cells.length / 7) }, (_, w) => (
                  <tr key={w}>
                    {cells.slice(w * 7, w * 7 + 7).map((day, i) => {
                      const date = day ? `${month}-${String(day).padStart(2, "0")}` : "";
                      const here = day ? onDate.get(date) : undefined;
                      return (
                        <td key={i} className={here ? "rounded bg-emerald-600 font-semibold text-white" : "text-slate-500"}
                            title={here ? here.map((h) => h.label).join(", ") : undefined}>
                          {day ?? ""}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          );
        })}
      </div>
    </div>
  );
}
