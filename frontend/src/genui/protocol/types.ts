/**
 * The GenUI protocol, as the browser holds it.
 *
 * The one artefact is `backend/app/genui/protocol.json`; `parity.test.ts`
 * reads it off disk and deep-compares it with what is here, as the IR
 * contract does. Nothing here knows about React: an agent says *which*
 * component and *what* data, the registry decides how it looks, and nothing
 * an agent sends is ever code.
 */

export const PROTOCOL_VERSION = 1;

export const COMPONENT_TYPES = [
  "metric",
  "optimization-summary",
  "solver-status",
  "solver-progress",
  "model-summary",
  "variable-editor",
  "constraint-builder",
  "objective-editor",
  "expression-builder",
  "query-builder",
  "data-table",
  "chart",
  "solution-table",
  "scenario-comparison",
  "sensitivity-analysis",
  "solver-log",
  "validation-result",
  "confirmation",
  "timeline",
] as const;

export const COMPONENT_STATES = ["skeleton", "hydrating", "hydrated", "interactive", "error"] as const;

export const AGENT_STATES = [
  "idle",
  "understanding",
  "planning",
  "loading_data",
  "building_model",
  "validating_model",
  "generating_expressions",
  "selecting_solver",
  "submitting_job",
  "solving",
  "post_processing",
  "hydrating_ui",
  "complete",
  "warning",
  "error",
] as const;

export const EVENTS = [
  "agent.state",
  "agent.message",
  "component.created",
  "component.updated",
  "component.data",
  "component.action",
  "component.completed",
  "component.error",
] as const;

export type ComponentType = (typeof COMPONENT_TYPES)[number];
export type ComponentState = (typeof COMPONENT_STATES)[number];
export type AgentState = (typeof AGENT_STATES)[number];
export type EventName = (typeof EVENTS)[number];

/** Where a piece of data comes from, when it is not sent inline. */
export type DataBinding = { source: "run"; runId: number } | { source: "inline" };

/** Something the user can do with a component, performed by the platform's own API. */
export type UIAction = { id: string; label: string; kind: "open" | "cancel" | "confirm" | "navigate"; target?: string };

export type LayoutIntent = { size?: "compact" | "wide" | "full"; expandable?: boolean };

export type AnimationIntent = { enter?: "fade" | "grow" | "none" };

/** One component, as an agent describes it. */
export interface UIIntent {
  id: string;
  type: ComponentType;
  state: ComponentState;
  props?: Record<string, unknown>;
  data?: DataBinding | Record<string, unknown>;
  actions?: UIAction[];
  layout?: LayoutIntent;
  animation?: AnimationIntent;
}

export type GenUIEvent =
  | { event: "agent.state"; state: AgentState }
  | { event: "agent.message"; text: string }
  | { event: "component.created"; component: UIIntent }
  | { event: "component.updated"; id: string; state: ComponentState }
  | { event: "component.data"; id: string; data: Record<string, unknown> }
  | { event: "component.action"; id: string; action: UIAction }
  | { event: "component.completed"; id: string }
  | { event: "component.error"; id: string; message?: string };
