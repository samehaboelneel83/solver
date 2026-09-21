import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import PropertyPanel from "./PropertyPanel";
import { ToastProvider } from "./ToastProvider";
import { fallbackColour } from "../lib/colour";
import { editorQueryClient } from "../test/me";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch, ApiError } from "../api/client";

// v1 shape: a type's `code` and `name` are one column, so they are equal.
// "unit (unit)" is what the v0 heading template produces here.
const graph = {
  nodes: [
    { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
    // `label` is null on this entity, so the graph read falls back to its
    // `key` -- which is why the panel must not seed its Label box from here.
    { id: "2", type: "employee", label: "ahmed", parent: "1", attributes: { code: "E-1", status: "active", grade: 3 } },
  ],
  edges: [{ id: "10", source: "1", target: "2", type: "works_for", label: "works_for", attributes: { weight: 1 } }],
  entity_types: [
    { id: "1", code: "employee", name: "employee", is_abstract: false, colour: "#1f77b4" },
    { id: "2", code: "unit", name: "unit", is_abstract: false, colour: null },
  ],
  relationship_types: [],
  hierarchies: [],
  attribute_definitions: [],
};

const ENTITY_TYPES = {
  items: [
    {
      id: 1,
      domain_id: 1,
      name: "employee",
      role: "agent",
      colour: "#1f77b4",
      attributes: [
        { id: 11, entity_type_id: 1, name: "code", data_type: "text", required: false, unit: null, enum_values: null, default_value: null },
        { id: 12, entity_type_id: 1, name: "status", data_type: "enum", required: false, unit: null, enum_values: ["active", "leave"], default_value: null },
        { id: 13, entity_type_id: 1, name: "grade", data_type: "integer", required: false, unit: null, enum_values: null, default_value: null },
        { id: 14, entity_type_id: 1, name: "on_call", data_type: "boolean", required: false, unit: null, enum_values: null, default_value: null },
      ],
    },
    { id: 2, domain_id: 1, name: "unit", role: "org", colour: null, attributes: [] },
  ],
  total: 2,
};

/** The stored entity behind node "2". `label` is null and `key` is "ahmed",
 * which is what the graph node's label shows. */
const HQ = { id: 1, entity_type_id: 2, key: "hq", label: "hq", sort_order: 0, active: true, attrs: {} };

const ENTITY = {
  id: 2,
  entity_type_id: 1,
  key: "ahmed",
  label: null,
  sort_order: 0,
  active: true,
  attrs: { code: "E-1", status: "active", grade: 3, on_call: false },
};

type Stub = { entity?: unknown; entityTypes?: unknown; write?: (path: string, options: RequestInit) => unknown };

function stubApi(stub: Stub = {}) {
  (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
    if (options?.method && options.method !== "GET") {
      return stub.write ? stub.write(path, options) : Promise.resolve({ ...ENTITY });
    }
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve(stub.entityTypes ?? ENTITY_TYPES);
    if (path === "/api/v1/entities/1") return Promise.resolve(HQ);
    if (path.startsWith("/api/v1/entities/")) return Promise.resolve(stub.entity ?? ENTITY);
    return Promise.resolve({});
  });
}

function bodyOf(call: any[]): any {
  return JSON.parse((call[1] as RequestInit).body as string);
}

function callsTo(method: string, prefix: string): any[][] {
  return (apiFetch as any).mock.calls.filter(
    (call: any[]) => typeof call[0] === "string" && call[0].startsWith(prefix) && call[1]?.method === method
  );
}

function renderWithProviders(props: Record<string, unknown> = {}) {
  const queryClient = editorQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
      <PropertyPanel
        domainId={1}
        mode="objects"
        graph={graph as any}
        selection={{ kind: "node", id: "2" }}
        onClose={vi.fn()}
        {...props}
      />
      </ToastProvider>
    </QueryClientProvider>
  );
}

