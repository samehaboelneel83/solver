import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DomainOverview, ProblemOverview } from "./PlanningOverview";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";

const domain = { id: 7, name: "Workforce" };
const problem = { id: 9, domain_id: 7, name: "Weekly staffing", owner: "Planning team" };
let versionItems: { id: number; version: number }[];
let scenarioItems: { id: number; name: string; problem_id: number }[];
let capabilities: string[];

function mount(path: string) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><Routes>
      <Route path="domains/:domainId/overview" element={<DomainOverview />} />
      <Route path="domains/:domainId/problems" element={<DomainOverview listing />} />
      <Route path="domains/:domainId/problems/:problemId/overview" element={<ProblemOverview />} />
    </Routes></MemoryRouter>
  </QueryClientProvider>);
}

describe("planning overviews", () => {
  beforeEach(() => {
    versionItems = [{ id: 20, version: 4 }];
    scenarioItems = [{ id: 12, name: "Busy week", problem_id: 9 }];
    capabilities = ["domain.edit", "model.publish"];
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path) => {
      if (path.startsWith("/api/domain/")) return { items: [domain], total: 1 };
      if (path === "/api/problem/9") return problem;
      if (path.startsWith("/api/problem/?")) return { items: [problem], total: 1 };
      if (path.includes("/versions")) return { items: versionItems, total: versionItems.length };
      if (path.includes("/scenarios")) return { items: scenarioItems, total: scenarioItems.length };
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
    expect(screen.getByRole("link", { name: "Records & relationships" })).toHaveAttribute("href", "/domains/7/data");
    expect(screen.getByRole("link", { name: /New problem/ })).toHaveAttribute("href", "/public/problem/new?f_domain_id=7");
  });

  it("searches within the same domain and resets pagination", async () => {
    mount("/domains/7/problems?page=2");
    await screen.findByRole("link", { name: /Weekly staffing/ });
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a problem" }), { target: { value: "weekly" } });
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([path]) =>
      path.includes("q=weekly") && path.includes("offset=0") && path.includes("f_domain_id=7"))).toBe(true));
  });

  it("does not offer creation to readers", async () => {
    capabilities = [];
    mount("/domains/7/overview");
    await screen.findByRole("link", { name: /Weekly staffing/ });
    expect(screen.queryByRole("link", { name: /New problem/ })).not.toBeInTheDocument();
  });

  it("shows real version and scenario readiness with scoped next actions", async () => {
    mount("/domains/7/problems/9/overview");
    expect(await screen.findByRole("heading", { name: "Weekly staffing", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Published version 4")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open results" })).toHaveAttribute("href", "/domains/7/problems/9/runs");
    expect(screen.getByRole("link", { name: "Busy week" })).toHaveAttribute("href", "/domains/7/problems/9/scenarios/12");
    expect(screen.getByRole("link", { name: "Review results for Busy week" })).toHaveAttribute("href", "/domains/7/problems/9/runs?scenario=12");
  });

  it("points an empty problem to model creation without claiming it is ready to run", async () => {
    versionItems = [];
    scenarioItems = [];
    mount("/domains/7/problems/9/overview");
    expect(await screen.findByRole("link", { name: "Build the model" })).toHaveAttribute("href", "/domains/7/problems/9/model");
    expect(screen.getByText("No published version")).toBeInTheDocument();
    expect(screen.queryByText("Ready to review or run")).not.toBeInTheDocument();
  });

  it("reports failed readiness queries instead of showing zero scenarios", async () => {
    const serve = vi.mocked(apiFetch).getMockImplementation()!;
    vi.mocked(apiFetch).mockImplementation((path, options) => path.includes("/scenarios")
      ? Promise.reject(new Error("unreachable")) : serve(path, options));
    mount("/domains/7/problems/9/overview");
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    expect(screen.queryByText("0 scenarios")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
