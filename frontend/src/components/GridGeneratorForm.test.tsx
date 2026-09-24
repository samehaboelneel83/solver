import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EntityType } from "../api/v1";
import GridGeneratorForm, { parsePointsCsv } from "./GridGeneratorForm";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../api/client";

const SQUARE = { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] };
const AREA = {
  id: 7,
  domain_id: 1,
  name: "area",
  role: "location",
  colour: null,
  icon: null,
  attributes: [{ id: 70, entity_type_id: 7, name: "outline", data_type: "geometry", required: false, unit: null,
    enum_values: null, default_value: null, sort_order: 0 }],
} as unknown as EntityType;
const PLAIN = { ...AREA, id: 8, name: "depot", attributes: [] } as unknown as EntityType;
const ENTITIES = [
  { id: 71, entity_type_id: 7, key: "cairo", label: "Cairo", attrs: { outline: SQUARE } },
  { id: 72, entity_type_id: 7, key: "pin", label: "A pin", attrs: { outline: { type: "Point", coordinates: [0, 0] } } },
];
const REPORT = { entity_type_id: 9, relationship_type_id: 10, cells: 8, edges: 13, dropped: 2,
  layer_totals: { population: 40 }, layer_outside: { population: 5 } };

function renderForm(types: EntityType[] = [AREA, PLAIN]) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <GridGeneratorForm domainId={1} entityTypes={types} />
    </QueryClientProvider>
  );
}

function posts() {
  return (apiFetch as any).mock.calls.filter(([, init]: [string, RequestInit?]) => init?.method === "POST");
}

describe("parsePointsCsv", () => {
  it("reads lon, lat and named columns", () => {
    expect(parsePointsCsv("lon,lat,population\n31.2, 30.0, 1200\n\n31.3,30.1,5")).toEqual({
      rows: [{ lon: 31.2, lat: 30, population: 1200 }, { lon: 31.3, lat: 30.1, population: 5 }],
      problem: null,
    });
  });

  it("names the line and column that is not a number", () => {
    expect(parsePointsCsv("lon,lat,population\n31.2,30.0,many").problem).toBe('Line 2: "population" is not a number.');
    expect(parsePointsCsv("lon,lat,population\n31.2,30.0").problem).toBe('Line 2: "population" is not a number.');
  });

  it("wants the header", () => {
    expect(parsePointsCsv("31.2,30.0,4").problem).toMatch(/starts "lon,lat"/);
    expect(parsePointsCsv("  \n")).toEqual({ rows: [], problem: null });
  });
});

