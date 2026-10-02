import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import type { EntityType, ParameterDef } from "../api/v1";
import EntityPicture, { CalendarView, placeOf } from "./EntityPicture";
import ParameterPicture from "./ParameterPicture";

const days = [{ id: 1, entity_type_id: 10, key: "mon", label: "Monday" }, { id: 2, entity_type_id: 10, key: "tue", label: null }];
const sites = [
  { id: 5, entity_type_id: 20, key: "n", label: null, attrs: { size: 10, place: { type: "Point", coordinates: [31, 30] } } },
  { id: 6, entity_type_id: 20, key: "s", label: null, attrs: { size: 30 } },
];
vi.mock("../api/v1", async () => {
  const actual = await vi.importActual<typeof import("../api/v1")>("../api/v1");
  return {
    ...actual,
    useEntitiesOfTypes: () => ({ items: days, isLoading: false, error: null, truncated: false }),
    useParameterValues: () => ({ isLoading: false, data: { index_types: [], default_value: 1, cells: [{ entity_ids: [2], value: 4 }] } }),
    useEntities: () => ({ data: { items: sites, total: 2 } }),
  };
});
const mount = (ui: ReactElement) => render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);

describe("input views (queue R17b)", () => {
  it("draws a parameter over the week as a line, the empty cell at its default", () => {
    const parameter = { id: 3, name: "demand", index_type_ids: [10], default_value: 1 } as unknown as ParameterDef;
    const types = [{ id: 10, name: "day", role: "time" }] as unknown as EntityType[];
    mount(<ParameterPicture parameter={parameter} entityTypes={types} />);
    expect(screen.getByText("2 cells")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Line", selected: true })).toBeInTheDocument();
  });

  it("spreads a type's numbers and puts its placed entities on a map", () => {
    const type = { id: 20, name: "site", attributes: [
      { name: "size", data_type: "integer", unit: null }, { name: "place", data_type: "geometry", unit: null }] } as unknown as EntityType;
    mount(<EntityPicture type={type} />);
    expect(screen.getByRole("img", { name: "size spread over 2 entities" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Map of 1 chosen of 1 places and 0 lines" })).toBeInTheDocument();
  });

  it("draws a road as a line, not as its middle point (benchmark, October 2026)", () => {
    sites[1] = { ...sites[1], attrs: { size: 30, place: { type: "LineString", coordinates: [[31, 30], [31.1, 30.1]] } } } as never;
    const type = { id: 20, name: "site", attributes: [{ name: "place", data_type: "geometry", unit: null }] } as unknown as EntityType;
    const { container } = mount(<EntityPicture type={type} />);
    expect(screen.getByText(/Where they are \(2 placed/)).toBeInTheDocument();
    expect(container.querySelector("polyline, path")).not.toBeNull();
    sites[1] = { id: 6, entity_type_id: 20, key: "s", label: null, attrs: { size: 30 } } as never;
  });

  it("places a shape at the middle of its outer ring", () => {
    expect(placeOf({ type: "Polygon", coordinates: [[[0, 0], [2, 0], [2, 4], [0, 4], [0, 0]]] })).toEqual([1, 2]);
    expect(placeOf({ type: "Point", coordinates: [3, 4] })).toEqual([3, 4]);
    expect(placeOf("nowhere")).toBeNull();
  });
});

describe("a time set on a calendar (queue R17c)", () => {
  it("marks each dated member on its month, Monday first", () => {
    render(<CalendarView days={[{ date: "2026-09-28", key: "mon", label: "Monday" }, { date: "2026-10-01", key: "thu", label: "Thursday" }]} by="on" />);
    expect(screen.getByRole("table", { name: "Calendar 2026-09" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Calendar 2026-10" })).toBeInTheDocument();
    expect(screen.getByTitle("Monday")).toHaveTextContent("28");
  });
});
