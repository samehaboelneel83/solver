import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => ({
  ...await vi.importActual<typeof import("../api/client")>("../api/client"), apiFetch: vi.fn(),
}));
const access = vi.hoisted(() => ({ capabilities: ["integration.run", "integration.manage"] }));
vi.mock("../hooks/useCapability", () => ({ useCapabilities: () => ({ known: true, can: (c: string) => access.capabilities.includes(c) }) }));
import { apiFetch } from "../api/client";
import { ImportWizard, SourcesPage, guessMapping } from "./Sources";

function mount(path: string) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><Routes>
      <Route path="/domains/:domainId/data/sources" element={<SourcesPage />} />
      <Route path="/domains/:domainId/data/sources/:connectionId/jobs/:jobId/import" element={<ImportWizard />} />
    </Routes></MemoryRouter>
  </QueryClientProvider>);
}

const calls = () => vi.mocked(apiFetch).mock.calls.map(([path, init]) => `${(init as RequestInit | undefined)?.method ?? "GET"} ${String(path)}`);

describe("sources and extractions (Epic UX, U-4)", () => {
  beforeEach(() => {
    access.capabilities = ["integration.run", "integration.manage"];
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path) => {
      const p = String(path);
      if (p.startsWith("/api/v1/connections?")) return { items: [{ id: 4, name: "HR database", enabled: true, config: { schema: "hr", table: "staff" } }], total: 1 };
      if (p.startsWith("/api/v1/connections/4/jobs?")) return { total: 2, items: [
        { id: 12, state: "extracted", cancel_requested: false, created_at: "2026-09-29T08:00:00Z", finished_at: "2026-09-29T08:01:00Z", artifact_id: "a", error_code: null,
          loads: [{ id: 3, entity_type: "nurse", rows_written: 40, artifact_sha256: "ab".repeat(32), mapping_hash: "cd".repeat(32), created_at: "" }] },
        { id: 11, state: "failed", cancel_requested: false, created_at: "2026-09-28T08:00:00Z", finished_at: null, artifact_id: null, error_code: "deadline_exceeded", loads: [] },
      ] };
      if (p === "/api/v1/connections/4/jobs") return { id: 13, state: "queued" };
      if (p === "/api/v1/connections") return { id: 5 };
      throw new Error(`unexpected ${p}`);
    });
  });

  it("shows each extraction's state, why one failed, what was loaded, and the way to import", async () => {
    mount("/domains/7/data/sources");
    fireEvent.click(await screen.findByRole("button", { name: "Extractions" }));
    const history = await screen.findByRole("list", { name: "Extractions of HR database" });
    expect(history).toHaveTextContent("Extracted: ready to import");
    expect(history).toHaveTextContent("ran past its time limit");
    expect(history).toHaveTextContent("Loaded 40 nurse records (import 3");
    expect(within(history).getByRole("link", { name: "Import…" })).toHaveAttribute("href", "/domains/7/data/sources/4/jobs/12/import");
    fireEvent.click(screen.getByRole("button", { name: "Run extraction" }));
    await waitFor(() => expect(calls()).toContain("POST /api/v1/connections/4/jobs"));
  });

  it("adds a source from the form, never echoing the password", async () => {
    mount("/domains/7/data/sources");
    fireEvent.click(await screen.findByRole("button", { name: "Add a source" }));
    const form = screen.getByRole("form", { name: "Add a source" });
    for (const [label, value] of [["Name", "Rota"], ["Host", "10.0.0.5"], ["Database", "rota"], ["User name", "reader"],
      ["Password", "s3cret"], ["Table or view", "shifts"], ["Columns to extract, separated by commas", "id, day , hours"]]) {
      fireEvent.change(within(form).getByLabelText(label), { target: { value } });
    }
    fireEvent.click(within(form).getByRole("button", { name: "Save source" }));
    await waitFor(() => expect(calls()).toContain("POST /api/v1/connections"));
    const body = JSON.parse(String((vi.mocked(apiFetch).mock.calls.find(([p]) => p === "/api/v1/connections")![1] as RequestInit).body));
    expect(body.source).toEqual({ host: "10.0.0.5", port: 5432, database: "rota", username: "reader", schema: "public", table: "shifts", columns: ["id", "day", "hours"] });
  });

  it("offers no source form to an account that may only run extractions", async () => {
    access.capabilities = ["integration.run"];
    mount("/domains/7/data/sources");
    await screen.findByText("HR database");
    expect(screen.queryByRole("button", { name: "Add a source" })).not.toBeInTheDocument();
  });
});

