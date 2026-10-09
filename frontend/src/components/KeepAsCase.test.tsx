import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";
import { KeepAsCase } from "./KeepAsCase";

describe("keeping a run's answer as an acceptance case", () => {
  it("saves it under a name", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ id: 4 });
    render(<QueryClientProvider client={new QueryClient()}><KeepAsCase problemId={3} runId={77} /></QueryClientProvider>);
    fireEvent.click(screen.getByText("Keep this answer as an acceptance case"));
    fireEvent.change(screen.getByLabelText("Case name"), { target: { value: "base week" } });
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(await screen.findByText("Kept as “base week”.")).toBeInTheDocument();
    const [path, init] = vi.mocked(apiFetch).mock.calls[0];
    expect(path).toBe("/api/v1/problems/3/suite-cases/from-run/77");
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ name: "base week" });
  });
});
