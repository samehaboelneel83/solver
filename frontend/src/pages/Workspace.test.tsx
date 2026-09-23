import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Workspace from "./Workspace";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

const { apiFetch } = await import("../api/client");
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const PROBLEMS = { items: [{ id: 1, name: "weekly_rota", domain_id: 1 }], total: 1 };
const SCENARIOS = { items: [{ id: 7, problem_id: 1, model_version_id: 2, name: "base", patch: {} }], total: 1 };

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

function renderAt(url: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[url]}>
          <Workspace />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.setItem(DOMAIN_STORAGE_KEY, "1");
  mockFetch.mockImplementation((path: string, options?: { method?: string }) => {
    if (options?.method === "POST") return Promise.resolve({ id: 9, status: "queued" });
    if (path.startsWith("/api/problem")) return Promise.resolve(PROBLEMS);
    if (path.startsWith("/api/v1/scenarios")) return Promise.resolve(SCENARIOS);
    if (path.startsWith("/api/v1/me")) {
      return Promise.resolve({ username: "a", display_name: "A", capabilities: ["run.submit"] });
    }
    return Promise.reject(new Error(`unexpected ${path}`));
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamOf(RUN_EVENTS)));
  // Batches flush on the next frame; jsdom's is a timer.
  vi.stubGlobal("requestAnimationFrame", (flush: () => void) => setTimeout(flush, 0));
});

afterEach(() => vi.unstubAllGlobals());

describe("the GenUI workspace", () => {
  it("is ready, in words, before anything is solved", async () => {
    renderAt("/workspace");
    expect(await screen.findByText("Choose a scenario and solve it.", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("solves a scenario and tells the run as it goes: words, then hydrated cards", async () => {
    renderAt("/workspace");
    const solve = await screen.findByRole("button", { name: "Solve this scenario" });
    await waitFor(() => expect(solve).toBeEnabled());
    fireEvent.click(solve);
    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/v1/scenarios/7/runs",
        expect.objectContaining({ method: "POST", body: expect.stringContaining('"reuse":false') })
      )
    );
    expect(await screen.findByText("The model is IP: 40 decisions, 1 rule instances.")).toBeInTheDocument();
    expect(await screen.findByLabelText("objective")).toHaveTextContent("1,284,920");
    expect(await screen.findByText("The answer is proven the best.", { exact: false })).toBeInTheDocument();
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/v1/runs/9/genui");
  });

  it("opens a card into the workspace and gives it back", async () => {
    renderAt("/workspace?run=9");
    const workspace = await screen.findByRole("region", { name: "Workspace" });
    fireEvent.click(await screen.findByRole("button", { name: "Open The model in the workspace" }));
    // Expanded, the model says more than its compact card did.
    expect(await within(workspace).findByText("Knapsacks")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open in the workspace →" })).toBeInTheDocument();
    fireEvent.click(within(workspace).getByRole("button", { name: "Back to the conversation" }));
    expect(await screen.findByText("Open a card from the conversation to work with it here.")).toBeInTheDocument();
  });
});
