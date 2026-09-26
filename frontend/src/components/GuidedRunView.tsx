/**
 * Guided GenUI view of a run (OAAS N06): conversation + expandable cards.
 * Shared by the Runs detail tab and the legacy /workspace entry.
 */
import { LayoutGroup, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import AgentStatus from "../genui/AgentStatus";
import { layoutSpring } from "../genui/animation/variants";
import { entryFor } from "../genui/registry/componentRegistry";
import { GenUIComponent } from "../genui/runtime/GenUIRenderer";
import { GenUIStore, useGenUIStructure, type TranscriptEntry } from "../genui/runtime/store";
import { streamRun } from "../genui/streaming/streamManager";

export default function GuidedRunView({ runId }: { runId: number }) {
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
              The live view could not be reached. The run carries on; the record below still updates.
            </p>
          )}
          <Transcript store={store} entries={transcript} open={open} onOpen={setOpen} />
        </div>
        <section aria-label="Guided workspace" className="min-h-[12rem] rounded-xl border border-slate-200 bg-slate-50/60 p-4">
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
