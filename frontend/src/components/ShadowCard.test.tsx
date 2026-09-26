import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ShadowCard from "./ShadowCard";

const emptyMock = {
  data: { problem_id: 1, candidates: [] },
  isError: false,
  error: null,
};

const filledMock = {
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
        recent: [
          {
            real_run: 10,
            shadow_run: 11,
            status: "optimal",
            verdict: { delta: 0, at_least_as_good: true },
          },
        ],
      },
    ],
  },
  isError: false,
  error: null,
};

vi.mock("../api/v1", () => ({
  useShadowReport: vi.fn(),
}));

import { useShadowReport } from "../api/v1";

function renderCard() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ShadowCard problemId={1} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ShadowCard (OAAS W02)", () => {
  it("explains how to start without naming setting keys", () => {
    vi.mocked(useShadowReport).mockReturnValue(emptyMock as ReturnType<typeof useShadowReport>);
    renderCard();
    expect(screen.getByRole("region", { name: "Candidate comparison" })).toBeInTheDocument();
    expect(screen.getByText(/Model versions/i)).toBeInTheDocument();
    expect(screen.queryByText(/shadow\.version/)).not.toBeInTheDocument();
    expect(screen.queryByText(/shadow\.rate/)).not.toBeInTheDocument();
  });

  it("shows candidate share and recent pairs in plain language", () => {
    vi.mocked(useShadowReport).mockReturnValue(filledMock as ReturnType<typeof useShadowReport>);
    renderCard();
    expect(screen.getByText(/Version 7/)).toBeInTheDocument();
    expect(screen.getByText(/100% as good or better/)).toBeInTheDocument();
    expect(screen.getByText(/Live plan 10 ↔ candidate 11/)).toBeInTheDocument();
  });
});