describe("PropertyPanel", () => {
  beforeEach(() => {
    (apiFetch as any).mockReset();
    stubApi();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a prompt when nothing is selected", () => {
    renderWithProviders({ selection: null });
    expect(screen.getByText(/select a node or edge/i)).toBeInTheDocument();
  });

  it("heads the node with its type and label, naming the type once", async () => {
    renderWithProviders({ selection: { kind: "node", id: "1" } });
    const heading = await screen.findByRole("heading", { level: 2 });
    expect(heading).toHaveTextContent("unit: hq");
    // v0 rendered "{name} ({code})" for the type, which in v1 is "unit (unit)".
    expect(heading.textContent).not.toContain("unit (unit)");
  });

  it("shows the entity's key, and seeds Label from the stored label rather than the node's key fallback", async () => {
    renderWithProviders();
    await screen.findByTestId("node-property-form");

    // The graph node's label is "ahmed" -- the key, because `label` is null.
    // Seeding the box from it would silently write the key into `label`.
    expect((await screen.findByLabelText(/^Label/)) as HTMLInputElement).toHaveValue("");
    expect(screen.getByTestId("node-key")).toHaveTextContent("ahmed");
  });

  it("edits an attribute named code or status -- both are ordinary v1 attributes", async () => {
    renderWithProviders();
    await screen.findByTestId("node-property-form");

    expect(await screen.findByTestId("attr-code")).toHaveValue("E-1");
    expect(screen.getByTestId("attr-status")).toHaveValue("active");
    expect(screen.queryByText(/collides with a built-in field/)).not.toBeInTheDocument();
  });

  it("saves label and attrs through the v1 entities route, keeping falsy values", async () => {
    renderWithProviders();
    await screen.findByTestId("attr-code");

    fireEvent.change(screen.getByLabelText(/^Label/), { target: { value: "Ahmed Z" } });
    fireEvent.change(screen.getByTestId("attr-grade"), { target: { value: "0" } });
    fireEvent.submit(screen.getByTestId("node-property-form"));

    await waitFor(() => expect(callsTo("PATCH", "/api/v1/entities/2")).toHaveLength(1));
    expect(bodyOf(callsTo("PATCH", "/api/v1/entities/2")[0])).toEqual({
      label: "Ahmed Z",
      // 0 and false survive; `attrs` is rebuilt from the definitions, never merged.
      attrs: { code: "E-1", status: "active", grade: 0, on_call: false },
    });
  });

  it("clears the label when the box is emptied, so the node falls back to showing its key", async () => {
    stubApi({ entity: { ...ENTITY, label: "Ahmed Z" } });
    renderWithProviders();
    await waitFor(() => expect(screen.getByLabelText(/^Label/)).toHaveValue("Ahmed Z"));

    fireEvent.change(screen.getByLabelText(/^Label/), { target: { value: "   " } });
    fireEvent.submit(screen.getByTestId("node-property-form"));

    await waitFor(() => expect(callsTo("PATCH", "/api/v1/entities/2")).toHaveLength(1));
    // null, not "" or "   ": `label` is nullable and the graph shows the key
    // only when it is NULL -- an empty string would draw a blank node.
    expect(bodyOf(callsTo("PATCH", "/api/v1/entities/2")[0]).label).toBeNull();
  });

  it("drops a stored key whose attribute definition is gone, and says so before saving", async () => {
    stubApi({ entity: { ...ENTITY, attrs: { ...ENTITY.attrs, colour: "red" } } });
    renderWithProviders();

    expect(await screen.findByTestId("stale-attrs")).toHaveTextContent("colour");

    fireEvent.submit(screen.getByTestId("node-property-form"));
    await waitFor(() => expect(callsTo("PATCH", "/api/v1/entities/2")).toHaveLength(1));
    expect(bodyOf(callsTo("PATCH", "/api/v1/entities/2")[0]).attrs).not.toHaveProperty("colour");
  });

  it("refuses a decimal in an integer attribute without sending anything", async () => {
    renderWithProviders();
    await screen.findByTestId("attr-grade");

    fireEvent.change(screen.getByTestId("attr-grade"), { target: { value: "2.5" } });
    fireEvent.submit(screen.getByTestId("node-property-form"));

    expect(await screen.findByText(/grade: must be a whole number/)).toBeInTheDocument();
    expect(callsTo("PATCH", "/api/v1/entities/2")).toHaveLength(0);
  });

  it("puts a trigger's 422 on the attribute it names", async () => {
    stubApi({
      write: () =>
        Promise.reject(
          new ApiError(
            422,
            JSON.stringify({
              detail: [
                {
                  loc: ["body", "grade"],
                  msg: 'entity ahmed: attribute "grade" must be integer',
                  kind: "attribute_type",
                },
              ],
            })
          )
        ),
    });
    renderWithProviders();
    await screen.findByTestId("attr-grade");

    fireEvent.submit(screen.getByTestId("node-property-form"));

    expect(await screen.findByText('entity ahmed: attribute "grade" must be integer')).toBeInTheDocument();
  });

  it("renders a formatted message when the save is rejected with a 409", async () => {
    stubApi({ write: () => Promise.reject(new ApiError(409, JSON.stringify({ detail: "entity already exists" }))) });
    renderWithProviders();
    await screen.findByTestId("attr-grade");

    fireEvent.submit(screen.getByTestId("node-property-form"));

    expect(await screen.findByText(/already has this key|entity already exists/)).toBeInTheDocument();
  });

  it("deletes the entity only after confirming, because deleting it cascades", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWithProviders();
    await screen.findByTestId("node-property-form");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalled();
    // The same turn-of-the-loop wait as the edge case below: this
    // assertion used to run on the click's own tick, so it passed against
    // a panel that deleted regardless of the answer.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(callsTo("DELETE", "/api/v1/entities/2")).toHaveLength(0);

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(callsTo("DELETE", "/api/v1/entities/2")).toHaveLength(1));
  });

  it("heads an edge with its relationship type, named once", async () => {
    renderWithProviders({ selection: { kind: "edge", id: "10" } });
    const heading = await screen.findByRole("heading", { level: 2 });
    expect(heading).toHaveTextContent("works_for");
    expect(heading.textContent).not.toContain("works_for (works_for)");
  });

  it("edits a relationship's attrs as JSON through the v1 relationships route", async () => {
    renderWithProviders({ selection: { kind: "edge", id: "10" } });
    const form = await screen.findByTestId("edge-property-form");
    expect(within(form).getByRole("textbox")).toHaveValue(JSON.stringify({ weight: 1 }, null, 2));

    fireEvent.change(within(form).getByRole("textbox"), { target: { value: '{"weight": 5}' } });
    fireEvent.submit(form);

    await waitFor(() => expect(callsTo("PATCH", "/api/v1/relationships/10")).toHaveLength(1));
    expect(bodyOf(callsTo("PATCH", "/api/v1/relationships/10")[0])).toEqual({ attrs: { weight: 5 } });
  });

  it("refuses invalid JSON for a relationship's attrs without sending anything", async () => {
    renderWithProviders({ selection: { kind: "edge", id: "10" } });
    const form = await screen.findByTestId("edge-property-form");

    fireEvent.change(within(form).getByRole("textbox"), { target: { value: "{oops" } });
    fireEvent.submit(form);

    expect(await screen.findByText(/must be valid JSON/i)).toBeInTheDocument();
    expect(callsTo("PATCH", "/api/v1/relationships/10")).toHaveLength(0);
  });

  /*
   * This was one click, no confirmation, no undo, and no toast naming
   * what went -- in a product whose other delete confirmations count the
   * real objects that go with the record. Worse here than anywhere else,
   * because until this round an accidentally deleted relationship was
   * invisible afterwards: there was no list to miss it from.
   */
  it("deletes a relationship only after confirming, and does nothing on cancel", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWithProviders({ selection: { kind: "edge", id: "10" } });
    await screen.findByTestId("edge-property-form");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalled();
    // After a turn of the event loop, not on the same tick: the delete is
    // async, so asserting immediately passes against a panel that went
    // ahead anyway -- which is exactly what a mutant proved.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(callsTo("DELETE", "/api/v1/relationships/10")).toHaveLength(0);

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(callsTo("DELETE", "/api/v1/relationships/10")).toHaveLength(1));
  });

  it("names the relationship type AND both endpoints in the confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWithProviders({ selection: { kind: "edge", id: "10" } });
    await screen.findByTestId("edge-property-form");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    const message = confirm.mock.calls[0][0] as string;
    expect(message).toContain("works_for");
    // Both ends, in the edge's own direction -- "hq works_for ahmed", not
    // the reverse, and not the node ids.
    expect(message.indexOf("hq")).toBeLessThan(message.indexOf("ahmed"));
    // It volunteers what is NOT deleted, the way the other confirmations do.
    expect(message).toMatch(/entities at (either|both) end/i);
    expect(message).toMatch(/cannot be undone/i);
  });

  it("shows both endpoints in the panel, so the edge is identifiable before it is touched", async () => {
    renderWithProviders({ selection: { kind: "edge", id: "10" } });
    await screen.findByTestId("edge-property-form");
    const ends = screen.getByTestId("edge-ends");
    expect(ends).toHaveTextContent("hq");
    expect(ends).toHaveTextContent("ahmed");
    expect(ends.textContent!.indexOf("hq")).toBeLessThan(ends.textContent!.indexOf("ahmed"));
  });

  it("names what went in the toast after the delete", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders({ selection: { kind: "edge", id: "10" } });
    await screen.findByTestId("edge-property-form");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(callsTo("DELETE", "/api/v1/relationships/10")).toHaveLength(1));
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent("works_for");
    expect(toast).toHaveTextContent("hq");
    expect(toast).toHaveTextContent("ahmed");
  });

  it("shows a cardinality violation's own message when re-pointing is refused", async () => {
    stubApi({
      write: () =>
        Promise.reject(
          new ApiError(
            422,
            JSON.stringify({
              detail: [
                {
                  loc: ["body", "works_for"],
                  msg: 'relationship "works_for": would create a cycle',
                  kind: "cycle",
                },
              ],
            })
          )
        ),
    });
    renderWithProviders({ selection: { kind: "edge", id: "10" } });
    const form = await screen.findByTestId("edge-property-form");

    fireEvent.submit(form);

    const message = await screen.findByText('relationship "works_for": would create a cycle');
    expect(message).toBeInTheDocument();
  });

  it("renders both headings at level 2 so the page outline has no skipped level (N-3)", async () => {
    const { unmount } = renderWithProviders();
    expect(await screen.findByRole("heading", { level: 2 })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3 })).not.toBeInTheDocument();
    unmount();

    renderWithProviders({ selection: { kind: "edge", id: "10" } });
    expect(await screen.findByRole("heading", { level: 2 })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3 })).not.toBeInTheDocument();
  });
});

