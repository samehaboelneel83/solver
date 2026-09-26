import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import ShadowCard from "./ShadowCard";

vi.mock("../api/v1", () => ({
  useShadowReport: () => ({
    data: {
      problem_id: 1,
      candidates: [
        {
          model_version_id: 7,
          runs: 3,
          compared: 2,
          at_least_as_good: 2,
          share_at_least_as_good: 1,
          median_time_ratio: 1.1,
          worst: null,
          recent: [{ real_run: 10, shadow_run: 11, status: "optimal", verdict: { delta: 0, at_least_as_good: true } }],
        },
      ],
    },
    isError: false,
    error: null,
  }),
}));

describe("ShadowCard", () => {
  it("shows candidate share and recent pairs", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <ShadowCard problemId={1} />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("region", { name: "Shadow runs" })).toBeInTheDocument();
    expect(screen.getByText(/100% at least as good/)).toBeInTheDocument();
    expect(screen.getByText(/real 10 ↔ shadow 11/)).toBeInTheDocument();
  });
});
