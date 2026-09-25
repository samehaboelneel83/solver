import { formatAmount } from "../lib/runViews";

/** Bins for a spread: `count` equal widths from the least to the most (one bin when all are equal). */
export function binsOf(values: number[], count = 12): { from: number; to: number; n: number }[] {
  if (values.length === 0) return [];
  const low = Math.min(...values);
  const high = Math.max(...values);
  if (high === low) return [{ from: low, to: high, n: values.length }];
  const width = (high - low) / count;
  const bins = Array.from({ length: count }, (_, i) => ({ from: low + i * width, to: low + (i + 1) * width, n: 0 }));
  for (const v of values) bins[Math.min(count - 1, Math.floor((v - low) / width))].n += 1;
  return bins;
}

/**
 * What a stochastic plan costs across the fresh futures it was costed on (queue R17b): a
 * histogram, the mean as a line and its 95% interval as a band -- how wide the spread is says
 * more than the average alone.
 */
export default function SpreadView({ costs, mean, ci95, unmet }: { costs: number[]; mean: number; ci95: number; unmet: number }) {
  const bins = binsOf(costs);
  if (bins.length === 0) return null;
  const W = 560, H = 160, left = 8, right = 8, top = 10, bottom = 28;
  const low = bins[0].from, high = bins[bins.length - 1].to;
  const span = high - low || 1;
  const x = (v: number) => left + ((v - low) / span) * (W - left - right);
  const tallest = Math.max(...bins.map((b) => b.n));
  const barW = bins.length === 1 ? 40 : (W - left - right) / bins.length;
  return (
    <figure className="mt-3">
      <figcaption className="mb-1 text-xs text-slate-600">
        What the plan costs on each of {costs.length} fresh futures{unmet > 0 ? ` (${unmet} it cannot meet are not drawn)` : ""}: the
        line is the mean, the band its 95% interval.
      </figcaption>
      <svg role="img" aria-label={`Spread of ${costs.length} futures from ${formatAmount(low)} to ${formatAmount(high)}`} width={W} height={H}>
        <rect x={x(mean - ci95)} y={top} width={Math.max(1, x(mean + ci95) - x(mean - ci95))} height={H - top - bottom} fill="#2563eb" fillOpacity={0.12} />
        {bins.map((b, i) => {
          const h = ((H - top - bottom) * b.n) / tallest;
          const bx = bins.length === 1 ? x(b.from) - barW / 2 : x(b.from);
          return (
            <rect key={i} x={bx + 1} y={H - bottom - h} width={Math.max(1, barW - 2)} height={h} fill="#64748b">
              <title>{`${b.n} ${b.n === 1 ? "future" : "futures"}: ${formatAmount(b.from)} to ${formatAmount(b.to)}`}</title>
            </rect>
          );
        })}
        <line x1={x(mean)} x2={x(mean)} y1={top} y2={H - bottom} stroke="#2563eb" strokeWidth={2} />
        <text x={left} y={H - 8} fontSize={10} className="fill-slate-500">{formatAmount(low)}</text>
        <text x={W - right} y={H - 8} fontSize={10} textAnchor="end" className="fill-slate-500">{formatAmount(high)}</text>
        <text x={x(mean)} y={H - 8} fontSize={10} textAnchor="middle" className="fill-blue-700">mean {formatAmount(mean)}</text>
      </svg>
    </figure>
  );
}