// --- Task 14b: the types view's panels ------------------------------------
//
// In the types view a node IS an `entity_type` and an edge IS a
// `relationship_type`, so the panel edits something else entirely. Both
// fetch the row rather than reading the canvas, for the reason the entity
// panel does: the built graph carries only what is drawn.

const EMPLOYEE_TYPE = {
  id: 1,
  domain_id: 1,
  name: "employee",
  role: "agent",
  colour: "#1f77b4",
  attributes: ENTITY_TYPES.items[0].attributes,
};

const WORKS_FOR_TYPE = {
  id: 6,
  domain_id: 1,
  name: "works_for",
  from_type_id: 1,
  to_type_id: 2,
  cardinality: "many_to_one",
  is_hierarchy: false,
  colour: null,
};

function stubTypesApi(write?: (path: string, options: RequestInit) => unknown) {
  (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
    if (options?.method && options.method !== "GET") {
      return write ? write(path, options) : Promise.resolve({});
    }
    if (path === "/api/v1/entity-types/1") return Promise.resolve(EMPLOYEE_TYPE);
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve(ENTITY_TYPES);
    if (path === "/api/v1/relationship-types/6") return Promise.resolve(WORKS_FOR_TYPE);
    return Promise.resolve({});
  });
}

function renderTypesPanel(selection: { kind: "node" | "edge"; id: string }) {
  const queryClient = editorQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PropertyPanel
          domainId={1}
          mode="types"
          graph={graph as any}
          selection={selection}
          onClose={vi.fn()}
        />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("PropertyPanel, types view", () => {
  beforeEach(() => {
    (apiFetch as any).mockReset();
    stubTypesApi();
  });

  it("shows the entity type behind a node, fetched rather than read off the canvas", async () => {
    renderTypesPanel({ kind: "node", id: "type-1" });
    const panel = await screen.findByTestId("entity-type-panel");
    expect(panel).toHaveTextContent("employee");
    // Role and attribute count come from the row, not from the graph
    // payload -- which carries neither.
    expect(screen.getByTestId("entity-type-role")).toHaveTextContent(/agent/i);
    expect(screen.getByTestId("entity-type-attribute-count")).toHaveTextContent("4");
    expect(within(panel).getByRole("link", { name: /edit this type/i })).toHaveAttribute(
      "href",
      "/entity-types/1"
    );
  });

  it("seeds the colour control from the stored colour", async () => {
    renderTypesPanel({ kind: "node", id: "type-1" });
    await screen.findByTestId("entity-type-panel");
    expect(screen.getByTestId("colour-hex")).toHaveValue("#1f77b4");
    expect(screen.getByTestId("colour-preview")).toHaveAttribute("data-fill", "#1f77b4");
  });

  it("saves an entity type's colour, lower case, as a PATCH naming only that field", async () => {
    stubTypesApi(() => Promise.resolve({ ...EMPLOYEE_TYPE, colour: "#ff8800" }));
    renderTypesPanel({ kind: "node", id: "type-1" });
    await screen.findByTestId("entity-type-panel");

    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "#FF8800" } });
    await waitFor(() => expect(callsTo("PATCH", "/api/v1/entity-types/1")).toHaveLength(1));
    // Only `colour`: the name and role belong to the type's own editor, and
    // sending them from here would overwrite a concurrent rename.
    expect(bodyOf(callsTo("PATCH", "/api/v1/entity-types/1")[0])).toEqual({ colour: "#ff8800" });
  });

  it("clears an entity type's colour back to automatic", async () => {
    stubTypesApi(() => Promise.resolve({ ...EMPLOYEE_TYPE, colour: null }));
    renderTypesPanel({ kind: "node", id: "type-1" });
    await screen.findByTestId("entity-type-panel");

    fireEvent.click(screen.getByTestId("colour-clear"));
    await waitFor(() => expect(callsTo("PATCH", "/api/v1/entity-types/1")).toHaveLength(1));
    expect(bodyOf(callsTo("PATCH", "/api/v1/entity-types/1")[0])).toEqual({ colour: null });
  });

  it("surfaces the server's refusal instead of pretending it saved", async () => {
    stubTypesApi(() =>
      Promise.reject(
        new ApiError(
          422,
          JSON.stringify({
            detail: [
              { loc: ["body", "colour"], msg: "must be a six-digit hex colour", type: "value_error" },
            ],
          })
        )
      )
    );
    renderTypesPanel({ kind: "node", id: "type-1" });
    await screen.findByTestId("entity-type-panel");
    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "#ff8800" } });
    expect(await screen.findByText(/six-digit hex colour/i)).toBeInTheDocument();
  });

  it("shows the relationship type behind an edge, with its shape", async () => {
    renderTypesPanel({ kind: "edge", id: "reltype-6" });
    const panel = await screen.findByTestId("relationship-type-panel");
    expect(panel).toHaveTextContent("works_for");
    await waitFor(() =>
      expect(screen.getByTestId("relationship-type-ends")).toHaveTextContent("employee → unit")
    );
    expect(screen.getByTestId("relationship-type-cardinality")).toHaveTextContent("n → 1");
    expect(screen.getByTestId("relationship-type-hierarchy")).toHaveTextContent("No");
  });

  it("is the only place a relationship type's colour can be set, and it works", async () => {
    // There is no relationship-type page in this app; without this panel a
    // relationship type could only be coloured through the API.
    stubTypesApi(() => Promise.resolve({ ...WORKS_FOR_TYPE, colour: "#2ca02c" }));
    renderTypesPanel({ kind: "edge", id: "reltype-6" });
    await screen.findByTestId("relationship-type-panel");
    // It has none stored, so the control previews the fallback the canvas
    // uses -- keyed on the relationship type's id, not the edge id.
    expect(screen.getByTestId("colour-preview")).toHaveAttribute("data-fill", fallbackColour("6"));

    fireEvent.change(screen.getByTestId("colour-hex"), { target: { value: "#2CA02C" } });
    await waitFor(() => expect(callsTo("PATCH", "/api/v1/relationship-types/6")).toHaveLength(1));
    expect(bodyOf(callsTo("PATCH", "/api/v1/relationship-types/6")[0])).toEqual({ colour: "#2ca02c" });
  });

  it("renders nothing for an id that is not a types id", async () => {
    // An objects-mode id can reach here only through a bug; it must not be
    // parsed as a type id and fetch the wrong row.
    const { container } = renderTypesPanel({ kind: "node", id: "2" });
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(
      (apiFetch as any).mock.calls.filter((call: any[]) =>
        /^\/api\/v1\/entity-types\/\d+$/.test(String(call[0]))
      )
    ).toHaveLength(0);
  });
});
