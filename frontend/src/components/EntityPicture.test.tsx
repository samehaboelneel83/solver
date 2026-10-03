import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import EntityPicture, { SEQUENTIAL, stepsOf } from "./EntityPicture";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
// The map itself is drawn by a canvas library; here, what it is given.
vi.mock("./map/GeoMap", () => ({
  default: ({ marks }: { marks: { id: string; colour: string; title: string }[] }) => (
    <ul aria-label="map marks">{marks.map((m) => <li key={m.id} data-colour={m.colour}>{m.title}</li>)}</ul>
  ),
}));

const TYPE = { id: 3, domain_id: 1, name: "district", role: "location", colour: null, icon: null, attributes: [
  { id: 1, name: "calls", data_type: "integer" }, { id: 2, name: "zone_type", data_type: "text" }, { id: 3, name: "shape", data_type: "geometry" },
] } as never;

it("counts each value of a text field, and colours the map by a number field (benchmark round 3)", async () => {
  const items = Array.from({ length: 10 }, (_, i) => ({ id: i, key: `d${i}`, label: null, entity_type_id: 3,
    attrs: { calls: i * 10, zone_type: i < 7 ? "urban" : "rural", shape: { type: "Point", coordinates: [31 + i / 100, 30] } } }));
  vi.mocked(apiFetch).mockResolvedValue({ items, total: 10 } as never);
  render(<QueryClientProvider client={new QueryClient()}><EntityPicture type={TYPE} /></QueryClientProvider>);
  const counts = await screen.findByRole("list", { name: "zone_type: records per value" });
  expect(within(counts).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["urban7", "rural3"]);
  fireEvent.change(screen.getByLabelText("Colour the map by"), { target: { value: "calls" } });
  const marks = within(screen.getByRole("list", { name: "map marks" })).getAllByRole("listitem");
  expect(marks[0]).toHaveAttribute("data-colour", SEQUENTIAL[0]);
  expect(marks[9]).toHaveAttribute("data-colour", SEQUENTIAL[4]);
  expect(marks[9]).toHaveTextContent("d9: calls 90");
  expect(screen.getByLabelText("Colours for calls")).toHaveTextContent("80 and more");
});

it("bins by count, so a few large values do not wash out the rest", () => {
  const { step } = stepsOf([1, 2, 3, 4, 5, 6, 7, 8, 9, 1000]);
  expect([1, 3, 5, 7, 9, 1000].map(step)).toEqual([0, 1, 2, 3, 4, 4]);
});
