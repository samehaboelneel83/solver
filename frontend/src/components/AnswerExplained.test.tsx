import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";
import { AnswerExplained } from "./AnswerExplained";

describe("the answer explained on the run's page", () => {
  it("reads the explanation only when opened", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ text: "GOAL 10 (maximize)\\nuse: A, B" });
    render(<QueryClientProvider client={new QueryClient()}><AnswerExplained runId={12} /></QueryClientProvider>);
    expect(apiFetch).not.toHaveBeenCalled();
    const summary = screen.getByText("The answer explained");
    (summary.parentElement as HTMLDetailsElement).open = true;
    fireEvent(summary.parentElement!, new Event("toggle"));
    expect(await screen.findByLabelText("The answer explained")).toHaveTextContent("GOAL 10 (maximize)");
    expect(apiFetch).toHaveBeenCalledWith("/api/v1/runs/12/explanation");
  });
});
