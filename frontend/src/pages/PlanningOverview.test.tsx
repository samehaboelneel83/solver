import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import type { Readiness } from "../api/v1";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DomainOverview, ProblemOverview } from "./PlanningOverview";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";

const domain = { id: 7, name: "Workforce" };
const problem = { id: 9, domain_id: 7, name: "Weekly staffing", owner: "Planning team" };
let capabilities: string[];
const ready = (): Readiness => ({
  problem: { id: 9, domain_id: 7, name: "Weekly staffing" },
  latest_version: { id: 20, version: 4, created_at: "2026-09-30T09:00:00Z" },
  draft: null,
  check: { ready: true, findings: [], model_class: "IP", sets: { employee: 2 } },
  base_scenario: null,
  last_run: null,
  workers: { state: "ready", online: 1, solving: 0, queued: 0, last_seen: null, says: "1 worker is online; a new run starts at once" },
});
let readiness: Readiness;

function RunPage() {
  return <p>run page {useParams().runId}</p>;
}

function mount(path: string) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><Routes>
      <Route path="domains/:domainId/overview" element={<DomainOverview />} />
      <Route path="domains/:domainId/problems" element={<DomainOverview listing />} />
      <Route path="domains/:domainId/problems/:problemId/overview" element={<ProblemOverview />} />
      <Route path="domains/:domainId/problems/:problemId/runs/:runId" element={<RunPage />} />
    </Routes></MemoryRouter>
  </QueryClientProvider>);
}

