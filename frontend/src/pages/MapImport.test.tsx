import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { DomainRouteProvider } from "../hooks/useDomain";
import MapImport from "./MapImport";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

beforeAll(() => {
  globalThis.ResizeObserver = class {
    constructor(private cb: ResizeObserverCallback) {}
    observe() { this.cb([{ contentRect: { width: 800, height: 500 } } as ResizeObserverEntry], this as unknown as ResizeObserver); }
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

const UPLOAD = {
  upload_id: "u1", filename: "mina-camp.geojson", size_bytes: 6745, unit_choices: {}, utm_zones: [],
  summary: {
    version: "GeoJSON", units_code: 0, units_name: null, unit_metres: null, extent: [39.8928, 21.4128, 39.8932, 21.4131],
    layers: [{ name: "CAMP_BOUNDARY", color: "#2563eb", linetype: "Continuous", on: true, frozen: false, locked: false,
      kinds: { polygon: 1 }, entities: { Polygon: 1 }, features: 1 }],
    kinds: { polygon: 1 }, features: 1, geodata: { epsg: 4326, reason: "GeoJSON is longitude and latitude in WGS 84 (RFC 7946)" },
    notes: [], skipped: {},
  },
  candidates: [{ placement: { kind: "epsg", code: 4326 }, name: "WGS 84", area: "World", reason: "GeoJSON is longitude and latitude",
    centre: [39.893, 21.413], fits: true, score: 11, sure: true }],
};

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
  mockFetch.mockImplementation((path: string) => {
    if (path === "/api/v1/gis/uploads") return Promise.resolve(UPLOAD);
    if (path.startsWith("/api/v1/gis/uploads/u1/preview")) return Promise.resolve({
      placement: { kind: "epsg", code: 4326 }, bbox: [39.8928, 21.4128, 39.8932, 21.4131], sampled: false, total: 1,
      warnings: [], repaired: 0, dropped: 0, features: { type: "FeatureCollection", features: [] } });
    if (path.startsWith("/api/v1/gis/regions")) return Promise.resolve({ items: [] });
    if (path.startsWith("/api/v1/me")) return Promise.resolve({ username: "a", display_name: null, capabilities: ["domain.edit"] });
    if (path.startsWith("/api/v1/settings")) return Promise.resolve({ items: [] });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
});

it("takes GIS files, not only drawings, and says when a file names its coordinate system", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/domains/7/map-data/import"]}>
        <Routes>
          <Route path="/domains/:domainId/map-data/import" element={<DomainRouteProvider><MapImport /></DomainRouteProvider>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const input = await screen.findByLabelText("Map data file");
  for (const ending of [".dxf", ".geojson", ".kml", ".kmz", ".gpx", ".zip", ".gpkg", ".csv"]) {
    expect(input.getAttribute("accept")).toContain(ending);
  }
  fireEvent.change(input, { target: { files: [new File(["{}"], "mina-camp.geojson", { type: "application/geo+json" })] } });
  expect(await screen.findByText(/mina-camp\.geojson · GeoJSON · 1 features/)).toBeInTheDocument();
  expect(screen.getByText(/The file names its coordinate system \(EPSG:4326\)/)).toBeInTheDocument();
  await waitFor(() => expect(screen.getByDisplayValue("mina-camp")).toBeInTheDocument());
});

it("imports several files at once, each whose coordinate system is certain, and names the rest", async () => {
  const unsure = { ...UPLOAD, upload_id: "u2", candidates: [{ ...UPLOAD.candidates[0], sure: false }] };
  const posted: unknown[] = [];
  let uploads = 0;
  mockFetch.mockImplementation((path: string, init?: { body?: string }) => {
    if (path === "/api/v1/gis/uploads") return Promise.resolve(uploads++ === 0 ? UPLOAD : unsure);
    if (path === "/api/v1/gis/datasets") { posted.push(JSON.parse(init?.body ?? "{}")); return Promise.resolve({ id: 41 }); }
    if (path.startsWith("/api/v1/gis/regions")) return Promise.resolve({ items: [] });
    if (path.startsWith("/api/v1/me")) return Promise.resolve({ username: "a", display_name: null, capabilities: ["domain.edit"] });
    if (path.startsWith("/api/v1/settings")) return Promise.resolve({ items: [] });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={["/domains/7/map-data/import"]}>
        <Routes>
          <Route path="/domains/:domainId/map-data/import" element={<DomainRouteProvider><MapImport /></DomainRouteProvider>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const input = await screen.findByLabelText("Map data file");
  expect(input).toHaveAttribute("multiple");
  fireEvent.change(input, { target: { files: [new File(["{}"], "candidate_sites.geojson"), new File(["0"], "site plan.dxf")] } });
  const list = await screen.findByRole("region", { name: "Imported files" });
  await waitFor(() => expect(list).toHaveTextContent("site plan.dxf: its coordinate system is not certain"));
  expect(screen.getByRole("link", { name: "candidate_sites.geojson" })).toHaveAttribute("href", "/domains/7/map-data/41");
  expect(posted).toEqual([{ upload_id: "u1", domain_id: 7, name: "candidate sites", placement: { kind: "epsg", code: 4326 }, units: null,
    layers: ["CAMP_BOUNDARY"] }]);
});
