import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RecordPicker from "./RecordPicker";
import { editorQueryClient } from "../test/me";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const rec = (id: number, key: string, label: string | null = null) => ({
  id, entity_type_id: 3, key, label, sort_order: 0, active: true, attrs: {},
});

// 900 depots on the server: the one chosen is far past any first page.
const ALL = Array.from({ length: 900 }, (_, i) => rec(i + 1, `D${i + 1}`, `Depot ${i + 1}`));

function serve(url: string) {
  const q = new URL(url, "http://x").searchParams.get("q");
  const hits = q ? ALL.filter((e) => e.key.includes(q) || (e.label ?? "").includes(q)) : ALL;
  return Promise.resolve({ items: hits.slice(0, 20), total: hits.length });
}

function Harness({ start = "", blocked }: { start?: string; blocked?: Map<string, string> }) {
  const [value, setValue] = useState(start);
  return (
    <>
      <RecordPicker typeId={3} value={value} onChange={setValue} blocked={blocked} data-testid="picker" />
      <output data-testid="value">{value}</output>
    </>
  );
}

function renderPicker(props: { start?: string; blocked?: Map<string, string> } = {}) {
  return render(
    <QueryClientProvider client={editorQueryClient()}>
      <Harness {...props} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockImplementation((url: string) => serve(url));
});

describe("RecordPicker", () => {
  it("shows a chosen record past the first 500 by its name, not as 'not found'", async () => {
    renderPicker({ start: "D777" });
    await waitFor(() => expect(screen.getByTestId("picker")).toHaveValue("D777 — Depot 777"));
    expect(screen.queryByText(/not a record here/)).toBeNull();
  });

  it("searches the server by what is typed and picks the result", async () => {
    renderPicker();
    const input = screen.getByTestId("picker");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "D850" } });
    const option = await screen.findByRole("option", { name: "D850 — Depot 850" });
    expect(mockFetch.mock.calls.some(([url]) => String(url).includes("q=D850"))).toBe(true);
    fireEvent.mouseDown(option);
    expect(screen.getByTestId("value")).toHaveTextContent("D850");
  });

  it("lists a blocked record with its reason and does not take it", async () => {
    renderPicker({ blocked: new Map([["D12", "would make a loop"]]) });
    const input = screen.getByTestId("picker");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "D12" } });
    const option = await screen.findByRole("option", { name: /D12 — Depot 12 \(would make a loop\)/ });
    expect(option).toHaveAttribute("aria-disabled", "true");
    fireEvent.mouseDown(option);
    expect(screen.getByTestId("value")).toHaveTextContent("");
  });

  it("names a value that no longer exists", async () => {
    renderPicker({ start: "GONE" });
    expect(await screen.findByText("“GONE” is not a record here any more.")).toBeInTheDocument();
  });

  it("clears an optional value", async () => {
    renderPicker({ start: "D5" });
    fireEvent.click(await screen.findByRole("button", { name: "Clear" }));
    expect(screen.getByTestId("value")).toHaveTextContent("");
  });
});
