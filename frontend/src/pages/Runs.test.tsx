import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Runs, { formatGap, howFound, statusNote, unexpressedRules } from "./Runs";
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
  cancel_requested: false,
};

const RUN_DETAIL = {
  ...RUN_SUMMARY,
  params: { classified_as: "IP", time_limit_s: 30 },
  conflict: null,
  conflict_minimal: null,
  labels: { employee: { ahmed: "Ahmed Salah", bilal: "Bilal Omar" }, day: { mon: "Monday", tue: "Tuesday" } },
  index_sets: {
    variables: { assign: ["employee", "day", "shift"] },
    constraints: { c_cover: ["day", "shift"], c_max_hours: ["employee"] },
  },
  assignments: { assign: [["ahmed", "mon", "morning"], ["bilal", "tue", "night"]] },
  reduced_costs: null,
  constraints: [
    {
      constraint_id: "c_cover_demand",
      label: "c_cover_demand",
      hard: false,
      satisfied: false,
      total_violation: 36,
      penalty_paid: 3600,
      slack: -36,
      dual: null,
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
      slack: 0,
      dual: 6,
      violations: [],
    },
  ],
};

const COMPARISON = {
  left: {
    id: 11, scenario_id: 7, scenario_name: "strict", status: "infeasible", solver: "cp-sat",
    solver_version: "cp-sat (ortools 9.15)", objective: null, wall_time_s: 0.01, dataset_id: 3, patch: {},
  },
  right: {
    id: 12, scenario_id: 8, scenario_name: "relaxed", status: "optimal", solver: "cp-sat",
    solver_version: "cp-sat (ortools 9.15)", objective: 3621, wall_time_s: 0.02, dataset_id: 3,
    patch: { soften: { c_cover: 100 } },
  },
  objective_delta: 120,
  moved: { assign: { added: [["sara", "tue", "morning"]], removed: [["ahmed", "tue", "morning"]], unchanged: 4 } },
  rules: [
    {
      constraint_id: "c_cover",
      left_satisfied: true, right_satisfied: false,
      left_violation: 0, right_violation: 2,
      left_penalty: 0, right_penalty: 200,
    },
  ],
  differs_by: ["patch"],
  patch_is_the_only_difference: true,
  note: "the patch is the only difference, so the change in the answer is down to it",
};

