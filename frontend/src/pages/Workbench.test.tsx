import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Workbench, { pathNodes } from "./Workbench";
import { moveField } from "../components/workbench/WorkbenchTree";
import { ToastProvider } from "../components/ToastProvider";
import { editorQueryClient } from "../test/me";
import type { WorkbenchSchema } from "../api/workbench";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

// region (root) <- depot.region
const SCHEMA: WorkbenchSchema = {
  domain_id: 7,
  kinds: [
    { id: 1, name: "region", is_abstract: false, inherited_from: null, count: 1 },
    { id: 2, name: "depot", is_abstract: false, inherited_from: null, count: 1 },
  ],
  edges: [{ group_key: "ref:10", child_kind: 2, parent_kind: 1, field: "region", required: true, relationship_type_id: 50, child_end: "from_entity_id" }],
  roots: [1],
};
const attr = (id: number, kind: number, name: string, data_type: string, extra = {}) => ({
  id, entity_type_id: kind, name, data_type, required: false, unit: null, enum_values: null, default_value: null, ...extra,
});
const TYPES: Record<number, object> = {
  1: { id: 1, domain_id: 7, name: "region", role: "location", attributes: [] },
  2: { id: 2, domain_id: 7, name: "depot", role: "location",
    attributes: [attr(11, 2, "region", "reference", { required: true, target_type_id: 1 }), attr(12, 2, "bays", "integer")] },
};
const rec = (id: number, kind: number, key: string, label: string, attrs: object, children = 0) => ({
  id, entity_type_id: kind, key, label, sort_order: 0, active: true, attrs, updated_at: "t", children,
});
const EGYPT = rec(20, 1, "egypt", "Egypt", {}, 1);
const D1 = rec(21, 2, "D1", "Depot 1", { region: "egypt", bays: 12 });

function serve(path: string) {
  const url = new URL(path, "http://x");
  const p = url.pathname;
  const q = url.searchParams;
  if (p.endsWith("/workbench/schema")) return SCHEMA;
  if (p.endsWith("/workbench/problems"))
    return { records: { "21": ["inactive_target"] }, items: [{ id: 21, key: "D1", label: "Depot 1", entity_type_id: 2, kind: "depot", codes: ["inactive_target"] }] };
  if (p.endsWith("/workbench/children")) {
    if (q.get("group") === "root:1") return { items: [EGYPT], total: 1 };
    if (q.get("group") === "ref:10" && q.get("parent") === "20") return { items: [D1], total: 1 };
    return { items: [], total: 0 };
  }
  if (p.endsWith("/workbench/groups"))
    return q.get("parent") === "20"
      ? { parent: 20, groups: [{ group: "ref:10", kind_id: 2, kind: "depot", field: "region", via: "reference", required: true, count: 1 }] }
      : { parent: Number(q.get("parent")), groups: [] };
  if (p.endsWith("/workbench/place"))
    return q.get("entity") === "21"
      ? { entity: 21, kind_id: 2, group: "ref:10", parent: { id: 20, key: "egypt", label: "Egypt", entity_type_id: 1 },
          path: [{ id: 20, key: "egypt", label: "Egypt", entity_type_id: 1, child_group: "ref:10" }] }
      : { entity: Number(q.get("entity")), kind_id: 1, group: "root:1", parent: null, path: [] };
  if (p.endsWith("/workbench/search")) return { items: [] };
  const type = p.match(/^\/api\/v1\/entity-types\/(\d+)$/);
  if (type) return TYPES[Number(type[1])];
  if (p === "/api/v1/entities/20") return EGYPT;
  if (p === "/api/v1/entities/21") return D1;
  if (p.endsWith("/trees")) return { trees: [] };
  if (p.endsWith("/referrers")) return { fields: [], blocks_delete: false };
  if (p.endsWith("/values")) return { parameters: [] };
  return { items: [], total: 0 };
}

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.search}</output>;
}

function renderAt(search = "") {
  render(
    <QueryClientProvider client={editorQueryClient()}>
      <ToastProvider>
        <MemoryRouter initialEntries={[`/domains/7/data/workbench${search}`]}>
          <Routes>
            <Route path="/domains/:domainId/data/workbench" element={<><Workbench /><Where /></>} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockImplementation((path: string) => Promise.resolve(serve(String(path))));
});

describe("Data workbench", () => {
  it("opens on the first root kind, with its records in the tree and as cards", async () => {
    renderAt();
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("?kind=1"));
    const tree = screen.getByRole("navigation", { name: "Records tree" });
    expect(await within(tree).findByRole("button", { name: /Egypt/ })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "region at the top" })).toBeInTheDocument();
  });

  it("shows what sits under a record, and a new one starts placed under it", async () => {
    renderAt("?record=20");
    expect(await screen.findByRole("heading", { name: "depot under Egypt" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Depot 1.*D1.*bays: 12/s })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "+ New depot" }));
    expect(await screen.findByLabelText("new row 2: key")).toHaveValue("");
    expect(screen.getByText(/new rows get region = egypt/)).toBeInTheDocument();
    expect(screen.getByLabelText("Selected record")).toHaveTextContent("Egypt");
  });

  it("shows a record nothing can sit under among the records beside it, its branch open in the tree", async () => {
    renderAt("?record=21");
    expect(await screen.findByRole("button", { name: "Collapse egypt" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "depot under Egypt" })).toBeInTheDocument();
    expect(screen.getByText(/Nothing sits under a depot/)).toBeInTheDocument();
  });

  it("marks a record with a problem in the tree, and lists only those on request", async () => {
    renderAt("?record=20");
    fireEvent.click(await screen.findByRole("button", { name: "Expand egypt" }));
    expect(await screen.findByRole("img", { name: /refers to a switched-off record/ })).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Only records with problems \(1\)/));
    const list = screen.getByRole("list", { name: "Records with problems" });
    fireEvent.click(within(list).getByRole("button", { name: /Depot 1/ }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("?record=21"));
  });

  it("opens the record's own value in the Values tab", async () => {
    mockFetch.mockImplementation((path: string) =>
      Promise.resolve(String(path).endsWith("/entities/20/values")
        ? { parameters: [{ parameter_id: 9, name: "population", unit: null, index_kinds: ["region"], default_value: 0,
            entity_valued: false, single: true, cells: [{ entity_ids: [20], keys: ["egypt"], value: 105, value_key: null, updated_at: "t" }] }] }
        : serve(String(path)))
    );
    renderAt("?record=20");
    fireEvent.click(await screen.findByRole("tab", { name: "Values" }));
    expect(await screen.findByLabelText("population")).toHaveValue("105");
  });
});

describe("workbench helpers", () => {
  it("knows by which field a record can be moved under another", () => {
    expect(moveField(SCHEMA, 2, 1)).toBe("region");
    expect(moveField(SCHEMA, 1, 2)).toBeNull();
  });

  it("opens the branches above a record found by search", () => {
    const hit = { entity_type_id: 2, path: [{ id: 20, key: "egypt", label: null, entity_type_id: 1, child_group: "ref:10" }] };
    expect(pathNodes(hit, [1])).toEqual(["g:root:1", "r:20", "g:ref:10:20"]);
  });
});
