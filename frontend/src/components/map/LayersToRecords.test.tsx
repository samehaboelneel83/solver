import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import LayersToRecords from "./LayersToRecords";
import type { GisDataset } from "../../api/gis";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
import { apiFetch } from "../../api/client";

const DATASET = { id: 7, domain_id: 11, name: "hospitals", layers: [{ id: 1, name: "points", feature_count: 4 }] } as unknown as GisDataset;
const PLAN = { layers: ["points"], name: "point", exists: true, features: 4, skipped_text: 0, shapes: ["point"], key: "name",
  key_candidates: ["name"], fields: [], geometry_field: "shape", measures: [], properties: [] };

it("will not quietly add features to a kind that already exists", async () => {
  vi.mocked(apiFetch).mockImplementation(((path: string) => Promise.resolve(
    path.includes("/records/propose") ? PLAN
      : { items: [{ id: 3, name: "point", attributes: [{ name: "seats" }, { name: "cost_egp_day" }] }], total: 1 },
  )) as never);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><LayersToRecords dataset={DATASET} canEdit /></MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Show what it would make" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("A kind named point already exists (fields: seats, cost_egp_day)");
  const make = screen.getByRole("button", { name: "Make 4 records" });
  expect(make).toBeDisabled();
  // Renamed: a kind of their own, no warning.
  fireEvent.change(screen.getByLabelText("Kind of record"), { target: { value: "hospital" } });
  expect(screen.queryByRole("alert")).toBeNull();
  expect(make).toBeEnabled();
  // Or added on purpose.
  fireEvent.change(screen.getByLabelText("Kind of record"), { target: { value: "point" } });
  fireEvent.click(screen.getByLabelText("Yes, add them to point"));
  expect(make).toBeEnabled();
});
