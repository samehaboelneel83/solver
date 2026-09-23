import { useEffect, useId, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { useEntityList } from "../api/entities";
import { formatApiError } from "../api/errors";
import {
  useCancelRun,
  useCreateRun,
  useCreateScenario,
  useRun,
  useRunComparison,
  useRuns,
  useVersion,
useScenario,
  useScenarios,
  useSolvers,
  type ConflictItem,
  type ParetoPoint,
  type ConstraintOutcome,
  type Id,
  type Run,
  type RunStatus,
} from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";
import RunProgress from "../components/RunProgress";
import { useToast } from "../components/ToastProvider";

/**
 * Solving, and what came of it.
 *
 * A run belongs to a **scenario**, not to a problem: the scenario names the
 * model version and the patch, so "solve this" is only well defined once one
 * is chosen. Picking a problem then a scenario is that chain made visible.
 *
 * Two things this screen refuses to flatten, because the platform does not:
 *
 * - **`optimal` and `feasible` are different answers.** One is the best
 *   roster, the other is *a* roster found before the clock ran out. Merging
 *   them into a tick would overstate what the solver proved.
 * - **A roster with no account of what it broke is not usable.** A soft
 *   constraint that gave is shown with the instances that gave and by how
 *   much -- "Thursday morning, 4 short" is what a planner can act on, where
 *   "coverage: broken" is not.
 *
 * Solving happens in a **worker**, so submitting returns a `queued` run and
 * the answer arrives later. This page follows it: `useRun` polls while a run
 * is unfinished and stops the moment it settles, because a run is immutable
 * once written and there is nothing left to poll for.
 */

const PAGE_SIZE = 50;

const STATUS_STYLE: Record<RunStatus, string> = {
  optimal: "bg-green-100 text-green-900",
  feasible: "bg-green-50 text-green-900",
  infeasible: "bg-amber-100 text-amber-900",
  unbounded: "bg-amber-100 text-amber-900",
  error: "bg-red-100 text-red-900",
  unknown: "bg-slate-100 text-slate-700",
  queued: "bg-slate-100 text-slate-700",
  running: "bg-blue-100 text-blue-900",
  cancelled: "bg-slate-100 text-slate-700",
};

/** What each status means, in a planner's terms rather than a solver's. */
const STATUS_NOTE: Record<RunStatus, string> = {
  optimal: "Best possible answer, proven.",
  feasible: "An answer, found before the time limit -- not proven best.",
  infeasible: "No answer exists: the rules cannot all hold at once.",
  unbounded: "The goal can improve forever: a decision is missing a limit, or a rule is missing.",
  error: "The model could not be solved. The reason is below.",
  unknown: "The solver stopped without deciding. Try a longer time limit.",
  queued: "Waiting to start.",
  running: "Solving.",
  cancelled: "Stopped before an answer.",
};

/**
 * What the status means, qualified by what the answer may claim.
 *
 * "Optimal" is only a complete sentence when the solver that said it proves
 * the best of ALL answers. A local solver's optimum is the best among its
 * neighbours, and on a model that is not convex a better one can exist
 * somewhere else; worded like a global optimum, it would be believed. So the
 * claim decides the words, and a missing claim (an older run) falls back to
 * the plain status note.
 */
export function statusNote(run: {
  status: RunStatus;
  optimality?: string | null;
  gap?: number | null;
  /** The run was stopped on request and kept the answer it had. */
  stopped?: boolean;
}): string {
  if (run.status === "feasible" && run.stopped) {
    return typeof run.gap === "number"
      ? `Stopped on request. The best answer found by then -- at most ${formatGap(run.gap)} worse than the best possible.`
      : "Stopped on request. The best answer found by then -- not proven best.";
  }
  if (run.status === "feasible" && typeof run.gap === "number") {
    return `An answer, found before the time limit -- at most ${formatGap(run.gap)} worse than the best possible.`;
  }
  if (run.status === "optimal" && run.optimality === "local") {
    return "The best answer near where the search looked -- not proven the best overall. A better one may exist; solving from another start, or with a global solver, is how to find out.";
  }
  if (run.status === "optimal" && run.optimality === "global") {
    return "Best possible answer, proven: no other answer does better.";
  }
  return STATUS_NOTE[run.status];
}

/** A gap as a percentage a planner can read: two significant figures, and
 * "under 0.01%" rather than a string of zeros. */
export function formatGap(gap: number): string {
  const percent = gap * 100;
  if (percent === 0) return "0%";
  if (percent < 0.01) return "under 0.01%";
  return `${Number(percent.toPrecision(2))}%`;
}

export default function Runs() {
  useDocumentTitle("Runs");
  const { domainId } = useDomain();

  return (
    <div className="max-w-5xl">
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Runs</h1>
      <p className="mb-4 text-sm text-slate-500">
        Solving a scenario freezes its data, runs the solver, and keeps the answer. Runs are never changed:
        solving again makes a new one, which is what lets two be compared.
      </p>
      {domainId === null ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen).</p>
        </div>
      ) : (
        <ForDomain domainId={domainId} />
      )}
    </div>
  );
}

