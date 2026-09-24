import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunMapFeature } from "../../api/v1";
import SpatialMap, { RunMapView, SVG_LIMIT } from "./SpatialMap";
import type { ComponentRecord } from "../runtime/store";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../../api/client";

function square(x: number, y: number, key: string, group: string, population = 0): RunMapFeature {
  const s = 0.01;
  return {
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[x, y], [x + s, y], [x + s, y + s], [x, y + s], [x, y]]] },
    properties: { key, group, subgroup: null, population },
  };
}

const CELLS = [
  square(31.2, 30.0, "a", "east", 10),
  square(31.21, 30.0, "b", "east", 5),
  square(31.2, 30.01, "c", "west", 7),
  square(31.21, 30.01, "d", "west", 0),
];
const ZONES = [
  { ...square(31.2, 30.0, "", "east"), properties: { group: "east", subgroup: null, cells: 2, population: 15 } },
  { ...square(31.2, 30.01, "", "west"), properties: { group: "west", subgroup: null, cells: 2, population: 7 } },
];

let TILES_INDEX = "";

function serve(cells: RunMapFeature[] = CELLS) {
  (apiFetch as any).mockImplementation((path: string) =>
    path.startsWith("/api/v1/settings")
      ? Promise.resolve({ items: [{ key: "spatial.tiles_index", value: TILES_INDEX, source: "platform", value_type: "string", description: "" }], total: 1 })
      : Promise.resolve({ type: "FeatureCollection", features: path.includes("dissolve=true") ? ZONES : cells })
  );
}

function wrap(node: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>);
}

const RECORD = {
  id: "run-5-map", type: "spatial-map", state: "hydrated", props: { title: "The partition", runId: 5 },
  data: { source: "run", runId: 5 }, actions: [], history: [], completed: true, error: null,
} as ComponentRecord;

describe("SpatialMap", () => {
  beforeEach(() => {
    (apiFetch as any).mockReset();
    serve();
  });

  it("draws every cell coloured by its group, with the totals of each group beside", async () => {
    wrap(<SpatialMap record={RECORD} variant="expanded" />);
    const map = await screen.findByRole("img", { name: "4 cells in 2 groups" });
    const paths = map.querySelectorAll("path");
    expect(paths).toHaveLength(4);
    expect(new Set([...paths].map((p) => p.getAttribute("fill"))).size).toBe(2);
    expect(paths[0].querySelector("title")?.textContent).toBe("a: east");
    await waitFor(() =>
      expect(screen.getAllByRole("row").map((r) => r.textContent)).toEqual(["GroupCellspopulation", "east215", "west27"])
    );
    expect(apiFetch).toHaveBeenCalledWith("/api/v1/runs/5/map");
  });

  it("shades a zone's sub-zones apart, within the zone's colour", async () => {
    const nested = CELLS.map((cell, i) => ({ ...cell, properties: { ...cell.properties, subgroup: `${cell.properties.group}${i % 2 ? "b" : "a"}` } }));
    serve(nested);
    wrap(<SpatialMap record={RECORD} variant="expanded" />);
    const paths = [...(await screen.findByRole("img", { name: "4 cells in 2 groups" })).querySelectorAll("path")];
    const east = paths.slice(0, 2).map((p) => [p.getAttribute("fill"), p.getAttribute("fill-opacity")]);
    expect(east[0][0]).toBe(east[1][0]);
    expect(east[0][1]).not.toBe(east[1][1]);
    expect(paths[1].querySelector("title")?.textContent).toBe("b: east / eastb");
  });

  it("keeps the drawing inside its frame and the right way up", async () => {
    wrap(<SpatialMap record={RECORD} variant="expanded" />);
    const map = await screen.findByRole("img", { name: "4 cells in 2 groups" });
    const numbers = [...map.querySelectorAll("path")].flatMap((p) =>
      (p.getAttribute("d") ?? "").match(/-?\d+(\.\d+)?/g)!.map(Number)
    );
    expect(Math.min(...numbers)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...numbers)).toBeLessThanOrEqual(640);
    // North is up: the southern cell "a" is lower on screen than "c", north of it.
    const [a, , c] = [...map.querySelectorAll("path")].map((p) => Number(p.getAttribute("d")!.split(",")[1].split(" ")[0]));
    expect(a).toBeGreaterThan(c);
  });

  it("exports the zones as a GeoJSON file", async () => {
    const created = vi.fn(() => "blob:zones");
    const revoked = vi.fn();
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    wrap(<SpatialMap record={RECORD} variant="expanded" />);
    fireEvent.click(await screen.findByRole("button", { name: "Export the zones (GeoJSON)" }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    const blob = (created.mock.calls[0] as unknown as [Blob])[0];
    expect(blob.type).toBe("application/geo+json");
    const body = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob);
    });
    expect(JSON.parse(body).features).toHaveLength(2);
    expect(revoked).toHaveBeenCalledWith("blob:zones");
    click.mockRestore();
  });

  it("draws on a canvas when there are too many cells for SVG", async () => {
    const many = Array.from({ length: SVG_LIMIT + 1 }, (_, i) => square(31 + (i % 100) * 0.01, 30 + Math.floor(i / 100) * 0.01, `k${i}`, i % 2 ? "a" : "b"));
    serve(many);
    const { container } = wrap(<SpatialMap record={RECORD} variant="expanded" />);
    expect(await screen.findByRole("img", { name: `${SVG_LIMIT + 1} cells in 2 groups` })).toBeInstanceOf(HTMLCanvasElement);
    expect(container.querySelector("svg path")).toBeNull();
  });

  it("shows nothing on a run page when the run has no map, and says so in the stream", async () => {
    (apiFetch as any).mockRejectedValue(new ApiError(404, '{"detail": "this run has no connected rule over units with a geometry"}'));
    const { container } = wrap(<RunMapView runId={9} quietIfNone />);
    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    wrap(<SpatialMap record={RECORD} variant="expanded" />);
    expect(await screen.findByText("This run has no map to draw.")).toBeInTheDocument();
  });
});

