import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DataChecks from "./DataChecks";
import { editorQueryClient } from "../test/me";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const rec = (id: number, key: string) => ({ id, key, label: null });

function renderChecks() {
  return render(
    <QueryClientProvider client={editorQueryClient()}>
      <MemoryRouter>
        <DataChecks domainId={7} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => mockFetch.mockReset());

describe("DataChecks", () => {
  it("lists each finding with its records as links, worst first as the server sends them", async () => {
    mockFetch.mockResolvedValue({
      findings: [
        { code: "loop", severity: "error", says: "1 loop through “manager”.", count: 2, records: [rec(1, "a"), rec(2, "b")], attribute: "manager" },
        { code: "empty_reference", severity: "info", says: "empty on 1 record.", count: 1, records: [rec(3, "c")], attribute: "region" },
      ],
    });
    renderChecks();
    const loop = await screen.findByTestId("finding-loop");
    expect(loop).toHaveTextContent("Must fix");
    expect(loop).toHaveTextContent("Chain loops back on itself");
    expect(within(loop).getByRole("link", { name: "a" })).toHaveAttribute("href", "/entities/1");
    expect(screen.getByTestId("finding-empty_reference")).toHaveTextContent("Note");
  });

  it("asks again with the depth limit the reader sets", async () => {
    mockFetch.mockResolvedValue({ findings: [] });
    renderChecks();
    await screen.findByTestId("checks-clean");
    fireEvent.change(screen.getByLabelText(/Deepest level allowed/), { target: { value: "3" } });
    await waitFor(() => expect(mockFetch).toHaveBeenLastCalledWith("/api/v1/domains/7/data-checks?max_depth=3"));
  });

  it("shows twelve records, then the rest on request, and says how many were not listed", async () => {
    const records = Array.from({ length: 50 }, (_, i) => rec(i + 1, `r${i + 1}`));
    mockFetch.mockResolvedValue({ findings: [{ code: "outside_tree", severity: "warning", says: "x", count: 80, records }] });
    renderChecks();
    const finding = await screen.findByTestId("finding-outside_tree");
    expect(within(finding).getAllByRole("link")).toHaveLength(12);
    expect(finding).toHaveTextContent("and 30 not listed");
    fireEvent.click(within(finding).getByRole("button", { name: "38 more" }));
    expect(within(finding).getAllByRole("link")).toHaveLength(50);
  });
});
