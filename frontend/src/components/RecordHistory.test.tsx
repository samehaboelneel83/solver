import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RecordHistory from "./RecordHistory";
import { editorQueryClient } from "../test/me";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const entry = (id: number, op: string, changes: object[] = [], actor: string | null = "mona") =>
  ({ id, at: "2026-10-02T09:30:00Z", actor, op, changes });

function renderHistory() {
  render(
    <QueryClientProvider client={editorQueryClient()}>
      <RecordHistory entityId={21} />
    </QueryClientProvider>
  );
}

beforeEach(() => mockFetch.mockReset());

describe("RecordHistory", () => {
  it("lists changes newest first, each field from what to what, and who made it", async () => {
    mockFetch.mockResolvedValue({ total: 2, items: [
      entry(2, "update", [{ field: "depot", before: "D3", after: "D7" }, { field: "parked", before: null, after: { type: "Point", coordinates: [1, 2] } }]),
      entry(1, "insert", [], null),
    ] });
    renderHistory();
    const list = await screen.findByRole("list", { name: "Changes, newest first" });
    const [latest, first] = within(list).getAllByRole("listitem");
    expect(latest).toHaveTextContent("Changed");
    expect(latest).toHaveTextContent("mona");
    expect(within(latest).getByRole("rowheader", { name: "depot" }).nextSibling).toHaveTextContent("D3→ became D7");
    expect(latest).toHaveTextContent("a Point");
    expect(first).toHaveTextContent("Created");
    expect(first).toHaveTextContent("the system");
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/entities/21/history?limit=20");
  });

  it("offers older changes, and says when there are none", async () => {
    mockFetch.mockResolvedValueOnce({ total: 30, items: Array.from({ length: 20 }, (_, i) => entry(30 - i, "update", [])) });
    renderHistory();
    fireEvent.click(await screen.findByRole("button", { name: "Older changes (10)" }));
    expect(mockFetch).toHaveBeenLastCalledWith("/api/v1/entities/21/history?limit=40");
  });

  it("says so when nothing is kept yet", async () => {
    mockFetch.mockResolvedValue({ total: 0, items: [] });
    renderHistory();
    expect(await screen.findByText(/No change kept yet/)).toBeInTheDocument();
  });
});
