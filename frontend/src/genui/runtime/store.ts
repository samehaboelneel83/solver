/**
 * What a GenUI stream has said so far, and who needs to hear what changed.
 *
 * Not a second state library: a small external store read with
 * `useSyncExternalStore`, beside TanStack Query (which keeps the server's
 * records). The point is the granularity: a card subscribes to its own id,
 * so a solver reporting twice a second re-renders one progress card -- not
 * the transcript, not the workspace (spec: "never re-render the entire
 * workspace for every solver event"). Events arrive in batches (one per
 * animation frame, `streamManager`), and each batch notifies each touched
 * id once.
 */
import { useCallback, useSyncExternalStore } from "react";
import type { AgentState, ComponentState, ComponentType, GenUIEvent, UIAction } from "../protocol/types";

export type ComponentRecord = {
  id: string;
  type: ComponentType;
  state: ComponentState;
  props: Record<string, unknown>;
  data: Record<string, unknown>;
  actions: UIAction[];
  /** Past data snapshots, for a component that draws a curve (solver-progress). */
  history: Record<string, unknown>[];
  completed: boolean;
  error: string | null;
};

/** The conversation, in order: what the agent said and what it showed. */
export type TranscriptEntry = { kind: "message"; key: string; text: string } | { kind: "component"; key: string; id: string };

type Structure = { agentState: AgentState; transcript: TranscriptEntry[] };

const HISTORY_LIMIT = 600;

export class GenUIStore {
  private components = new Map<string, ComponentRecord>();
  private structure: Structure = { agentState: "idle", transcript: [] };
  private idListeners = new Map<string, Set<() => void>>();
  private structureListeners = new Set<() => void>();
  private messages = 0;

  getComponent = (id: string): ComponentRecord | undefined => this.components.get(id);
  getStructure = (): Structure => this.structure;

  subscribeId(id: string, listener: () => void): () => void {
    let set = this.idListeners.get(id);
    if (!set) this.idListeners.set(id, (set = new Set()));
    set.add(listener);
    return () => set!.delete(listener);
  }

  subscribeStructure(listener: () => void): () => void {
    this.structureListeners.add(listener);
    return () => this.structureListeners.delete(listener);
  }

  /** Forget everything: a stream that reconnects replays from the start. */
  reset(): void {
    const ids = [...this.components.keys()];
    this.components.clear();
    this.structure = { agentState: "idle", transcript: [] };
    this.messages = 0;
    ids.forEach((id) => this.notifyId(id));
    this.structureListeners.forEach((listener) => listener());
  }

  apply(events: GenUIEvent[]): void {
    const touched = new Set<string>();
    let structural = false;
    let { agentState, transcript } = this.structure;
    for (const event of events) {
      switch (event.event) {
        case "agent.state":
          if (event.state !== agentState) {
            agentState = event.state;
            structural = true;
          }
          break;
        case "agent.message":
          transcript = [...transcript, { kind: "message", key: `m${(this.messages += 1)}`, text: event.text }];
          structural = true;
          break;
        case "component.created": {
          const c = event.component;
          const existing = this.components.get(c.id);
          // An upsert: a replayed stream re-creates what it already made.
          this.components.set(c.id, {
            id: c.id,
            type: c.type,
            state: c.state,
            props: { ...(existing?.props ?? {}), ...(c.props ?? {}) },
            data: existing?.data ?? {},
            actions: c.actions ?? existing?.actions ?? [],
            history: existing?.history ?? [],
            completed: existing?.completed ?? false,
            error: null,
          });
          if (!existing) {
            transcript = [...transcript, { kind: "component", key: c.id, id: c.id }];
            structural = true;
          }
          touched.add(c.id);
          break;
        }
        case "component.updated":
          this.patch(event.id, (c) => ({ ...c, state: event.state }), touched);
          break;
        case "component.data":
          this.patch(
            event.id,
            (c) => {
              const { append, ...rest } = event.data as { append?: unknown } & Record<string, unknown>;
              const data: Record<string, unknown> = { ...c.data, ...rest };
              if (Array.isArray(append)) data.lines = [...((c.data.lines as unknown[]) ?? []), ...append].slice(-HISTORY_LIMIT);
              const history = c.type === "solver-progress" ? [...c.history, rest].slice(-HISTORY_LIMIT) : c.history;
              return { ...c, data, history };
            },
            touched
          );
          break;
        case "component.completed":
          this.patch(event.id, (c) => ({ ...c, completed: true }), touched);
          break;
        case "component.error":
          this.patch(event.id, (c) => ({ ...c, state: "error", error: event.message ?? "failed" }), touched);
          break;
        case "component.action":
          this.patch(event.id, (c) => ({ ...c, actions: [...c.actions.filter((a) => a.id !== event.action.id), event.action] }), touched);
          break;
      }
    }
    if (structural) this.structure = { agentState, transcript };
    touched.forEach((id) => this.notifyId(id));
    if (structural) this.structureListeners.forEach((listener) => listener());
  }

  private patch(id: string, change: (c: ComponentRecord) => ComponentRecord, touched: Set<string>): void {
    const current = this.components.get(id);
    if (!current) return; // data for a component never created is dropped
    this.components.set(id, change(current));
    touched.add(id);
  }

  private notifyId(id: string): void {
    this.idListeners.get(id)?.forEach((listener) => listener());
  }
}

/** One component, re-rendering only when that component changes. */
export function useGenUIComponent(store: GenUIStore, id: string): ComponentRecord | undefined {
  const subscribe = useCallback((listener: () => void) => store.subscribeId(id, listener), [store, id]);
  return useSyncExternalStore(subscribe, () => store.getComponent(id));
}

/** The agent's state and the transcript -- not any component's data. */
export function useGenUIStructure(store: GenUIStore): Structure {
  const subscribe = useCallback((listener: () => void) => store.subscribeStructure(listener), [store]);
  return useSyncExternalStore(subscribe, store.getStructure);
}
