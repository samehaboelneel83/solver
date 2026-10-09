import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
vi.mock("../hooks/useCapability", () => ({ useCapabilities: () => ({ known: true, can: () => true }) }));
import { apiFetch } from "../api/client";
import { SourcesPage, fileMapping } from "./Sources";

const calls = () => vi.mocked(apiFetch).mock.calls.map(([path, init]) => `${(init as RequestInit | undefined)?.method ?? "GET"} ${String(path)}`);
const bodyOf = (path: string) => JSON.parse(String((vi.mocked(apiFetch).mock.calls.find(([p, i]) => p === path
  && (i as RequestInit | undefined)?.method === "POST")![1] as RequestInit).body));

function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={["/domains/7/data/sources"]}><Routes>
      <Route path="/domains/:domainId/data/sources" element={<SourcesPage />} />
    </Routes></MemoryRouter></QueryClientProvider>);
}

const TYPES = { total: 1, items: [{ id: 9, name: "crew", is_abstract: false, attributes: [{ name: "size", data_type: "number" }] }] };

describe("keeping data refreshed, without the Assistant", () => {
  let bindings: unknown[];
  beforeEach(() => {
    bindings = [];
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path, init) => {
      const p = String(path);
      const method = (init as RequestInit | undefined)?.method ?? "GET";
      if (p.startsWith("/api/v1/connections?")) return { items: [], total: 0 };
      if (p === "/api/v1/domains/7/files") return { items: [{ name: "crews.csv", latest: 1, versions: 1, rows: 2, updated_at: "2026-10-09T08:00:00Z" }] };
      if (p === "/api/v1/domains/7/files/crews.csv") return { name: "crews.csv", sheets: [{ name: "crews", columns: ["crew", "size"], rows: [["A", 4], ["B", 6]] }] };
      if (p === "/api/v1/domains/7/source-bindings" && method === "GET") return { items: bindings };
      if (p === "/api/v1/domains/7/source-bindings" && method === "POST") {
        bindings = [{ id: 3, connection_id: null, connection: "crews.csv", file_name: "crews.csv", file_version: null, kind: "entities", target: "crew", job_id: null, refreshed_at: null }];
        return { bound: true, rows: 2 };
      }
      if (p === "/api/v1/domains/7/source-bindings/3" && method === "DELETE") { bindings = []; return null; }
      if (p === "/api/v1/domains/7/sources/refresh") return { applied: true, changes: 2, bindings: [{ binding_id: 3, connection_id: null, file_name: "crews.csv", source: "crews.csv", kind: "entities", target: "crew", job_id: null, same_extraction: false, counts: { added: 2, changed: 0, removed: 0, unchanged: 0 }, added: [], changed: [], removed: [] }] };
      if (p.startsWith("/api/v1/entity-types")) return TYPES;
      if (p.startsWith("/api/v1/relationship-types")) return { total: 0, items: [] };
      if (p.startsWith("/api/v1/parameters")) return { total: 0, items: [] };
      if (p.startsWith("/api/v1/domains/7/refresh-schedule")) return null;
      throw new Error(`unexpected ${method} ${p}`);
    });
  });

  it("loads a kept file into records and keeps them refreshed, then can stop", async () => {
    mount();
    const files = await screen.findByRole("region", { name: "Files kept in this workspace" }).catch(() => screen.getByText("Files kept in this workspace").closest("section")!);
    fireEvent.click(await within(files as HTMLElement).findByRole("button", { name: "Load into…" }));
    const form = await screen.findByRole("group", { name: "Load crews.csv" });
    fireEvent.change(within(form).getByLabelText("Of"), { target: { value: "9" } });
    expect(within(form).getByLabelText("crew becomes")).toHaveValue(""); // no same-named target: chosen by hand
    fireEvent.change(within(form).getByLabelText("crew becomes"), { target: { value: "key" } });
    expect(within(form).getByLabelText("size becomes")).toHaveValue("size");
    fireEvent.click(within(form).getByRole("button", { name: "Load and keep refreshed" }));
    expect(await within(form).findByText(/Loaded: 2 added, 0 changed. Kept refreshed from crews.csv/)).toBeInTheDocument();
    expect(bodyOf("/api/v1/domains/7/source-bindings")).toEqual({ file_name: "crews.csv", kind: "entities", target: "crew",
      mapping: { key: "crew", attrs: { size: "size" } } });
    expect(bodyOf("/api/v1/domains/7/sources/refresh")).toEqual({ files: { "crews.csv": 1 }, apply: true });
    const bound = await screen.findByRole("heading", { name: "Kept refreshed from these sources" });
    fireEvent.click(screen.getByLabelText(/Keep records, links and values a source no longer has/));
    fireEvent.click(screen.getByRole("button", { name: "Check for changes" }));
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([p, i]) => p === "/api/v1/domains/7/sources/refresh"
      && JSON.parse(String((i as RequestInit).body)).remove_missing === false)).toBe(true));
    fireEvent.click(within(bound.closest("section")!).getByRole("button", { name: "Stop keeping refreshed" }));
    await waitFor(() => expect(calls()).toContain("DELETE /api/v1/domains/7/source-bindings/3"));
  });
});

describe("a mapping as a refresh reads it", () => {
  const types = [{ id: 1, name: "site" }, { id: 2, name: "ward" }] as never[];
  it("names links by their end types and values by every index", () => {
    expect(fileMapping("relationship_type", { from_type_id: 1, to_type_id: 2 } as never, { a: "from", b: "to" }, types, null))
      .toEqual({ from: ["site", "a"], to: ["ward", "b"] });
    expect(fileMapping("parameter", { index_type_ids: [1, 1] } as never, { x: "site_1", y: "site_2", d: "value" }, types, "km"))
      .toEqual({ sheet: "km", entities: [["site", "x"], ["site", "y"]], value: "d" });
  });
});
