import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import LocationEditor from "./LocationEditor";
import { ToastProvider } from "../ToastProvider";
import { editorQueryClient } from "../../test/me";
import { shapeOf } from "../../lib/geoShape";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const TYPE = { id: 2, domain_id: 7, name: "depot", role: "location", attributes: [
  { id: 1, entity_type_id: 2, name: "bays", data_type: "integer", required: false, unit: null, enum_values: null, default_value: null },
  { id: 2, entity_type_id: 2, name: "site", data_type: "geometry", required: false, unit: null, enum_values: null, default_value: null },
] };
const depot = (attrs: object) => ({ id: 21, entity_type_id: 2, key: "D1", label: "Depot 1", sort_order: 0, active: true, attrs, updated_at: "t1" });

beforeAll(() => {
  // jsdom has no layout: the map measures itself with a ResizeObserver.
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
});

function renderEditor(attrs: object, context: object[] = []) {
  render(
    <QueryClientProvider client={editorQueryClient()}>
      <ToastProvider>
        <LocationEditor entity={depot(attrs) as never} type={TYPE as never} context={context as never} />
      </ToastProvider>
    </QueryClientProvider>
  );
}

const patched = () => mockFetch.mock.calls.filter(([, init]) => init?.method === "PATCH").map(([, init]) => JSON.parse(String(init.body)));

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockImplementation((path: string, init?: RequestInit) =>
    Promise.resolve(init?.method === "PATCH" ? depot({}) : path === "/api/v1/entities/21" ? depot({ bays: 4, site: { type: "Point", coordinates: [31, 30] } }) : { items: [] })
  );
});

describe("LocationEditor", () => {
  it("says where the record is and draws it on a map", () => {
    renderEditor({ site: { type: "Point", coordinates: [31, 30] } });
    expect(screen.getByText(/a point at 30\.00000, 31\.00000/)).toBeInTheDocument();
    expect(screen.getByTestId("location-map")).toBeInTheDocument();
  });

  it("puts a record at a typed latitude and longitude, keeping its other fields", async () => {
    renderEditor({ bays: 4, site: { type: "Point", coordinates: [31, 30] } });
    fireEvent.change(screen.getByLabelText("Latitude, longitude"), { target: { value: "30.0444, 31.2357" } });
    fireEvent.click(screen.getByRole("button", { name: "Put it here" }));
    fireEvent.click(screen.getByRole("button", { name: "Save the place" }));
    await waitFor(() => expect(patched()).toHaveLength(1));
    expect(patched()[0]).toEqual({ attrs: { bays: 4, site: { type: "Point", coordinates: [31.2357, 30.0444] } }, updated_at: "t1" });
  });

  it("with no place anywhere near, asks for one before showing a map", () => {
    renderEditor({});
    expect(screen.queryByTestId("location-map")).toBeNull();
    expect(screen.getByText(/Type a latitude and longitude above/)).toBeInTheDocument();
  });

  it("opens on the surroundings when the record has no place yet", () => {
    renderEditor({}, [{ type: "Polygon", coordinates: [[[31, 30], [31.1, 30], [31.1, 30.1], [31, 30]]] }]);
    expect(screen.getByTestId("location-map")).toBeInTheDocument();
    expect(screen.getByText(/no place yet/)).toHaveTextContent("site: no place yet");
  });

  it("clears the place", async () => {
    renderEditor({ bays: 4, site: { type: "Point", coordinates: [31, 30] } });
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(patched()).toEqual([{ attrs: { bays: 4 }, updated_at: "t1" }]));
  });
});

describe("shapeOf", () => {
  it("closes an area and refuses one of two corners", () => {
    expect(shapeOf("area", [[1, 1], [2, 1], [2, 2]])).toEqual({ geometry: { type: "Polygon", coordinates: [[[1, 1], [2, 1], [2, 2], [1, 1]]] } });
    expect(shapeOf("area", [[1, 1], [2, 1]])).toEqual({ problem: "An area needs three corners or more." });
    expect(shapeOf("line", [[1, 1], [2, 2]])).toEqual({ geometry: { type: "LineString", coordinates: [[1, 1], [2, 2]] } });
  });
});
