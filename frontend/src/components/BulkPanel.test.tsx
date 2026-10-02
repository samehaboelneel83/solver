import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BulkPanel from "./BulkPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("../hooks/useCapability", () => ({ useCapabilities: () => ({ can: () => true }) }));
import { apiFetch } from "../api/client";

describe("BulkPanel (queue R21)", () => {
  it("sends the chosen file with its options and lists each fault by row and column", async () => {
    vi.mocked(apiFetch).mockReset();
    vi.mocked(apiFetch).mockResolvedValue({
      ok: false, rows: 3, written: 0, skipped: 3, dry_run: false,
      faults: [{ row: 3, column: "capacity", message: "must be a whole number, not 'ten'" }],
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <BulkPanel base="/api/v1/relationship-types/3" what="open_on links" />
      </QueryClientProvider>
    );
    const file = new File(["key,capacity\nnorth,ten\n"], "sites.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("File to upload"), { target: { files: [file] } });
    fireEvent.click(screen.getByLabelText(/Write the clean rows/));
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(screen.getByText("must be a whole number, not 'ten'")).toBeInTheDocument());
    const [path, init] = vi.mocked(apiFetch).mock.calls[0];
    expect(path).toBe("/api/v1/relationship-types/3/upload?clean_only=true&dry_run=false");
    expect((init?.body as FormData).get("file")).toBe(file);
    expect(screen.getByText(/Nothing was written: 1 fault/)).toBeInTheDocument();
  });

  it("reads a records file's columns first, and sends how each is read", async () => {
    vi.mocked(apiFetch).mockReset();
    vi.mocked(apiFetch).mockImplementation((path: string) =>
      Promise.resolve(
        path.endsWith("/upload/preview")
          ? {
              rows: 2,
              columns: [
                { name: "team", sample: ["T1", "T2"], unique: true, suggestion: "key" },
                { name: "hospital", sample: ["H1", "Haram Hospital"], unique: true, suggestion: "base_hospital" },
                { name: "Doctors on duty", sample: ["2", "1"], unique: false, suggestion: null },
                { name: "notes", sample: ["x"], unique: false, suggestion: null },
              ],
              targets: [
                { name: "key", kind: "text", required: true },
                { name: "label", kind: "text", required: false },
                { name: "base_hospital", kind: "reference", required: false, links_to: "hospital" },
              ],
            }
          : { ok: true, rows: 2, written: 2, skipped: 0, dry_run: false, faults: [],
              notes: ["base_hospital: 2 value(s) matched their record by its label or a code"] },
      ) as never,
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <BulkPanel base="/api/v1/entity-types/30" what="medical_team records" />
      </QueryClientProvider>
    );
    const file = new File(["team,hospital\n"], "teams.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("File to upload"), { target: { files: [file] } });
    const hospital = await screen.findByRole("combobox", { name: "hospital is read as" });
    expect(hospital).toHaveValue("base_hospital");
    expect(within(hospital).getByRole("option", { name: /base_hospital — a link to a hospital, by key, name or code/ })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Doctors on duty is read as" })).toHaveValue("__new__");
    fireEvent.change(screen.getByRole("combobox", { name: "notes is read as" }), { target: { value: "" } });

    // Two columns as the label: refused before anything is sent.
    fireEvent.change(screen.getByRole("combobox", { name: "hospital is read as" }), { target: { value: "label" } });
    fireEvent.change(screen.getByRole("combobox", { name: "notes is read as" }), { target: { value: "label" } });
    expect(screen.getByText(/Two columns are read as label/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "notes is read as" }), { target: { value: "" } });
    // Two columns as the key make one key (benchmark, October 2026).
    fireEvent.change(screen.getByRole("combobox", { name: "hospital is read as" }), { target: { value: "key" } });
    expect(screen.getByText(/The key is made of .* joined by/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload" })).toBeEnabled();
    fireEvent.change(screen.getByRole("combobox", { name: "hospital is read as" }), { target: { value: "base_hospital" } });

    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByText(/matched their record by its label or a code/)).toBeInTheDocument();
    const [path, init] = vi.mocked(apiFetch).mock.calls[1];
    expect(path).toBe("/api/v1/entity-types/30/upload?clean_only=false&dry_run=false&add_fields=true");
    expect(JSON.parse((init?.body as FormData).get("mapping") as string)).toEqual({
      team: "key", hospital: "base_hospital", "Doctors on duty": "doctors_on_duty", notes: "",
    });
  });

  it("warns when the key matches none of the stored records, and says what a check would make", async () => {
    vi.mocked(apiFetch).mockReset();
    vi.mocked(apiFetch).mockImplementation((path: string) =>
      Promise.resolve(
        path.endsWith("/upload/preview")
          ? {
              rows: 3, existing: 12,
              columns: [
                { name: "name", sample: ["Tanta DC"], unique: true, suggestion: "key", matches_keys: 0 },
                { name: "wh_id", sample: ["WH01"], unique: true, suggestion: null, matches_keys: 3 },
              ],
              targets: [{ name: "key", kind: "text", required: true }, { name: "label", kind: "text", required: false }],
            }
          : { ok: true, rows: 3, written: 0, skipped: 0, dry_run: true, faults: [], created: 0, updated: 3 },
      ) as never,
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <BulkPanel base="/api/v1/entity-types/9" what="warehouse records" />
      </QueryClientProvider>
    );
    fireEvent.change(screen.getByLabelText("File to upload"), { target: { files: [new File(["x"], "w.csv")] } });
    expect(await screen.findByText(/name matches none of the 12 warehouse records already stored/)).toBeInTheDocument();
    expect(screen.getByText(/wh_id matches 3 of them/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("wh_id is read as"), { target: { value: "key" } });
    fireEvent.change(screen.getByLabelText("name is read as"), { target: { value: "label" } });
    expect(screen.queryByText(/matches none of the/)).toBeNull();
    fireEvent.click(screen.getByLabelText("Check only"));
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByText(/would make 0 new records and update 3/)).toBeInTheDocument();
  });

  it("reads a values file's columns as the index and the value (benchmark, October 2026)", async () => {
    vi.mocked(apiFetch).mockReset();
    vi.mocked(apiFetch).mockImplementation((path: string) =>
      Promise.resolve(
        path.endsWith("/upload/preview")
          ? { rows: 2,
              columns: [
                { name: "Weekday", sample: ["mon"], unique: true, suggestion: "day" },
                { name: "Where", sample: ["north"], unique: true, suggestion: null },
                { name: "score", sample: ["4"], unique: true, suggestion: "value" },
              ],
              targets: [{ name: "site", kind: "text", required: true, links_to: "site" },
                        { name: "day", kind: "text", required: true, links_to: "day" }, { name: "value", kind: "number", required: false }] }
          : { ok: true, rows: 2, written: 2, skipped: 0, dry_run: false, faults: [] },
      ) as never,
    );
    render(<QueryClientProvider client={new QueryClient()}><BulkPanel base="/api/v1/parameters/7" what="demand cells" exportRows={false} /></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText("File to upload"), { target: { files: [new File(["a\n"], "d.csv")] } });
    const where = await screen.findByRole("combobox", { name: "Where is read as" });
    expect(within(where).queryByRole("option", { name: /the key/ })).toBeNull();
    expect(screen.getByText("Choose the column read as site.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
    fireEvent.change(where, { target: { value: "site" } });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.length).toBe(2));
    const body = vi.mocked(apiFetch).mock.calls[1][1]!.body as FormData;
    expect(JSON.parse(String(body.get("mapping")))).toEqual({ Weekday: "day", Where: "site", score: "value" });
  });
});
