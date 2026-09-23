/**
 * The Phase 1 GenUI components. Each renders a component record the stream
 * built; none computes a number of its own -- every figure is one the run
 * recorded (`app/genui/translate.py`).
 */
import { Link } from "react-router-dom";
import { useCancelRun } from "../../api/v1";
import {
  Bar,
  Card,
  Row,
  SkeletonCard,
  formatNumber,
  formatPercent,
  formatSeconds,
  num,
  useWorkspaceContext,
  type GenUIProps,
} from "./shared";

// -- metric ------------------------------------------------------------------

export function MetricCard({ record }: GenUIProps) {
  const label = String(record.props.label ?? "Metric");
  const format = record.props.format;
  const value = record.data.value;
  const shown = format === "percent" ? formatPercent(value) : format === "seconds" ? formatSeconds(value) : formatNumber(value);
  return (
    <section className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="font-mono text-lg tabular-nums text-slate-900">{shown}</p>
    </section>
  );
}

export function MetricSkeleton({ record }: GenUIProps) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm" aria-busy="true" aria-label="loading">
      <p className="text-xs uppercase tracking-wide text-slate-400">{String(record.props.label ?? "Metric")}</p>
      <div className="py-1.5">
        <Bar w="w-2/3" h="h-4" />
      </div>
    </section>
  );
}

// -- optimization summary ------------------------------------------------------

const STATUS_WORDS: Record<string, string> = {
  optimal: "Optimal — proven the best",
  feasible: "An answer, not proven the best",
  infeasible: "No answer satisfies every rule",
  unbounded: "The goal can improve without limit",
  unknown: "No answer within the time allowed",
  error: "The run failed",
  cancelled: "Stopped",
};

export function OptimizationSummary({ record, variant }: GenUIProps) {
  const { problemId, scenarioId } = useWorkspaceContext();
  const d = record.data;
  const status = String(d.status ?? "");
  const tone = status === "optimal" ? "plain" : status === "feasible" || status === "cancelled" ? "warn" : "bad";
  return (
    <Card title={String(record.props.title ?? "Result")} tone={tone}>
      <p className="mb-2 font-medium text-slate-900">{STATUS_WORDS[status] ?? status}</p>
      {num(d.objective) !== null && (
        <p className="mb-2 font-mono text-2xl tabular-nums text-slate-900" aria-label="objective">
          {formatNumber(d.objective)}
        </p>
      )}
      <dl>
        <Row label="Gap" value={formatPercent(d.gap)} />
        {variant === "expanded" && <Row label="Bound" value={formatNumber(d.bound)} />}
        <Row label="Solver" value={String(d.solver ?? "—")} />
        <Row label="Time" value={formatSeconds(d.wallTime)} />
        {variant === "expanded" && d.optimality != null && <Row label="Optimality" value={String(d.optimality)} />}
      </dl>
      {d.error != null && <p className="mt-2 text-rose-700">{String(d.error)}</p>}
      {variant === "expanded" && problemId != null && scenarioId != null && (
        <Link
          to={`/runs?problem=${problemId}&scenario=${scenarioId}`}
          className="mt-3 inline-block text-blue-700 underline"
        >
          Explore the solution on the Runs page →
        </Link>
      )}
    </Card>
  );
}

export function OptimizationSummarySkeleton({ record }: GenUIProps) {
  return (
    <SkeletonCard title={String(record.props.title ?? "Result")}>
      <div className="space-y-2">
        <Bar w="w-1/2" />
        <Bar w="w-1/3" h="h-7" />
        <Bar w="w-full" />
        <Bar w="w-full" />
        <Bar w="w-full" />
      </div>
    </SkeletonCard>
  );
}

// -- solver status -------------------------------------------------------------

export function SolverStatus({ record }: GenUIProps) {
  const d = record.data;
  return (
    <Card title={String(record.props.title ?? "Solver")}>
      <dl>
        <Row label="Solver" value={String(d.solver ?? "—")} />
        {d.modelClass != null && <Row label="Problem type" value={String(d.modelClass)} />}
        {num(d.timeLimit) !== null && <Row label="Time limit" value={formatSeconds(d.timeLimit)} />}
      </dl>
      {d.why != null && <p className="mt-2 text-xs text-slate-600">{String(d.why)}.</p>}
    </Card>
  );
}

