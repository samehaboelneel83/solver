import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Runs from "./Runs";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

const { apiFetch } = await import("../api/client");
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const PROBLEMS = { items: [{ id: 1, name: "weekly_rota", domain_id: 1 }], total: 1 };
const SCENARIOS = { items: [{ id: 7, problem_id: 1, model_version_id: 2, name: "relaxed_cover", patch: {} }], total: 1 };

const RUN_SUMMARY = {
  id: 11,
  scenario_id: 7,
  dataset_id: 3,
  status: "optimal",
  solver: "cp-sat",
  solver_version: "cp-sat (ortools 9.15.6755)",
  compiler_version: "ir-compiler 1",
  objective: 3621,
  wall_time_s: 0.009,
  error: null,
  queued_at: "2026-09-20T10:00:00Z",
  started_at: "2026-09-20T10:00:00Z",
  finished_at: "2026-09-20T10:00:01Z",
};

const RUN_DETAIL = {
  ...RUN_SUMMARY,
  params: { classified_as: "IP", time_limit_s: 30 },
  assignments: { assign: [["ahmed", "mon", "morning"], ["bilal", "tue", "night"]] },
  constraints: [
    {
      constraint_id: "c_cover_demand",
      label: "c_cover_demand",
      hard: false,
      satisfied: false,
      total_violation: 36,
      penalty_paid: 3600,
      violations: [
        { index: ["thu", "morning"], by: 4 },
        { index: ["tue", "evening"], by: 3 },
      ],
    },
    {
      constraint_id: "c_max_hours",
      label: "c_max_hours",
      hard: true,
      satisfied: true,
      total_violation: 0,
      penalty_paid: 0,
      violations: [],
    },
  ],
};

