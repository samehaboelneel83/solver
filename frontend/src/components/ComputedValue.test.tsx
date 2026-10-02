import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ComputedValue from "./ComputedValue";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
import { apiFetch } from "../api/client";

const KINDS = [
  { id: 1, name: "soil", attributes: [] },
  { id: 2, name: "crop", attributes: [] },
  { id: 3, name: "parcel", attributes: [{ id: 9, name: "soil", data_type: "reference", target_type_id: 1 }, { id: 10, name: "prev_crop", data_type: "text" }] },
] as never;

function mount(onMade = vi.fn()) {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(apiFetch).mockImplementation(async (path: string) =>
    (String(path).includes("derive-value") ? { parameter_id: 77, name: "made", cells: 6, index: [3, 2] }
      : String(path).includes("relationship-types") ? { items: [{ id: 4, name: "in_district", from_type_id: 3, to_type_id: 5 }], total: 1 }
      : { items: [{ id: 8, name: "suitability", index_type_ids: [1, 2] }, { id: 9, name: "cost", index_type_ids: [2] },
          { id: 10, name: "call_rate", index_type_ids: [5, 2] }], total: 3 }) as never);
  render(<QueryClientProvider client={new QueryClient()}><ComputedValue domainId={1} entityTypes={KINDS} onMade={onMade} /></QueryClientProvider>);
  return onMade;
}

const sent = () => JSON.parse(String((vi.mocked(apiFetch).mock.calls.find(([p]) => String(p).includes("derive-value"))![1] as RequestInit).body));

it("reads a data value through a link: only data indexed first by the linked kind is offered", async () => {
  const onMade = mount();
  fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "parcel" } });
  fireEvent.change(screen.getByLabelText("Link"), { target: { value: "soil" } });
  await screen.findByRole("option", { name: "suitability" });
  expect(screen.queryByRole("option", { name: "cost" })).toBeNull();
  fireEvent.change(screen.getByLabelText("Data value read"), { target: { value: "suitability" } });
  fireEvent.change(screen.getByLabelText("Name of the data value"), { target: { value: "parcel_suit" } });
  fireEvent.click(screen.getByRole("button", { name: "Compute" }));
  expect(await screen.findByText("made made with 6 values.")).toBeInTheDocument();
  expect(sent()).toEqual({ op: "lookup", name: "parcel_suit", kind: "parcel", field: "soil", source: "suitability" });
  expect(onMade).toHaveBeenCalledWith(77);
});

it("makes 1 or 0 by comparing a field with the other kind's key", async () => {
  mount();
  fireEvent.click(screen.getByLabelText("1 or 0 by a comparison"));
  fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "parcel" } });
  fireEvent.change(screen.getByLabelText("Field compared"), { target: { value: "prev_crop" } });
  fireEvent.change(screen.getByLabelText("Other kind"), { target: { value: "crop" } });
  fireEvent.change(screen.getByLabelText("Name of the data value"), { target: { value: "rotation_ok" } });
  fireEvent.click(screen.getByRole("button", { name: "Compute" }));
  await screen.findByRole("status");
  expect(sent()).toEqual({ op: "compare", name: "rotation_ok", kind: "parcel", field: "prev_crop", other: "crop", against: "key", compare: "!=" });
});

it("reads through a relationship too, not only a link field (benchmark re-test, October 2026)", async () => {
  mount();
  fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "parcel" } });
  await screen.findByRole("option", { name: "in_district" });
  fireEvent.change(screen.getByLabelText("Link"), { target: { value: "in_district" } });
  await screen.findByRole("option", { name: "call_rate" });
  expect(screen.queryByRole("option", { name: "suitability" })).toBeNull();
});