function stub(overrides: Record<string, unknown> = {}) {
  mockFetch.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
    if (options?.method && options.method !== "GET") {
      const write = overrides.write as
        | ((p: string, o?: { method?: string; body?: string }) => Promise<unknown>)
        | undefined;
      if (write) return write(path, options);
      return Promise.reject(new Error(`unexpected write ${path}`));
    }
    // `/api/problem/`, not `/api/public/problem` -- the public schema's
    // prefix is collapsed (Ruling 27).
    if (path.startsWith("/api/problem")) return Promise.resolve(overrides.problems ?? PROBLEMS);
    if (/^\/api\/v1\/scenarios\/\d+$/.test(path)) {
      return Promise.resolve(overrides.scenario ?? SCENARIOS.items[0]);
    }
    if (path.startsWith("/api/v1/scenarios")) return Promise.resolve(overrides.scenarios ?? SCENARIOS);
    // A function lets a test change what the server says between polls,
    // which is the whole point of a queued run.
    const resolve = (value: unknown, fallback: unknown) =>
      Promise.resolve(typeof value === "function" ? (value as () => unknown)() : (value ?? fallback));
    if (path.startsWith("/api/v1/me")) {
      return Promise.resolve(
        overrides.me ?? {
          username: "admin",
          display_name: "Administrator",
          capabilities: ["domain.edit", "model.publish", "run.submit", "solver.configure"],
        }
      );
    }
    // The scenario's model version: expressed by default.
    if (path.startsWith("/api/v1/versions/")) {
      return Promise.resolve(
        overrides.version ?? {
          id: 2,
          problem_id: 1,
          version: 2,
          ir_hash: "h",
          note: null,
          created_at: "2026-09-20T09:00:00Z",
          ir: { constraints: [{ id: "c_cover", left: { const: 0 }, relation: "<=", right: { const: 1 }, severity: "hard" }] },
        }
      );
    }
    if (path.startsWith("/api/v1/solvers")) {
      return Promise.resolve({
        items: [
          { name: "cp-sat", available: true, classes: ["IP"], note: "constraint programming" },
          { name: "milp", available: true, classes: ["IP"], note: "branch and cut" },
          { name: "gone", available: false, classes: ["IP"], note: "not in this build" },
        ],
      });
    }
    if (path.includes("/compare/")) return resolve(overrides.comparison, COMPARISON);
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

describe("gap and unbounded (migration 0029)", () => {
  it("says how far an unproven answer may be from the best", () => {
    expect(statusNote({ status: "feasible", optimality: "none", gap: 0.0231 })).toMatch(/at most 2.3% worse/);
  });

  it("says a run stopped on request kept the answer it had", () => {
    expect(statusNote({ status: "feasible", gap: 0.1, stopped: true })).toMatch(
      /Stopped on request\. The best answer found by then -- at most 10% worse/
    );
    expect(statusNote({ status: "feasible", gap: null, stopped: true })).toMatch(/not proven best/);
  });

  it("falls back to the plain note when there is no bound", () => {
    expect(statusNote({ status: "feasible", optimality: "none", gap: null })).toMatch(/not proven best/);
  });

  it("names the modelling mistake behind an unbounded run", () => {
    expect(statusNote({ status: "unbounded" })).toMatch(/missing a limit/);
  });

  it("writes a gap a planner can read", () => {
    expect(formatGap(0)).toBe("0%");
    expect(formatGap(0.00000001)).toBe("under 0.01%");
    expect(formatGap(0.123456)).toBe("12%");
    expect(formatGap(0.5)).toBe("50%");
  });
});

describe("statusNote (migration 0028)", () => {
  it("promises the best of all answers only when that was proven", () => {
    expect(statusNote({ status: "optimal", optimality: "global" })).toMatch(/no other answer does better/);
  });

  it("says a local optimum is not proven the best overall", () => {
    // Worded like a global optimum, it would be believed -- and on a model
    // that is not convex a better answer can exist elsewhere.
    const note = statusNote({ status: "optimal", optimality: "local" });
    expect(note).toMatch(/not proven the best overall/);
    expect(note).not.toMatch(/no other answer does better/);
  });

  it("keeps the plain note for a run older than the claim, and for every other status", () => {
    expect(statusNote({ status: "optimal" })).toBe("Best possible answer, proven.");
    expect(statusNote({ status: "feasible", optimality: "none" })).toMatch(/not proven best/);
  });
});

describe("unexpressedRules and scheduling", () => {
  it("does not call a scheduling rule unexpressed", () => {
    expect(
      unexpressedRules({
        constraints: [
          { id: "c_room", no_overlap: { interval: { var: "task", index: ["d"] }, over: [] }, severity: "hard" },
          { id: "c_old", note: "named only" },
        ],
      })
    ).toEqual(["c_old"]);
  });
});

describe("unexpressedRules", () => {
  it("names rules that carry no arithmetic, and nothing for an expressed model", () => {
    expect(
      unexpressedRules({
        constraints: [
          { id: "c_old", note: "named only" },
          { id: "c_new", left: { const: 0 }, relation: "<=", right: { const: 1 } },
        ],
      })
    ).toEqual(["c_old"]);
    expect(unexpressedRules({ constraints: [] })).toEqual([]);
    expect(unexpressedRules(undefined)).toEqual([]);
  });
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

  it("leads with whether the mandatory rules held, not the solver name", async () => {
    renderPage();

    expect(await screen.findByText(/all mandatory rules held/i)).toBeInTheDocument();
    expect(screen.getByText(/1 preference bent, at cost 3600/i)).toBeInTheDocument();
    // Solver facts stay available, under Technical rather than in the header.
    expect(screen.getByText("Technical")).toBeInTheDocument();
    expect(screen.getByText(/no room left/i)).toBeInTheDocument();
    expect(screen.getByText(/worth 6 on the goal/i)).toBeInTheDocument();
  });

  it("names a decision that would move the goal", async () => {
    stub({
      run: {
        ...RUN_DETAIL,
        reduced_costs: { buy: [{ index: ["oats"], value: 94 }] },
        index_sets: {
          ...RUN_DETAIL.index_sets,
          variables: { ...RUN_DETAIL.index_sets.variables, buy: ["feed"] },
        },
        labels: { ...RUN_DETAIL.labels, feed: { oats: "Oats" } },
      },
    });
    renderPage();

    expect(await screen.findByText(/would move the goal/i)).toBeInTheDocument();
    expect(screen.getByText(/Oats/)).toBeInTheDocument();
    expect(screen.getByText(/worth 94 on the goal/i)).toBeInTheDocument();
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

  it("shows the answer in the names people use, not the keys", async () => {
    // `ahmed` is a spelling the platform chose; a planner reads names.
    stub();
    renderPage();

    expect(await screen.findByText(/Ahmed Salah . Monday . morning/)).toBeInTheDocument();
    // `shift` has no labels in the frozen data, so that position stays as the
    // key rather than going blank.
    expect(screen.queryByText(/ahmed . mon . morning/)).not.toBeInTheDocument();
  });

  it("falls back to the key for a run made before names were frozen", async () => {
    // Runs from before migration 0012 have no labels. They must read back in
    // keys -- which is what they were shown as when they were made -- rather
    // than render empty.
    stub({ run: { ...RUN_DETAIL, labels: {} } });
    renderPage();

    expect(await screen.findByText(/ahmed . mon . morning/)).toBeInTheDocument();
  });

  it("names the rules that cannot hold together when there is no answer", async () => {
    // The difference between a tool and a calculator: "infeasible" is not a
    // finding, "coverage and the hours cap collide on Monday morning" is.
    const infeasible = {
      ...RUN_DETAIL,
      status: "infeasible",
      objective: null,
      assignments: null,
      constraints: [],
      conflict: [
        { constraint_id: "c_cover", instance: ["mon", "morning"] },
        { constraint_id: "c_cover", instance: ["tue", "morning"] },
        { constraint_id: "c_max_hours", instance: ["sara"] },
      ],
      conflict_minimal: true,
    };
    stub({ run: infeasible, runs: { items: [{ ...RUN_SUMMARY, status: "infeasible", objective: null }], total: 1 } });
    renderPage();

    const why = await screen.findByRole("heading", { name: /why there is no answer/i });
    const panel = why.closest("section") as HTMLElement;
    expect(within(panel).getByText("c_cover")).toBeInTheDocument();
    expect(within(panel).getByText("c_max_hours")).toBeInTheDocument();
    // The instances, in names, because a rule alone does not say where to
    // look and "mon" is a key rather than a day.
    expect(within(panel).getByText(/Monday . morning/)).toBeInTheDocument();
    // Proven irreducible, so the stronger promise is the one shown.
    expect(within(panel).getByText(/relax or remove any single one/i)).toBeInTheDocument();
  });

  it("reads a conflict in the rules' own words, and says how it was found", async () => {
    const infeasible = {
      ...RUN_DETAIL,
      status: "infeasible",
      solver: "cp-sat",
      objective: null,
      assignments: null,
      constraints: [],
      rule_notes: { c_cover: "each day/shift is staffed to demand", c_budget: "the batch is exactly 100 kg" },
      conflict: [
        { constraint_id: "c_cover", instance: ["mon", "morning"] },
        { constraint_id: "c_max_hours", instance: ["sara"] },
        { constraint_id: "c_budget", instance: [] },
      ],
      conflict_minimal: true,
      params: { ...RUN_DETAIL.params, conflict_method: "cp-sat", conflict_probes: 3, conflict_seconds: 0.004 },
    };
    stub({ run: infeasible, runs: { items: [{ ...RUN_SUMMARY, status: "infeasible", objective: null }], total: 1 } });
    renderPage();

    const why = await screen.findByRole("heading", { name: /why there is no answer/i });
    const panel = why.closest("section") as HTMLElement;
    // The author's words lead; the id follows, to find it in the model.
    expect(within(panel).getByText("each day/shift is staffed to demand")).toBeInTheDocument();
    expect(within(panel).getByText("(c_cover)")).toBeInTheDocument();
    // A rule with no note is still named, by its id.
    expect(within(panel).getByText("c_max_hours")).toBeInTheDocument();
    // A rule over nothing names no day: it is the rule as a whole.
    expect(within(panel).getByText("the rule as a whole")).toBeInTheDocument();
    expect(
      within(panel).getByText(
        "Found from CP-SAT's own reasoning about why no answer exists, then each rule checked by solving again with CP-SAT (3 checks, under 0.01 s)."
      )
    ).toBeInTheDocument();
  });

  it("offers to turn the fighting rules into preferences", async () => {
    const write = vi.fn().mockResolvedValue({
      id: 9,
      problem_id: 1,
      model_version_id: 2,
      name: "from run 11",
      patch: { soften: { c_cover: 100, c_max_hours: 100 } },
      created_at: "2026-09-21T10:00:00Z",
    });
    const infeasible = {
      ...RUN_DETAIL,
      status: "infeasible",
      objective: null,
      assignments: null,
      constraints: [],
      conflict: [
        { constraint_id: "c_cover", instance: ["mon", "morning"] },
        { constraint_id: "c_max_hours", instance: ["sara"] },
      ],
      conflict_minimal: true,
    };
    stub({
      write,
      run: infeasible,
      runs: { items: [{ ...RUN_SUMMARY, status: "infeasible", objective: null }], total: 1 },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /make these preferences/i }));

    await waitFor(() => expect(write).toHaveBeenCalled());
    const [path, options] = write.mock.calls[0];
    expect(path).toBe("/api/v1/scenarios");
    expect(JSON.parse(options.body as string)).toMatchObject({
      problem_id: 1,
      model_version_id: 2,
      name: "from run 11",
      patch: { soften: { c_cover: 100, c_max_hours: 100 } },
    });
  });

  it("names a rule that ranged over nobody", async () => {
    stub({
      run: {
        ...RUN_DETAIL,
        params: {
          ...RUN_DETAIL.params,
          empty_ranges: [{ constraint_id: "c_north", kind: "forall", index: {} }],
        },
      },
    });
    renderPage();

    expect(await screen.findByText(/rules that ranged over nobody/i)).toBeInTheDocument();
    expect(screen.getByText(/c_north/)).toBeInTheDocument();
    expect(screen.getByText(/never applied to anyone/i)).toBeInTheDocument();
  });

  it("does not promise that relaxing one rule is enough when the search was cut short", async () => {
    // A truncated search still returns a set that conflicts, but some members
    // may not be needed. Saying "remove any one" would send a planner to
    // change a rule that changes nothing.
    const infeasible = {
      ...RUN_DETAIL,
      status: "infeasible",
      objective: null,
      assignments: null,
      constraints: [],
      conflict: [{ constraint_id: "c_cover", instance: ["mon", "morning"] }],
      conflict_minimal: false,
    };
    stub({ run: infeasible, runs: { items: [{ ...RUN_SUMMARY, status: "infeasible", objective: null }], total: 1 } });
    renderPage();

    const why = await screen.findByRole("heading", { name: /why there is no answer/i });
    const panel = why.closest("section") as HTMLElement;
    expect(within(panel).getByText(/stopped before it could narrow/i)).toBeInTheDocument();
    expect(within(panel).queryByText(/relax or remove any single one/i)).not.toBeInTheDocument();
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

  it("offers to stop a queued run, and does not offer it on a finished one", async () => {
    let status = "queued";
    stub({
      run: () => ({
        ...RUN_DETAIL,
        status,
        finished_at: status === "queued" ? null : RUN_DETAIL.finished_at,
        assignments: status === "cancelled" ? null : RUN_DETAIL.assignments,
        constraints: status === "cancelled" ? [] : RUN_DETAIL.constraints,
        cancel_requested: status !== "queued",
      }),
      runs: () => ({ items: [{ ...RUN_SUMMARY, status, finished_at: status === "queued" ? null : RUN_SUMMARY.finished_at }], total: 1 }),
      write: (path?: string) => {
        if (String(path).includes("/cancel")) {
          status = "cancelled";
          return Promise.resolve({
            ...RUN_DETAIL,
            status: "cancelled",
            cancel_requested: true,
            assignments: null,
            constraints: [],
          });
        }
        return Promise.reject(new Error(`unexpected write ${path}`));
      },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /stop this run/i }));

    expect(await screen.findByText(/stopped before an answer/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /stop this run/i })).not.toBeInTheDocument();
  });

  it("does not offer to stop a finished run", async () => {
    renderPage();

    await screen.findByRole("button", { name: /run 11/i });
    expect(screen.queryByRole("button", { name: /stop this run/i })).not.toBeInTheDocument();
  });

  it("offers only the solvers this build actually has, and defaults to letting it choose", async () => {
    renderPage();

    const picker = await screen.findByLabelText(/solver/i);
    // The registry is fetched, so the options arrive after the control does.
    await screen.findByRole("option", { name: "milp" });
    const offered = Array.from((picker as HTMLSelectElement).options).map((o) => o.value);
    expect(offered).toEqual(["", "cp-sat", "milp"]);
    // A build without a solver must not offer it: the run would fail at
    // selection rather than being quietly given to another.
    expect(offered).not.toContain("gone");
    expect(picker).toHaveValue("");
  });

  it("asks for a named solver when one is chosen", async () => {
    const write = vi.fn().mockResolvedValue({ ...RUN_DETAIL, id: 12 });
    stub({ write, runs: { items: [], total: 0 } });
    renderPage();

    await screen.findByRole("option", { name: "milp" });
    fireEvent.change(screen.getByLabelText(/solver/i), { target: { value: "milp" } });
    fireEvent.click(screen.getByRole("button", { name: /^solve/i }));

    await waitFor(() => expect(write).toHaveBeenCalled());
    expect(JSON.parse(write.mock.calls[0][1].body).solver).toBe("milp");
  });

  it("says why a solver was chosen, not only which", async () => {
    stub({ run: { ...RUN_DETAIL, params: { ...RUN_DETAIL.params, why_solver: "asked for milp" } } });
    renderPage();

    expect(await screen.findByText("asked for milp")).toBeInTheDocument();
  });

  it("compares two runs and shows what moved between them", async () => {
    stub({
      runs: {
        items: [RUN_SUMMARY, { ...RUN_SUMMARY, id: 12, objective: 3741 }],
        total: 2,
      },
    });
    renderPage();

    const chooser = await screen.findByLabelText(/compare run 11 with/i);
    fireEvent.change(chooser, { target: { value: "12" } });

    const heading = await screen.findByRole("heading", { name: /run 11 compared with run 12/i });
    const panel = heading.closest("section") as HTMLElement;
    // What moved, in both directions -- a list of only additions would read
    // as a bigger roster rather than a different one.
    expect(within(panel).getByText(/sara . tue . morning/)).toBeInTheDocument();
    expect(within(panel).getByText(/ahmed . tue . morning/)).toBeInTheDocument();
    expect(within(panel).getByText(/\+120/)).toBeInTheDocument();
    expect(within(panel).getByText("c_cover")).toBeInTheDocument();
  });

  it("refuses to credit the patch when the runs differ by more than it", async () => {
    // The honesty rule, on screen: two runs over different data can differ
    // for reasons that have nothing to do with the rules.
    stub({
      runs: { items: [RUN_SUMMARY, { ...RUN_SUMMARY, id: 12 }], total: 2 },
      comparison: {
        ...COMPARISON,
        differs_by: ["data", "patch"],
        patch_is_the_only_difference: false,
        note: "these runs differ by data, patch, so a change in the answer cannot be attributed to any one of them",
      },
    });
    renderPage();

    fireEvent.change(await screen.findByLabelText(/compare run 11 with/i), { target: { value: "12" } });

    const heading = await screen.findByRole("heading", { name: /run 11 compared with run 12/i });
    const panel = heading.closest("section") as HTMLElement;
    expect(within(panel).getByText(/cannot be attributed/i)).toBeInTheDocument();
  });

  it("does not offer to compare a run with itself", async () => {
    stub({ runs: { items: [RUN_SUMMARY], total: 1 } });
    renderPage();

    await screen.findByText(/Run 11/);
    expect(screen.queryByLabelText(/compare run/i)).not.toBeInTheDocument();
  });

  it("does not offer to solve to an account that may not", async () => {
    // Absent, not broken: a button whose only outcome is a 403 is worse than
    // no button, because it reads as the platform being unreliable.
    stub({ me: { username: "viewer", display_name: null, capabilities: [] } });
    renderPage();

    expect(await screen.findByText(/may read runs but not start them/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Solve/ })).not.toBeInTheDocument();
  });

  it("hides the solver chooser from an account that may solve but not choose", async () => {
    stub({ me: { username: "planner", display_name: null, capabilities: ["run.submit"] } });
    renderPage();

    expect(await screen.findByRole("button", { name: /^Solve/ })).toBeInTheDocument();
    // The chooser would only ever produce a refusal for this account.
    expect(screen.queryByLabelText(/^Solver$/)).not.toBeInTheDocument();
  });

  it("explains a scenario that can never be solved instead of offering Solve", async () => {
    // A version published before rules had arithmetic is permanent, so every
    // run of it errors. Say that, and where to go, before anyone presses a
    // button whose only outcome is an error.
    stub({
      version: {
        id: 1,
        problem_id: 1,
        version: 1,
        ir_hash: "h",
        note: "first",
        created_at: "2026-09-19T09:00:00Z",
        ir: { constraints: [{ id: "c_cover_demand", note: "each day is covered" }] },
      },
    });
    renderPage();

    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent(/c_cover_demand is named but says nothing a solver can check/);
    expect(note).toHaveTextContent(/version 1/);
    expect(screen.queryByRole("button", { name: /^Solve/ })).not.toBeInTheDocument();
    // The history stays readable.
    expect(await screen.findByText(/Run 11/)).toBeInTheDocument();
  });

  it("offers Solve for a scenario whose rules are all expressed", async () => {
    stub();
    renderPage();
    expect(await screen.findByRole("button", { name: /^Solve/ })).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
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


describe("howFound", () => {
  it("says which reasoning found a conflict, and what making sure of it cost", () => {
    expect(howFound({ conflict_method: "iis", conflict_probes: 1, conflict_seconds: 0.48 }, "glop")).toBe(
      "Found from HiGHS's analysis of the model, then each rule checked by solving again with GLOP (1 check, 0.48 s)."
    );
    expect(howFound({ conflict_method: "deletion", conflict_probes: 24, conflict_seconds: 1.2 }, "highs")).toBe(
      "Found by solving the model again with HiGHS, leaving rules out one at a time (24 checks, 1.2 s)."
    );
    // Runs from before the method was recorded say nothing rather than guess.
    expect(howFound({}, "cp-sat")).toBeNull();
  });
});
