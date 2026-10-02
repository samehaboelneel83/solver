import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import LinkedTotalField from "./LinkedTotalField";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("../hooks/useCapability", () => ({ useCapabilities: () => ({ can: () => true }) }));
import { apiFetch } from "../api/client";

const DISTRICT = { id: 4, domain_id: 1, name: "district", role: "location", attributes: [] } as never;
const CALL = { id: 5, domain_id: 1, name: "call", role: "other", attributes: [
  { id: 1, name: "district", data_type: "reference", target_type_id: 4 }, { id: 2, name: "minutes", data_type: "number" }] };

it("totals the records that link to each record into a field (benchmark, October 2026)", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) =>
    (String(path).includes("/derive") ? { made: ["call_minutes_sum"], records: 3, left_empty: 0 }
      : { items: [DISTRICT, CALL], total: 2 }) as never);
  render(<QueryClientProvider client={new QueryClient()}><LinkedTotalField kind={DISTRICT} /></QueryClientProvider>);
  fireEvent.change(await screen.findByLabelText("How to total"), { target: { value: "sum" } });
  expect(screen.getByRole("button", { name: "Compute" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Number totalled"), { target: { value: "minutes" } });
  fireEvent.click(screen.getByRole("button", { name: "Compute" }));
  expect(await screen.findByText("call_minutes_sum computed on 3 district records.")).toBeInTheDocument();
  const call = vi.mocked(apiFetch).mock.calls.find(([p]) => String(p).includes("/derive"))!;
  expect(call[0]).toBe("/api/v1/entity-types/4/derive");
  expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual(
    { op: "linked_total", field: "call_minutes_sum", from_kind: "call", link: "district", how: "sum", of: "minutes" });
});

it("is not shown when nothing links to the kind", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ items: [DISTRICT], total: 1 } as never);
  const { container } = render(<QueryClientProvider client={new QueryClient()}><LinkedTotalField kind={DISTRICT} /></QueryClientProvider>);
  await new Promise((r) => setTimeout(r, 0));
  expect(container).toBeEmptyDOMElement();
});
