import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
import { apiFetch } from "../api/client";
import { RecordTotals } from "./RecordTotals";

const WARD = { id: 9, name: "ward", attributes: [{ name: "site", data_type: "text" }, { name: "beds", data_type: "integer" }] } as never;

describe("totals over a kind of record", () => {
  it("counts and adds up by a field, with a total row", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ truncated: false, total: { rows: 3, beds: 32 }, groups: [
      { group: "North", rows: 2, sums: { beds: 24 } }, { group: "South", rows: 1, sums: { beds: 8 } }] });
    render(<QueryClientProvider client={new QueryClient()}><RecordTotals type={WARD} /></QueryClientProvider>);
    const summary = screen.getByText("Totals of ward");
    (summary.parentElement as HTMLDetailsElement).open = true;
    fireEvent(summary.parentElement!, new Event("toggle"));
    fireEvent.change(screen.getByLabelText("Grouped by"), { target: { value: "site" } });
    fireEvent.click(screen.getByLabelText("beds"));
    const table = await screen.findByRole("table", { name: "Totals of ward" });
    expect(table).toHaveTextContent("North224South18Total332");
    expect(vi.mocked(apiFetch).mock.calls.at(-1)![0]).toBe("/api/v1/entity-types/9/totals?by=site&sum=beds");
  });
});