describe("the import wizard", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset().mockImplementation(async (path) => {
      const p = String(path);
      if (p.startsWith("/api/v1/ingestion-jobs/12/preview")) return { columns: ["id", "full_name", "hours"], rows_total: 3, source_object: "staff", sha256: "ab".repeat(32),
        rows: [{ id: "n1", full_name: "Ada", hours: "37.5" }, { id: "n2", full_name: "Ben", hours: "x" }] };
      if (p.startsWith("/api/v1/entity-types")) return { total: 2, items: [
        { id: 9, name: "nurse", is_abstract: false, attributes: [{ name: "hours", data_type: "number" }] },
        { id: 10, name: "ward", is_abstract: false, attributes: [] },
      ] };
      if (p.startsWith("/api/v1/relationship-types")) return { total: 1, items: [
        { id: 21, name: "works_on", from_type_id: 9, to_type_id: 10, attributes: [{ name: "hours", data_type: "number" }] },
      ] };
      if (p.startsWith("/api/v1/parameters")) return { total: 1, items: [
        { id: 31, name: "distance", index_type_ids: [10, 10], default_value: 0, unit: "km" },
      ] };
      if (p.endsWith("/validate")) return { validation_id: 5, ok: false, rows: 3, would_write: 2, entity_type: "nurse", artifact_sha256: "ab".repeat(32), mapping_hash: "cd".repeat(32),
        faults: [{ row: 2, column: "hours → hours", message: "must be a number, not 'x'" }] };
      throw new Error(`unexpected ${p}`);
    });
  });

  it("previews, guesses a mapping, checks every row and names the faulty ones", async () => {
    mount("/domains/7/data/sources/4/jobs/12/import");
    expect(await screen.findByRole("table", { name: "Extracted rows" })).toHaveTextContent("Ada");
    fireEvent.change(await screen.findByLabelText("The rows become records of"), { target: { value: "9" } });
    // `id` onto `key` and `hours` onto the attribute of that name; `full_name` left for the planner.
    expect(screen.getByLabelText("id becomes")).toHaveValue("key");
    expect(screen.getByLabelText("hours becomes")).toHaveValue("hours");
    fireEvent.change(screen.getByLabelText("full_name becomes"), { target: { value: "label" } });
    fireEvent.click(screen.getByRole("button", { name: "Check the rows" }));
    const problems = await screen.findByRole("table", { name: "Problems found" });
    expect(problems).toHaveTextContent("2hours → hoursmust be a number, not 'x'");
    const body = JSON.parse(String((vi.mocked(apiFetch).mock.calls.find(([p]) => String(p).endsWith("/validate"))![1] as RequestInit).body));
    expect(body).toEqual({ entity_type_id: 9, columns: { id: "key", full_name: "label", hours: "hours" } });
    expect(screen.getByRole("button", { name: "Load" })).toBeDisabled();
  });

  it("maps rows onto links between records, asking for both ends", async () => {
    mount("/domains/7/data/sources/4/jobs/12/import");
    await screen.findByRole("table", { name: "Extracted rows" });
    fireEvent.change(screen.getByLabelText("What the rows become"), { target: { value: "relationship_type" } });
    fireEvent.change(await screen.findByLabelText("The rows become links of"), { target: { value: "21" } });
    expect(screen.getByLabelText("hours becomes")).toHaveValue("hours");
    expect(screen.getByText(/they are the keys of the two records each row links/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check the rows" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("id becomes"), { target: { value: "from" } });
    fireEvent.change(screen.getByLabelText("full_name becomes"), { target: { value: "to" } });
    fireEvent.click(screen.getByRole("button", { name: "Check the rows" }));
    await screen.findByRole("table", { name: "Problems found" });
    const body = JSON.parse(String((vi.mocked(apiFetch).mock.calls.find(([p]) => String(p).endsWith("/validate"))![1] as RequestInit).body));
    expect(body).toEqual({ relationship_type_id: 21, columns: { id: "from", full_name: "to", hours: "hours" } });
  });

  it("names a parameter's index columns as its template does", async () => {
    mount("/domains/7/data/sources/4/jobs/12/import");
    await screen.findByRole("table", { name: "Extracted rows" });
    fireEvent.change(screen.getByLabelText("What the rows become"), { target: { value: "parameter" } });
    fireEvent.change(await screen.findByLabelText("The rows become values of"), { target: { value: "31" } });
    const options = Array.from((screen.getByLabelText("id becomes") as HTMLSelectElement).options).map((o) => o.value);
    expect(options).toEqual(["", "ward_1", "ward_2", "value"]);
  });
});

describe("guessing a mapping", () => {
  it("maps same-named columns and an id column onto the key, each target once", () => {
    expect(guessMapping(["ID", "label", "hours", "Hours"], ["key", "label", "hours"])).toEqual({ ID: "key", label: "label", hours: "hours" });
  });
});
