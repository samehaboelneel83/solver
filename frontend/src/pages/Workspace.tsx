/**
 * The GenUI workspace (Phase 1): the conversation on one side, the workspace
 * on the other. Solving a scenario opens its run's GenUI stream
 * (`GET /runs/{id}/genui`); the agent's words and the components it creates
 * appear in the conversation in order, each a skeleton that hydrates as the
 * run reports, and a card opens into the workspace by moving there (shared
 * `layoutId`) rather than being drawn again.
 *
 * The agent is the solve pipeline itself: no language model is involved yet,
 * and every number on the page is one the run recorded.
 */
import { LayoutGroup, MotionConfig, motion } from "framer-motion";
import { useEffect, useId, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useEntityList } from "../api/entities";
import { formatApiError } from "../api/errors";
import { useCreateRun, useScenarios } from "../api/v1";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import AgentStatus from "../genui/AgentStatus";
import { layoutSpring } from "../genui/animation/variants";
import { GenUIContext } from "../genui/components/shared";
import { entryFor } from "../genui/registry/componentRegistry";
import { GenUIComponent } from "../genui/runtime/GenUIRenderer";
import { GenUIStore, useGenUIStructure, type TranscriptEntry } from "../genui/runtime/store";
import { streamRun } from "../genui/streaming/streamManager";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useDomain } from "../hooks/useDomain";
import { parseRouteId } from "../lib/routeId";

export default function Workspace() {
  useDocumentTitle("Workspace");
  const { domainId } = useDomain();
  return (
    // "user": transforms are dropped for anyone who asked for less motion;
    // every state is still said in words.
    <MotionConfig reducedMotion="user">
      <div className="max-w-7xl">
        <h1 className="mb-1 text-lg font-semibold text-slate-900">Workspace</h1>
        <p className="mb-4 text-sm text-slate-500">
          Solve a scenario and watch the run build its answer. Open any card to work with it on the right.
        </p>
        {domainId === null ? (
          <p className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
            Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen).
          </p>
        ) : (
          <ForDomain domainId={domainId} />
        )}
      </div>
    </MotionConfig>
  );
}