describe("SpatialMap over a basemap", () => {
  const INDEX = [
    { tiles: ["http://tiles.test/data/egypt_topo/{z}/{x}/{y}.jpg"], name: "Egypt Topo", id: "egypt_topo", minzoom: 1, maxzoom: 12, attribution: "Copernicus DEM GLO-30 (ESA)" },
    { tiles: ["http://tiles.test/data/egypt_satellite/{z}/{x}/{y}.jpg"], name: "Egypt Satellite Imagery", id: "egypt_satellite", minzoom: 1, maxzoom: 11,
      attribution: "Tiles Â© Esri â€” Source: Esri" },
    { tiles: ["http://tiles.test/data/egypt_terrain/{z}/{x}/{y}.png"], name: "Egypt Terrain RGB", id: "egypt_terrain", encoding: "mapbox" },
  ];

  beforeEach(() => {
    (apiFetch as any).mockReset();
    localStorage.clear();
    TILES_INDEX = "http://tiles.test/index.json";
    serve();
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify(INDEX)))));
  });
  afterEach(() => {
    TILES_INDEX = "";
    vi.unstubAllGlobals();
  });

  it("draws the first picture tileset under the cells, with its credit, and leaves the terrain data out", async () => {
    wrap(<SpatialMap record={RECORD} variant="expanded" />);
    const background = await screen.findByLabelText("Background");
    expect([...(background as HTMLSelectElement).options].map((o) => o.value)).toEqual(["none", "egypt_topo", "egypt_satellite"]);
    const images = (await screen.findByTestId("basemap")).querySelectorAll("image");
    expect(images.length).toBeGreaterThan(0);
    expect(images[0].getAttribute("href")).toMatch(/^http:\/\/tiles\.test\/data\/egypt_topo\/\d+\/\d+\/\d+\.jpg$/);
    fireEvent.change(background, { target: { value: "egypt_satellite" } });
    expect(await screen.findByText("Tiles © Esri — Source: Esri")).toBeInTheDocument();
    expect(localStorage.getItem("solver_map_basemap")).toBe("egypt_satellite");
  });

  it("lets the viewer turn the background off", async () => {
    wrap(<SpatialMap record={RECORD} variant="expanded" />);
    fireEvent.change(await screen.findByLabelText("Background"), { target: { value: "none" } });
    await waitFor(() => expect(screen.queryByTestId("basemap")).toBeNull());
    expect(screen.getByRole("img", { name: "4 cells in 2 groups" })).toBeInTheDocument();
  });

  it("fetches nothing for an address that is not http(s), and draws the plain map", async () => {
    TILES_INDEX = "file:///etc/passwd";
    serve();
    wrap(<SpatialMap record={RECORD} variant="expanded" />);
    await screen.findByRole("img", { name: "4 cells in 2 groups" });
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Background")).toBeNull();
  });

  it("draws the plain map when the index cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    wrap(<SpatialMap record={RECORD} variant="expanded" />);
    await screen.findByRole("img", { name: "4 cells in 2 groups" });
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.queryByTestId("basemap")).toBeNull();
  });
});
