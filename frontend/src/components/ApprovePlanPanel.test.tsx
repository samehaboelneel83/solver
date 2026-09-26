import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ApprovePlanPanel from "./ApprovePlanPanel";

vi.mock("../hooks/useCapability", () => ({
  useCapabilities: () => ({ can: (c: string) => c === "model.publish" }),
}));

vi.mock("../api/v1", () => ({
  useScenario: () => ({ data: { problem_id: 1 } }),
  useProblemApprovals: () => ({ data: [] }),
  useApproveRun: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("./ToastProvider", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

function wrap(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("ApprovePlanPanel", () => {
  it("offers approve for a usable plan with no current approval", () => {
    wrap(<ApprovePlanPanel runId={9} scenarioId={2} status="optimal" />);
    expect(screen.getByText(/No approved plan/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve this plan/i })).toBeInTheDocument();
  });

  it("does not offer approve for a failed run", () => {
    wrap(<ApprovePlanPanel runId={9} scenarioId={2} status="error" />);
    expect(screen.getByText(/Only a usable plan/i)).toBeInTheDocument();
  });
});
