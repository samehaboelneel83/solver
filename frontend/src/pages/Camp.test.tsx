import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { DomainRouteProvider } from "../hooks/useDomain";
import CampEditor from "./CampEditor";
import CampList from "./CampList";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

beforeAll(() => {
  // jsdom has no layout: the map is given a size by hand.
  globalThis.ResizeObserver = class {
    constructor(private cb: ResizeObserverCallback) {}
    observe() { this.cb([{ contentRect: { width: 800, height: 500 } } as ResizeObserverEntry], this as unknown as ResizeObserver); }
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

const PROBLEM = {
  format: "camp-problem/1", name: "North camp", grid: 0.5, origin_lonlat: [31.6, 30.1],
  boundary: [[0, 0], [30, 0], [30, 20], [0, 20]],
  doors: [{ id: "D1", a: [14, 0], b: [16, 0], depth: 0.3, capacity: 40 }],
  zones: [{ door: "D1", depth: 2, max_depth: 4, step: 1, margin: 0.5, area_per_bed: 0.25 }],
  obstacles: [{ id: "tank", ring: [[5, 5], [7, 5], [7, 7], [5, 7]], kind: "closed" }],
  prohibited: [], placement_zones: [],
  bed_types: [{ id: "cot", length: 2, width: 0.9, sizes: [], rotation: true, side_gap: 0.1, min_count: 0, max_count: null, zone: null, priority: 1 }],
  corridor: { min_width: 1, access: "long_sides" },
  objectives: { mode: "lexicographic", order: ["beds", "distance", "corridor", "modifications"], weights: {}, tolerance: { distance: 0.02, corridor: 0.02 }, trade_beds: false },
};
const CHECK = {
  ok: true,
  faults: [{ where: "obstacle tank", message: "is outside the camp; it has no effect", severity: "warning" }],
  derived: { area_m2: 600, cells: 2400, door_zones: [{ door: "D1", depth: [[13.5, 0], [16.5, 0], [16.5, 2], [13.5, 2], [13.5, 0]], max_depth: [], area_m2: 6, beds_room: 24 }] },
};
const OPTIONS = { solver: "cpsat", beds_seconds: 120, seconds: 60, threads: 4 };
const DONE = {
  id: 4, status: "done", beds: 2, valid: true, error: null, options: OPTIONS, queued_at: "2026-10-01T10:00:00Z",
  started_at: "2026-10-01T10:00:01Z", finished_at: "2026-10-01T10:01:00Z",
};
const PLAN = { id: 11, domain_id: 7, name: "North camp", problem: PROBLEM, options: OPTIONS, created_at: "2026-10-01T09:00:00Z",
  updated_at: "2026-10-01T09:00:00Z", check: CHECK, solves: [DONE] };
const bed = (id: string, x: number, door: string, walk: number) => ({
  type: "Feature", geometry: { type: "Polygon", coordinates: [[[x, 4], [x + 2, 4], [x + 2, 4.9], [x, 4.9], [x, 4]]] },
  properties: { layer: "bed", id, bed_type: "cot", size: "2 x 0.9 m", resized: false, rotated: false, door, walk_m: walk },
});
const SOLVE = {
  ...DONE, camp_id: 11, camp_name: "North camp", domain_id: 7, seconds: 59, progress: ["stage 0: 2 beds"], deadline_seconds: 480,
  problem: PROBLEM,
  result: {
    input: { type: "FeatureCollection", features: [] },
    output: { type: "FeatureCollection", features: [bed("B1", 10, "D1", 4.5), bed("B2", 13, "D1", 6.25),
      { type: "Feature", geometry: { type: "LineString", coordinates: [[11, 4], [15, 0]] }, properties: { layer: "path", bed: "B1", door: "D1", walk_m: 4.5 } }] },
    report: {
      camp: "North camp", solver: "cpsat", beds: 2, beds_by_type: { cot: 2 }, resized_beds: 0, stage0_beds: 2, objectives: {}, stages: [],
      zone_depth_m: { D1: 2 }, seconds: {},
      validation: { valid: true, checks: [{ name: "no two beds overlap", ok: true, detail: "none overlap" }], walk_total_m: 10.75, walk_max_m: 6.25, walk_mean_m: 5.4, door_loads: { D1: 2 } },
    },
    origin_lonlat: [31.6, 30.1], beds: 2, valid: true,
  },
};

function stub(write = vi.fn()) {
  mockFetch.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
    if (path === "/api/v1/camps/check") return Promise.resolve(CHECK);
    if (options?.method && options.method !== "GET") return write(path, options);
    if (path.startsWith("/api/v1/camps?domain_id=")) return Promise.resolve({ items: [
      { id: 11, name: "North camp", updated_at: "2026-10-01T09:00:00Z", origin_lonlat: [31.6, 30.1], doors: 1, solve_id: 4, status: "done", beds: 2, valid: true, finished_at: null },
    ] });
    if (path === "/api/v1/camps/11") return Promise.resolve(PLAN);
    if (path === "/api/v1/camp-solves/4") return Promise.resolve(SOLVE);
    if (path.startsWith("/api/v1/me")) return Promise.resolve({ username: "a", display_name: null, capabilities: ["domain.edit", "run.submit"] });
    if (path.startsWith("/api/v1/settings")) return Promise.resolve({ items: [] });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
  return write;
}

function renderAt(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/domains/:domainId/map-data/camps" element={<DomainRouteProvider><CampList /></DomainRouteProvider>} />
          <Route path="/domains/:domainId/map-data/camps/:campId" element={<DomainRouteProvider><CampEditor /></DomainRouteProvider>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
});

it("lists the domain's camps with their latest layout and starts a new one", async () => {
  const write = stub(vi.fn().mockResolvedValue({ ...PLAN, id: 12 }));
  renderAt("/domains/7/map-data/camps");
  const row = await screen.findByTestId("camp");
  expect(within(row).getByText("North camp")).toBeInTheDocument();
  expect(row).toHaveTextContent("Latest layout: 2 beds, every check passed");
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "South camp" } });
  fireEvent.click(screen.getByLabelText("Complex example"));
  fireEvent.click(screen.getByRole("button", { name: /Create and draw/ }));
  await waitFor(() => expect(write).toHaveBeenCalled());
  expect(JSON.parse(write.mock.calls[0][1].body)).toEqual({ domain_id: 7, name: "South camp", start: "complex" });
});

