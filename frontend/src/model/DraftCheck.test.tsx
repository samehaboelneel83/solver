import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";
import { DraftCheck } from "./DraftCheck";

describe("reading a draft back and trial-solving it, as the Assistant's check does", () => {
  it("shows the read-back and the trial in words", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ refusal: null, readback: ["- rule two: at most 2 crews", ""],
      trial: { status: "optimal", objective: 10, seconds: 15, used: { use: { non_zero: 2, cells: 3, chosen: ["A", "B"] } } } });
    render(<QueryClientProvider client={new QueryClient()}><DraftCheck problemId={5} ir={{ version: 2 }} /></QueryClientProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Read it back and trial-solve" }));
    expect(await screen.findByRole("list", { name: "As built" })).toHaveTextContent("rule two: at most 2 crews");
    expect(screen.getByRole("status")).toHaveTextContent("optimal, goal 10; use used in 2 of 3 (A, B).");
    const [path, init] = vi.mocked(apiFetch).mock.calls[0];
    expect(path).toBe("/api/v1/problems/5/draft-check");
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ ir: { version: 2 }, trial: true });
  });

  it("says when no answer exists, and when the draft is refused", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ refusal: { code: "set_not_in_domain", loc: ["sets", 1], message: "no such kind" },
      readback: [] });
    render(<QueryClientProvider client={new QueryClient()}><DraftCheck problemId={5} ir={{ version: 2 }} /></QueryClientProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Read it back" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Not publishable yet: no such kind [set_not_in_domain at sets / 1]");
  });
});
