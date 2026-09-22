import { useEffect, useMemo, useRef, useState } from "react";
import { watchRun, type RunEvent } from "../api/runEvents";

/**
 * A run as it happens: the best answer found so far and the bound on how
 * good any answer could be, drawn closing on each other.
 *
 * The gap between the two curves is the honest measure of "how far might
 * this still be from the best?" -- the same gap the run records when it
 * settles. A finished run replays its whole curve, so a slow one can be
 * looked at afterwards and the time it spent proving optimality (the flat
 * stretch after the answer stops improving) is visible.
 */

type Point = { t: number; objective: number | null; bound: number | null };

const WIDTH = 560;
const HEIGHT = 180;
const PAD = { left: 56, right: 12, top: 10, bottom: 22 };

function path(points: Point[], pick: (p: Point) => number | null, x: (t: number) => number, y: (v: number) => number) {
  // Each series steps: a value holds until the solver reports a better one.
  let d = "";
  let last: number | null = null;
  for (const point of points) {
    const value = pick(point);
    if (value === null || !Number.isFinite(value)) continue;
    if (last === null) d += `M ${x(point.t)} ${y(value)}`;
    else d += ` L ${x(point.t)} ${y(last)} L ${x(point.t)} ${y(value)}`;
    last = value;
  }
  return d;
}

function format(value: number): string {
  if (Math.abs(value) >= 1e6 || (value !== 0 && Math.abs(value) < 1e-3)) return value.toExponential(2);
  return String(Number(value.toPrecision(6)));
}

export default function RunProgress({
  runId,
  live,
  onSettled,
}: {
  runId: number | string;
  /** Watch for more, rather than only replaying what was recorded. */
  live: boolean;
  onSettled?: () => void;
}) {
  const [points, setPoints] = useState<Point[]>([]);
  const [stage, setStage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const onSettledRef = useRef(onSettled);
  onSettledRef.current = onSettled;

  useEffect(() => {
    setPoints([]);
    setStage(null);
    setFailed(false);
    const stop = watchRun(runId, {
      onEvent: (event: RunEvent) => {
        if (event.kind === "stage") setStage(String(event.stage ?? ""));
        if (event.kind === "incumbent" || event.kind === "bound") {
          setPoints((current) => [
            ...current,
            { t: Number(event.t ?? 0), objective: event.objective ?? null, bound: event.bound ?? null },
          ]);
        }
      },
      onEnd: (why) => {
        if (why === "failed") setFailed(true);
        else onSettledRef.current?.();
      },
    });
    // `live` only decides what this says while it watches; the stream is
    // the same either way, so it is not a reason to re-subscribe.
    return stop;
  }, [runId]);

  const chart = useMemo(() => {
    const values = points.flatMap((point) => [point.objective, point.bound]).filter((v): v is number => v !== null && Number.isFinite(v));
    if (points.length < 2 || values.length === 0) return null;
    const times = points.map((point) => point.t);
    const t0 = Math.min(...times);
    const t1 = Math.max(...times);
    const low = Math.min(...values);
    const high = Math.max(...values);
    const spanT = t1 - t0 || 1;
    const spanV = high - low || Math.abs(high) || 1;
    const x = (t: number) => PAD.left + ((t - t0) / spanT) * (WIDTH - PAD.left - PAD.right);
    const y = (v: number) => PAD.top + (1 - (v - low) / spanV) * (HEIGHT - PAD.top - PAD.bottom);
    return {
      answer: path(points, (p) => p.objective, x, y),
      bound: path(points, (p) => p.bound, x, y),
      low,
      high,
      t1,
      y,
      x,
    };
  }, [points]);

  const latest = points[points.length - 1];

  if (failed && points.length === 0) return null;

  return (
    <section className="mb-4 rounded-md border border-slate-200 bg-white p-3" data-testid="run-progress">
      <div className="mb-2 flex flex-wrap items-baseline gap-3">
        <h3 className="text-sm font-semibold text-slate-900">{live ? "Solving" : "How it was solved"}</h3>
        {stage && <span className="text-xs text-slate-500">{stage}</span>}
        {latest && (
          <span className="text-xs text-slate-700">
            best {latest.objective === null ? "—" : format(latest.objective)} · bound{" "}
            {latest.bound === null ? "—" : format(latest.bound)}
          </span>
        )}
      </div>
      {chart ? (
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-auto w-full max-w-2xl"
          role="img"
          aria-label={`The best answer and the bound over ${chart.t1.toFixed(1)} seconds`}
        >
          <line x1={PAD.left} y1={chart.y(chart.high)} x2={WIDTH - PAD.right} y2={chart.y(chart.high)} stroke="#e2e8f0" />
          <line x1={PAD.left} y1={chart.y(chart.low)} x2={WIDTH - PAD.right} y2={chart.y(chart.low)} stroke="#e2e8f0" />
          <text x={4} y={chart.y(chart.high) + 4} className="fill-slate-500 text-[10px]">{format(chart.high)}</text>
          <text x={4} y={chart.y(chart.low) + 4} className="fill-slate-500 text-[10px]">{format(chart.low)}</text>
          <text x={WIDTH - PAD.right} y={HEIGHT - 6} textAnchor="end" className="fill-slate-500 text-[10px]">
            {chart.t1.toFixed(1)} s
          </text>
          <path d={chart.bound} fill="none" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 3" />
          <path d={chart.answer} fill="none" stroke="#2563eb" strokeWidth={2} />
        </svg>
      ) : (
        <p className="text-sm text-slate-500">
          {live ? "Waiting for the solver's first answer…" : "This run reported no progress: it finished too quickly to say anything."}
        </p>
      )}
      <p className="mt-1 text-xs text-slate-500">
        <span className="text-blue-700">—</span> the best answer so far · <span className="text-slate-400">- -</span> the
        best any answer could be. They meet when the answer is proven best.
      </p>
    </section>
  );
}
