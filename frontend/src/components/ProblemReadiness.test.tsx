import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProblemReadiness from "./ProblemReadiness";

const runs = vi.hoisted(() => ({ total: 0, versions: 0, scenarios: 0 }));
vi.mock("../api/v1", async () => {
  const actual = await vi.importActual<typeof import("../api/v1")>("../api/v1");
  return {
    ...actual,
    useVersions: () => ({ data: { items: Array.from({ length: runs.versions }, (_, id) => ({ id })) }, isLoading: false }),
    useScenarios: () => ({ data: { items: Array.from({ length: runs.scenarios }, (_, id) => ({ id })) }, isLoading: false }),
    useProblemRuns: () => ({ data: { items: [], total: runs.total }, isLoading: false }),
  };
});

describe("ProblemReadiness", () => {
  it("keeps readiness links inside the scoped problem", () => {
    render(<QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/domains/7/problems/12/model"]}><Routes>
        <Route path="/domains/:domainId/problems/:problemId/model" element={<ProblemReadiness problemId={12} />} />
      </Routes></MemoryRouter>
    </QueryClientProvider>);
    expect(screen.getByRole("link", { name: "Create a scenario" })).toHaveAttribute("href", "/domains/7/problems/12/scenarios");
  });
  beforeEach(() => {
    vi.clearAllMocks();
    runs.total = 0;
    runs.versions = 0;
    runs.scenarios = 0;
  });

  it("shrinks to one line naming the next step, and to nothing once every step is done (operator trial F13)", () => {
    runs.versions = 1;
    runs.scenarios = 1;
    const view = render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><ProblemReadiness problemId={12} /></MemoryRouter></QueryClientProvider>);
    expect(screen.getByRole("note", { name: "Problem readiness" })).toHaveTextContent("2 of 3 steps done. Next: Run and review a result");
    runs.total = 1;
    view.rerender(<QueryClientProvider client={new QueryClient()}><MemoryRouter><ProblemReadiness problemId={12} /></MemoryRouter></QueryClientProvider>);
    expect(screen.queryByLabelText("Problem readiness")).not.toBeInTheDocument();
  });

  it("ticks running a result once the problem has a run (operator trial F10)", () => {
    runs.total = 3;
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><ProblemReadiness problemId={12} /></MemoryRouter></QueryClientProvider>);
    expect(screen.queryByRole("link", { name: "Run and review a result" })).not.toBeInTheDocument();
    expect(screen.getByText("Run and review a result")).toHaveClass("line-through");
  });

  it("links the next incomplete modelling steps", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <ProblemReadiness problemId={12} />
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(screen.getByRole("region", { name: "Problem readiness" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Publish a model version" })).toHaveAttribute(
      "href",
      "/model?problem=12"
    );
    expect(screen.getByRole("link", { name: "Create a scenario" })).toHaveAttribute(
      "href",
      "/scenarios?problem=12"
    );
  });
});

