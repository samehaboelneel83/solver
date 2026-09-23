/**
 * What the agent is doing, in words -- never a bare "Loading…". The words
 * are the whole message: the mark beside them only restates it, so with
 * motion reduced (or ignored by a screen reader) nothing is lost.
 */
import type { AgentState } from "./protocol/types";

export const AGENT_WORDS: Record<AgentState, { label: string; detail: string }> = {
  idle: { label: "Ready", detail: "Choose a scenario and solve it." },
  understanding: { label: "Understanding", detail: "Reading the model against its frozen data." },
  planning: { label: "Planning", detail: "Deciding the steps." },
  loading_data: { label: "Loading data", detail: "Reading the scenario's data." },
  building_model: { label: "Building the model", detail: "Expanding every rule over its sets." },
  validating_model: { label: "Validating", detail: "Checking the model is well formed." },
  generating_expressions: { label: "Writing expressions", detail: "Composing the model's arithmetic." },
  selecting_solver: { label: "Choosing a solver", detail: "Matching the model's shape to what each solver proves." },
  submitting_job: { label: "Queued", detail: "Waiting for a worker." },
  solving: { label: "Solving", detail: "Searching, and proving how good the best answer is." },
  post_processing: { label: "Working up the answer", detail: "Checking each rule and recording the result." },
  hydrating_ui: { label: "Showing the result", detail: "Filling in what the run found." },
  complete: { label: "Done", detail: "The answer is proven the best." },
  warning: { label: "Done, with a caveat", detail: "See the result for what was not proven." },
  error: { label: "Stopped", detail: "See the result for why." },
};

const BUSY = new Set<AgentState>([
  "understanding", "planning", "loading_data", "building_model", "validating_model",
  "generating_expressions", "selecting_solver", "submitting_job", "solving", "post_processing", "hydrating_ui",
]);

export default function AgentStatus({ state }: { state: AgentState }) {
  const words = AGENT_WORDS[state];
  const tone = state === "error" ? "bg-rose-500" : state === "warning" ? "bg-amber-500" : state === "complete" ? "bg-emerald-500" : "bg-blue-500";
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2" role="status" aria-live="polite">
      <span className="relative flex h-3 w-3" aria-hidden="true">
        {BUSY.has(state) && (
          <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 motion-reduce:animate-none ${tone}`} />
        )}
        <span className={`relative inline-flex h-3 w-3 rounded-full ${tone}`} />
      </span>
      <span className="text-sm">
        <span className="font-medium text-slate-900">{words.label}</span>
        <span className="text-slate-500"> — {words.detail}</span>
      </span>
    </div>
  );
}
