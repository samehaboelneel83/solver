import LoadFailure from "../components/LoadFailure";
import Pager from "../components/Pager";
import SearchBox, { NoMatches } from "../components/SearchBox";
import { useEffect, useId, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import ProblemPicker from "../components/ProblemPicker";
import { useDomainProblem } from "../hooks/useDomainProblem";
import { formatApiError } from "../api/errors";
import {
  useCancelRun,
  useCreateRun,
  useCreateScenario,
  usePreflight,
  useUpdateScenario,
  type Preflight,
  type PreflightFinding,
  useRun,
  useRunEta,
  type RunEta,
  useRunComparison,
  useRuns,
  useVersion,
useScenario,
  useScenarios,
  useSolvers,
  type ConflictItem,
  type ModelStructure,
  type AlternativePlan,
  type ParetoPoint,
  type ConstraintOutcome,
  type Id,
  type Run,
  type RunStatus,
  type ComputedSource,
} from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";
import { resolveById } from "../lib/selection";
import ContextMismatch from "../components/ContextMismatch";
import RunProgress from "../components/RunProgress";
import { useToast } from "../components/ToastProvider";
import RunViews from "../components/RunViews";
import PlannerPanel from "../components/PlannerPanel";
import SpreadView from "../components/SpreadView";
import GuidedRunView from "../components/GuidedRunView";
import ApprovePlanPanel from "../components/ApprovePlanPanel";
import { RunMapView } from "../genui/components/SpatialMap";

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

/** A two-stage stochastic run's record (queue R7). */
export type StochasticRecord = {
  samples: number;
  stage_two: string[];
  expected: number | null;
  /** `costs`: each fresh future's cost, sorted (queue R17b), for the spread. */
  out_of_sample?: { futures: number; mean: number | null; ci95: number | null; unmet: number; costs?: number[] };
  /** Per chance rule (queue R8): the share of futures asked for, and the share it held in out of sample. */
  chance?: Record<string, { asked: number; held: number; held_in_sample?: number }>;
};

/** What the plan is likely to be worth on futures it was not chosen for. */
export function stochasticOutlook(record: StochasticRecord): string {
  const out = record.out_of_sample;
  if (!out || out.mean === null) return "It could not be costed on fresh futures.";
  const unmet = out.unmet > 0 ? ` It cannot meet ${out.unmet} of them at all.` : "";
  const percent = (share: number) => `${Number((share * 100).toPrecision(3))}%`;
  const chances = Object.entries(record.chance ?? {})
    .map(([rule, c]) => ` ${rule} held in ${percent(c.held)} of them (asked: ${percent(c.asked)}).`)
    .join("");
  const short = Object.values(record.chance ?? {}).some((c) => c.held < c.asked);
  const advice = short && record.samples < 50
    ? ` ${record.samples} futures are few to promise that from: asking for more (up to 50) makes the plan firmer.`
    : "";
  return `On ${out.futures} fresh futures it averages ${Number(out.mean.toPrecision(6))}, give or take ${Number((out.ci95 ?? 0).toPrecision(3))} (95%).${unmet}${chances}${advice}`;
}

/** The learned selector's record on a run (queue R11): its pick beside the solver that ran. */
export type SelectorRecord = {
  pick: string; confidence: number; confident: boolean; like: string[]; chosen: string; agree: boolean;
  /** It chose the solver (setting `solve.selector_acts`, Epic engine E-4), over `rules_chose`. */
  acted?: boolean; rules_chose?: string;
};

/** In a few words: what it would pick, or -- when allowed to act -- what it picked over the rules. */
export function selectorText(record: SelectorRecord): string {
  const vote = `${Math.round(record.confidence * 100)}% of its nearest models`;
  if (record.acted) return `picked ${record.pick} over the rules' ${record.rules_chose} (${vote}, like ${record.like.join(", ")})`;
  return record.agree
    ? `would also pick ${record.pick} (${vote}, like ${record.like.join(", ")})`
    : `would pick ${record.pick} instead of ${record.chosen} (${vote}, like ${record.like.join(", ")})`;
}

/** The metaheuristic lane (queue R14), in words. */
const SEARCH_NAMES: Record<string, string> = {
  ga: "a genetic algorithm",
  "cma-es": "an evolution strategy (CMA-ES)",
  pso: "a particle swarm",
};

/** What `solve.metaheuristic` (queue R14) did after the exact solver ended with nothing. */
export type MetaheuristicRecord =
  | { used: true; method: string; after: string; seconds: number; status: string; objective: number | null; kept: boolean; exact_failed?: string }
  | { used: false; why: string };

export function metaheuristicText(record: MetaheuristicRecord): string {
  if (!record.used) return `not searched: ${record.why}`;
  const method = SEARCH_NAMES[record.method] ?? record.method;
  return record.kept
    ? `${method} for ${record.seconds}s after ${record.after} ended with no answer`
    : `${method} for ${record.seconds}s after ${record.after}: nothing that keeps every rule`;
}

/** What the platform computed from the map for this run (queue R16a), in a line per input. */
export function computedText(inputs: (ComputedSource & { input: string; name: string })[]): string {
  return inputs
    .map((i) => {
      const timed = i.max_min !== undefined || i.unit === "s" || i.unit === "min";
      const how = i.metric.startsWith("road") ? (timed ? "road travel time" : "along the roads") : "straight line";
      const gaps = i.no_road ? `, ${i.no_road} pairs with no road left far` : "";
      return i.kind === "within"
        ? `${i.name}: ${i.from} to ${i.to} within ${i.max_min !== undefined ? `${i.max_min} min` : `${Number(((i.max_m ?? 0) / 1000).toPrecision(3))} km`}, ${how}, ${i.computed_at.slice(0, 10)}`
        : `${i.name}: ${i.from} to ${i.to} in ${i.unit ?? "m"}, ${how}${i.nearest ? `, nearest ${i.nearest} kept` : ""}${gaps}, ${i.computed_at.slice(0, 10)}`;
    })
    .join("; ");
}

/** What `solve.routing_start` (queue R15b) did: the routes the exact solver started from, or why none. */
export type RoutingStartRecord =
  | { used: true; stops: number; vehicles: number; used_vehicles?: number; feasible: boolean; objective?: number; seconds: number; why?: string }
  | { used: false; why: string };

export function routingStartText(record: RoutingStartRecord): string {
  if (!record.used) return `none: ${record.why}`;
  if (!record.feasible) return `no routes: ${record.why ?? "the routing search found none that keep every rule"}`;
  return `routes for ${record.stops - 1} stops on ${record.used_vehicles ?? record.vehicles} of ${record.vehicles} vehicles from the routing search in ${record.seconds}s (goal ${record.objective})`;
}

/** What `solve.connected_start` (queue R13) did: the start the solver was handed, or why none. */
export type ConnectedStartRecord =
  | { used: true; groups: number; units: number; feasible: boolean; objective: number; breach: number; seconds: number }
  | { used: false; why: string };

export function connectedStartText(record: ConnectedStartRecord): string {
  if (!record.used) return `none: ${record.why}`;
  return record.feasible
    ? `${record.groups} connected, balanced groups of ${record.units} built in ${record.seconds}s (goal ${record.objective})`
    : `${record.groups} connected groups of ${record.units}, short of the rules by ${record.breach} -- the solver repaired from there`;
}

/** A run's model structure (queue R4) in a few words: the input to a decomposition. */
export function structureText(found: ModelStructure): string {
  if (found.linking_rules === 0) return `${found.blocks} independent parts`;
  return `${found.blocks} parts by ${found.by ?? "?"}, tied by ${found.linking_rules} ${found.linking.join(", ")}`;
}

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
  /** An approximate optimum's tolerance (PDLP), or the stochastic record (R7), on the run. */
  params?: { tolerance?: number; stochastic?: StochasticRecord } | Record<string, unknown>;
}): string {
  if (run.status === "feasible" && run.stopped) {
    return typeof run.gap === "number"
      ? `Stopped on request. The best answer found by then -- at most ${formatGap(run.gap)} worse than the best possible.`
      : "Stopped on request. The best answer found by then -- not proven best.";
  }
  const searched = (run.params as { metaheuristic_run?: MetaheuristicRecord } | undefined)?.metaheuristic_run;
  const chosen = (run.params as { chosen_solver?: string } | undefined)?.chosen_solver;
  if (run.status === "feasible" && ((searched?.used && searched.kept) || (chosen && chosen in SEARCH_NAMES))) {
    const method = SEARCH_NAMES[searched?.used ? searched.method : (chosen as string)] ?? "a search";
    return (
      `Found by ${method}` +
      (searched?.used ? `, after ${searched.after} ended with no answer` : "") +
      ": an answer that keeps every rule, but nothing says how far it is from the best."
    );
  }
  const routed = (run.params as { routing_start_run?: { answer?: boolean } } | undefined)?.routing_start_run;
  if (run.status === "feasible" && routed?.answer) {
    return (
      "The routes the routing search found: the solver ended with nothing better. " +
      "Every stop is visited within each vehicle's load, but the routes are not proven the shortest -- a longer time limit may improve them."
    );
  }
  const started = (run.params as { connected_start_run?: { answer?: boolean } } | undefined)?.connected_start_run;
  if (run.status === "feasible" && started?.answer) {
    return (
      "The connected, balanced start the solver was given: it ended with nothing better. " +
      "An answer that keeps every rule, but not proven the best -- a longer time limit may improve it."
    );
  }
  if (run.status === "feasible" && typeof run.gap === "number") {
    return `An answer, found before the time limit -- at most ${formatGap(run.gap)} worse than the best possible.`;
  }
  const stochastic = (run.params as { stochastic?: StochasticRecord } | undefined)?.stochastic;
  const rolled = (run.params as { rolling_horizon_run?: { used?: boolean; windows?: number; time_set?: string } } | undefined)
    ?.rolling_horizon_run;
  if (run.status === "feasible" && rolled?.used) {
    return (
      `Planned ${rolled.windows} stretches of ${rolled.time_set} one at a time, each with the later ones loosened: ` +
      "an answer that keeps every rule, but not proven the best -- solving the whole horizon at once is how to find out."
    );
  }
  if (run.status === "optimal" && run.optimality === "approximate" && stochastic) {
    return (
      `The best plan for ${stochastic.samples} sampled futures -- what to decide now` +
      (stochastic.stage_two.length
        ? `; ${stochastic.stage_two.join(", ")} ${stochastic.stage_two.length === 1 ? "waits" : "wait"} for the data. `
        : ". ") +
      stochasticOutlook(stochastic)
    );
  }
  if (run.status === "optimal" && run.optimality === "approximate") {
    const tolerance = run.params?.tolerance;
    return (
      `Optimal to within ${typeof tolerance === "number" ? `a tolerance of ${tolerance}` : "a small tolerance"} -- ` +
      "very close to the best possible, but not proven the best. A method for very large models answered it; " +
      "an exact solver proves the optimum when the model is small enough."
    );
  }
  const bounded = (run.params as { global_bound_run?: { used?: boolean; proven?: boolean; gap?: number | null } } | undefined)
    ?.global_bound_run;
  if (run.status === "optimal" && run.optimality === "global" && bounded?.proven) {
    return "Best possible answer, proven: the best of several starts, and SCIP's global bound shows no answer does better.";
  }
  if (run.status === "optimal" && run.optimality === "local" && bounded?.used && typeof bounded.gap === "number") {
    return (
      `The best answer from several starts -- a local optimum, at most ${formatGap(bounded.gap)} worse than the best possible, ` +
      "by SCIP's global bound. A longer time limit lets SCIP narrow that."
    );
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

function ForDomain({ domainId }: { domainId: Id }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const route = useParams();
  const scenarioChooser = useId();

  const found = useDomainProblem(domainId, searchParams.get("problem"));
  const problem = found.state === "ready" ? found.problem : null;
  const problemId = problem ? Number(problem.id) : null;

  const scenarios = useScenarios(problemId, { limit: 500, offset: 0 });
  const scenarioItems = scenarios.data?.items ?? [];
  const requestedScenario = parseRouteId(searchParams.get("scenario"));
  const { item: scenario, missing: scenarioMissing } = resolveById(
    scenarioItems,
    requestedScenario,
    (row) => row.id
  );

  if (found.state === "offline") return <OfflineNotice subject="The problem list" />;
  if (found.state === "loading") return <Skeleton rows={3} cols={4} />;
  if (found.state === "failed") return <Failed subject={found.subject} error={found.error} onRetry={found.retry} />;

  if (found.state === "mismatch") {
    return (
      <ContextMismatch
        title="This problem is not available here"
        detail="The link asked for a problem that is missing or belongs to another domain. Nothing was substituted."
        parentHref="/public/problem"
        parentLabel="Open problems in this domain"
      />
    );
  }

  if (found.state === "empty") {
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

  if (!scenarios.isLoading && scenarioMissing) {
    return (
      <ContextMismatch
        title="This scenario is not available here"
        detail="The link asked for a scenario that is missing or belongs to another problem. Nothing was substituted."
        parentHref={`/scenarios?problem=${problemId}`}
        parentLabel="Open scenarios for this problem"
      />
    );
  }

  return (
    <>
      <div className="mb-4 grid gap-4 sm:grid-cols-2">
        <ProblemPicker
          domainId={domainId}
          current={found.problem}
          firstPage={found.firstPage}
          total={found.total}
          onChoose={(id) => route.domainId
            ? navigate(`/domains/${domainId}/problems/${id}/runs`)
            : setSearchParams({ problem: id }, { replace: true })}
        />
        <div>
          <label htmlFor={scenarioChooser} className="block text-sm font-medium text-slate-700">
            Scenario
          </label>
          <select
            id={scenarioChooser}
            className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
            value={scenario ? String(scenario.id) : ""}
            disabled={scenarioItems.length === 0}
            onChange={(event) => route.domainId
              ? navigate(`/domains/${domainId}/problems/${problemId}/runs?scenario=${event.target.value}`)
              : setSearchParams(
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
          problemId={problemId!}
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
        // A scheduling or connected rule has no left or right: it is
        // expressed differently, and solves.
        rule.no_overlap === undefined &&
        rule.cumulative === undefined &&
        rule.connected === undefined
    )
    .map((rule) => String(rule.id ?? "?"));
}

function ScenarioRuns({
  scenarioId,
  scenarioName,
  modelVersionId,
  problemId,
}: {
  scenarioId: Id;
  scenarioName: string;
  modelVersionId: Id;
  problemId: Id;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { can } = useCapabilities();
  const version = useVersion(modelVersionId);
  const unexpressed = unexpressedRules(version.data?.ir);
  // A robust solve needs a parameter declared uncertain within a range.
  const uncertain = Object.values(
    ((version.data?.ir as { parameters?: Record<string, { uncertainty?: { kind?: string } }> } | undefined)
      ?.parameters ?? {})
  ).some((spec) => spec.uncertainty?.kind === "interval");
  // A trade-off front needs a goal of exactly two terms (app.solve.pareto).
  const twoGoals =
    ((version.data?.ir as { objective?: { terms?: unknown[] } } | undefined)?.objective?.terms ?? []).length === 2;
  // Alternatives are told apart by yes-or-no and bounded whole-number
  // decisions (app.solve.alternatives).
  const hasChoices = Object.values(
    ((version.data?.ir as { variables?: Record<string, { domain?: string; lower?: unknown; upper?: unknown }> } | undefined)?.variables ?? {})
  ).some((spec) => (spec.domain ?? "binary") === "binary"
    || (spec.domain === "integer" && typeof spec.lower === "number" && typeof spec.upper === "number"));
  // How many decisions each alternative changes from every other plan.
  const [apart, setApart] = useState("1");
  const solvers = useSolvers();
  const [solver, setSolver] = useState<string>("");
  // Before a run (Epic UX, U-5): what would stop it, which solvers fit, whether a worker is there.
  const preflightQuery = usePreflight(scenarioId);
  const moveScenario = useUpdateScenario();
  // Only a whole answer is acted on; a server from before the preflight existed simply has none.
  const preflight = { data: Array.isArray(preflightQuery.data?.solvers) && Array.isArray(preflightQuery.data?.findings)
    ? preflightQuery.data : undefined };
  const fits = new Map((preflight.data?.solvers ?? []).map((row) => [row.name, row]));
  const blockers = (preflight.data?.findings ?? []).filter((finding) => finding.kind === "blocker" &&
    // A model the rules give no solver may still be solved by one asked for by name.
    !(finding.code === "no_solver" && solver !== "" && fits.get(solver)?.fits));
  const blocked = blockers.length > 0;
  const [runQuery, setRunQuery] = useState("");
  const [runOffset, setRunOffset] = useState(0);
  const runs = useRuns(scenarioId, { limit: PAGE_SIZE, offset: runOffset, q: runQuery });
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
  const [againstId, setAgainstId] = useState<Id | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const items = runs.data?.items ?? [];
  const requestedRun = parseRouteId(searchParams.get("run"));
  // A Pareto point or an older run need not be in the first page of history.
  // Resolve explicit ids directly and verify ownership rather than substituting.
  const requestedDetail = useRun(requestedRun);
  const runMissing = requestedRun !== null && requestedDetail.data !== undefined &&
    requestedDetail.data.scenario_id !== scenarioId;
  const selected = requestedRun === null ? items[0]?.id ?? null
    : requestedDetail.data && !runMissing ? requestedRun : null;
  const navigate = useNavigate();
  const route = useParams();
  const tab = searchParams.get("tab") === "guided" ? "guided" : "summary";

  function setRunSelection(runId: Id | null, nextTab: "summary" | "guided" = tab) {
    const next = new URLSearchParams(searchParams);
    next.set("problem", String(problemId));
    next.set("scenario", String(scenarioId));
    if (runId === null) next.delete("run");
    else next.set("run", String(runId));
    if (nextTab === "guided") next.set("tab", "guided");
    else next.delete("tab");
    if (route.domainId && route.problemId) {
      const base = `/domains/${route.domainId}/problems/${problemId}/runs`;
      navigate({ pathname: runId === null ? base : `${base}/${runId}`, search: next.toString() });
    } else setSearchParams(next, { replace: true });
  }

  // Comparing is only offered once there is something to compare with.
  const comparable = items.filter((row) => row.id !== selected);
  const against = comparable.some((row) => row.id === againstId) ? againstId : null;

  function solve(how: "plain" | "front" | "robust" | "alternatives" = "plain") {
    setFailure(null);
    createRun.mutate(
      {
        scenarioId,
        body: {
          time_limit_s: 30,
          ...(solver ? { solver } : {}),
          ...(how === "front" ? { pareto_steps: 10 } : {}),
          ...(how === "robust" ? { robust: true } : {}),
          ...(how === "alternatives" ? {
            alternatives: ALTERNATIVES,
            alternatives_within: 0.05,
            ...(Number(apart) > 1 ? { alternatives_min_changes: Math.min(50, Number(apart)) } : {}),
          } : {}),
        },
      },
      {
        onSuccess: (run: Run) => {
          setRunSelection(run.id, tab);
          toast.success(`Run ${run.id}: ${run.status}`);
        },
        onError: (error: unknown) => setFailure(formatApiError(error)),
      }
    );
  }

  return (
    <>
      {preflight.data && <BeforeYouSolve preflight={preflight.data} blockers={blockers} moving={moveScenario.isPending}
        onMoveTo={can("model.publish") ? (versionId) => moveScenario.mutate({ id: scenarioId, body: { model_version_id: versionId } }, {
          onSuccess: () => toast.success("The scenario now solves the latest version."),
          onError: (error: unknown) => setFailure(formatApiError(error)),
        }) : undefined} />}
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
            disabled={createRun.isPending || blocked}
            className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {createRun.isPending ? "Queueing…" : `Solve ${scenarioName}`}
          </button>
          {twoGoals && (
            <button
              type="button"
              onClick={() => solve("front")}
              disabled={createRun.isPending || blocked}
              className="rounded-md border border-blue-600 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-60"
            >
              Show the trade-off between its two goals
            </button>
          )}
          {hasChoices && (
            <span className="inline-flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => solve("alternatives")}
                disabled={createRun.isPending || blocked}
                className="rounded-md border border-blue-600 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-60"
              >
                Solve, with {ALTERNATIVES} alternative plans
              </button>
              <label className="inline-flex items-center gap-1 text-sm text-slate-600">
                each differing in at least
                <input
                  inputMode="numeric"
                  className="w-12 rounded border border-slate-300 px-2 py-1 text-slate-900"
                  value={apart}
                  onChange={(event) => setApart(event.target.value.replace(/\D/g, "").slice(0, 2))}
                />
                {apart === "1" ? "decision" : "decisions"}
              </label>
            </span>
          )}
          {uncertain && (
            <button
              type="button"
              onClick={() => solve("robust")}
              disabled={createRun.isPending || blocked}
              className="rounded-md border border-blue-600 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-60"
            >
              Solve robustly
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
            {preflight.data
              // Every solver, with the ones that cannot take this model shown disabled and why (Epic UX, U-5).
              ? preflight.data.solvers.map((row) => (
                <option key={row.name} value={row.name} disabled={!row.fits}>
                  {row.name}{row.chosen ? " (the rules' choice)" : ""}{row.fits ? "" : ` — ${row.why}`}
                </option>
              ))
              : (solvers.data?.items ?? [])
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
              : `${preflight.data ? `${preflight.data.workers.says}. ` : "A worker solves it. "}This page follows along; stop a run if you asked the wrong question. The answer is kept, not recomputed.`}
          </span>
        )}
      </div>

      {failure && (
        <p role="alert" className="mb-4 whitespace-pre-line text-sm text-red-600">
          {failure}
        </p>
      )}

      {requestedRun !== null && requestedDetail.isError && (
        <Failed subject="The linked run" error={requestedDetail.error} onRetry={() => requestedDetail.refetch()} />
      )}
      {requestedRun !== null && requestedDetail.isLoading && <p role="status">Loading selected run…</p>}
      {(runQuery || (runs.data?.total ?? 0) > PAGE_SIZE) && (
        <div className="mb-3">
          <SearchBox label="runs" initial={runQuery} onSearch={(text) => { setRunQuery(text); setRunOffset(0); }} />
        </div>
      )}
      {runs.isError ? (
        <Failed subject="The run history" error={runs.error} onRetry={() => runs.refetch()} />
      ) : runs.isLoading && !runs.data ? (
        <Skeleton rows={3} cols={4} />
      ) : items.length === 0 && runQuery ? (
        <NoMatches label="runs" q={runQuery} />
      ) : items.length === 0 && requestedRun === null ? (
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
                      onClick={() => setRunSelection(row.id)}
                      className="rounded py-1 text-blue-600 underline"
                    >
                      Run {String(row.id)}
                    </button>
                    {(row.part_runs?.length ?? 0) > 0 && (
                      <span className="block text-xs text-slate-500">
                        its plans are {runSpan(row.part_runs!)}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    <span className={`inline-block rounded px-2 py-1 text-xs ${STATUS_STYLE[row.status]}`}>
                      {row.status}
                    </span>
                  </td>
                  <td className="py-2 pr-3 font-mono">{row.objective == null ? "—" : formatGoal(row.objective)}</td>
                  <td className="py-2 pr-3">{row.wall_time_s === null ? "—" : `${row.wall_time_s}s`}</td>
                  <td className="py-2 text-slate-600">{row.solver_version ?? row.solver}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager label="Run" offset={runOffset} size={PAGE_SIZE} total={runs.data?.total ?? 0} onOffset={setRunOffset} />

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

          {!runs.isLoading && runMissing && (
            <div className="mt-6">
              <ContextMismatch
                title="This run is not available here"
                detail="The link asked for a run that is missing or belongs to another scenario. Nothing was substituted."
                parentHref={`/runs?problem=${problemId}&scenario=${scenarioId}`}
                parentLabel="Open runs for this scenario"
              />
            </div>
          )}

          {selected !== null && (
            <RunDetail
              id={selected}
              tab={tab}
              onOpen={(id) => setRunSelection(id)}
              onTab={(next) => setRunSelection(selected, next)}
            />
          )}
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
    return <Failed subject="The comparison" error={comparison.error} onRetry={() => comparison.refetch()} />;
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
      {data.claims && <p role="note" className="mb-4 rounded bg-amber-50 px-3 py-2 text-sm text-amber-900">{data.claims}</p>}

      <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        <Fact
          label={`Run ${String(left)} (${data.left.scenario_name})`}
          value={`${data.left.status}${data.left.objective === null ? "" : ` — ${formatGoal(data.left.objective)}`}`}
        />
        <Fact
          label={`Run ${String(right)} (${data.right.scenario_name})`}
          value={`${data.right.status}${data.right.objective === null ? "" : ` — ${formatGoal(data.right.objective)}`}`}
        />
        <Fact
          label={`Objective change, run ${String(left)} → run ${String(right)}`}
          value={
            data.objective_delta === null
              ? "— (one run has no objective)"
              : `${data.objective_delta > 0 ? "+" : ""}${formatGoal(data.objective_delta)}`
          }
        />
        <Fact label="Differs by" value={data.differs_by.length === 0 ? "nothing" : data.differs_by.join(", ")} />
        {([data.left, data.right] as const).map((side) => (
          <Fact key={`quality-${side.id}`} label={`Run ${String(side.id)}: how good`}
            value={[claimText(side.optimality), side.gap != null && side.gap > 0 ? `gap ${formatGap(side.gap)}` : null,
              side.solver, side.wall_time_s != null ? `${side.wall_time_s}s` : null, side.classified_as].filter(Boolean).join(" · ")} />
        ))}
      </dl>

      {data.rules.length > 0 && (
        <>
          <h3 className="mb-2 text-sm font-semibold text-slate-900">Rules that changed, run {String(left)} &rarr; run {String(right)}</h3>
          <ul className="mb-4 space-y-1 text-sm">
            {data.rules.map((rule) => (
              <li key={rule.constraint_id} className="rounded border border-slate-200 px-3 py-2">
                <span className="font-mono text-slate-900">{rule.constraint_id}</span>{" "}
                <span className="text-slate-600">
                  {rule.left_satisfied ? "held" : `short by ${formatGoal(rule.left_violation)}`} &rarr;{" "}
                  {rule.right_satisfied ? "held" : `short by ${formatGoal(rule.right_violation)}`}
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

function RunDetail({
  id,
  tab = "summary",
  onOpen,
  onTab,
}: {
  id: Id;
  tab?: "summary" | "guided";
  onOpen?: (id: Id) => void;
  onTab?: (tab: "summary" | "guided") => void;
}) {
  const run = useRun(id);
  const { can } = useCapabilities();
  const cancelRun = useCancelRun();
  const toast = useToast();
  const [stopFailure, setStopFailure] = useState<string | null>(null);

  if (run.isLoading) return <Skeleton rows={4} cols={3} />;
  if (run.isError && !run.data) return <Failed subject="The run" error={run.error} onRetry={() => run.refetch()} />;
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
    structure?: ModelStructure;
    selector?: SelectorRecord;
    connected_start_run?: ConnectedStartRecord;
    routing_start_run?: RoutingStartRecord;
    computed_inputs?: (ComputedSource & { input: string; name: string })[];
    metaheuristic_run?: MetaheuristicRecord;
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
      {unfinished && <ExpectedTime runId={id} />}
      {lead && <p className="mb-4 text-sm font-medium text-slate-900">{lead}</p>}
      {onTab && (
        <div className="mb-4 flex gap-1 border-b border-slate-200" role="tablist" aria-label="Run views">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "summary"}
            className={`px-3 py-2 text-sm ${tab === "summary" ? "border-b-2 border-blue-600 font-semibold text-blue-700" : "text-slate-600"}`}
            onClick={() => onTab("summary")}
          >
            Summary
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "guided"}
            className={`px-3 py-2 text-sm ${tab === "guided" ? "border-b-2 border-blue-600 font-semibold text-blue-700" : "text-slate-600"}`}
            onClick={() => onTab("guided")}
          >
            Guided view
          </button>
        </div>
      )}
      {tab === "guided" ? (
        <div className="mb-2">
          <GuidedRunView runId={Number(id)} />
        </div>
      ) : null}
      {tab !== "guided" && (
      <>
      <ApprovePlanPanel runId={id} scenarioId={data.scenario_id} status={data.status} />
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

      {/* A partition over cells with a shape: its answer is also a map. Any
          other run answers the map request 404 and nothing is shown. */}
      {(data.status === "optimal" || data.status === "feasible") && (
        <div className="mb-4">
          <RunMapView runId={id} quietIfNone />
        </div>
      )}

      {/* `robust` is the request's `true` until the run settles, then its report. */}
      {typeof (data.params as { robust?: unknown }).robust === "object" && (
        <Robustness report={(data.params as { robust: RobustReport }).robust} objective={data.objective} />
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

      {(data.alternatives?.length || (data.params as { alternatives_result?: unknown }).alternatives_result) && (
        <Alternatives
          plans={data.alternatives ?? []}
          result={(data.params as { alternatives_result?: AlternativesResult }).alternatives_result}
          best={data.objective}
          onOpen={onOpen}
        />
      )}
      {(data.params as { alternative_of?: number }).alternative_of != null && (
        <p className="mb-4 rounded bg-slate-50 p-3 text-sm text-slate-700">
          Alternative plan {String((data.params as { alternative?: number }).alternative ?? "")} of run{" "}
          {String((data.params as { alternative_of: number }).alternative_of)}.
          {onOpen && (
            <>
              {" "}
              <button
                type="button"
                className="underline"
                onClick={() => onOpen((data.params as { alternative_of: number }).alternative_of)}
              >
                Back to the best plan
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

      {(() => {
        // A stochastic plan's cost on each fresh future (queue R17b).
        const out = (data.params as { stochastic?: StochasticRecord } | undefined)?.stochastic?.out_of_sample;
        return out?.costs?.length && out.mean !== null ? (
          <SpreadView costs={out.costs} mean={out.mean} ci95={out.ci95 ?? 0} unmet={out.unmet} />
        ) : null;
      })()}
      {Object.keys(roster).length > 0 && <RunViews run={data} />}
      {/* Queue R28: hold part of the plan and solve the rest, ask why not, see how far numbers may move. */}
      {can("run.submit") && <PlannerPanel run={data} onOpen={onOpen} />}

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
          {params.selector && <Fact label={params.selector.acted ? "Learned selector (chose the solver)" : "Learned selector (not acting)"} value={selectorText(params.selector)} />}
          {params.structure && params.structure.blocks > 1 && (
            <Fact label="How it splits" value={structureText(params.structure)} />
          )}
          {params.connected_start_run && <Fact label="Started from" value={connectedStartText(params.connected_start_run)} />}
          {params.routing_start_run && <Fact label="Started from" value={routingStartText(params.routing_start_run)} />}
          {params.computed_inputs && params.computed_inputs.length > 0 && (
            <Fact label="Computed from the map" value={computedText(params.computed_inputs)} />
          )}
          {params.metaheuristic_run && <Fact label="Searched by" value={metaheuristicText(params.metaheuristic_run)} />}
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
      </>
      )}
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

type RobustReport = {
  rows: { rule: string; index: string[]; moving: number; gamma: number }[];
  nominal?: number | null;
  nominal_status?: string;
  price?: number;
  price_share?: number;
  note?: string;
};

/** What a robust answer protects against, and what the protection costs. */
export function Robustness({ report, objective }: { report: RobustReport; objective: unknown }) {
  const shown = (value: number) => String(Number(value.toPrecision(6)));
  if (report.rows.length === 0) {
    return <p className="mb-4 rounded bg-slate-50 p-3 text-sm text-slate-700">{report.note}</p>;
  }
  const rules = [...new Set(report.rows.map((row) => row.rule))];
  return (
    <section className="mb-4 rounded-md border border-slate-200 p-3 text-sm text-slate-700">
      <h3 className="mb-1 text-sm font-semibold text-slate-900">A robust answer</h3>
      <p>
        {rules.join(", ")} {rules.length === 1 ? "holds" : "hold"} however the uncertain values turn out, within
        their declared range and budget ({report.rows.length} {report.rows.length === 1 ? "instance" : "instances"}{" "}
        protected).
      </p>
      {report.price !== undefined && report.nominal != null && (
        <p className="mt-1">
          The price of robustness: {shown(report.price)} on the goal
          {report.price_share !== undefined ? ` (${shown(report.price_share * 100)}%)` : ""} — {String(objective)} against{" "}
          {shown(report.nominal)} if the data were exact{report.nominal_status === "optimal" ? "" : " (not proven)"}.
        </p>
      )}
    </section>
  );
}

const FRONT = { width: 420, height: 240, pad: 44 };

/**
 * What a planner should know before solving (Epic UX, U-5): anything that would stop the run,
 * anything worth a look, and whether a worker will pick it up.
 */
export function BeforeYouSolve({ preflight, blockers, onMoveTo, moving = false }: {
  preflight: Preflight; blockers: PreflightFinding[];
  /** Move the scenario to a newer version (operator trial F29); without it the warning only says so. */
  onMoveTo?: (versionId: Id) => void; moving?: boolean;
}) {
  const warnings = preflight.findings.filter((finding) => finding.kind === "warning");
  const chosen = preflight.solvers.find((row) => row.chosen);
  const tone = blockers.length ? "border-red-300 bg-red-50" : warnings.length || preflight.workers.state === "offline"
    ? "border-amber-300 bg-amber-50" : "border-green-200 bg-green-50";
  return (
    <section aria-label="Before you solve" className={`mb-4 rounded-md border p-3 text-sm ${tone}`}>
      <p className="font-medium">
        {blockers.length ? "This scenario cannot be solved yet." : "Ready to solve."}{" "}
        <span className="font-normal text-slate-700">
          A {preflight.model_class} model{chosen ? `; ${chosen.name} will take it` : ""}. {preflight.workers.says}.
        </span>
      </p>
      {blockers.length > 0 && <ul className="mt-2 list-disc pl-5 text-red-900">{blockers.map((f) => <li key={f.code + f.says}>{f.says}</li>)}</ul>}
      {warnings.length > 0 && <ul className="mt-2 list-disc pl-5 text-amber-900">{warnings.map((f) => (
        <li key={f.code + f.says}>
          {f.says}
          {f.code === "newer_version" && f.latest_version_id != null && onMoveTo && (
            <button type="button" disabled={moving} className="ml-2 rounded border border-amber-600 px-2 py-0.5 text-amber-900 disabled:opacity-50"
              onClick={() => onMoveTo(f.latest_version_id as Id)}>
              {moving ? "Moving…" : `Move this scenario to version ${f.latest_version}`}
            </button>
          )}
        </li>
      ))}</ul>}
      <details className="mt-2">
        <summary className="cursor-pointer">Which solvers fit, and why the others do not</summary>
        <ul className="mt-1 space-y-0.5">{preflight.solvers.map((row) => (
          <li key={row.name}><span className={`font-mono ${row.fits ? "" : "text-slate-500"}`}>{row.name}</span>: {row.why}</li>
        ))}</ul>
      </details>
    </section>
  );
}

/** What an answer may claim, in a few words (the run's `optimality`). */
export function claimText(optimality: string | null | undefined): string {
  return ({ global: "proven best", local: "best nearby", approximate: "optimal to a tolerance", none: "no claim to be best" } as Record<string, string>)[optimality ?? "none"] ?? String(optimality);
}

/** How many next-best plans the Solve button asks for. */
const ALTERNATIVES = 5;

/** What the worker wrote about the alternatives it looked for (Epic engine E-1). */
export type AlternativesResult = {
  asked: number;
  within: number;
  min_changes?: number;
  found?: number;
  note?: string;
  skipped?: string;
};

/** In a few words: how many were found within the gap, or why none were looked for. */
export function alternativesText(result: AlternativesResult | undefined, found: number): string {
  if (result?.skipped) return `No alternatives listed: ${result.skipped}.`;
  const gap = result ? `${Math.round(result.within * 1000) / 10}%` : "the gap";
  if (found === 0) return `No other plan comes within ${gap} of the best.`;
  const asked = result && found < result.asked ? ` (of ${result.asked} asked for; no more come within ${gap})` : "";
  const apart = result?.min_changes && result.min_changes > 1 ? `${result.min_changes} decisions` : "one decision";
  return `${found} next-best ${found === 1 ? "plan" : "plans"} within ${gap} of the best${asked}, each differing from every other in at least ${apart}.`;
}

export function Alternatives({
  plans,
  result,
  best,
  onOpen,
}: {
  plans: AlternativePlan[];
  result?: AlternativesResult;
  best: number | null;
  onOpen?: (id: Id) => void;
}) {
  return (
    <section aria-label="Alternative plans" className="mb-4 rounded border border-slate-200 p-3 text-sm">
      <h3 className="mb-1 font-medium text-slate-800">Alternative plans</h3>
      <p className="mb-2 text-slate-600">{alternativesText(result, plans.length)}</p>
      {plans.length > 0 && (
        <ol className="space-y-1">
          {plans.map((plan) => (
            <li key={plan.seq} className="flex flex-wrap items-center gap-2">
              <span className="font-medium">Plan {plan.seq + 1}</span>
              <span>
                goal {plan.objective}
                {best != null && ` (${plan.objective - best >= 0 ? "+" : ""}${Math.round((plan.objective - best) * 1e6) / 1e6})`}
              </span>
              <span className="text-slate-600">
                {plan.changed} {plan.changed === 1 ? "decision differs" : "decisions differ"} from the best
                {plan.status === "feasible" ? "; not proven the next best" : ""}
              </span>
              {onOpen && plan.run_id != null && (
                <button type="button" className="underline" onClick={() => onOpen(plan.run_id as Id)}>
                  Open
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

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
  // Six significant figures: a solver's value is only as exact as its tolerance.
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

/** A duration as people say it: "about 40 s", "about 3 min". */
export function aboutTime(seconds: number): string {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} s`;
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

/** What to say about an unfinished run's expected time; null says nothing. */
export function etaText(eta: RunEta | undefined): string | null {
  if (!eta || eta.settled) return null;
  if (eta.estimate_seconds == null) return eta.reason ? `No time estimate yet: ${eta.reason}.` : null;
  const range = eta.low_seconds != null && eta.high_seconds != null && eta.high_seconds > eta.low_seconds
    ? ` (between ${aboutTime(eta.low_seconds)} and ${aboutTime(eta.high_seconds)})` : "";
  const runs = eta.based_on_runs ? `, judged from ${eta.based_on_runs} earlier runs` : "";
  const left = eta.elapsed_seconds != null ? eta.estimate_seconds - eta.elapsed_seconds : null;
  const remaining = left == null ? "" : left > 0 ? `; about ${aboutTime(left)} to go` : "; taking longer than expected";
  return `Expected to take about ${aboutTime(eta.estimate_seconds)}${range}${runs}${remaining}.`;
}

function ExpectedTime({ runId }: { runId: Id }) {
  const eta = useRunEta(runId, true);
  const text = etaText(eta.data);
  if (!text) return null;
  return <p className="mb-4 text-sm text-slate-600" data-testid="run-eta">{text}</p>;
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

/** The shared failure state (Epic UX, U-1): no access, not found, or a failure worth retrying. */
function Failed({ subject, error, onRetry }: { subject: string; error: unknown; onRetry: () => void }) {
  return <LoadFailure subject={subject} error={error} retry={() => void onRetry()} />;
}

/** "run 3", "runs 3–7", or "runs 3, 5, 9": the ids a run's parts took (F26). */
export function runSpan(ids: number[]): string {
  if (ids.length === 1) return `run ${ids[0]}`;
  const contiguous = ids.every((id, i) => i === 0 || id === ids[i - 1] + 1);
  return contiguous ? `runs ${ids[0]}–${ids[ids.length - 1]}` : `runs ${ids.join(", ")}`;
}

const GOAL = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

/** A goal value or change as a planner reads it: 3669, not 3669.000000 (operator trial F9 F27). */
export function formatGoal(value: number | string | null | undefined): string {
  const n = Number(value);
  return value == null || value === "" || !Number.isFinite(n) ? String(value ?? "—") : GOAL.format(n);
}
