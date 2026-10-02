import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import CoverageRecipeForm, { unreached } from "./CoverageRecipeForm";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
import { apiFetch } from "../api/client";

const KINDS = [
  { id: 1, name: "site", attributes: [{ name: "cost", data_type: "integer" }] },
  { id: 2, name: "zone", attributes: [{ name: "population", data_type: "integer" }] },
];

it("finds the places no reach cell names", () => {
  const cells = [{ entity_ids: [20, 10], value: 1 }, { entity_ids: [21, 10], value: 0 }];
  expect(unreached(cells, [20, 21, 22], 0)).toEqual([21, 22]);
});

it("opens on an empty model, and says before solving which places no site reaches", async () => {
  vi.mocked(apiFetch).mockImplementation((async (path: string) => {
    if (path === "/api/v1/parameters/5/values") return { index_types: [], default_value: 0, cells: [{ entity_ids: [20, 10], value: 1 }] };
    return { items: [{ id: 20, key: "Z1", label: "Imbaba 1" }, { id: 21, key: "Z2", label: "Bulaq Dakrour 6" }], total: 2 };
  }) as never);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CoverageRecipeForm kinds={KINDS} data={[{ id: 5, name: "covers", index: ["zone", "site"] }]} onApply={() => {}} startOpen />
    </QueryClientProvider>,
  );
  const form = screen.getByRole("form", { name: "Coverage recipe" });
  expect(form).toBeVisible();
  fireEvent.change(screen.getByLabelText("Kind to open"), { target: { value: "site" } });
  fireEvent.change(screen.getByLabelText("Kind to cover"), { target: { value: "zone" } });
  expect(await screen.findByRole("note")).toHaveTextContent("1 zone has no site within reach in covers, so cannot be covered: Bulaq Dakrour 6");
});
