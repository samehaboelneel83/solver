import { useEffect, useId, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { useEntityList } from "../api/entities";
import { formatApiError } from "../api/errors";
import {
  useCreateRun,
  useRun,
  useRuns,
  useScenarios,
  type ConstraintOutcome,
  type Id,
  type Run,
  type RunStatus,
} from "../api/v1";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";
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
  error: "bg-red-100 text-red-900",
  unknown: "bg-slate-100 text-slate-700",
  queued: "bg-slate-100 text-slate-700",
  running: "bg-blue-100 text-blue-900",
};

/** What each status means, in a planner's terms rather than a solver's. */
const STATUS_NOTE: Record<RunStatus, string> = {
  optimal: "Best possible answer, proven.",
  feasible: "An answer, found before the time limit -- not proven best.",
  infeasible: "No answer exists: the rules cannot all hold at once.",
  error: "The model could not be solved. The reason is below.",
  unknown: "The solver stopped without deciding. Try a longer time limit.",
  queued: "Waiting to start.",
  running: "Solving.",
};

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
        <ScenarioRuns key={scenario.id} scenarioId={scenario.id} scenarioName={scenario.name} />
      ) : null}
    </>
  );
}

function ScenarioRuns({ scenarioId, scenarioName }: { scenarioId: Id; scenarioName: string }) {
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
  const [failure, setFailure] = useState<string | null>(null);

  const items = runs.data?.items ?? [];
  const selected = openId ?? items[0]?.id ?? null;

  function solve() {
    setFailure(null);
    createRun.mutate(
      { scenarioId, body: { time_limit_s: 30 } },
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
        <button
          type="button"
          onClick={solve}
          disabled={createRun.isPending}
          className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {createRun.isPending ? "Queueing…" : `Solve ${scenarioName}`}
        </button>
        <span className="text-sm text-slate-500">
          {createRun.isPending
            ? "Queueing…"
            : "A worker solves it; this page follows along. The answer is kept, not recomputed."}
        </span>
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

          {selected !== null && <RunDetail id={selected} />}
        </>
      )}
    </>
  );
}

function RunDetail({ id }: { id: Id }) {
  const run = useRun(id);

  if (run.isLoading) return <Skeleton rows={4} cols={3} />;
  if (run.isError && !run.data) return <Failed error={run.error} onRetry={() => run.refetch()} />;
  const data = run.data;
  if (!data) return null;

  const roster = data.assignments ?? {};
  const broken = data.constraints.filter((c) => !c.satisfied);

  return (
    <section aria-labelledby={`run-${id}-heading`} className="mt-6 rounded-md border border-slate-200 bg-white p-4">
      <h2 id={`run-${id}-heading`} className="mb-1 text-base font-semibold text-slate-900">
        Run {String(id)}
      </h2>
      <p className="mb-4 text-sm text-slate-600">{STATUS_NOTE[data.status]}</p>

      {data.error && (
        <p role="alert" className="mb-4 whitespace-pre-line rounded bg-red-50 p-3 text-sm text-red-800">
          {data.error}
        </p>
      )}

      <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        <Fact label="Objective" value={data.objective === null ? "—" : String(data.objective)} />
        <Fact label="Solved in" value={data.wall_time_s === null ? "—" : `${data.wall_time_s}s`} />
        <Fact label="Solver" value={data.solver_version ?? data.solver} />
        <Fact label="Data" value={`dataset ${String(data.dataset_id)}`} />
      </dl>

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

      {Object.entries(roster).map(([variable, tuples]) => (
        <div key={variable}>
          <h3 className="mb-2 text-sm font-semibold text-slate-900">
            {variable} &mdash; {tuples.length} chosen
          </h3>
          <ul className="flex flex-wrap gap-2">
            {tuples.map((tuple) => (
              <li
                key={tuple.join("\u0001")}
                className="rounded border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-xs text-slate-700"
              >
                {tuple.join(" · ")}
              </li>
            ))}
          </ul>
        </div>
      ))}
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
