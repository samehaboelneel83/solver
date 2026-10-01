import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockImplementation((path: string) => {
    if (path.startsWith("/api/v1/gis/datasets")) return Promise.resolve({ postgis: true, items: [{
      id: 3, domain_id: 7, name: "Site plan", layers: 6, source: { filename: "site.dxf" },
      placement: { kind: "epsg", code: 32636, name: "WGS 84 / UTM zone 36N" }, bbox: [31.2, 30.0, 31.3, 30.1],
      stats: { features: 1234 }, notes: [], created_at: "2026-10-01T09:00:00Z", updated_at: "2026-10-01T09:00:00Z",
    }] });
    if (path.startsWith("/api/v1/me")) return Promise.resolve({ username: "a", display_name: null, capabilities: ["domain.edit"] });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
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
  expect(await screen.findByRole("link", { name: /Import a CAD drawing/ })).toHaveAttribute("href", "/domains/7/map-data/import");
});
