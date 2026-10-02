import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
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

function Harness({ start = "", blocked, allowCreate }: { start?: string; blocked?: Map<string, string>; allowCreate?: boolean }) {
  const [value, setValue] = useState(start);
  return (
    <>
      <RecordPicker typeId={3} value={value} onChange={setValue} blocked={blocked} data-testid="picker"
        allowCreate={allowCreate} kindName="depot" />
      <output data-testid="value">{value}</output>
    </>
  );
}

function renderPicker(props: { start?: string; blocked?: Map<string, string>; allowCreate?: boolean } = {}) {
  return render(
    <QueryClientProvider client={editorQueryClient()}>
      <MemoryRouter>
        <Harness {...props} />
      </MemoryRouter>
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

  it("takes a key or name typed in full without it being clicked", async () => {
    renderPicker();
    const input = screen.getByTestId("picker");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "D850" } });
    await screen.findByRole("option", { name: "D850 — Depot 850" });
    fireEvent.blur(input);
    expect(screen.getByTestId("value")).toHaveTextContent("D850");
    await new Promise((resolve) => setTimeout(resolve, 150)); // the list closes after a blur

    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "Depot 12" } });
    await screen.findByRole("option", { name: "D129 — Depot 129" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("value")).toHaveTextContent("D12");
    expect(screen.getByTestId("value")).not.toHaveTextContent("D129");
  });

  it("leaves a partly typed key unpicked", async () => {
    renderPicker();
    const input = screen.getByTestId("picker");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "D85" } });
    await screen.findByRole("option", { name: "D850 — Depot 850" });
    fireEvent.change(input, { target: { value: "D8" } });
    await waitFor(() => expect(mockFetch.mock.calls.some(([url]) => String(url).includes("q=D8&"))).toBe(true));
    fireEvent.blur(input);
    expect(screen.getByTestId("value")).toHaveTextContent("");
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

  it("creates a record with the typed key when none has it, and picks it", async () => {
    renderPicker({ allowCreate: true });
    const input = screen.getByTestId("picker");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "D9999" } });
    mockFetch.mockImplementation((url: string, init?: RequestInit) =>
      init?.method === "POST" ? Promise.resolve(rec(9999, "D9999")) : serve(url)
    );
    fireEvent.mouseDown(await screen.findByRole("option", { name: "+ Create “D9999” as a new depot" }));
    await waitFor(() => expect(screen.getByTestId("value")).toHaveTextContent("D9999"));
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/entities", expect.objectContaining({
      method: "POST", body: JSON.stringify({ entity_type_id: 3, key: "D9999" }),
    }));
  });

  it("does not offer to create a key that already exists", async () => {
    renderPicker({ allowCreate: true });
    const input = screen.getByTestId("picker");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "D12" } });
    await screen.findByRole("option", { name: "D12 — Depot 12" });
    expect(screen.queryByRole("option", { name: /Create/ })).toBeNull();
  });

  it("sends the reader to the full form when the new record needs more than a key", async () => {
    renderPicker({ allowCreate: true });
    const input = screen.getByTestId("picker");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "NEW" } });
    mockFetch.mockImplementation((url: string, init?: RequestInit) =>
      init?.method === "POST" ? Promise.reject(new Error("entity NEW: attribute \"capacity\" is required")) : serve(url)
    );
    fireEvent.mouseDown(await screen.findByRole("option", { name: /Create “NEW”/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/capacity/);
    expect(screen.getByRole("link", { name: "Open the full form" })).toHaveAttribute("href", "/entities/new?type=3");
    expect(screen.getByTestId("value")).toHaveTextContent("");
  });
});
