import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PlannerPanel from "./PlannerPanel";
import type { Run } from "../api/v1";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

const { apiFetch } = await import("../api/client");
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const RUN = {
  id: 7, scenario_id: 3, dataset_id: 1, status: "optimal", solver: "cp-sat", solver_version: null, compiler_version: null,
  objective: 2, wall_time_s: 0.1, error: null, queued_at: "", started_at: null, finished_at: null, cancel_requested: false,
  purpose: "plan", params: {}, labels: { employee: { ann: "Ann", bob: "Bob" }, day: { mon: "Monday", tue: "Tuesday" } },
  index_sets: { variables: { assign: ["employee", "day"] }, constraints: {} },
  rule_notes: { c_max_hours: "at most eight hours a week" },
  conflict: null, conflict_minimal: null, assignments: { assign: [["ann", "mon"], ["bob", "tue"]] }, reduced_costs: null,
  variable_kinds: { assign: "binary" }, set_order: { employee: ["ann", "bob"], day: ["mon", "tue"] }, constraints: [], ranges: null,
} as unknown as Run;

let calls: { path: string; method: string; body: unknown }[] = [];
let whyNot: unknown = null;
let probe: unknown = null;

function renderPanel(run: Run = RUN, onOpen = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PlannerPanel run={run} onOpen={onOpen} />
    </QueryClientProvider>,
  );
  return onOpen;
}

beforeEach(() => {
  calls = [];
  mockFetch.mockReset();
  mockFetch.mockImplementation(async (path: string, options: RequestInit = {}) => {
    const method = options.method ?? "GET";
    calls.push({ path, method, body: options.body ? JSON.parse(String(options.body)) : undefined });
    if (path === "/api/v1/scenarios/3") return { id: 3, problem_id: 9, model_version_id: 4, name: "base", patch: { soften: { c_x: 5 } }, created_at: "" };
    if (path === "/api/v1/scenarios" && method === "POST") return { id: 11, problem_id: 9, model_version_id: 4, name: "x", patch: {}, created_at: "" };
    if (path === "/api/v1/scenarios/11/runs" && method === "POST") return { ...RUN, id: 12, status: "queued" };
    if (path === "/api/v1/runs/7/why-not") return whyNot;
    if (path === "/api/v1/runs/20") return probe;
    throw new Error(`unexpected ${method} ${path}`);
  });
});

describe("PlannerPanel", () => {
  it("keeps the chosen days as this run has them and solves the rest, staying close", async () => {
    const onOpen = renderPanel();
    fireEvent.change(screen.getByLabelText("Keep it for"), { target: { value: "day" } });
    fireEvent.click(await screen.findByLabelText("Monday"));
    const go = screen.getByRole("button", { name: "Keep 1 and solve the rest" });
    await waitFor(() => expect(go).toBeEnabled());
    fireEvent.click(go);
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(12));
    const scenario = calls.find((c) => c.path === "/api/v1/scenarios" && c.method === "POST")!.body as { patch: unknown; problem_id: number };
    expect(scenario.problem_id).toBe(9);
    expect(scenario.patch).toEqual({
      soften: { c_x: 5 },
      lock: [{ var: "assign", where: { day: ["mon"] }, from_run: 7 }],
      stay_close: { from_run: 7, mode: "lex" },
    });
    expect(calls.find((c) => c.path === "/api/v1/scenarios/11/runs")!.body).toEqual({ reuse: false });
  });

  it("asks why a cell is not on, and says what blocks it in the rules' own words", async () => {
    whyNot = { run_id: 20, verdict: null };
    probe = { ...RUN, id: 20, purpose: "why_not", verdict: { kind: "blocked", forced: ["lock:1"], minimal: true,
      conflict: [{ constraint_id: "c_max_hours", instance: ["ann"] }, { constraint_id: "lock:1", instance: [] }] } };
    renderPanel();
    fireEvent.change(screen.getAllByLabelText("day")[0], { target: { value: "tue" } });
    fireEvent.click(screen.getByRole("button", { name: "Why isn't Ann · Tuesday on?" }));
    expect(await screen.findByText(/No plan allows it/)).toBeInTheDocument();
    expect(screen.getByText("at most eight hours a week (c_max_hours)")).toBeInTheDocument();
    expect(screen.getByText("what you asked")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/v1/runs/7/why-not")!.body).toEqual({
      force: [{ var: "assign", index: ["ann", "tue"], value: 1 }], override: [],
    });
  });

  it("asks about a cell that is on as why it is on, and shows a cost and what moves", async () => {
    whyNot = { run_id: 20, verdict: null };
    probe = { ...RUN, id: 20, purpose: "why_not", verdict: { kind: "possible", proven: true, objective: 2, delta: 0, change: 4,
      turned_on: [["assign", "ann", "tue"], ["assign", "bob", "mon"]], turned_off: [["assign", "ann", "mon"], ["assign", "bob", "tue"]] } };
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Why is Ann · Monday on?" }));
    expect(await screen.findByText(/Possible, at no extra cost -- the closest plan moves 4 cells/)).toBeInTheDocument();
    expect(screen.getByText("On: assign · Ann · Tuesday; assign · Bob · Monday")).toBeInTheDocument();
    expect((calls.find((c) => c.path === "/api/v1/runs/7/why-not")!.body as { force: { value: number }[] }).force[0].value).toBe(0);
  });

  it("shows how far each number may move on a linear model, and says why not on any other", () => {
    renderPanel({ ...RUN, ranges: {
      rows: [{ rule: "c_max_hours", index: {}, rhs: 40, dual: 2.5, low: 30, high: null }],
      costs: [{ var: "assign", index: ["ann", "mon"], cost: 3, low: 1, high: 4 }] } } as Run);
    expect(screen.getByText("at most eight hours a week")).toBeInTheDocument();
    expect(screen.getByText("30 … no limit")).toBeInTheDocument();
    expect(screen.getByText("1 … 4")).toBeInTheDocument();
  });

  it("is not offered on a question, or on a run with no plan", () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <PlannerPanel run={{ ...RUN, purpose: "why_not" } as Run} />
        <PlannerPanel run={{ ...RUN, status: "infeasible" } as Run} />
      </QueryClientProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
