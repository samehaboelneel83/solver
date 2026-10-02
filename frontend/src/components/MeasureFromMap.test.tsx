import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EntityType } from "../api/v1";
import MeasureFromMap from "./MeasureFromMap";
import { ToastProvider } from "./ToastProvider";

const shaped = (id: number, name: string, geometry = true) =>
  ({ id, domain_id: 1, name, role: "location", colour: null, icon: null,
     attributes: geometry ? [{ id: id * 10, name: "place", data_type: "geometry" }] : [] }) as unknown as EntityType;

function renderForm(types: EntityType[]) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ToastProvider>
          <MeasureFromMap domainId={7} entityTypes={types} />
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

afterEach(() => vi.restoreAllMocks());

describe("computing distances from the map (queue R16a)", () => {
  it("offers only types with a shape, and shows nothing when none has one", () => {
    renderForm([shaped(1, "worker", false)]);
    expect(screen.queryByRole("form", { name: "Compute from the map" })).toBeNull();
  });

  it("sends a distance request for the types chosen, nearest kept", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ parameter_id: 3, pairs: 12, missing: [], source: {} }), { status: 201, headers: { "Content-Type": "application/json" } })
    );
    renderForm([shaped(1, "site"), shaped(2, "customer"), shaped(3, "worker", false)]);
    expect(screen.getAllByRole("option").map((o) => o.textContent)).not.toContain("worker");
    fireEvent.change(screen.getByLabelText(/Keep only the nearest/), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Compute" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/domains\/7\/distances$/);
    expect(JSON.parse(init.body as string)).toEqual({ name: "distance", from_type_id: 1, to_type_id: 2, metric: "straight", unit: "m", nearest: 5 });
  });

  it("links pairs within a distance given in km", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ relationship_type_id: 4, edges: 3, missing: [], source: {} }), { status: 201, headers: { "Content-Type": "application/json" } })
    );
    renderForm([shaped(1, "site"), shaped(2, "customer")]);
    fireEvent.change(screen.getByLabelText("Make"), { target: { value: "within" } });
    fireEvent.change(screen.getByLabelText(/Within \(km\)/), { target: { value: "2.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Compute" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/within$/);
    expect(JSON.parse(init.body as string)).toEqual({ name: "within_reach", from_type_id: 1, to_type_id: 2, metric: "straight", max_m: 2500 });
    // Kept on screen with where the result went: a toast alone fades.
    const status = await screen.findByText(/within_reach: 3 pairs within 2.5 km linked/, { selector: "p[role=status]" });
    // Simple (the default) has no Relationships page: the links are shown in the workbench.
    expect(status.querySelector("a")).toHaveAttribute("href", "/domains/7/data/workbench");
    expect(status).toHaveTextContent("a model walks them from either end");
  });

  it("keeps a name typed before the kind of result is chosen", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ relationship_type_id: 4, edges: 3, missing: [], source: {} }), { status: 201, headers: { "Content-Type": "application/json" } })
    );
    renderForm([shaped(1, "site"), shaped(2, "customer")]);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "site_reach" } });
    fireEvent.change(screen.getByLabelText("Make"), { target: { value: "within" } });
    expect(screen.getByLabelText("Name")).toHaveValue("site_reach");
    fireEvent.click(screen.getByRole("button", { name: "Compute" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    expect(JSON.parse((fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string).name).toBe("site_reach");
  });

  it("asks again when a reach in km looks like metres", () => {
    renderForm([shaped(1, "site"), shaped(2, "customer")]);
    fireEvent.change(screen.getByLabelText("Make"), { target: { value: "within_flag" } });
    fireEvent.change(screen.getByLabelText(/Within \(km\)/), { target: { value: "1500" } });
    expect(screen.getByText(/1,500 km — did you mean 1.5 km/)).toBeInTheDocument();
  });

  it("measures a reach in road travel time, in minutes", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ relationship_type_id: 4, edges: 3, missing: [], source: {} }), { status: 201, headers: { "Content-Type": "application/json" } })
    );
    renderForm([shaped(1, "site"), shaped(2, "customer")]);
    fireEvent.change(screen.getByLabelText("Make"), { target: { value: "within" } });
    fireEvent.change(screen.getByLabelText("Measured"), { target: { value: "time" } });
    fireEvent.change(screen.getByLabelText(/Within \(minutes\)/), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Compute" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ name: "within_reach", from_type_id: 1, to_type_id: 2, metric: "time", max_min: 12 });
  });

  it("marks pairs within reach as a 0/1 parameter a rule multiplies by (improvement plan 2.2)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ parameter_id: 9, edges: 4, missing: [], source: {} }), { status: 201, headers: { "Content-Type": "application/json" } })
    );
    renderForm([shaped(1, "yard"), shaped(2, "hotspot")]);
    fireEvent.change(screen.getByLabelText("Make"), { target: { value: "within_flag" } });
    fireEvent.change(screen.getByLabelText(/Within \(km\)/), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Compute" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/within$/);
    expect(JSON.parse(init.body as string)).toEqual({ name: "reach", from_type_id: 1, to_type_id: 2, metric: "straight", max_m: 3000, output: "parameter" });
  });

  it("counts places within a radius into a field, and links each place to its area", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ field: "near_count", records: 3, with_any: 1, links: 3, missing: [] }), { status: 201, headers: { "Content-Type": "application/json" } })
    );
    renderForm([shaped(1, "hotspot"), shaped(2, "hospital")]);
    fireEvent.change(screen.getByLabelText("Make"), { target: { value: "count" } });
    fireEvent.change(screen.getByLabelText(/Within \(metres\)/), { target: { value: "300" } });
    fireEvent.click(screen.getByRole("button", { name: "Compute" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    let [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/domains\/7\/spatial\/count$/);
    expect(JSON.parse(init.body as string)).toEqual({ name: "near_count", from_type_id: 1, to_type_id: 2, max_m: 300 });
    fireEvent.change(screen.getByLabelText("Make"), { target: { value: "inside" } });
    fireEvent.click(screen.getByRole("button", { name: "Compute" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    [url, init] = fetchSpy.mock.calls[1] as [string, RequestInit];
    expect(url).toMatch(/\/spatial\/inside$/);
    expect(JSON.parse(init.body as string)).toEqual({ name: "area_of", from_type_id: 1, to_type_id: 2 });
  });

  it("travels along my lines with closed roads, delays and areas to avoid (benchmark, October 2026)", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const body = url.includes("/gis/datasets/5") ? { id: 5, name: "roads", layers: [{ id: 1, name: "ROADS", kinds: { line: 9 } }] }
        : url.includes("/gis/datasets") ? { items: [{ id: 5, name: "roads" }], total: 1 }
        : { parameter_id: 3, pairs: 4, missing: [], source: {} };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    const zone = { ...shaped(9, "flood_zone"), role: "area" } as EntityType;
    renderForm([shaped(1, "site"), shaped(2, "customer"), zone]);
    fireEvent.change(screen.getByLabelText("Measured"), { target: { value: "network_time" } });
    await screen.findByRole("option", { name: "ROADS" });
    fireEvent.change(screen.getByLabelText("Closed when (a field, optional)"), { target: { value: "flooded" } });
    fireEvent.change(screen.getByLabelText("Delay (minutes field, optional)"), { target: { value: "delay_min" } });
    fireEvent.change(screen.getByLabelText("Never through (areas, optional)"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Compute" }));
    await waitFor(() => expect(fetchSpy.mock.calls.some(([u]) => String(u).endsWith("/distances"))).toBe(true));
    const [, init] = fetchSpy.mock.calls.find(([u]) => String(u).endsWith("/distances")) as [string, RequestInit];
    expect(JSON.parse(init.body as string).network).toEqual({ dataset_id: 5, layer: "ROADS", closed_field: "flooded", delay_field: "delay_min", avoid_type_id: 9 });
  });
});
