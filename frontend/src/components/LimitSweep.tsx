import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { formatApiError } from "../api/errors";
import { createRun, createScenario, getRun, useVersion, type Id, type Run } from "../api/v1";
import { ruleLimit } from "../model/ruleLimit";

/** At most this many solves in one sweep: each is a scenario and a run a person may open later. */
export const MAX_STEPS = 8;

/** The limits a sweep tries: `steps` values from `from` to `to`, evenly spaced. */
export function sweepValues(from: number, to: number, steps: number): number[] {
  if (!Number.isFinite(from) || !Number.isFinite(to) || steps < 2) return [];
  const n = Math.min(MAX_STEPS, Math.floor(steps));
  // Six places is finer than any limit is typed, and hides 0.1 + 0.2 sums.
  return Array.from({ length: n }, (_, i) => Number((from + ((to - from) * i) / (n - 1)).toFixed(6)));
}

type Point = { value: number; scenarioId: Id; runId: Id };
const SETTLED = new Set(["optimal", "feasible", "infeasible", "unbounded", "failed", "cancelled", "timeout"]);

/** What each step of a sweep bought: the goal, and its change per unit of limit from the step before. */
export function gains(rows: { value: number; goal: number | null }[]): (number | null)[] {
  return rows.map((row, i) => {
    const before = rows[i - 1];
    if (!before || row.goal === null || before.goal === null || row.value === before.value) return null;
    return (row.goal - before.goal) / (row.value - before.value);
  });
}

const W = 560, H = 220, PAD = { l: 64, r: 36, t: 16, b: 36 };

/** Goal against the limit: one series, so no legend; the table below carries the same numbers. */
function Curve({ rows, rule }: { rows: { value: number; goal: number | null }[]; rule: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const pts = rows.filter((r): r is { value: number; goal: number } => r.goal !== null);
  if (pts.length < 2) return null;
  const xs = pts.map((p) => p.value), ys = pts.map((p) => p.goal);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [yMin, yMax] = [Math.min(...ys), Math.max(...ys)];
  const y0 = yMin - (yMax - yMin || Math.abs(yMax) || 1) * 0.1, y1 = yMax + (yMax - yMin || Math.abs(yMax) || 1) * 0.1;
  const X = (v: number) => PAD.l + ((v - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
  const Y = (v: number) => H - PAD.b - ((v - y0) / (y1 - y0 || 1)) * (H - PAD.t - PAD.b);
  const fmt = (v: number) => v.toLocaleString("en-US", { maximumFractionDigits: 1 });
  const ticks = [y0 + (y1 - y0) * 0.1, (y0 + y1) / 2, y1 - (y1 - y0) * 0.1];
  const shown = hover !== null ? pts[hover] : null;
  return (
    <figure className="mt-3">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-xl" role="img"
        aria-label={`The goal as ${rule}'s limit goes from ${fmt(x0)} to ${fmt(x1)}`} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={Y(t)} y2={Y(t)} stroke="currentColor" className="text-slate-200" />
            <text x={PAD.l - 6} y={Y(t) + 4} textAnchor="end" fontSize={11} className="fill-slate-500">{fmt(t)}</text>
          </g>
        ))}
        {pts.map((p) => (
          <text key={p.value} x={X(p.value)} y={H - PAD.b + 16} textAnchor="middle" fontSize={11} className="fill-slate-500">{fmt(p.value)}</text>
        ))}
        <text x={(PAD.l + W - PAD.r) / 2} y={H - 4} textAnchor="middle" fontSize={11} className="fill-slate-600">{rule} limit</text>
        <polyline points={pts.map((p) => `${X(p.value)},${Y(p.goal)}`).join(" ")} fill="none" stroke="#2563eb" strokeWidth={2}
          strokeLinejoin="round" strokeLinecap="round" />
        {pts.map((p, i) => (
          <g key={p.value} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={0}
            aria-label={`${rule} ${fmt(p.value)}: goal ${fmt(p.goal)}`}>
            {/* A hit target bigger than the mark. */}
            <circle cx={X(p.value)} cy={Y(p.goal)} r={12} fill="transparent" />
            <circle cx={X(p.value)} cy={Y(p.goal)} r={hover === i ? 5 : 4} fill="#2563eb" stroke="white" strokeWidth={2} />
          </g>
        ))}
        {shown && (
          <g pointerEvents="none">
            <rect x={Math.min(X(shown.value) + 8, W - 150)} y={Math.max(Y(shown.goal) - 34, 2)} width={140} height={28} rx={4}
              className="fill-white" stroke="#cbd5e1" />
            <text x={Math.min(X(shown.value) + 16, W - 142)} y={Math.max(Y(shown.goal) - 16, 20)} fontSize={11} className="fill-slate-800">
              {fmt(shown.value)} → {fmt(shown.goal)}
            </text>
          </g>
        )}
      </svg>
    </figure>
  );
}

/**
 * "What does each extra 10,000 buy?" (enhancement after the user trial): the same model solved at
 * several values of one rule's limit, as scenarios a person may open later, and the goal drawn
 * against the limit -- where the curve flattens, more budget stops buying coverage.
 */
