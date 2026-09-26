import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GuidedRunView from "./GuidedRunView";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

/** What the server's translator sends for a run solved to optimality. */
const RUN_EVENTS = [
  { event: "component.created", component: { id: "run-9-timeline", type: "timeline", state: "interactive", props: { title: "What the solver is doing" } } },
  { event: "component.created", component: { id: "run-9-model", type: "model-summary", state: "skeleton", props: { title: "The model" } } },
  { event: "agent.state", state: "building_model" },
  { event: "agent.message", text: "The model is IP: 40 decisions, 1 rule instances." },
  { event: "component.updated", id: "run-9-model", state: "hydrated" },
  { event: "component.data", id: "run-9-model", data: { modelClass: "IP", variables: 40, constraints: 1, fingerprint: { binary: 40, rows_knapsack: 1, blocks: 1 } } },
  { event: "component.created", component: { id: "run-9-summary", type: "optimization-summary", state: "skeleton", props: { title: "Result" } } },
  { event: "component.updated", id: "run-9-summary", state: "hydrated" },
  { event: "component.data", id: "run-9-summary", data: { status: "optimal", objective: 1284920, gap: 0, solver: "cp-sat", wallTime: 2.5 } },
  { event: "agent.state", state: "complete" },
];

function streamOf(events: unknown[]) {
  const encoder = new TextEncoder();
  const chunks = events.map((e) => `event: genui\ndata: ${JSON.stringify(e)}\n\n`);
  let i = 0;
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () =>
          i < chunks.length ? { value: encoder.encode(chunks[i++]), done: false } : { value: undefined, done: true },
      }),
    },
  } as unknown as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamOf(RUN_EVENTS)));
  vi.stubGlobal("requestAnimationFrame", (flush: () => void) => setTimeout(flush, 0));
});

afterEach(() => vi.unstubAllGlobals());

describe("GuidedRunView", () => {
  it("tells the run as it goes: words, then hydrated cards", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <GuidedRunView runId={9} />
      </QueryClientProvider>
    );
    expect(await screen.findByText("The model is IP: 40 decisions, 1 rule instances.")).toBeInTheDocument();
    expect(await screen.findByLabelText("objective")).toHaveTextContent("1,284,920");
    expect(await screen.findByText("The answer is proven the best.", { exact: false })).toBeInTheDocument();
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/v1/runs/9/genui");
  });

  it("opens a card into the guided workspace and gives it back", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <GuidedRunView runId={9} />
      </QueryClientProvider>
    );
    const workspace = await screen.findByRole("region", { name: "Guided workspace" });
    fireEvent.click(await screen.findByRole("button", { name: "Open The model in the workspace" }));
    expect(await within(workspace).findByText("Knapsacks")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open in the workspace →" })).toBeInTheDocument();
    fireEvent.click(within(workspace).getByRole("button", { name: "Back to the conversation" }));
    expect(await screen.findByText("Open a card from the conversation to work with it here.")).toBeInTheDocument();
  });
});