function stub(overrides: Record<string, unknown> = {}) {
  mockFetch.mockImplementation((path: string, options?: { method?: string }) => {
    if (options?.method && options.method !== "GET") {
      const write = overrides.write as ((p: string) => Promise<unknown>) | undefined;
      if (write) return write(path);
      return Promise.reject(new Error(`unexpected write ${path}`));
    }
    // `/api/problem/`, not `/api/public/problem` -- the public schema's
    // prefix is collapsed (Ruling 27).
    if (path.startsWith("/api/problem")) return Promise.resolve(overrides.problems ?? PROBLEMS);
    if (path.startsWith("/api/v1/scenarios")) return Promise.resolve(overrides.scenarios ?? SCENARIOS);
    // A function lets a test change what the server says between polls,
    // which is the whole point of a queued run.
    const resolve = (value: unknown, fallback: unknown) =>
      Promise.resolve(typeof value === "function" ? (value as () => unknown)() : (value ?? fallback));
    if (path.startsWith("/api/v1/runs/")) return resolve(overrides.run, RUN_DETAIL);
    if (path.startsWith("/api/v1/runs")) return resolve(overrides.runs, { items: [RUN_SUMMARY], total: 1 });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/runs"]}>
          <Runs />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.setItem(DOMAIN_STORAGE_KEY, "1");
  stub();
});

describe("Runs", () => {
  it("points at the domain selector rather than showing an empty page when no domain is chosen", async () => {
    localStorage.removeItem(DOMAIN_STORAGE_KEY);
    renderPage();

    expect(await screen.findByText(/choose a domain/i)).toBeInTheDocument();
  });

  it("shows a run with the objective, the solver that produced it and how long it took", async () => {
    renderPage();

    expect(await screen.findByRole("button", { name: /run 11/i })).toBeInTheDocument();
    // Reproducibility facts belong on screen, not only in the database.
    expect(screen.getAllByText(/ortools 9\.15\.6755/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("3621").length).toBeGreaterThan(0);
    expect(screen.getAllByText("0.009s").length).toBeGreaterThan(0);
  });

  it("distinguishes a proven optimum from a merely feasible answer", async () => {
    stub({ run: { ...RUN_DETAIL, status: "feasible" }, runs: { items: [{ ...RUN_SUMMARY, status: "feasible" }], total: 1 } });
    renderPage();

    // "an answer" is a weaker claim than "the best answer", and the screen
    // must not upgrade it.
    expect(await screen.findByText(/not proven best/i)).toBeInTheDocument();
  });

  it("names the instances a soft constraint broke, not just that it broke", async () => {
    renderPage();

    // "coverage: broken" is not actionable; "thursday morning, short by 4" is.
    const detail = await screen.findByRole("region", { name: /run 11/i });
    expect(within(detail).getByText(/short by 36/)).toBeInTheDocument();
    expect(within(detail).getByText("thu · morning")).toBeInTheDocument();
    expect(within(detail).getByText(/short by 4/)).toBeInTheDocument();
    expect(within(detail).getByText("c_max_hours")).toBeInTheDocument();
    expect(within(detail).getByText("held")).toBeInTheDocument();
  });

  it("explains an infeasible run instead of showing an empty roster", async () => {
    const infeasible = {
      ...RUN_DETAIL,
      status: "infeasible",
      objective: null,
      assignments: null,
      constraints: [],
    };
    stub({ run: infeasible, runs: { items: [{ ...RUN_SUMMARY, status: "infeasible", objective: null }], total: 1 } });
    renderPage();

    expect(await screen.findByText(/no answer exists/i)).toBeInTheDocument();
  });

  it("shows the reason a model could not be solved at all", async () => {
    const errored = {
      ...RUN_DETAIL,
      status: "error",
      objective: null,
      assignments: null,
      constraints: [],
      error: "constraint 'c_old' carries no expression, so there is nothing to solve",
    };
    stub({ run: errored, runs: { items: [{ ...RUN_SUMMARY, status: "error", objective: null }], total: 1 } });
    renderPage();

    // `findAllByRole("alert")` resolves as soon as *an* alert exists, which
    // can be a toast region rather than the run's own message -- so wait for
    // the text itself.
    const message = await screen.findByText(/carries no expression/);
    expect(message).toHaveAttribute("role", "alert");
  });

  it("queues on demand and says so while the request is in flight", async () => {
    let resolveWrite: (value: unknown) => void = () => {};
    stub({
      write: () => new Promise((resolve) => { resolveWrite = resolve; }),
      runs: { items: [], total: 0 },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /solve relaxed_cover/i }));

    // Submitting only queues now, so the button says that rather than
    // claiming the solver is working -- a worker does that, elsewhere.
    expect(await screen.findByRole("button", { name: /queueing/i })).toBeDisabled();
    resolveWrite({ ...RUN_DETAIL, id: 12 });
    await waitFor(() => expect(screen.getByRole("button", { name: /solve relaxed_cover/i })).toBeEnabled());
  });

  it("follows a queued run until it settles, then stops asking", async () => {
    // The answer arrives from a worker, so the page must keep looking --
    // and must stop once a run is finished, since a run never changes again.
    let status = "queued";
    stub({
      run: () => ({ ...RUN_DETAIL, status }),
      runs: () => ({ items: [{ ...RUN_SUMMARY, status }], total: 1 }),
    });
    renderPage();

    expect(await screen.findByText(/waiting to start/i)).toBeInTheDocument();
    status = "optimal";

    expect(await screen.findByText(/best possible answer/i, {}, { timeout: 4000 })).toBeInTheDocument();
  });

  it("says a problem has no scenarios rather than offering to solve nothing", async () => {
    stub({ scenarios: { items: [], total: 0 } });
    renderPage();

    expect(await screen.findByText(/a run solves one/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^solve/i })).not.toBeInTheDocument();
  });

  it("reports a failed solve without losing the runs already listed", async () => {
    const { ApiError } = await import("../api/client");
    stub({ write: () => Promise.reject(new ApiError(500, JSON.stringify({ detail: "boom" }))) });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /solve/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run 11/i })).toBeInTheDocument();
  });
});