export function SolverStatusSkeleton({ record }: GenUIProps) {
  return <SkeletonCard title={String(record.props.title ?? "Solver")} rows={3} />;
}

// -- solver progress -----------------------------------------------------------

function Curve({ history }: { history: Record<string, unknown>[] }) {
  const points = history
    .map((h) => ({ t: num(h.elapsed), o: num(h.objective), b: num(h.bound) }))
    .filter((p): p is { t: number; o: number | null; b: number | null } => p.t !== null);
  const values = points.flatMap((p) => [p.o, p.b]).filter((v): v is number => v !== null);
  if (points.length < 2 || values.length < 2) return null;
  const [w, h] = [320, 90];
  const tMax = Math.max(...points.map((p) => p.t)) || 1;
  const [lo, hi] = [Math.min(...values), Math.max(...values)];
  const x = (t: number) => (t / tMax) * w;
  const y = (v: number) => (hi === lo ? h / 2 : h - ((v - lo) / (hi - lo)) * h);
  const line = (pick: (p: (typeof points)[number]) => number | null) =>
    points
      .filter((p) => pick(p) !== null)
      .map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(pick(p)!).toFixed(1)}`)
      .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="mt-2 h-24 w-full" role="img" aria-label="best answer and bound over time">
      <path d={line((p) => p.b)} fill="none" stroke="rgb(148 163 184)" strokeDasharray="4 3" strokeWidth="1.5" />
      <path d={line((p) => p.o)} fill="none" stroke="rgb(37 99 235)" strokeWidth="2" />
    </svg>
  );
}

export function SolverProgress({ record, variant }: GenUIProps) {
  const cancel = useCancelRun();
  const { scenarioId } = useWorkspaceContext();
  const d = record.data;
  const share = num(d.timeShare);
  const running = !record.completed;
  const runId = num(record.props.runId);
  return (
    <Card title={String(record.props.title ?? "Optimization")}>
      {share !== null && (
        <div className="mb-2">
          <div
            className="h-2 overflow-hidden rounded bg-slate-100"
            role="progressbar"
            aria-label="time used of the time allowed"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(share * 100)}
          >
            {/* Width by transform, not by `width`: no layout on each report. */}
            <div
              className="h-full origin-left bg-blue-600 transition-transform duration-300 motion-reduce:transition-none"
              style={{ transform: `scaleX(${running ? share : 1})` }}
            />
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {running ? `${Math.round(share * 100)}% of the time allowed` : "Search finished"}
          </p>
        </div>
      )}
      <dl>
        <Row label="Best answer" value={formatNumber(d.objective)} />
        <Row label="Bound" value={formatNumber(d.bound)} />
        <Row label="Gap" value={formatPercent(d.gap)} />
        <Row label="Elapsed" value={formatSeconds(d.elapsed)} />
      </dl>
      {variant === "expanded" && <Curve history={record.history} />}
      {variant === "expanded" && running && runId !== null && scenarioId != null && (
        <button
          type="button"
          className="mt-3 rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
          onClick={() => cancel.mutate(runId)}
          disabled={cancel.isPending}
        >
          {cancel.isPending ? "Stopping…" : "Stop the run"}
        </button>
      )}
    </Card>
  );
}

export function SolverProgressSkeleton({ record }: GenUIProps) {
  return (
    <SkeletonCard title={String(record.props.title ?? "Optimization")}>
      <div className="space-y-2">
        <Bar h="h-2" />
        <Bar w="w-1/3" />
        <Bar />
        <Bar />
        <Bar />
        <Bar />
      </div>
    </SkeletonCard>
  );
}

// -- model summary -------------------------------------------------------------

const ROW_KINDS: [string, string][] = [
  ["rows_partition", "Set partitions"],
  ["rows_cover", "Set covers"],
  ["rows_packing", "Set packings"],
  ["rows_cardinality", "Cardinality"],
  ["rows_knapsack", "Knapsacks"],
  ["rows_general", "General"],
  ["rows_quadratic", "Quadratic"],
  ["rows_conditional", "Conditional"],
  ["rows_scheduling", "Scheduling"],
];

export function ModelSummary({ record, variant }: GenUIProps) {
  const d = record.data;
  const f = (d.fingerprint ?? {}) as Record<string, unknown>;
  return (
    <Card title={String(record.props.title ?? "The model")}>
      <dl>
        <Row label="Problem type" value={String(d.modelClass ?? "—")} />
        <Row label="Decisions" value={formatNumber(d.variables)} />
        <Row label="Rule instances" value={formatNumber(d.constraints)} />
        {num(f.blocks) !== null && <Row label="Independent parts" value={formatNumber(f.blocks)} />}
      </dl>
      {variant === "expanded" && (
        <>
          <h4 className="mb-1 mt-3 text-xs font-semibold text-slate-500">Decisions</h4>
          <dl>
            <Row label="Yes-or-no" value={formatNumber(f.binary)} />
            <Row label="Whole numbers" value={formatNumber(f.integer)} />
            <Row label="Quantities" value={formatNumber(f.continuous)} />
          </dl>
          <h4 className="mb-1 mt-3 text-xs font-semibold text-slate-500">Rules, by shape</h4>
          <dl>
            {ROW_KINDS.filter(([key]) => (num(f[key]) ?? 0) > 0).map(([key, label]) => (
              <Row key={key} label={label} value={formatNumber(f[key])} />
            ))}
          </dl>
          <h4 className="mb-1 mt-3 text-xs font-semibold text-slate-500">Numbers</h4>
          <dl>
            <Row label="Non-zeros" value={formatNumber(f.nnz)} />
            <Row label="Coefficient range" value={`${formatNumber(f.coef_min)} – ${formatNumber(f.coef_max)}`} />
            <Row label="Whole-number data" value={f.integral_data === true ? "yes" : f.integral_data === false ? "no" : "—"} />
          </dl>
        </>
      )}
    </Card>
  );
}

export function ModelSummarySkeleton({ record }: GenUIProps) {
  return <SkeletonCard title={String(record.props.title ?? "The model")} rows={3} />;
}

// -- timeline --------------------------------------------------------------------

const STEP_WORDS: Record<string, string> = {
  submitting_job: "Queued",
  understanding: "Reading the model",
  building_model: "Building the model",
  selecting_solver: "Choosing a solver",
  solving: "Solving",
  post_processing: "Working up the answer",
  complete: "Done",
};

export function Timeline({ record }: GenUIProps) {
  const steps = (record.data.steps as string[] | undefined) ?? Object.keys(STEP_WORDS);
  const done = new Set((record.data.done as string[] | undefined) ?? []);
  const current = record.data.current as string | undefined;
  const ended = current === "warning" || current === "error";
  return (
    <Card title={String(record.props.title ?? "Progress")}>
      <ol className="space-y-1">
        {steps.map((step) => {
          const isDone = done.has(step) || (step === "complete" && current === "complete");
          const isNow = step === current || (ended && step === "complete");
          const mark = isDone ? "●" : isNow ? "◐" : "○";
          return (
            <li key={step} className={`flex gap-2 ${isNow ? "font-medium text-slate-900" : isDone ? "text-slate-700" : "text-slate-400"}`}>
              <span aria-hidden="true">{mark}</span>
              <span>
                {step === "complete" && ended ? (current === "error" ? "Ended with a problem" : "Done, with a caveat") : STEP_WORDS[step] ?? step}
                <span className="sr-only">{isDone ? " (done)" : isNow ? " (now)" : ""}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

export function TimelineSkeleton({ record }: GenUIProps) {
  return <SkeletonCard title={String(record.props.title ?? "Progress")} rows={6} />;
}

// -- solver log --------------------------------------------------------------------

export function SolverLog({ record }: GenUIProps) {
  const lines = (record.data.lines as string[] | undefined) ?? [];
  return (
    <Card title={String(record.props.title ?? "Solver log")}>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs text-slate-700">{lines.slice(-200).join("\n")}</pre>
    </Card>
  );
}

export function SolverLogSkeleton({ record }: GenUIProps) {
  return <SkeletonCard title={String(record.props.title ?? "Solver log")} rows={4} />;
}
