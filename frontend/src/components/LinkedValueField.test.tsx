import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import LinkedValueField from "./LinkedValueField";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("../hooks/useCapability", () => ({ useCapabilities: () => ({ can: () => true }) }));
import { apiFetch } from "../api/client";

const DISTRICT = { id: 4, domain_id: 1, name: "district", role: "location", attributes: [{ id: 3, name: "calls_forecast", data_type: "number" }] };
const CELL = { id: 5, domain_id: 1, name: "cell", role: "location", attributes: [
  { id: 1, name: "of_district", data_type: "reference", target_type_id: 4 }, { id: 2, name: "people", data_type: "number" }] } as never;

it("copies a number of the linked record onto each record, in the open (benchmark round 5)", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) =>
    (String(path).includes("/derive") ? { made: ["of_district_calls_forecast"], records: 150, left_empty: 0 }
      : { items: [DISTRICT, CELL], total: 2 }) as never);
  render(<QueryClientProvider client={new QueryClient()}><LinkedValueField kind={CELL} /></QueryClientProvider>);
  fireEvent.change(await screen.findByLabelText("The linked record's number"), { target: { value: "calls_forecast" } });
  expect(screen.getByText(/rate\[of_district\[i\]\]/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Copy onto each" }));
  expect(await screen.findByText(/of_district_calls_forecast copied onto 150 cell records/)).toBeInTheDocument();
  const call = vi.mocked(apiFetch).mock.calls.find(([p]) => String(p).includes("/derive"))!;
  expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({ op: "from_link", field: "of_district", of: "calls_forecast" });
});
