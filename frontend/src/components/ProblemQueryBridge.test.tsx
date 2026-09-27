import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProblemQueryBridge from "./ProblemQueryBridge";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";

const renders: string[] = [];
function Page() {
  const { search } = useLocation();
  renders.push(search);
  return <p data-testid="page">{search}</p>;
}
function mount(path: string) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><Routes>
      <Route path="domains/:domainId/problems/:problemId" element={<ProblemQueryBridge />}>
        <Route path="model" element={<Page />} />
        <Route path="runs/:runId" element={<Page />} />
        <Route path="versions/:versionId" element={<Page />} />
      </Route>
    </Routes></MemoryRouter>
  </QueryClientProvider>);
}
describe("problem route validation", () => {
  beforeEach(() => {
    renders.length = 0;
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path) => {
      if (path === "/api/problem/9") return { id: 9, domain_id: 7 };
      if (path === "/api/v1/runs/42") return { id: 42, scenario_id: 10, status: "optimal" };
      if (path === "/api/v1/scenarios/10") return { id: 10, problem_id: 9 };
      if (path === "/api/v1/versions/20") return { id: 20, problem_id: 11 };
      throw new Error(`Unexpected ${path}`);
    });
  });
  it("never mounts the page with a conflicting problem query and preserves view state", async () => {
    mount("/domains/7/problems/9/model?problem=99&tab=rules");
    expect(await screen.findByTestId("page")).toHaveTextContent("problem=9&tab=rules");
    expect(renders.every((search) => !search.includes("problem=99"))).toBe(true);
  });
  it("rejects a problem in another domain", async () => {
    mount("/domains/3/problems/9/model");
    expect(await screen.findByRole("alert")).toHaveTextContent("does not belong");
    expect(renders).toHaveLength(0);
  });
  it("resolves and verifies the run's scenario before showing results", async () => {
    mount("/domains/7/problems/9/runs/42?scenario=99");
    const page = await screen.findByTestId("page");
    expect(page).toHaveTextContent("scenario=10");
    expect(page).toHaveTextContent("run=42");
    expect(renders.every((search) => !search.includes("scenario=99"))).toBe(true);
  });
  it("rejects a version from another problem", async () => {
    mount("/domains/7/problems/9/versions/20");
    expect(await screen.findByRole("alert")).toHaveTextContent("does not belong");
    expect(renders).toHaveLength(0);
  });
  it("rejects an invalid explicit run id", async () => {
    mount("/domains/7/problems/9/runs/invalid");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(renders).toHaveLength(0);
  });
});
