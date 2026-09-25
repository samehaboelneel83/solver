import { useEntitiesOfTypes, useParameterValues, type Id } from "../api/v1";
import { formatAmount } from "../lib/runViews";

/** Past this many stored cells, the picture shows the first ones and says so. */
export const RANGE_ROWS = 40;

/**
 * An uncertain parameter's values as ranges (queue R17d): each stored cell a dot at its value
 * and a bar to how far it may move -- value x (1 - d) to value x (1 + d) -- and one row for the
 * default every empty cell takes. What a robust solve protects against, drawn.
 */
export default function RangePicture({ parameterId, deviation, name }: { parameterId: Id; deviation: number; name: string }) {
  const values = useParameterValues(parameterId);
  // A partial answer (an older server, a test's stand-in) draws what it has.
  const types = values.data?.index_types?.map((t) => t.id) ?? [];
  const entities = useEntitiesOfTypes(types);
  if (!values.data) return null;
  const keyOf = new Map(entities.items.map((e) => [e.id, e.key]));
  const cells = (values.data.cells ?? [])
    .filter((c) => c.value !== null && c.value !== undefined)
    .map((c) => ({ label: c.entity_ids.map((id) => keyOf.get(id) ?? String(id)).join(", "), value: Number(c.value) }));
  const rows = [
    ...cells.slice(0, RANGE_ROWS),
    { label: "all others (default)", value: Number(values.data.default_value ?? 0) },
  ];
  const reach = (v: number) => [v - Math.abs(v) * deviation, v + Math.abs(v) * deviation] as const;
  const low = Math.min(0, ...rows.map((r) => reach(r.value)[0]));
  const high = Math.max(1e-9, ...rows.map((r) => reach(r.value)[1]));
  const W = 320, left = 96, band = 20;
  const x = (v: number) => left + ((v - low) / (high - low || 1)) * (W - left - 12);
  return (
    <figure className="mt-1">
      <figcaption className="text-xs text-slate-600">
        What a robust solve protects against: each {name} value may be off by up to {Number((deviation * 100).toPrecision(4))}%
        {cells.length > RANGE_ROWS ? ` (the first ${RANGE_ROWS} of ${cells.length} stored cells)` : ""}.
      </figcaption>
      {/* Scales to its column: the Model editor's parameter card is narrower than the drawing. */}
      <svg role="img" aria-label={`${name} as ranges: ${rows.length} rows`} viewBox={`0 0 ${W} ${rows.length * band + 20}`}
           className="h-auto w-full max-w-[320px]">
        {rows.map((r, i) => {
          const [a, b] = reach(r.value);
          const y = 8 + i * band + band / 2;
          return (
            <g key={i}>
              <text x={left - 6} y={y + 4} textAnchor="end" fontSize={12} className="fill-slate-600">{r.label}</text>
              <line x1={x(a)} x2={x(b)} y1={y} y2={y} stroke="#d97706" strokeWidth={4} strokeLinecap="round" strokeOpacity={0.55}>
                <title>{`${r.label}: ${formatAmount(r.value)}, from ${formatAmount(a)} to ${formatAmount(b)}`}</title>
              </line>
              <circle cx={x(r.value)} cy={y} r={3} fill="#1e293b" />
            </g>
          );
        })}
        <text x={left} y={rows.length * band + 18} fontSize={11} className="fill-slate-500">{formatAmount(low)}</text>
        <text x={W - 12} y={rows.length * band + 18} fontSize={11} textAnchor="end" className="fill-slate-500">{formatAmount(high)}</text>
      </svg>
    </figure>
  );
}
