import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProblemReadiness from "./ProblemReadiness";

vi.mock("../api/v1", async () => {
  const actual = await vi.importActual<typeof import("../api/v1")>("../api/v1");
  return {
    ...actual,
    useVersions: () => ({ data: { items: [] }, isLoading: false }),
    useScenarios: () => ({ data: { items: [] }, isLoading: false }),
  };
});

describe("ProblemReadiness", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
