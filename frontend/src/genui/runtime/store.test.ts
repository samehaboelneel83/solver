import { describe, expect, it, vi } from "vitest";
import type { ComponentState, ComponentType, GenUIEvent } from "../protocol/types";
import { GenUIStore } from "./store";

const created = (id: string, type: ComponentType = "metric", state: ComponentState = "skeleton"): GenUIEvent => ({
  event: "component.created",
  component: { id, type, state, props: { label: id } },
});

describe("the GenUI store", () => {
  it("builds a component from skeleton to hydrated, merging data", () => {
    const store = new GenUIStore();
    store.apply([created("a", "solver-progress")]);
    store.apply([
      { event: "component.updated", id: "a", state: "hydrating" },
      { event: "component.data", id: "a", data: { objective: 90, bound: 100 } },
      { event: "component.data", id: "a", data: { bound: 95 } },
      { event: "component.completed", id: "a" },
    ]);
    const a = store.getComponent("a")!;
    expect(a.state).toBe("hydrating");
    expect(a.data).toEqual({ objective: 90, bound: 95 });
    // A progress card keeps its history, for its curve.
    expect(a.history).toEqual([{ objective: 90, bound: 100 }, { bound: 95 }]);
    expect(a.completed).toBe(true);
  });

  it("tells only the component that changed, once per batch", () => {
    const store = new GenUIStore();
    store.apply([created("a"), created("b")]);
    const a = vi.fn();
    const b = vi.fn();
    const structure = vi.fn();
    store.subscribeId("a", a);
    store.subscribeId("b", b);
    store.subscribeStructure(structure);

    store.apply([
      { event: "component.data", id: "a", data: { value: 1 } },
      { event: "component.data", id: "a", data: { value: 2 } },
      { event: "component.data", id: "a", data: { value: 3 } },
    ]);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).not.toHaveBeenCalled();
    // Data is not structure: the transcript does not re-render for it.
    expect(structure).not.toHaveBeenCalled();
  });

  it("keeps the conversation in order and a replay as an upsert", () => {
    const store = new GenUIStore();
    const events: GenUIEvent[] = [
      { event: "agent.state", state: "solving" },
      { event: "agent.message", text: "Solving." },
      created("a"),
      { event: "component.data", id: "a", data: { value: 5 } },
    ];
    store.apply(events);
    store.apply([created("a")]); // a reconnect's replay
    const { agentState, transcript } = store.getStructure();
    expect(agentState).toBe("solving");
    expect(transcript.map((entry) => entry.kind)).toEqual(["message", "component"]);
    expect(store.getComponent("a")!.data).toEqual({ value: 5 });
  });

  it("appends log lines and drops data for a component never created", () => {
    const store = new GenUIStore();
    store.apply([created("log", "solver-log", "hydrating")]);
    store.apply([
      { event: "component.data", id: "log", data: { append: ["one"] } },
      { event: "component.data", id: "log", data: { append: ["two"] } },
      { event: "component.data", id: "ghost", data: { value: 1 } },
    ]);
    expect(store.getComponent("log")!.data.lines).toEqual(["one", "two"]);
    expect(store.getComponent("ghost")).toBeUndefined();
  });
});