function problemName(problem: Record<string, unknown>): string {
  return typeof problem.name === "string" && problem.name ? problem.name : String(problem.id ?? "");
}

function ForDomain({ domainId }: { domainId: Id }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const problemChooser = useId();
  const scenarioChooser = useId();

  const problems = useEntityList("public", "problem", {
    limit: 500,
    offset: 0,
    orderBy: "name",
    order: "asc",
    filters: { domain_id: String(domainId) },
  });

  const problemItems = problems.data?.items ?? [];
  const requestedProblem = parseRouteId(searchParams.get("problem"));
  const problem = problemItems.find((row) => Number(row.id) === requestedProblem) ?? problemItems[0];
  const problemId = problem ? Number(problem.id) : null;

  const scenarios = useScenarios(problemId, { limit: 500, offset: 0 });
  const scenarioItems = scenarios.data?.items ?? [];
  const requestedScenario = parseRouteId(searchParams.get("scenario"));
  const scenario = scenarioItems.find((row) => row.id === requestedScenario) ?? scenarioItems[0];

  if (problems.fetchStatus === "paused" && !problems.data) return <OfflineNotice subject="The problem list" />;
  if (problems.isLoading) return <Skeleton rows={3} cols={4} />;
  if (problems.isError && !problems.data) {
    return <Failed error={problems.error} onRetry={() => problems.refetch()} />;
  }

  if (problemItems.length === 0) {
    return (
      <Empty>
        <p>This domain has no problems yet, and every run belongs to one.</p>
        <p className="mt-1">
          Create one on the{" "}
          <Link to="/public/problem" className="inline-block rounded py-1 text-blue-600 underline">
            Problems page
          </Link>
          .
        </p>
      </Empty>
    );
  }

  return (
    <>
      <div className="mb-4 grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor={problemChooser} className="block text-sm font-medium text-slate-700">
            Problem
          </label>
          <select
            id={problemChooser}
            className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
            value={String(problemId ?? "")}
            onChange={(event) => setSearchParams({ problem: event.target.value }, { replace: true })}
          >
            {problemItems.map((row) => (
              <option key={String(row.id)} value={String(row.id)}>
                {problemName(row)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={scenarioChooser} className="block text-sm font-medium text-slate-700">
            Scenario
          </label>
          <select
            id={scenarioChooser}
            className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
            value={scenario ? String(scenario.id) : ""}
            disabled={scenarioItems.length === 0}
            onChange={(event) =>
              setSearchParams(
                { problem: String(problemId ?? ""), scenario: event.target.value },
                { replace: true }
              )
            }
          >
            {scenarioItems.length === 0 && <option value="">No scenarios</option>}
            {scenarioItems.map((row) => (
              <option key={String(row.id)} value={String(row.id)}>
                {row.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {scenarioItems.length === 0 ? (
        <Empty>
          <p>
            This problem has no scenarios, and a run solves one. A scenario names the model version to solve
            and any constraints to relax.
          </p>
        </Empty>
      ) : scenario ? (
        <ScenarioRuns
          key={scenario.id}
          scenarioId={scenario.id}
          scenarioName={scenario.name}
          modelVersionId={scenario.model_version_id}
        />
      ) : null}
    </>
  );
}

/**
 * The rules of a model version published before rules had arithmetic -- an
 * id and a prose note, nothing a solver can read -- or an empty list when
 * every rule is expressed.
 *
 * Such a version is permanent: versions are immutable, and a run points at
 * one. So a scenario on it can never be solved, and offering "Solve" there
 * only ever produced an errored run. This lets the screen say so first.
 */
export function unexpressedRules(ir: Record<string, unknown> | undefined): string[] {
  const constraints = Array.isArray(ir?.constraints) ? (ir.constraints as Record<string, unknown>[]) : [];
  return constraints
    .filter(
      (rule) =>
        rule &&
        (rule.left === undefined || rule.right === undefined) &&
        // A scheduling rule has no left or right: it is expressed differently.
        rule.no_overlap === undefined &&
        rule.cumulative === undefined
    )
    .map((rule) => String(rule.id ?? "?"));
}

function ScenarioRuns({
  scenarioId,
  scenarioName,
  modelVersionId,
}: {
  scenarioId: Id;
  scenarioName: string;
  modelVersionId: Id;
}) {
  const { can } = useCapabilities();
  const version = useVersion(modelVersionId);
  const unexpressed = unexpressedRules(version.data?.ir);
  // A trade-off front needs a goal of exactly two terms (app.solve.pareto).
  const twoGoals =
    ((version.data?.ir as { objective?: { terms?: unknown[] } } | undefined)?.objective?.terms ?? []).length === 2;
  const solvers = useSolvers();
  const [solver, setSolver] = useState<string>("");
  const runs = useRuns(scenarioId, { limit: PAGE_SIZE, offset: 0 });
  // While anything is unfinished the list is stale the moment it arrives.
  const settling = (runs.data?.items ?? []).some(
    (row) => row.status === "queued" || row.status === "running"
  );
  useEffect(() => {
    if (!settling) return;
    const timer = setInterval(() => runs.refetch(), 1000);
    return () => clearInterval(timer);
  }, [settling, runs]);
  const createRun = useCreateRun();
  const toast = useToast();
  const [openId, setOpenId] = useState<Id | null>(null);
  const [againstId, setAgainstId] = useState<Id | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const items = runs.data?.items ?? [];
  const selected = openId ?? items[0]?.id ?? null;
  // Comparing is only offered once there is something to compare with.
  const comparable = items.filter((row) => row.id !== selected);
  const against = comparable.some((row) => row.id === againstId) ? againstId : null;

  function solve(front = false) {
    setFailure(null);
    createRun.mutate(
      {
        scenarioId,
        body: { time_limit_s: 30, ...(solver ? { solver } : {}), ...(front ? { pareto_steps: 10 } : {}) },
      },
      {
        onSuccess: (run: Run) => {
          setOpenId(run.id);
          toast.success(`Run ${run.id}: ${run.status}`);
        },
        onError: (error: unknown) => setFailure(formatApiError(error)),
      }
    );
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        {unexpressed.length > 0 ? (
          <p role="note" className="max-w-2xl rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            This scenario is on model version {version.data?.version}, published before rules could be
            written as arithmetic: {unexpressed.join(", ")} {unexpressed.length === 1 ? "is named but says" : "are named but say"}{" "}
            nothing a solver can check, so it cannot be solved. Versions never change, so point a
            scenario at a newer version on the{" "}
            <Link to="/scenarios" className="underline">
              Scenarios page
            </Link>
            , or express the rules in the{" "}
            <Link to="/model" className="underline">
              Model editor
            </Link>{" "}
            and publish. Past runs of it are below.
          </p>
        ) : can("run.submit") ? (
          <>
          <button
            type="button"
            onClick={() => solve()}
            disabled={createRun.isPending}
            className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {createRun.isPending ? "Queueing…" : `Solve ${scenarioName}`}
          </button>
          {twoGoals && (
            <button
              type="button"
              onClick={() => solve(true)}
              disabled={createRun.isPending}
              className="rounded-md border border-blue-600 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-60"
            >
              Show the trade-off between its two goals
            </button>
          )}
          </>
        ) : (
          <p className="text-sm text-slate-600">
            This account may read runs but not start them. Past answers are below.
          </p>
        )}
        {can("solver.configure") && (
        <label className="text-sm text-slate-600">
          <span className="mr-2">Solver</span>
          <select
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            value={solver}
            onChange={(event) => setSolver(event.target.value)}
          >
            {/* Empty means "let the platform choose", which is the default
                and records why it chose. */}
            <option value="">chosen for me</option>
            {(solvers.data?.items ?? [])
              .filter((option) => option.available)
              .map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name}
                </option>
              ))}
          </select>
        </label>
        )}
        {can("run.submit") && (
          <span className="text-sm text-slate-500">
            {createRun.isPending
              ? "Queueing…"
              : "A worker solves it; this page follows along. Stop it if you asked the wrong question. The answer is kept, not recomputed."}
          </span>
        )}
      </div>

      {failure && (
        <p role="alert" className="mb-4 whitespace-pre-line text-sm text-red-600">
          {failure}
        </p>
      )}

      {runs.isLoading ? (
        <Skeleton rows={3} cols={4} />
      ) : items.length === 0 ? (
        <Empty>
          <p>No runs yet for this scenario. Solve it to get one.</p>
        </Empty>
      ) : (
        <>
          <table className="w-full table-auto border-collapse text-sm">
            <caption className="sr-only">Runs for {scenarioName}, newest first</caption>
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-600">
                <th scope="col" className="py-2 pr-3 font-medium">Run</th>
                <th scope="col" className="py-2 pr-3 font-medium">Status</th>
                <th scope="col" className="py-2 pr-3 font-medium">Objective</th>
                <th scope="col" className="py-2 pr-3 font-medium">Time</th>
                <th scope="col" className="py-2 font-medium">Solver</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr
                  key={String(row.id)}
                  className={`border-b border-slate-100 ${row.id === selected ? "bg-blue-50" : ""}`}
                >
                  <td className="py-2 pr-3">
                    <button
                      type="button"
                      onClick={() => setOpenId(row.id)}
                      className="rounded py-1 text-blue-600 underline"
                    >
                      Run {String(row.id)}
                    </button>
                  </td>
                  <td className="py-2 pr-3">
                    <span className={`inline-block rounded px-2 py-1 text-xs ${STATUS_STYLE[row.status]}`}>
                      {row.status}
                    </span>
                  </td>
                  <td className="py-2 pr-3 font-mono">{row.objective ?? "—"}</td>
                  <td className="py-2 pr-3">{row.wall_time_s === null ? "—" : `${row.wall_time_s}s`}</td>
                  <td className="py-2 text-slate-600">{row.solver_version ?? row.solver}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {selected !== null && comparable.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-slate-600">
              <label>
                <span className="mr-2">Compare run {String(selected)} with</span>
                <select
                  className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
                  value={against === null ? "" : String(against)}
                  onChange={(event) =>
                    setAgainstId(event.target.value === "" ? null : Number(event.target.value))
                  }
                >
                  <option value="">nothing</option>
                  {comparable.map((row) => (
                    <option key={String(row.id)} value={String(row.id)}>
                      Run {String(row.id)} ({row.status})
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}

          {selected !== null && against !== null && <Comparison left={selected} right={against} />}

          {selected !== null && <RunDetail id={selected} onOpen={setOpenId} />}
        </>
      )}
    </>
  );
}

/**
 * Two runs, side by side.
 *
 * The question this answers is causal -- "I relaxed the coverage rule; what
 * did it buy me, and what did it cost?" -- so the caveat is not a footnote.
 * Two runs can differ by the patch, the model version, the frozen data, the
 * solver or the seed, and only when the patch is the *only* difference may a
 * change in the roster be credited to it. When it is not, this says so before
 * it says anything else: crediting a rule for a change an added employee
 * caused is a wrong answer dressed as an insight.
 */
function Comparison({ left, right }: { left: Id; right: Id }) {
  const comparison = useRunComparison(left, right);

  if (comparison.isLoading) return <Skeleton rows={3} cols={3} />;
  if (comparison.isError && !comparison.data) {
    return <Failed error={comparison.error} onRetry={() => comparison.refetch()} />;
  }
  const data = comparison.data;
  if (!data) return null;

  return (
    <section
      aria-labelledby={`compare-${left}-${right}`}
      className="mt-4 rounded-md border border-slate-200 bg-white p-4"
    >
      <h2 id={`compare-${left}-${right}`} className="mb-1 text-base font-semibold text-slate-900">
        Run {String(left)} compared with run {String(right)}
      </h2>
      <p
        className={`mb-4 rounded px-3 py-2 text-sm ${
          data.patch_is_the_only_difference
            ? "bg-green-50 text-green-900"
            : "bg-amber-50 text-amber-900"
        }`}
      >
        {data.note}
      </p>

      <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        <Fact
          label={`Run ${String(left)} (${data.left.scenario_name})`}
          value={`${data.left.status}${data.left.objective === null ? "" : ` — ${data.left.objective}`}`}
        />
        <Fact
          label={`Run ${String(right)} (${data.right.scenario_name})`}
          value={`${data.right.status}${data.right.objective === null ? "" : ` — ${data.right.objective}`}`}
        />
        <Fact
          label="Objective change"
          value={
            data.objective_delta === null
              ? "— (one run has no objective)"
              : `${data.objective_delta > 0 ? "+" : ""}${data.objective_delta}`
          }
        />
        <Fact label="Differs by" value={data.differs_by.length === 0 ? "nothing" : data.differs_by.join(", ")} />
      </dl>

      {data.rules.length > 0 && (
        <>
          <h3 className="mb-2 text-sm font-semibold text-slate-900">Rules that changed</h3>
          <ul className="mb-4 space-y-1 text-sm">
            {data.rules.map((rule) => (
              <li key={rule.constraint_id} className="rounded border border-slate-200 px-3 py-2">
                <span className="font-mono text-slate-900">{rule.constraint_id}</span>{" "}
                <span className="text-slate-600">
                  {rule.left_satisfied ? "held" : `short by ${rule.left_violation}`} &rarr;{" "}
                  {rule.right_satisfied ? "held" : `short by ${rule.right_violation}`}
                  {rule.left_penalty !== rule.right_penalty &&
                    ` (cost ${rule.left_penalty} → ${rule.right_penalty})`}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {Object.keys(data.moved).length === 0 ? (
        <p className="text-sm text-slate-600">The answer is identical.</p>
      ) : (
        Object.entries(data.moved).map(([variable, diff]) => (
          <div key={variable} className="mb-3">
            <h3 className="mb-2 text-sm font-semibold text-slate-900">
              {variable} &mdash; {diff.added.length} added, {diff.removed.length} removed,{" "}
              {diff.unchanged} unchanged
            </h3>
            <ul className="flex flex-wrap gap-2">
              {diff.removed.map((tuple) => (
                <li
                  key={`-${tuple.join("\u0001")}`}
                  className="rounded border border-red-200 bg-red-50 px-2 py-1 font-mono text-xs text-red-900"
                >
                  &minus; {tuple.join(" · ")}
                </li>
              ))}
              {diff.added.map((tuple) => (
                <li
                  key={`+${tuple.join("\u0001")}`}
                  className="rounded border border-green-200 bg-green-50 px-2 py-1 font-mono text-xs text-green-900"
                >
                  + {tuple.join(" · ")}
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </section>
  );
}

/**
 * A tuple of keys, in the names people use.
 *
 * `["ahmed", "mon"]` becomes "Ahmed Salah - Monday" when the run's frozen
 * dataset knew those names, and stays as the key when it did not. The set for
 * each position comes from the model, because a key is unique within its type
 * and not across types: looking "mon" up in every set at once would
 * eventually find the wrong one.
 */
function naming(labels: Run["labels"], sets: string[] | undefined) {
  return (tuple: string[]) =>
    tuple.map((key, position) => labels[sets?.[position] ?? ""]?.[key] ?? key);
}

function RunDetail({ id, onOpen }: { id: Id; onOpen?: (id: Id) => void }) {
  const run = useRun(id);
  const { can } = useCapabilities();
  const cancelRun = useCancelRun();
  const toast = useToast();
  const [stopFailure, setStopFailure] = useState<string | null>(null);

  if (run.isLoading) return <Skeleton rows={4} cols={3} />;
  if (run.isError && !run.data) return <Failed error={run.error} onRetry={() => run.refetch()} />;
  const data = run.data;
  if (!data) return null;

  const roster = data.assignments ?? {};
  const broken = data.constraints.filter((c) => !c.satisfied);
  const emptyRanges = (data.params as { empty_ranges?: EmptyRange[] }).empty_ranges ?? [];
  const lead = outcomeLead(data);
  const params = data.params as {
    stopped_by_request?: boolean;
    why_solver?: string;
    classified_as?: string;
    objective_mode?: string;
    objective_terms?: { id: string; value: number }[];
  };
  const unfinished = data.status === "queued" || data.status === "running";
  const stopping = data.cancel_requested || cancelRun.isPending;

  function stop() {
    setStopFailure(null);
    cancelRun.mutate(id, {
      onSuccess: (next) => toast.success(`Run ${next.id}: ${next.status}`),
      onError: (error: unknown) => setStopFailure(formatApiError(error)),
    });
  }

  return (
    <section aria-labelledby={`run-${id}-heading`} className="mt-6 rounded-md border border-slate-200 bg-white p-4">
      <h2 id={`run-${id}-heading`} className="mb-1 text-base font-semibold text-slate-900">
        Run {String(id)}
      </h2>
      <p className="mb-4 text-sm text-slate-600">{statusNote({ ...data, stopped: params.stopped_by_request === true })}</p>
      {lead && <p className="mb-4 text-sm font-medium text-slate-900">{lead}</p>}
      {data.reused_from != null && (
        <p className="mb-4 rounded bg-slate-50 p-3 text-sm text-slate-700">
          Answered by run {String(data.reused_from)}: the same model, data and settings were already
          solved to a proven optimum, so this was not solved again.
        </p>
      )}

      {/* The solve itself: live while it runs, replayed afterwards. When it
          settles, refresh the run so the answer below it appears at once
          rather than at the next poll. */}
      <RunProgress runId={id} live={unfinished} onSettled={() => void run.refetch()} />

      {can("run.submit") && unfinished && (
        <div className="mb-4">
          <button
            type="button"
            onClick={stop}
            disabled={stopping}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            {stopping ? "Stopping…" : "Stop this run"}
          </button>
        </div>
      )}
      {stopFailure && (
        <p role="alert" className="mb-4 whitespace-pre-line text-sm text-red-600">
          {stopFailure}
        </p>
      )}

      {data.error && (
        <p role="alert" className="mb-4 whitespace-pre-line rounded bg-red-50 p-3 text-sm text-red-800">
          {data.error}
        </p>
      )}

      {data.pareto && data.pareto.length > 0 && (
        <TradeOff points={data.pareto} terms={data.pareto_terms ?? ["first goal", "second goal"]} onOpen={onOpen} />
      )}
      {(data.params as { pareto_of?: number }).pareto_of != null && (
        <p className="mb-4 rounded bg-slate-50 p-3 text-sm text-slate-700">
          One point of run {String((data.params as { pareto_of: number }).pareto_of)}&rsquo;s trade-off front.
          {onOpen && (
            <>
              {" "}
              <button
                type="button"
                className="underline"
                onClick={() => onOpen((data.params as { pareto_of: number }).pareto_of)}
              >
                Back to the front
              </button>
            </>
          )}
        </p>
      )}

      {data.conflict && data.conflict.length > 0 && (
        <Conflict
          runId={data.id}
          scenarioId={data.scenario_id}
          items={data.conflict}
          minimal={data.conflict_minimal}
          labels={data.labels}
          sets={data.index_sets.constraints}
          notes={data.rule_notes ?? {}}
          found={data.params as ConflictFinding}
          solver={data.solver}
        />
      )}

      {emptyRanges.length > 0 && (
        <section className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-3">
          <h3 className="mb-1 text-sm font-semibold text-slate-900">Rules that ranged over nobody</h3>
          <p className="mb-2 text-sm text-slate-700">
            A rule that matches nobody never constrains anyone. Check the filter, or the data it ranges over.
          </p>
          <ul className="space-y-1 text-sm text-slate-800">
            {emptyRanges.map((item) => (
              <li key={`${item.constraint_id}:${item.kind}:${Object.values(item.index).join(",")}`}>
                <span className="font-mono">{item.constraint_id}</span>
                {item.kind === "forall"
                  ? " never applied to anyone"
                  : ` counted nobody${emptyRangeWhere(item, data.labels)}`}
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.constraints.length > 0 && (
        <>
          <h3 className="mb-2 text-sm font-semibold text-slate-900">
            Rules {broken.length > 0 ? `— ${broken.length} gave` : "— all held"}
          </h3>
          <ul className="mb-4 space-y-2">
            {data.constraints.map((c) => (
              <ConstraintRow key={c.constraint_id} outcome={c} />
            ))}
          </ul>
        </>
      )}

      {Object.entries(roster).map(([variable, tuples]) => {
        const name = naming(data.labels, data.index_sets.variables[variable]);
        return (
          <div key={variable}>
            <h3 className="mb-2 text-sm font-semibold text-slate-900">
              {variable} &mdash; {tuples.length} chosen
            </h3>
            <ul className="flex flex-wrap gap-2">
              {tuples.map((tuple) => (
                <li
                  key={tuple.join("\u0001")}
                  className="rounded border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-700"
                >
                  {name(tuple).join(" · ")}
                </li>
              ))}
            </ul>
          </div>
        );
      })}

      {data.reduced_costs &&
        Object.values(data.reduced_costs).some((entries) => entries.length > 0) && (
          <div className="mt-4">
            <h3 className="mb-2 text-sm font-semibold text-slate-900">Would move the goal</h3>
            <ul className="space-y-1 text-xs text-slate-600">
              {Object.entries(data.reduced_costs).flatMap(([variable, entries]) => {
                const name = naming(data.labels, data.index_sets.variables[variable]);
                return entries.map((entry) => (
                  <li key={`${variable}\u0001${entry.index.join("\u0001")}`}>
                    <span className="font-mono text-slate-900">
                      {variable}
                      {entry.index.length > 0 ? ` · ${name(entry.index).join(" · ")}` : ""}
                    </span>{" "}
                    worth {entry.value} on the goal
                  </li>
                ));
              })}
            </ul>
          </div>
        )}

      <details className="mt-6 text-sm">
        <summary className="cursor-pointer font-semibold text-slate-900">Technical</summary>
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
          <Fact label="Objective" value={data.objective === null ? "—" : String(data.objective)} />
          <Fact label="Best bound" value={data.best_bound == null ? "—" : String(Number(data.best_bound.toPrecision(10)))} />
          <Fact label="Gap" value={data.gap == null ? "—" : formatGap(data.gap)} />
          <Fact label="Solved in" value={data.wall_time_s === null ? "—" : `${data.wall_time_s}s`} />
          <Fact label="Solver" value={data.solver_version ?? data.solver} />
          <Fact label="Chosen because" value={String(params.why_solver ?? "—")} />
          <Fact label="Class" value={String(params.classified_as ?? "—")} />
          <Fact label="Data" value={`dataset ${String(data.dataset_id)}`} />
          {params.objective_mode === "lex" && (params.objective_terms ?? []).length > 0 && (
            <Fact
              label="Goals in order"
              value={(params.objective_terms ?? [])
                .map((term) => `${term.id} ${term.value}`)
                .join(" → ")}
            />
          )}
        </dl>
      </details>
    </section>
  );
}

type EmptyRange = { constraint_id: string; kind: string; index: Record<string, string> };

function emptyRangeWhere(item: EmptyRange, labels: Run["labels"]): string {
  const keys = Object.values(item.index);
  if (keys.length === 0) return "";
  const named = keys.map((key) => {
    for (const table of Object.values(labels)) {
      if (key in table) return table[key];
    }
    return key;
  });
  return ` at ${named.join(" · ")}`;
}

function outcomeLead(data: Run): string | null {
  if (data.status !== "optimal" && data.status !== "feasible") return null;
  const hard = data.constraints.filter((c) => c.hard);
  const soft = data.constraints.filter((c) => !c.hard);
  if (hard.length === 0 && soft.length === 0) return null;
  const hardBroke = hard.filter((c) => !c.satisfied).length;
  const softBent = soft.filter((c) => !c.satisfied).length;
  const paid = soft.reduce((sum, c) => sum + c.penalty_paid, 0);
  const parts: string[] = [
    hardBroke === 0
      ? "All mandatory rules held."
      : `${hardBroke} mandatory ${hardBroke === 1 ? "rule" : "rules"} broke.`,
  ];
  if (soft.length > 0) {
    parts.push(
      paid > 0
        ? `${softBent} ${softBent === 1 ? "preference" : "preferences"} bent, at cost ${paid}.`
        : "Every preference held."
    );
  }
  return parts.join(" ");
}

/**
 * Why there is no answer.
 *
 * `infeasible` on its own tells a planner what they already know: they cannot
 * build the roster. The rules that cannot hold together, and the days they
 * collide on, are what they can act on -- so this is the loudest thing on an
 * infeasible run, above the rule list and the (empty) roster.
 *
 * `minimal` is not a detail. When the search proved irreducibility, "relax
 * any one of these and it solves" is a promise the platform can make. When it
 * was cut short, the same list is only a set that conflicts somewhere, and
 * saying the stronger thing would send someone to relax a rule that changes
 * nothing.
 */
/** How a conflict was found, as the run recorded it (`diagnose.explain`). */
type ConflictFinding = { conflict_method?: string; conflict_probes?: number; conflict_seconds?: number };

/** One sentence on how the list was found and what it cost, for a planner:
 * which reasoning proposed it, and how many times the model was solved again
 * to make sure of it. Null for runs from before it was recorded. */
export function howFound(found: ConflictFinding, solver: string | null): string | null {
  const checks = found.conflict_probes;
  if (checks === undefined) return null;
  const cost = `${checks} ${checks === 1 ? "check" : "checks"}${
    found.conflict_seconds !== undefined ? `, ${found.conflict_seconds < 0.01 ? "under 0.01" : found.conflict_seconds} s` : ""
  }`;
  const by = solver ? ` with ${solverName(solver)}` : "";
  switch (found.conflict_method) {
    case "cp-sat":
      return `Found from CP-SAT's own reasoning about why no answer exists, then each rule checked by solving again${by} (${cost}).`;
    case "iis":
      return `Found from HiGHS's analysis of the model, then each rule checked by solving again${by} (${cost}).`;
    default:
      return `Found by solving the model again${by}, leaving rules out one at a time (${cost}).`;
  }
}

function solverName(solver: string): string {
  return solver.split(" ")[0].replace(/^cp-sat$/, "CP-SAT").replace(/^glop$/, "GLOP").replace(/^highs$/, "HiGHS").replace(/^scip$/, "SCIP");
}

function Conflict({
  runId,
  scenarioId,
  items,
  minimal,
  labels,
  sets,
  notes,
  found,
  solver,
}: {
  runId: Id;
  scenarioId: Id;
  items: ConflictItem[];
  minimal: boolean | null;
  labels: Run["labels"];
  sets: Record<string, string[]>;
  notes: Record<string, string>;
  found: ConflictFinding;
  solver: string | null;
}) {
  const { can } = useCapabilities();
  const scenario = useScenario(scenarioId);
  const create = useCreateScenario();
  const toast = useToast();
  const byRule = new Map<string, string[][]>();
  for (const item of items) {
    byRule.set(item.constraint_id, [...(byRule.get(item.constraint_id) ?? []), item.instance]);
  }

  function soften() {
    if (!scenario.data) return;
    const patch: Record<string, number> = {};
    for (const id of byRule.keys()) patch[id] = 100;
    create.mutate(
      {
        problem_id: scenario.data.problem_id,
        model_version_id: scenario.data.model_version_id,
        name: `from run ${runId}`,
        patch: { soften: patch },
      },
      {
        onSuccess: (created) => {
          toast.success(`Created scenario “${created.name}”: these rules are now preferences.`);
        },
        onError: (error: unknown) => toast.error(formatApiError(error)),
      }
    );
  }

  return (
    <section className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3">
      <h3 className="mb-1 text-sm font-semibold text-amber-900">Why there is no answer</h3>
      <p className="mb-3 text-sm text-amber-900">
        {minimal
          ? "These rules cannot all hold at once. Every one of them is needed for the clash: relax or remove any single one and the model can be solved."
          : "These rules cannot all hold at once. The search stopped before it could narrow the list, so some of them may not be needed."}
      </p>
      {howFound(found, solver) && <p className="mb-3 text-xs text-amber-800">{howFound(found, solver)}</p>}
      <ul className="space-y-2">
        {[...byRule.entries()].map(([rule, instances]) => (
          <li key={rule} className="text-sm">
            {/* The author's words first; the id is how to find it in the model. */}
            {notes[rule] ? (
              <>
                <span className="font-medium text-amber-950">{notes[rule]}</span>{" "}
                <span className="font-mono text-xs text-amber-800">({rule})</span>
              </>
            ) : (
              <span className="font-mono text-amber-900">{rule}</span>
            )}
            <ul className="mt-1 flex flex-wrap gap-2">
              {instances.map((instance) => (
                <li
                  key={instance.join("\u0001")}
                  className="rounded border border-amber-200 bg-white px-2 py-1 text-xs text-amber-900"
                >
                  {instance.length > 0
                    ? naming(labels, sets[rule])(instance).join(" · ")
                    : "the rule as a whole"}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      {can("model.publish") && scenario.data && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={soften}
            disabled={create.isPending}
            className="rounded-md bg-amber-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-900 disabled:opacity-60"
          >
            {create.isPending ? "Creating…" : "Make these preferences"}
          </button>
          <span className="text-xs text-amber-900">
            Creates a scenario that softens the fighting rules. Solve it from the Scenarios page.
          </span>
        </div>
      )}
    </section>
  );
}

const FRONT = { width: 420, height: 240, pad: 44 };

/**
 * The trade-off front: one goal across, the other up, each point an answer
 * neither goal can improve on without the other giving way. Each point is
 * its own run -- the chart and the list under it open it.
 */
export function TradeOff({
  points,
  terms,
  onOpen,
}: {
  points: ParetoPoint[];
  terms: string[];
  onOpen?: (id: Id) => void;
}) {
  const xs = points.map((p) => p.first);
  const ys = points.map((p) => p.second);
  const span = (values: number[]) => {
    const low = Math.min(...values);
    const high = Math.max(...values);
    return { low, high, width: high - low || 1 };
  };
  const [sx, sy] = [span(xs), span(ys)];
  const inner = { w: FRONT.width - 2 * FRONT.pad, h: FRONT.height - 2 * FRONT.pad };
  const x = (v: number) => FRONT.pad + ((v - sx.low) / sx.width) * inner.w;
  const y = (v: number) => FRONT.pad + (1 - (v - sy.low) / sy.width) * inner.h;
  const [first, second] = terms;
  // Six significant figures: a solver's 4.99998562 is the 5 it was held to.
  const shown = (value: number) => String(Number(value.toPrecision(6)));
  const say = (p: ParetoPoint) =>
    `Point ${p.seq}: ${first} ${shown(p.first)}, ${second} ${shown(p.second)}${p.status === "optimal" ? "" : " (not proven)"}`;

  return (
    <section className="mb-4 rounded-md border border-slate-200 p-3">
      <h3 className="mb-1 text-sm font-semibold text-slate-900">The trade-off between {first} and {second}</h3>
      <p className="mb-2 text-sm text-slate-700">
        Each point is an answer where neither goal can get better without the other getting worse. Choose one
        to open its answer.
      </p>
      <svg
        role="img"
        aria-label={`Trade-off front, ${points.length} points`}
        viewBox={`0 0 ${FRONT.width} ${FRONT.height}`}
        className="w-full max-w-md"
      >
        <line x1={FRONT.pad} y1={FRONT.height - FRONT.pad} x2={FRONT.width - FRONT.pad} y2={FRONT.height - FRONT.pad} stroke="#94a3b8" />
        <line x1={FRONT.pad} y1={FRONT.pad} x2={FRONT.pad} y2={FRONT.height - FRONT.pad} stroke="#94a3b8" />
        <text x={FRONT.width / 2} y={FRONT.height - 8} textAnchor="middle" fontSize="11" fill="#475569">
          {first}
        </text>
        <text x={12} y={FRONT.height / 2} textAnchor="middle" fontSize="11" fill="#475569" transform={`rotate(-90 12 ${FRONT.height / 2})`}>
          {second}
        </text>
        <polyline
          fill="none"
          stroke="#93c5fd"
          points={points.map((p) => `${x(p.first)},${y(p.second)}`).join(" ")}
        />
        {points.map((p) => (
          <circle
            key={p.seq}
            cx={x(p.first)}
            cy={y(p.second)}
            r={6}
            fill={p.status === "optimal" ? "#2563eb" : "#f59e0b"}
            className={onOpen && p.run_id != null ? "cursor-pointer" : undefined}
            onClick={() => p.run_id != null && onOpen?.(p.run_id)}
          >
            <title>{say(p)}</title>
          </circle>
        ))}
      </svg>
      <ol className="mt-2 space-y-1 text-sm">
        {points.map((p) => (
          <li key={p.seq}>
            {onOpen && p.run_id != null ? (
              <button type="button" className="text-blue-700 underline" onClick={() => onOpen(p.run_id as number)}>
                {say(p)}
              </button>
            ) : (
              say(p)
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

function ConstraintRow({ outcome }: { outcome: ConstraintOutcome }) {
  return (
    <li className="rounded border border-slate-200 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-slate-900">{outcome.label}</span>
        <span className="text-xs text-slate-500">{outcome.hard ? "must hold" : "can bend"}</span>
        {outcome.satisfied ? (
          <span className="rounded bg-green-100 px-2 py-0.5 text-xs text-green-900">held</span>
        ) : (
          <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">
            short by {outcome.total_violation}
            {outcome.penalty_paid > 0 && ` (cost ${outcome.penalty_paid})`}
          </span>
        )}
        {outcome.slack != null && outcome.satisfied && (
          <span className="text-xs text-slate-500">
            {outcome.slack === 0 ? "no room left" : `room ${outcome.slack}`}
          </span>
        )}
        {outcome.dual != null && outcome.dual !== 0 && (
          <span className="text-xs text-slate-500">worth {outcome.dual} on the goal</span>
        )}
      </div>
      {outcome.violations.length > 0 && (
        <ul className="mt-1 flex flex-wrap gap-2">
          {outcome.violations.map((v) => (
            <li key={v.index.join("\u0001")} className="text-xs text-slate-600">
              <span className="font-mono">{v.index.join(" · ")}</span> short by {v.by}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium text-slate-900">{value}</dd>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">{children}</div>
  );
}

function Failed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <p className="whitespace-pre-line">{formatApiError(error)}</p>
      <button type="button" onClick={onRetry} className="mt-2 rounded py-1 text-red-900 underline">
        Retry
      </button>
    </div>
  );
}
