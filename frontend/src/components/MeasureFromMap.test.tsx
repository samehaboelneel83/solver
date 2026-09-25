import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      <ToastProvider>
        <MeasureFromMap domainId={7} entityTypes={types} />
      </ToastProvider>
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
    expect(JSON.parse(init.body as string)).toEqual({ name: "distance", from_type_id: 1, to_type_id: 2, unit: "m", nearest: 5 });
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
    expect(JSON.parse(init.body as string)).toEqual({ name: "within_reach", from_type_id: 1, to_type_id: 2, max_m: 2500 });
  });
});