describe("planning overviews", () => {
  beforeEach(() => {
    capabilities = ["domain.edit", "model.publish", "run.submit"];
    readiness = ready();
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path, options) => {
      if (path.startsWith("/api/v1/problems/9/readiness/check")) return { check: readiness.check };
      if (path.startsWith("/api/v1/problems/9/readiness")) return readiness;
      if (path === "/api/v1/problems/9/solve") return { id: 77, status: "queued" };
      if (path === "/api/v1/problems/9/draft/publish") return { id: 21, version: 5 };
      if (path === "/api/v1/entities/41") return options?.method === "PATCH" ? {} : { id: 41, attrs: { band: "senior" }, updated_at: "2026-09-30T10:00:00Z" };
      if (path === "/api/v1/attributes/5") return {};
      if (path.startsWith("/api/domain/")) return { items: [domain], total: 1 };
      if (path === "/api/problem/9") return problem;
      if (path.startsWith("/api/problem/?")) return { items: [problem], total: 1 };
      if (path === "/api/v1/me") return { username: "planner", capabilities };
      throw new Error(`Unexpected ${path}`);
    });
  });

  it("opens domain problems through canonical links and scopes the query even with conflicting filters", async () => {
    mount("/domains/7/overview?f_domain_id=99");
    expect(await screen.findByRole("heading", { name: "Workforce", level: 1 })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Weekly staffing/ })).toHaveAttribute("href", "/domains/7/problems/9/overview");
    const request = vi.mocked(apiFetch).mock.calls.find(([path]) => path.startsWith("/api/problem/?"))?.[0];
    expect(request).toContain("f_domain_id=7");
    expect(request).not.toContain("99");
    expect(screen.getByText("1 problem in this workspace")).toBeInTheDocument();  // not "1 problems" (F19)
    expect(screen.getByRole("link", { name: "Records & relationships" })).toHaveAttribute("href", "/domains/7/data");
    expect(screen.getByRole("link", { name: /New problem/ })).toHaveAttribute("href", "/domains/7/start");
  });

  it("searches within the same domain and resets pagination", async () => {
    mount("/domains/7/problems?page=2");
    await screen.findByRole("link", { name: /Weekly staffing/ });
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a problem" }), { target: { value: "weekly" } });
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([path]) =>
      path.includes("q=weekly") && path.includes("offset=0") && path.includes("f_domain_id=7"))).toBe(true));
  });

  it("tells a new, empty workspace where to begin", async () => {
    const served = vi.mocked(apiFetch).getMockImplementation()!;
    vi.mocked(apiFetch).mockImplementation(async (path, options) => {
      if (path.startsWith("/api/v1/entity-types")) return { items: [], total: 0 };
      if (path.startsWith("/api/problem/?")) return { items: [], total: 0 };
      return served(path, options);
    });
    mount("/domains/7/overview");
    const begin = await screen.findByRole("region", { name: "Where to begin" });
    expect(within(begin).getByRole("link", { name: "map files" })).toHaveAttribute("href", "/domains/7/map-data/import");
    expect(within(begin).getByRole("link", { name: "Start a problem" })).toHaveAttribute("href", "/domains/7/start");
  });

  it("does not offer creation to readers", async () => {
    capabilities = [];
    mount("/domains/7/overview");
    await screen.findByRole("link", { name: /Weekly staffing/ });
    expect(screen.queryByRole("link", { name: /New problem/ })).not.toBeInTheDocument();
  });

  it("walks the five steps and solves from the problem page in one click", async () => {
    mount("/domains/7/problems/9/overview");
    expect(await screen.findByRole("heading", { name: "Weekly staffing", level: 1 })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Run model check" }));
    await screen.findByRole("button", { name: "Solve" });
    const steps = within(screen.getByRole("list", { name: "Steps" })).getAllByRole("listitem").map((item) => item.getAttribute("aria-label"));
    expect(steps).toEqual(["Step 1, Data: done", "Step 2, Model: done", "Step 3, Check: done", "Step 4, Solve: to do", "Step 5, Results: waiting"]);
    expect(screen.getByTestId("step-data-says")).toHaveTextContent("employee: 2");
    fireEvent.click(screen.getByRole("button", { name: "Solve" }));
    expect(await screen.findByText("run page 77")).toBeInTheDocument();
    expect(vi.mocked(apiFetch).mock.calls.some(([path, options]) => path === "/api/v1/problems/9/solve" && options?.method === "POST")).toBe(true);
  });

  it("renders the overview while the full model check is still running", async () => {
    let finishCheck!: (value: { check: Readiness["check"] }) => void;
    const serve = vi.mocked(apiFetch).getMockImplementation()!;
    vi.mocked(apiFetch).mockImplementation((path, options) => path.endsWith("/readiness/check")
      ? new Promise((resolve) => { finishCheck = resolve; })
      : serve(path, options));
    mount("/domains/7/problems/9/overview");

    expect(await screen.findByRole("heading", { name: "Weekly staffing", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run model check" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Run model check" }));
    expect(screen.getByRole("status")).toHaveTextContent("Large models may take longer");
    expect(screen.getByRole("button", { name: "Checking model…" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Solve" })).not.toBeInTheDocument();

    finishCheck({ check: readiness.check });
    expect(await screen.findByRole("button", { name: "Solve" })).toBeInTheDocument();
  });

  it("takes the person to what stops the solve, focused and lit (benchmark re-test, October 2026)", async () => {
    readiness = { ...ready(), check: { ready: false, model_class: "IP", sets: { employee: 2 }, findings: [{
      kind: "blocker", code: "does_not_compile", says: "c_cover reads a field no employee has." }] } };
    mount("/domains/7/problems/9/overview");
    fireEvent.click(await screen.findByRole("button", { name: "Run model check" }));
    fireEvent.click(await screen.findByRole("button", { name: /See what stops it/ }));
    const check = screen.getByRole("listitem", { name: /^Step 3, Check/ });
    expect(check).toHaveFocus();
    expect(check.className).toContain("ring-2");
    expect(check).toHaveTextContent("c_cover reads a field no employee has.");
  });

  it("fills a missing value in place, from the step that needs it", async () => {
    readiness = { ...ready(), check: { ready: false, model_class: "IP", sets: { employee: 2 }, findings: [{
      kind: "blocker", code: "missing_values", says: "1 employee record has no hours_per_week, which the model reads as a number.",
      missing: { set: "employee", attribute: "hours_per_week", attribute_id: 5, entity_type_id: 3, data_type: "integer", enum_values: null,
        default_value: null, records: [{ id: 41, key: "ahmed", label: null, updated_at: "2026-09-30T10:00:00Z" }] },
    }] } };
    mount("/domains/7/problems/9/overview");
    fireEvent.click(await screen.findByRole("button", { name: "Run model check" }));
    expect(await screen.findByRole("button", { name: "Fill in 1 missing value" })).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "Step 1, Data: something to fix" })).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "Step 3, Check: waiting" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("hours_per_week for ahmed"), { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: "Save 1 value" }));
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([path, options]) => path === "/api/v1/entities/41" && options?.method === "PATCH")).toBe(true));
    const [, sent] = vi.mocked(apiFetch).mock.calls.find(([path, options]) => path === "/api/v1/entities/41" && options?.method === "PATCH")!;
    expect(JSON.parse(String(sent?.body))).toEqual({ attrs: { band: "senior", hours_per_week: 40 }, updated_at: "2026-09-30T10:00:00Z" });
    // Or one value for everyone without one, kept as the default.
    fireEvent.change(screen.getByLabelText("hours_per_week for every employee without one"), { target: { value: "38" } });
    fireEvent.click(screen.getByRole("button", { name: "Use as default" }));
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([path, options]) => path === "/api/v1/attributes/5" && options?.method === "PATCH")).toBe(true));
  });

  it("keeps what was typed when a save changes the count of missing values", async () => {
    const gap = (records: { id: number; key: string }[]) => ({ ...ready(), check: { ready: false, model_class: "IP", sets: { employee: 3 }, findings: [{
      kind: "blocker" as const, code: "missing_values", says: `${records.length} employee records have no hours_per_week, which the model reads as a number.`,
      missing: { set: "employee", attribute: "hours_per_week", attribute_id: 5, entity_type_id: 3, data_type: "integer", enum_values: null,
        default_value: null, records: records.map((r) => ({ ...r, label: null, updated_at: "2026-09-30T10:00:00Z" })) },
    }] } });
    readiness = gap([{ id: 41, key: "ahmed" }, { id: 42, key: "sara" }]);
    mount("/domains/7/problems/9/overview");
    fireEvent.click(await screen.findByRole("button", { name: "Run model check" }));
    fireEvent.change(await screen.findByLabelText("hours_per_week for every employee without one"), { target: { value: "38" } });
    fireEvent.change(screen.getByLabelText("hours_per_week for ahmed"), { target: { value: "40" } });
    readiness = gap([{ id: 42, key: "sara" }]);
    fireEvent.click(screen.getByRole("button", { name: "Save 1 value" }));
    await waitFor(() => expect(screen.queryByLabelText("hours_per_week for ahmed")).not.toBeInTheDocument());
    // The count in the words changed; the table did not start over.
    expect(screen.getByText("Saved 1 value.")).toBeInTheDocument();
  });

  it("publishes unpublished changes before solving them", async () => {
    readiness = { ...ready(), draft: { revision: 3, updated_at: "2026-09-30T10:00:00Z", unpublished: true } };
    mount("/domains/7/problems/9/overview");
    expect(await screen.findByRole("listitem", { name: "Step 2, Model: to do" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Publish changes and solve" })[0]);
    expect(await screen.findByText("run page 77")).toBeInTheDocument();
    const posted = vi.mocked(apiFetch).mock.calls.filter(([, options]) => options?.method === "POST").map(([path]) => path);
    expect(posted).toEqual(["/api/v1/problems/9/draft/publish", "/api/v1/problems/9/solve"]);
  });

  it("points an empty problem to model creation without claiming it is ready to run", async () => {
    readiness = { ...ready(), latest_version: null, check: null };
    mount("/domains/7/problems/9/overview");
    expect(await screen.findByRole("link", { name: "Build the model" })).toHaveAttribute("href", "/domains/7/problems/9/model");
    expect(screen.getByRole("listitem", { name: "Step 2, Model: to do" })).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "Step 4, Solve: waiting" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Solve" })).not.toBeInTheDocument();
  });

  it("leads to the results once a run has settled, and still offers what-if work", async () => {
    readiness = { ...ready(), last_run: { id: 77, status: "optimal", optimality: "global", objective: 120, queued_at: "", finished_at: "", scenario_id: 12, scenario: "Base" } };
    mount("/domains/7/problems/9/overview");
    fireEvent.click(await screen.findByRole("button", { name: "Run model check" }));
    expect(await screen.findByRole("link", { name: "See the results" })).toHaveAttribute("href", "/domains/7/problems/9/runs/77");
    expect(screen.getByTestId("step-results-says")).toHaveTextContent("A plan was found, worth 120.");
    expect(screen.getByRole("button", { name: "Solve again" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Scenarios" })).toHaveAttribute("href", "/domains/7/problems/9/scenarios");
  });

  it("reports a failed readiness read instead of guessing", async () => {
    const serve = vi.mocked(apiFetch).getMockImplementation()!;
    vi.mocked(apiFetch).mockImplementation((path, options) => path.includes("/readiness")
      ? Promise.reject(new Error("unreachable")) : serve(path, options));
    mount("/domains/7/problems/9/overview");
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    expect(screen.getByRole("button", { name: /^Retry/ })).toBeInTheDocument();
  });
});
