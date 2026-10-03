import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import LinkByField from "./LinkByField";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("../hooks/useCapability", () => ({ useCapabilities: () => ({ can: () => true }) }));
import { apiFetch } from "../api/client";

const CALL = { id: 5, domain_id: 1, name: "call", role: "other", attributes: [{ id: 1, name: "dist_code", data_type: "text" }] } as never;
const DISTRICT = { id: 4, domain_id: 1, name: "district", role: "location", attributes: [{ id: 2, name: "code", data_type: "text" }] };

it("links records to the record their code names, and says which were not (benchmark re-test, October 2026)", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) =>
    (String(path).includes("/derive") ? { made: ["district_link"], records: 298, left_empty: 2, unmatched: ["c3: GZ-99"], ambiguous: [] }
      : { items: [CALL, DISTRICT], total: 2 }) as never);
  render(<QueryClientProvider client={new QueryClient()}><LinkByField kind={CALL} /></QueryClientProvider>);
  fireEvent.change(await screen.findByLabelText("The field holding the code"), { target: { value: "dist_code" } });
  fireEvent.change(screen.getByLabelText("The kind it names"), { target: { value: "district" } });
  fireEvent.change(screen.getByLabelText("What of it the code matches"), { target: { value: "code" } });
  fireEvent.click(screen.getByRole("button", { name: "Link" }));
  expect(await screen.findByText(/298 call records linked to their district by district_link; 2 not, among them: c3: GZ-99 \(no district has it\)/)).toBeInTheDocument();
  const call = vi.mocked(apiFetch).mock.calls.find(([p]) => String(p).includes("/derive"))!;
  expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual(
    { op: "link_by", field: "district_link", of: "dist_code", to_kind: "district", match: "code" });
});