describe("GridGeneratorForm", () => {
  beforeEach(() => {
    (apiFetch as any).mockReset();
    (apiFetch as any).mockImplementation((path: string, init?: RequestInit) => {
      if (init?.method === "POST") return Promise.resolve(REPORT);
      if (path.startsWith("/api/v1/entities")) return Promise.resolve({ items: ENTITIES, total: 2 });
      return Promise.resolve({ items: [], total: 0 });
    });
  });

  it("explains what a grid needs when no type has a shape", () => {
    renderForm([PLAIN]);
    expect(screen.getByText(/give an entity type a/)).toBeInTheDocument();
    // Nothing to draw a grid over: no records are fetched (settings may be read).
    expect((apiFetch as any).mock.calls.filter(([path]: [string]) => !path.startsWith("/api/v1/settings"))).toEqual([]);
  });

  it("offers only records with an area, and sends the grid over the one chosen", async () => {
    renderForm();
    const over = await screen.findByLabelText("Over");
    await waitFor(() => expect(screen.getByRole("option", { name: "Cairo" })).toBeInTheDocument());
    expect(screen.queryByRole("option", { name: "A pin" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Cell width (metres)"), { target: { value: "750" } });
    fireEvent.change(screen.getByLabelText("Cells"), { target: { value: "square" } });
    fireEvent.change(screen.getByLabelText(/Points to add up/), { target: { value: "lon,lat,population\n0.5,0.5,40" } });
    expect(over).toHaveValue("71");
    fireEvent.click(screen.getByRole("button", { name: "Make the grid" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Made 8 cells and 13 adjacencies (2 dropped at the boundary). 5 of population fell outside the grid."
    );
    const [path, init] = posts()[0];
    expect(path).toBe("/api/v1/domains/1/grids");
    expect(JSON.parse(init.body)).toEqual({
      boundary_entity_id: 71, shape: "square", size_m: 750, entity_type: "cell", keep: "centre",
      layers: [{ lon: 0.5, lat: 0.5, population: 40 }], replace: false,
    });
  });

  it("holds the button while the width or the points are wrong", async () => {
    renderForm();
    await screen.findByRole("option", { name: "Cairo" });
    const button = screen.getByRole("button", { name: "Make the grid" });
    expect(button).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Cell width (metres)"), { target: { value: "0" } });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Cell width (metres)"), { target: { value: "500" } });
    fireEvent.change(screen.getByLabelText(/Points to add up/), { target: { value: "x,y\n1,2" } });
    expect(button).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent('starts "lon,lat"');
  });

  it("says what a grid in use would replace, and replaces it only when asked", async () => {
    const refusal = JSON.stringify({ detail: { message: "cell already has 4 cells", cells: 4, scenarios: [3, 5] } });
    (apiFetch as any).mockImplementation((path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return JSON.parse(init.body as string).replace ? Promise.resolve(REPORT) : Promise.reject(new ApiError(409, refusal));
      }
      return Promise.resolve({ items: ENTITIES, total: 2 });
    });
    renderForm();
    await screen.findByRole("option", { name: "Cairo" });
    fireEvent.click(screen.getByRole("button", { name: "Make the grid" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("cell already has 4 cells, used by scenarios 3, 5.");
    fireEvent.click(screen.getByRole("button", { name: "Replace them" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Made 8 cells");
    expect(posts().map(([, init]: [string, RequestInit]) => JSON.parse(init.body as string).replace)).toEqual([false, true]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows any other failure as the server named it", async () => {
    (apiFetch as any).mockImplementation((path: string, init?: RequestInit) =>
      init?.method === "POST"
        ? Promise.reject(new ApiError(422, JSON.stringify({ detail: "this grid would have 40000 cells; the limit is 20000" })))
        : Promise.resolve({ items: ENTITIES, total: 2 })
    );
    renderForm();
    await screen.findByRole("option", { name: "Cairo" });
    fireEvent.click(screen.getByRole("button", { name: "Make the grid" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("40000 cells");
  });
});

describe("GridGeneratorForm and elevation", () => {
  function serveWith(tilesIndex: string, report: Record<string, unknown> = REPORT) {
    (apiFetch as any).mockReset();
    (apiFetch as any).mockImplementation((path: string, init?: RequestInit) => {
      if (init?.method === "POST") return Promise.resolve(report);
      if (path.startsWith("/api/v1/settings")) {
        return Promise.resolve({ items: [{ key: "spatial.tiles_index", value: tilesIndex, source: "platform", value_type: "string", description: "" }], total: 1 });
      }
      if (path.startsWith("/api/v1/entities")) return Promise.resolve({ items: ENTITIES, total: 2 });
      return Promise.resolve({ items: [], total: 0 });
    });
  }

  it("is not offered without a tile index", async () => {
    serveWith("");
    renderForm();
    await screen.findByRole("option", { name: "Cairo" });
    expect(screen.queryByLabelText(/elevation and slope/)).toBeNull();
  });

  it("asks for it when ticked, and says what came back", async () => {
    serveWith("http://localhost:8080/index.json", { ...REPORT, layer_outside: {}, elevation_missing: 3, elevation_range: [12.5, 88] });
    renderForm();
    await screen.findByRole("option", { name: "Cairo" });
    fireEvent.click(await screen.findByLabelText(/elevation and slope/));
    fireEvent.click(screen.getByRole("button", { name: "Make the grid" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Elevation from 12.5 to 88 m. 3 cells are beyond the terrain tiles and have no elevation."
    );
    expect(JSON.parse(posts()[0][1].body).elevation).toBe(true);
  });
});
