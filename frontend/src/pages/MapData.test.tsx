import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { DomainRouteProvider } from "../hooks/useDomain";
import MapData from "./MapData";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

let kinds: object[] = [];

beforeEach(() => {
  kinds = [];
  mockFetch.mockReset();
  mockFetch.mockImplementation((path: string) => {
    if (path.startsWith("/api/v1/gis/datasets")) return Promise.resolve({ postgis: true, items: [{
      id: 3, domain_id: 7, name: "Site plan", layers: 6, source: { filename: "site.dxf" },
      placement: { kind: "epsg", code: 32636, name: "WGS 84 / UTM zone 36N" }, bbox: [31.2, 30.0, 31.3, 30.1],
      stats: { features: 1234 }, notes: [], created_at: "2026-10-01T09:00:00Z", updated_at: "2026-10-01T09:00:00Z",
    }] });
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve({ total: kinds.length, items: kinds });
    if (path.startsWith("/api/v1/me")) return Promise.resolve({ username: "a", display_name: null, capabilities: ["domain.edit"] });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/domains/7/map-data"]}>
        <Routes><Route path="/domains/:domainId/map-data" element={<DomainRouteProvider><MapData /></DomainRouteProvider>} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("says what comes next while no layer has been made records", async () => {
  renderPage();
  expect(await screen.findByText(/choose/)).toHaveTextContent("Next: open a layer and choose Use in models");
  expect(screen.queryByRole("form", { name: "Compute from the map" })).toBeNull();
});

it("computes distances and reach right here once records have shapes", async () => {
  kinds = [{ id: 1, domain_id: 7, name: "site", role: "location", attributes: [{ id: 10, name: "shape", data_type: "geometry" }] }];
  renderPage();
  expect(await screen.findByRole("form", { name: "Compute from the map" })).toBeInTheDocument();
});

it("lists imported drawings with their layers, size and coordinate system", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/domains/7/map-data"]}>
        <Routes><Route path="/domains/:domainId/map-data" element={<DomainRouteProvider><MapData /></DomainRouteProvider>} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const row = await screen.findByTestId("dataset");
  expect(within(row).getByRole("link", { name: "Site plan" })).toHaveAttribute("href", "/domains/7/map-data/3");
  expect(row).toHaveTextContent("site.dxf · 6 layers · 1,234 features · WGS 84 / UTM zone 36N");
  expect(screen.getByText(/Stored in PostGIS/)).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: /Import map data/ })).toHaveAttribute("href", "/domains/7/map-data/import");
});

it("makes records of a file in one click, and leaves a kind that exists to the file's page", async () => {
  const { QuickRecords } = await import("./MapData");
  const plan = { layers: ["points"], name: "hospital", exists: false, features: 4, skipped_text: 0, shapes: ["point"], key: "name",
    key_candidates: ["name"], fields: [], geometry_field: "shape", measures: [], properties: [] };
  let exists = false;
  mockFetch.mockImplementation((path: string) => {
    if (path === "/api/v1/gis/datasets/3") return Promise.resolve({ id: 3, layers: [{ name: "points", feature_count: 4 }, { name: "empty", feature_count: 0 }] });
    if (path.endsWith("/records/propose")) return Promise.resolve({ ...plan, exists });
    if (path.endsWith("/records")) return Promise.resolve({ type: "hospital", entity_type_id: 12, domain_id: 7, made: 4, updated: 0 });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
  const view = (
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><QuickRecords domainId={7} datasetId={3} /></MemoryRouter>
    </QueryClientProvider>
  );
  const { unmount } = render(view);
  fireEvent.click(screen.getByRole("button", { name: "Make records" }));
  expect(await screen.findByRole("link", { name: "✓ 4 hospital records" })).toHaveAttribute("href", "/domains/7/data/records?type=12");
  const sent = mockFetch.mock.calls.find(([p]) => String(p).endsWith("/records/propose"))!;
  expect(JSON.parse((sent[1] as { body: string }).body)).toEqual({ layers: ["points"] });
  unmount();
  exists = true;
  render(view);
  fireEvent.click(screen.getByRole("button", { name: "Make records" }));
  expect(await screen.findByRole("link", { name: /A kind “hospital” exists/ })).toHaveAttribute("href", "/domains/7/map-data/3");
});