function ForDomain({ domainId }: { domainId: number }) {
  const [params, setParams] = useSearchParams();
  const { can } = useCapabilities();
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
  const problem = problemItems.find((row) => Number(row.id) === parseRouteId(params.get("problem"))) ?? problemItems[0];
  const problemId = problem ? Number(problem.id) : null;
  const scenarios = useScenarios(problemId, { limit: 500, offset: 0 });
  const scenarioItems = scenarios.data?.items ?? [];
  const scenario = scenarioItems.find((row) => row.id === parseRouteId(params.get("scenario"))) ?? scenarioItems[0];
  const runId = parseRouteId(params.get("run"));
  const createRun = useCreateRun();
  const [failure, setFailure] = useState<string | null>(null);

  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next, { replace: true });
  };

  if (problems.fetchStatus === "paused" && !problems.data) return <OfflineNotice subject="The problem list" />;
  if (problems.isLoading) return <Skeleton rows={2} cols={3} />;

  function solve() {
    if (!scenario) return;
    setFailure(null);
    createRun.mutate(
      { scenarioId: scenario.id, body: { time_limit_s: 30, reuse: false } },
      {
        onSuccess: (run) => set({ run: String(run.id) }),
        onError: (error: unknown) => setFailure(formatApiError(error)),
      }
    );
  }

  return (
    <GenUIContext.Provider value={{ problemId, scenarioId: scenario?.id ?? null }}>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={problemChooser} className="block text-xs text-slate-600">
            Problem
          </label>
          <select
            id={problemChooser}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            value={problemId ?? ""}
            onChange={(event) => set({ problem: event.target.value, scenario: null, run: null })}
          >
            {problemItems.length === 0 && <option value="">No problems</option>}
            {problemItems.map((row) => (
              <option key={String(row.id)} value={String(row.id)}>
                {String(row.name ?? row.id)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={scenarioChooser} className="block text-xs text-slate-600">
            Scenario
          </label>
          <select
            id={scenarioChooser}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            value={scenario?.id ?? ""}
            onChange={(event) => set({ scenario: event.target.value, run: null })}
          >
            {scenarioItems.length === 0 && <option value="">No scenarios</option>}
            {scenarioItems.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
          </select>
        </div>
        {can("run.submit") && (
          <button
            type="button"
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            disabled={!scenario || createRun.isPending}
            onClick={solve}
          >
            {createRun.isPending ? "Submitting…" : "Solve this scenario"}
          </button>
        )}
      </div>
      {failure && (
        <p role="alert" className="mb-3 rounded bg-rose-50 p-2 text-sm text-rose-800">
          {failure}
        </p>
      )}
      {runId === null ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
          <AgentStatus state="idle" />
        </div>
      ) : (
        // Keyed by run: another run is another conversation.
        <RunConversation key={runId} runId={runId} />
      )}
    </GenUIContext.Provider>
  );
}

function RunConversation({ runId }: { runId: number }) {
  const store = useMemo(() => new GenUIStore(), []);
  const [ended, setEnded] = useState<"settled" | "failed" | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => streamRun(runId, store, { onEnd: setEnded }), [runId, store]);
  const { agentState, transcript } = useGenUIStructure(store);

  return (
    <LayoutGroup id={`run-${runId}`}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <div className="space-y-3" aria-label="Conversation">
          <AgentStatus state={agentState} />
          {ended === "failed" && (
            <p role="alert" className="rounded bg-amber-50 p-2 text-sm text-amber-900">
              The live view could not be reached. The run carries on; the Runs page has its record.
            </p>
          )}
          <Transcript store={store} entries={transcript} open={open} onOpen={setOpen} />
        </div>
        <section aria-label="Workspace" className="min-h-[12rem] rounded-xl border border-slate-200 bg-slate-50/60 p-4">
          {open ? (
            <div className="space-y-3">
              <div className="flex justify-end">
                <button type="button" className="text-xs text-slate-600 underline" onClick={() => setOpen(null)}>
                  Back to the conversation
                </button>
              </div>
              <GenUIComponent store={store} id={open} variant="expanded" />
            </div>
          ) : (
            <p className="text-sm text-slate-500">Open a card from the conversation to work with it here.</p>
          )}
        </section>
      </div>
    </LayoutGroup>
  );
}

/** Messages and cards in the order the agent produced them; metric cards
 * that arrive together sit side by side. */
function Transcript({
  store,
  entries,
  open,
  onOpen,
}: {
  store: GenUIStore;
  entries: TranscriptEntry[];
  open: string | null;
  onOpen: (id: string) => void;
}) {
  const groups: TranscriptEntry[][] = [];
  for (const entry of entries) {
    const inline = entry.kind === "component" && entryFor(store.getComponent(entry.id)?.type ?? "metric")?.inline;
    const last = groups[groups.length - 1];
    const lastInline =
      last && last[0].kind === "component" && entryFor(store.getComponent(last[0].id)?.type ?? "metric")?.inline;
    if (inline && lastInline) last.push(entry);
    else groups.push([entry]);
  }
  return (
    <ol className="space-y-3">
      {groups.map((group) => (
        <li key={group[0].key} className={group.length > 1 ? "grid grid-cols-3 gap-2" : undefined}>
          {group.map((entry) =>
            entry.kind === "message" ? (
              <motion.p
                key={entry.key}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={layoutSpring}
                className="text-sm text-slate-700"
              >
                {entry.text}
              </motion.p>
            ) : entry.id === open ? (
              <button
                key={entry.key}
                type="button"
                className="w-full rounded-lg border border-dashed border-slate-300 px-3 py-2 text-left text-xs text-slate-500"
                onClick={() => onOpen(entry.id)}
              >
                Open in the workspace →
              </button>
            ) : (
              <GenUIComponent key={entry.key} store={store} id={entry.id} variant="compact" onExpand={onOpen} />
            )
          )}
        </li>
      ))}
    </ol>
  );
}