it("shows the drawing's shapes and checks, and a door's numbers to type", async () => {
  stub();
  renderAt("/domains/7/map-data/camps/11");
  await screen.findByRole("heading", { name: "North camp" });
  fireEvent.click(screen.getByRole("button", { name: "Drawing" }));
  expect(screen.getByRole("toolbar", { name: "Drawing tools" })).toBeInTheDocument();
  const checks = await screen.findByRole("region", { name: "Checks" });
  expect(checks).toHaveTextContent("obstacle tank is outside the camp");
  fireEvent.click(screen.getByRole("button", { name: /^D1/ }));
  const selected = screen.getByRole("region", { name: "Selected shape" });
  expect(within(selected).getByText("Door D1")).toBeInTheDocument();
  expect((within(selected).getByLabelText("Capacity (most beds)") as HTMLInputElement).value).toBe("40");
  expect(within(selected).getByText(/2.00 m wide, on the horizontal wall at y 0 m/)).toBeInTheDocument();
  // A typed change is unsaved until Save.
  fireEvent.change(within(selected).getByLabelText("Capacity (most beds)"), { target: { value: "55" } });
  fireEvent.blur(within(selected).getByLabelText("Capacity (most beds)"));
  expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Beds" }));
  expect(screen.getAllByTestId("bed-type")).toHaveLength(1);
});

it("draws the latest layout on the map with its counts and downloads", async () => {
  stub();
  renderAt("/domains/7/map-data/camps/11");
  await screen.findByRole("heading", { name: "North camp" });
  fireEvent.click(screen.getByRole("tab", { name: "Layout" }));
  await waitFor(() => expect(screen.getAllByTestId("layout-bed")).toHaveLength(2));
  const panel = screen.getByRole("region", { name: "This layout" });
  expect(panel).toHaveTextContent("Beds2");
  expect(panel).toHaveTextContent("all pass");
  expect(within(panel).getByRole("button", { name: /Layout — GeoJSON \(WGS84/ })).toBeInTheDocument();
  fireEvent.pointerEnter(screen.getAllByTestId("layout-bed")[0]);
  expect(await within(panel).findByText(/to door D1, 4.5 m walk/)).toBeInTheDocument();
});
