import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WorkbookPanel from "./WorkbookPanel";
import { editorQueryClient } from "../test/me";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn(), apiDownload: vi.fn() };
});

import { ApiError, apiDownload, apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const sheet = (name: string, faults: object[] = [], second_pass: string[] = []) => ({
  sheet: name, kind: name, rows: 3, written: 0, second_pass, faults,
});

function renderPanel() {
  render(
    <QueryClientProvider client={editorQueryClient()}>
      <WorkbookPanel domainId={7} />
    </QueryClientProvider>
  );
  const file = new File(["x"], "records.xlsx");
  fireEvent.change(screen.getByLabelText("Workbook to upload"), { target: { files: [file] } });
}

beforeEach(() => mockFetch.mockReset());

describe("WorkbookPanel", () => {
  it("checks first, lists each sheet in the order it is read, and only then allows the import", async () => {
    renderPanel();
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
    mockFetch.mockResolvedValueOnce({ ok: true, dry_run: true, kept: false, order: ["region", "depot"],
      sheets: [sheet("region", [], ["parent"]), sheet("depot")], ignored: ["notes"] });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Clean — nothing was written yet");
    expect(mockFetch).toHaveBeenLastCalledWith("/api/v1/domains/7/workbook?dry_run=true", expect.objectContaining({ method: "POST" }));
    const rows = within(screen.getByTestId("workbook-report")).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual(["1region3noneparent", "2depot3none—"]);
    expect(screen.getByText("Not a kind of record, relationship or parameter here, so not read: notes.")).toBeInTheDocument();

    mockFetch.mockResolvedValueOnce({ ok: true, dry_run: false, kept: true, order: ["region", "depot"],
      sheets: [{ ...sheet("region"), written: 3 }, { ...sheet("depot"), written: 2 }], ignored: [] });
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Imported: 5 records across 2 sheets."));
  });

  it("names each problem by sheet, row and column and keeps the import closed", async () => {
    renderPanel();
    mockFetch.mockResolvedValueOnce({ ok: false, dry_run: true, kept: false, order: ["depot"],
      sheets: [sheet("depot", [{ row: 2, column: "bays", message: "must be a whole number" }])], ignored: [] });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText("row 2, bays: must be a whole number")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 problem — nothing was written.");
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
  });

  it("says why there is no template before any kind of record exists", async () => {
    vi.mocked(apiDownload).mockRejectedValueOnce(new ApiError(404, JSON.stringify({ detail: "this domain has no kinds of record to fill" })));
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Empty template" }));
    expect(await screen.findByText(/no kinds of record in this workspace yet/)).toBeInTheDocument();
  });
});
