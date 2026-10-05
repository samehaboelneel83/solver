import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import AutoRecords from "./AutoRecords";
import type { AutoMapping } from "../../api/gis";

const base = (over: Partial<AutoMapping>): AutoMapping => ({
  action: "existing", dataset_id: 5, dataset: "Site survey", layer: "WELLS_EXISTING", features: 3, skipped_text: 0, type: "well",
  confidence: 0.98, reasons: ["2 of 3 features name a well record by their “well_id”"], key: "well_id", key_candidates: ["well_id"],
  label: null, fields: [{ property: "depth", name: "depth", data_type: "integer", enum_values: null, new: false, skip: false }],
  geometry_field: "shape", updates: 2, creates: 1, create_missing: true, required_unfilled: [], faults: [], alternatives: [], ...over,
});

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

function renderIt() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><AutoRecords domainId={3} onClose={() => {}} /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AutoRecords", () => {
  it("shows each layer's kind, key and effect, maps a layer again when its kind changes, and applies", async () => {
    const calls: { url: string; body: Record<string, unknown> }[] = [];
    const wells = base({});
    const parcels = base({ layer: "Parcels", action: "new", type: "parcel", confidence: 0, reasons: [], key: "parcel_no",
      key_candidates: ["parcel_no"], updates: 0, creates: 2 });
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body ?? "{}"));
      calls.push({ url, body });
      if (url.endsWith("/records/propose")) {
        const skipped = (body.choices ?? []).some((c: { type: string | null }) => c.type === null);
        return respond({ domain_id: 3, types: ["hospital", "well"], mappings: [wells, skipped ? { ...parcels, action: "skip" } : parcels] });
      }
      return respond({ domain_id: 3, faults: [], results: [{ dataset_id: 5, layer: "WELLS_EXISTING", type: "well", entity_type_id: 11, made: 1, updated: 2 }] }, 201);
    }));
    renderIt();

    expect(await screen.findByText("WELLS_EXISTING")).toBeInTheDocument();
    expect(screen.getByLabelText("Kind of record for WELLS_EXISTING")).toHaveValue("well");
    expect(screen.getByText("sure")).toBeInTheDocument();
    expect(screen.getByText(/2 of 3 features name a well record/)).toBeInTheDocument();
    expect(screen.getByText("new kind")).toBeInTheDocument();
    expect(screen.getByText("2 records updated, 3 added", { exact: false })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Kind of record for Parcels"), { target: { value: "__skip__" } });
    await waitFor(() => expect(screen.getByText("left out")).toBeInTheDocument());
    expect(calls[1].body.choices).toEqual([{ dataset_id: 5, layer: "Parcels", type: null }]);

    fireEvent.click(screen.getByRole("button", { name: /Apply to 1 layer/ }));
    expect(await screen.findByText("Done")).toBeInTheDocument();
    const applied = calls.find((c) => c.url.endsWith("/domains/3/records"))!;
    expect((applied.body.mappings as AutoMapping[]).map((m) => m.layer)).toEqual(["WELLS_EXISTING"]);
    expect(screen.getByRole("link", { name: "well" })).toHaveAttribute("href", "/domains/3/data/records?type=11");
  });

  it("says what stopped an apply, and writes nothing", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/records/propose")
      ? respond({ domain_id: 3, types: ["well"], mappings: [base({ faults: ["feature 'W9', property 'owner': 'south' is not a whole number"] })] })
      : respond({ detail: { message: "Nothing was made: fix these first.", faults: ["WELLS_EXISTING: bad value"], more: 0 } }, 422)));
    renderIt();
    expect(await screen.findByText(/1 value would not fit/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Apply to 1 layer/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was made");
    expect(screen.getByRole("alert")).toHaveTextContent("WELLS_EXISTING: bad value");
  });
});