export default function LimitSweep({ problemId, versionId, scenarioHref }: {
  problemId: Id; versionId: Id; scenarioHref: (scenarioId: Id, runId: Id) => string;
}) {
  const id = useId();
  const client = useQueryClient();
  const version = useVersion(versionId);
  const rules = ((version.data?.ir as { constraints?: { id: string; left?: unknown; right?: unknown }[] } | undefined)?.constraints ?? [])
    .filter((c) => ruleLimit(c) !== null);
  const [rule, setRule] = useState("");
  const chosen = rules.find((r) => r.id === rule) ?? rules[0];
  const now = chosen ? ruleLimit(chosen) : null;
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [steps, setSteps] = useState("5");
  const [points, setPoints] = useState<Point[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const runs = useQueries({
    queries: points.map((p) => ({
      queryKey: ["v1", "runs", "sweep", p.runId],
      queryFn: () => getRun(p.runId),
      refetchInterval: (q: { state: { data?: Run } }) => (q.state.data && SETTLED.has(q.state.data.status) ? false : 1500),
    })),
  });

  if (!chosen || now === null) return null;
  const lo = from.trim() === "" ? now * 0.5 : Number(from.replace(/,/g, ""));
  const hi = to.trim() === "" ? now * 1.5 : Number(to.replace(/,/g, ""));
  const values = sweepValues(lo, hi, Number(steps));

  async function start() {
    setBusy(true);
    setProblem(null);
    setPoints([]);
    try {
      const made: Point[] = [];
      for (const value of values) {
        const scenario = await createScenario({ problem_id: problemId, model_version_id: versionId,
          name: `${chosen!.id} = ${value.toLocaleString("en-US")}`, patch: { set_limit: { [chosen!.id]: value } } });
        const run = await createRun(scenario.id, { time_limit_s: 30 });
        made.push({ value, scenarioId: scenario.id, runId: run.id });
        setPoints([...made]);
      }
      await client.invalidateQueries({ queryKey: ["v1", "scenarios"] });
    } catch (error) {
      setProblem(formatApiError(error));
    } finally {
      setBusy(false);
    }
  }

  const rows = points.map((p, i) => {
    const run = runs[i]?.data;
    const answered = run && (run.status === "optimal" || run.status === "feasible");
    return { ...p, status: run?.status ?? "queued", goal: answered && run.objective !== null ? Number(run.objective) : null };
  });
  const perUnit = gains(rows);
  const input = "rounded border border-slate-300 px-2 py-1 text-sm";

  return (
    <section aria-labelledby={`${id}-h`} className="mt-6 rounded-md border border-slate-200 bg-white p-4">
      <h2 id={`${id}-h`} className="mb-1 text-base font-semibold text-slate-900">Try a range of limits</h2>
      <p className="mb-3 text-sm text-slate-600">
        Solve the model at several values of one limit and see what each step buys — where the curve flattens, more stops helping.
        Each value is kept as a scenario.
      </p>
      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label className="flex flex-col text-xs text-slate-600">Rule
          <select className={input} value={chosen.id} onChange={(e) => setRule(e.target.value)}>
            {rules.map((r) => <option key={r.id} value={r.id}>{r.id} (now {ruleLimit(r)!.toLocaleString("en-US")})</option>)}
          </select>
        </label>
        <label className="flex flex-col text-xs text-slate-600">From
          <input className={`${input} w-28`} inputMode="decimal" placeholder={String(now * 0.5)} value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="flex flex-col text-xs text-slate-600">To
          <input className={`${input} w-28`} inputMode="decimal" placeholder={String(now * 1.5)} value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <label className="flex flex-col text-xs text-slate-600">Steps
          <input className={`${input} w-16`} inputMode="numeric" value={steps} onChange={(e) => setSteps(e.target.value)} />
        </label>
        <button type="button" disabled={busy || values.length < 2} onClick={() => void start()}
          className="rounded-md bg-blue-600 px-3 py-1.5 font-medium text-white disabled:opacity-60">
          {busy ? "Starting…" : `Solve ${values.length} times`}
        </button>
      </div>
      {values.length >= 2 && !points.length && (
        <p className="mt-2 text-xs text-slate-500">{values.map((v) => v.toLocaleString("en-US")).join(" · ")} (at most {MAX_STEPS})</p>
      )}
      {problem && <p role="alert" className="mt-2 text-sm text-red-700">{problem}</p>}
      {rows.length > 0 && (
        <>
          <Curve rows={rows} rule={chosen.id} />
          <table className="mt-2 text-left text-sm" aria-label="Goal at each limit">
            <thead>
              <tr className="text-xs text-slate-600">
                <th scope="col" className="px-2 py-1">{chosen.id}</th>
                <th scope="col" className="px-2 py-1">Goal</th>
                <th scope="col" className="px-2 py-1">Gained per unit</th>
                <th scope="col" className="px-2 py-1">Run</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.runId} className="border-t border-slate-100">
                  <td className="px-2 py-1 font-mono">{r.value.toLocaleString("en-US")}</td>
                  <td className="px-2 py-1">{r.goal !== null ? r.goal.toLocaleString("en-US", { maximumFractionDigits: 1 }) : r.status}</td>
                  <td className="px-2 py-1">{perUnit[i] !== null ? perUnit[i]!.toLocaleString("en-US", { maximumFractionDigits: 3 }) : "—"}</td>
                  <td className="px-2 py-1"><Link className="text-blue-700 underline" to={scenarioHref(r.scenarioId, r.runId)}>Run {String(r.runId)}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
