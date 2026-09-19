import type { ComponentProps } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphEditor, { applyGraphToCy, positionsAreDegenerate } from "./GraphEditor";

const { mockCytoscapeInstance, mockCytoscape, registeredHandlersRef, elementStore } = vi.hoisted(() => {
  const handlersRef: { current: Record<string, (...args: any[]) => void> } = { current: {} };

  type EleEntry = {
    data: Record<string, any>;
    isNode: boolean;
    styles: Record<string, any>;
    classes: Set<string>;
    position: { x: number; y: number };
  };
  const store = new Map<string, EleEntry>();

  function wrapEle(id: string) {
    return {
      id: () => id,
      isNode: () => store.get(id)?.isNode ?? false,
      data: (arg?: any) => {
        const entry = store.get(id);
        if (!entry) return undefined;
        if (arg === undefined) return { ...entry.data };
        if (typeof arg === "string") return entry.data[arg];
        Object.assign(entry.data, arg);
        return undefined;
      },
      move: (opts: { parent?: string | null }) => {
        const entry = store.get(id);
        if (!entry) return;
        entry.data.parent = opts.parent ?? undefined;
      },
      style: (key: string, value?: any) => {
        const entry = store.get(id);
        if (!entry) return undefined;
        if (value === undefined) return entry.styles[key];
        entry.styles[key] = value;
        return undefined;
      },
      // H-1: position getter/setter -- Arrow-key traversal orders nodes by this, and tests set
      // it explicitly (rather than relying on layout, which the mock never actually runs) to
      // exercise the left-to-right/top-to-bottom ordering.
      position: (val?: { x: number; y: number }) => {
        const entry = store.get(id);
        if (!entry) return undefined;
        if (val === undefined) return { ...entry.position };
        entry.position = { ...val };
        return undefined;
      },
      addClass: (cls: string) => store.get(id)?.classes.add(cls),
      removeClass: (cls: string) => cls.split(" ").forEach((c) => store.get(id)?.classes.delete(c)),
    };
  }

  function makeCollection(ids: string[]) {
    return {
      forEach: (fn: (ele: any) => void) => ids.forEach((id) => fn(wrapEle(id))),
      map: (fn: (ele: any) => any) => ids.map((id) => fn(wrapEle(id))),
      removeClass: (cls: string) => ids.forEach((id) => wrapEle(id).removeClass(cls)),
      remove: () => ids.forEach((id) => store.delete(id)),
      length: ids.length,
    };
  }

  function idsOf(target: any): string[] {
    if (!target) return [];
    if (typeof target.id === "function") return [target.id()];
    if (Array.isArray(target)) return target.map((t: any) => (typeof t === "string" ? t : t.id()));
    if (typeof target.forEach === "function") {
      const out: string[] = [];
      target.forEach((e: any) => out.push(e.id()));
      return out;
    }
    return [];
  }

  const instance: any = {
    add: vi.fn((elements: any[]) => {
      const added: string[] = [];
      (elements ?? []).forEach((el: any) => {
        const isNode = !("source" in el.data);
        store.set(el.data.id, {
          data: { ...el.data },
          isNode,
          styles: {},
          classes: new Set(),
          position: el.position ? { ...el.position } : { x: 0, y: 0 },
        });
        added.push(el.data.id);
      });
      return makeCollection(added);
    }),
    remove: vi.fn((target: any) => {
      idsOf(target).forEach((id) => store.delete(id));
    }),
    getElementById: vi.fn((id: string) => wrapEle(id)),
    nodes: vi.fn(() =>
      makeCollection([...store.entries()].filter(([, e]) => e.isNode).map(([id]) => id))
    ),
    edges: vi.fn(() =>
      makeCollection([...store.entries()].filter(([, e]) => !e.isNode).map(([id]) => id))
    ),
    elements: vi.fn(() => makeCollection([...store.keys()])),
    extent: vi.fn(() => ({ x1: 0, y1: 0, x2: 100, y2: 100 })),
    center: vi.fn(),
    autoungrabify: vi.fn(),
    layout: vi.fn(() => ({
      run: vi.fn(),
      on: vi.fn(),
      promiseOn: vi.fn(() => Promise.resolve()),
    })),
    fit: vi.fn(),
    destroy: vi.fn(),
    edgehandles: vi.fn(() => ({
      enableDrawMode: vi.fn(),
      disableDrawMode: vi.fn(),
      destroy: vi.fn(),
      start: vi.fn(),
    })),
    on: vi.fn((event: string, selectorOrHandler: any, maybeHandler?: any) => {
      if (typeof selectorOrHandler === "function") {
        handlersRef.current[event] = selectorOrHandler;
      } else {
        handlersRef.current[`${event}:${selectorOrHandler}`] = maybeHandler;
      }
    }),
  };
  const constructor: any = vi.fn(() => instance);
  constructor.use = vi.fn();
  return { mockCytoscapeInstance: instance, mockCytoscape: constructor, registeredHandlersRef: handlersRef, elementStore: store };
});

vi.mock("cytoscape", () => ({ default: mockCytoscape }));
vi.mock("cytoscape-elk", () => ({ default: {} }));
vi.mock("cytoscape-edgehandles", () => ({ default: {} }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch, ApiError } from "../api/client";

// --- v1 fixtures -----------------------------------------------------------
//
// Every `code` equals its `name`, because in schema v1 they are the same
// column (`entity_type.name` / `relationship_type.name`, Task 7's mapping).
// A fixture where they differ cannot catch the "{name} ({code})" template:
// it renders "Unit (unit)", which reads as deliberate. Here it renders
// "unit (unit)", which is the defect.

const GRAPH = {
  // Three levels of nesting: hq > ops > ahmed. One level would pass against
  // code that only ever sets a first-generation parent.
  nodes: [
    { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
    { id: "2", type: "unit", label: "ops", parent: "1", attributes: {} },
    { id: "3", type: "employee", label: "ahmed", parent: "2", attributes: { code: "E-1", status: "active" } },
  ],
  edges: [{ id: "10", source: "1", target: "2", type: "reports_to", label: "reports_to", attributes: {} }],
  entity_types: [
    { id: "1", code: "employee", name: "employee", is_abstract: false },
    { id: "2", code: "unit", name: "unit", is_abstract: false },
  ],
  relationship_types: [
    {
      id: "5",
      code: "reports_to",
      name: "reports_to",
      is_directed: true,
      source_entity_type: "unit",
      target_entity_type: "unit",
    },
    {
      id: "6",
      code: "works_for",
      name: "works_for",
      is_directed: true,
      source_entity_type: "employee",
      target_entity_type: "unit",
    },
  ],
  hierarchies: [{ id: "5", code: "reports_to", name: "reports_to" }],
  attribute_definitions: [],
};

const HIERARCHY_TYPES = {
  items: [
    {
      id: 5,
      domain_id: 1,
      name: "reports_to",
      from_type_id: 2,
      to_type_id: 2,
      cardinality: "one_to_many",
      is_hierarchy: true,
    },
  ],
  total: 1,
};

const ENTITY_TYPES = {
  items: [
    {
      id: 1,
      domain_id: 1,
      name: "employee",
      role: "agent",
      // `code` and `status` are ordinary v1 attribute names. v0 hid them as
      // "built-in collisions"; v1 has no built-ins for them to collide with.
      attributes: [
        { id: 11, entity_type_id: 1, name: "code", data_type: "text", required: false, unit: null, enum_values: null, default_value: null },
        { id: 12, entity_type_id: 1, name: "status", data_type: "enum", required: false, unit: null, enum_values: ["active", "leave"], default_value: null },
        { id: 13, entity_type_id: 1, name: "grade", data_type: "integer", required: false, unit: null, enum_values: null, default_value: null },
      ],
    },
    {
      id: 2,
      domain_id: 1,
      name: "unit",
      role: "org",
      // Shares the attribute NAME `code` with employee, which is what makes a
      // value typed for one type able to leak into the other's control.
      attributes: [
        { id: 21, entity_type_id: 2, name: "code", data_type: "text", required: false, unit: null, enum_values: null, default_value: null },
      ],
    },
  ],
  total: 2,
};

type Stub = {
  graph?: unknown;
  graphError?: unknown;
  relationshipTypes?: unknown;
  entityTypes?: unknown;
  write?: (path: string, options: RequestInit) => unknown;
};

function stubApi(stub: Stub = {}) {
  (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
    if (options?.method && options.method !== "GET") {
      return stub.write ? stub.write(path, options) : Promise.resolve({ id: 99, key: "new", label: null, attrs: {} });
    }
    if (path.startsWith("/api/v1/graph")) {
      return stub.graphError ? Promise.reject(stub.graphError) : Promise.resolve(stub.graph ?? GRAPH);
    }
    if (path.startsWith("/api/v1/relationship-types")) {
      return Promise.resolve(stub.relationshipTypes ?? HIERARCHY_TYPES);
    }
    if (path.startsWith("/api/v1/entity-types")) {
      return Promise.resolve(stub.entityTypes ?? ENTITY_TYPES);
    }
    return Promise.resolve({});
  });
}

function bodyOf(call: any[]): any {
  return JSON.parse((call[1] as RequestInit).body as string);
}

function writeCalls(method: string, prefix: string): any[][] {
  return (apiFetch as any).mock.calls.filter(
    (call: any[]) => typeof call[0] === "string" && call[0].startsWith(prefix) && call[1]?.method === method
  );
}

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWithProviders(props: Partial<ComponentProps<typeof GraphEditor>> = {}) {
  return render(
    <QueryClientProvider client={client()}>
      <GraphEditor domainId={1} hierarchyTypeId={null} onHierarchyTypeChange={vi.fn()} {...props} />
    </QueryClientProvider>
  );
}

/** Opens the create-node form and picks the entity type named `typeName`. */
async function openCreateNodeFor(typeName: string) {
  fireEvent.click(screen.getByTestId("toggle-create-node"));
  const typeSelect = (await screen.findByLabelText(/^Entity type/)) as HTMLSelectElement;
  await waitFor(() => expect(within(typeSelect).getByText(typeName)).toBeInTheDocument());
  const option = within(typeSelect).getByText(typeName) as HTMLOptionElement;
  fireEvent.change(typeSelect, { target: { value: option.value } });
}

describe("GraphEditor", () => {
  beforeEach(() => {
    mockCytoscape.mockClear();
    mockCytoscapeInstance.add.mockClear();
    mockCytoscapeInstance.remove.mockClear();
    mockCytoscapeInstance.getElementById.mockClear();
    mockCytoscapeInstance.nodes.mockClear();
    mockCytoscapeInstance.edges.mockClear();
    mockCytoscapeInstance.elements.mockClear();
    mockCytoscapeInstance.extent.mockClear();
    mockCytoscapeInstance.center.mockClear();
    mockCytoscapeInstance.autoungrabify.mockClear();
    mockCytoscapeInstance.on.mockClear();
    mockCytoscapeInstance.edgehandles.mockClear();
    mockCytoscapeInstance.layout.mockClear();
    mockCytoscapeInstance.layout.mockImplementation(() => ({
      run: vi.fn(),
      on: vi.fn(),
      promiseOn: vi.fn(() => Promise.resolve()),
    }));
    registeredHandlersRef.current = {};
    elementStore.clear();
    (apiFetch as any).mockReset();
    stubApi();
  });

  // --- the v1 read -------------------------------------------------------

  it("reads the graph from the v1 route for its domain, naming the hierarchy type when one is selected", async () => {
    renderWithProviders({ hierarchyTypeId: 5 });
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/api/v1/graph?domain_id=1&hierarchy_type_id=5"));
  });

  it("creates the cytoscape instance empty, then adds nodes and edges via cy.add, nesting every generation", async () => {
    renderWithProviders({ hierarchyTypeId: 5 });
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledTimes(1));
    expect(mockCytoscape.mock.calls[0][0].elements).toEqual([]);

    await waitFor(() => expect(mockCytoscapeInstance.add).toHaveBeenCalled());
    const added = mockCytoscapeInstance.add.mock.calls.flatMap((call: any[]) => call[0]);
    const nodes = added.filter((el: any) => !("source" in el.data));
    expect(nodes.map((el: any) => el.data.id)).toEqual(expect.arrayContaining(["1", "2", "3"]));
    // Two generations deep, not one.
    expect(nodes.find((el: any) => el.data.id === "2").data.parent).toBe("1");
    expect(nodes.find((el: any) => el.data.id === "3").data.parent).toBe("2");
    expect(added.filter((el: any) => "source" in el.data).map((el: any) => el.data.id)).toEqual(["10"]);
  });

  // --- the hierarchy picker ---------------------------------------------

  it("lists the domain's hierarchy relationship types, filtered server-side, each named once", async () => {
    renderWithProviders();

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/api/v1/relationship-types?domain_id=1&is_hierarchy=true&limit=500")
    );
    const select = screen.getByTestId("hierarchy-select");
    await waitFor(() => expect(within(select).getByText("reports_to")).toBeInTheDocument());
    // The v0 template rendered `{name} ({code})`, which in v1 is one string twice.
    expect(within(select).queryByText("reports_to (reports_to)")).not.toBeInTheDocument();
  });

  it("does not offer a relationship type that is not a hierarchy", async () => {
    renderWithProviders();
    const select = screen.getByTestId("hierarchy-select");
    await waitFor(() => expect(within(select).getByText("reports_to")).toBeInTheDocument());
    // `works_for` is in the graph payload's relationship_types but is not a
    // hierarchy, so the server-filtered list is what must feed this select.
    expect(within(select).queryByText("works_for")).not.toBeInTheDocument();
  });

  it("reports the chosen hierarchy type as a number, which is what the API takes", async () => {
    const onHierarchyTypeChange = vi.fn();
    renderWithProviders({ onHierarchyTypeChange });
    const select = screen.getByTestId("hierarchy-select");
    await waitFor(() => expect(within(select).getByText("reports_to")).toBeInTheDocument());

    fireEvent.change(select, { target: { value: "5" } });
    expect(onHierarchyTypeChange).toHaveBeenCalledWith(5);

    fireEvent.change(select, { target: { value: "" } });
    expect(onHierarchyTypeChange).toHaveBeenLastCalledWith(null);
  });

  // --- creating a node ---------------------------------------------------

  it("creates an entity through the v1 entities route, with its attrs typed by data_type", async () => {
    renderWithProviders();
    await openCreateNodeFor("employee");

    fireEvent.change(screen.getByLabelText(/^Key/), { target: { value: "ahmed" } });
    fireEvent.change(screen.getByLabelText(/^Label/), { target: { value: "Ahmed Z" } });
    fireEvent.change(screen.getByTestId("attr-code"), { target: { value: "E-9" } });
    fireEvent.change(screen.getByTestId("attr-status"), { target: { value: "leave" } });
    fireEvent.change(screen.getByTestId("attr-grade"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(writeCalls("POST", "/api/v1/entities")).toHaveLength(1));
    expect(bodyOf(writeCalls("POST", "/api/v1/entities")[0])).toEqual({
      entity_type_id: 1,
      key: "ahmed",
      label: "Ahmed Z",
      // 7 as a JSON number, not "7": entity_validate refuses a string for an
      // `integer` attribute.
      attrs: { code: "E-9", status: "leave", grade: 7 },
    });
  });

  it("offers an input for an attribute named code or status, which v1 has no built-in to collide with", async () => {
    renderWithProviders();
    await openCreateNodeFor("employee");

    expect(screen.getByTestId("attr-code")).toBeInTheDocument();
    expect(screen.getByTestId("attr-status")).toBeInTheDocument();
    expect(screen.queryByText(/collides with a built-in field/)).not.toBeInTheDocument();
  });

  it("starts the new type's controls empty when the type is changed, rather than carrying a same-named value across", async () => {
    renderWithProviders();
    await openCreateNodeFor("employee");
    fireEvent.change(screen.getByTestId("attr-code"), { target: { value: "E-9" } });

    const typeSelect = screen.getByLabelText(/^Entity type/) as HTMLSelectElement;
    fireEvent.change(typeSelect, { target: { value: "2" } });

    // unit's own `code`, not employee's value under the same name.
    expect(screen.getByTestId("attr-code")).toHaveValue("");
  });

  it("uses the v1 attribute vocabulary: an enum is a select of its values, an integer a numeric text box", async () => {
    renderWithProviders();
    await openCreateNodeFor("employee");

    const status = screen.getByTestId("attr-status") as HTMLSelectElement;
    expect(status.tagName).toBe("SELECT");
    expect(within(status).getByText("leave")).toBeInTheDocument();
    expect(screen.getByTestId("attr-grade")).toHaveAttribute("inputmode", "numeric");
  });

  it("refuses a decimal in an integer attribute before anything is sent", async () => {
    renderWithProviders();
    await openCreateNodeFor("employee");

    fireEvent.change(screen.getByLabelText(/^Key/), { target: { value: "ahmed" } });
    fireEvent.change(screen.getByTestId("attr-grade"), { target: { value: "2.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText(/grade: must be a whole number/)).toBeInTheDocument();
    expect(writeCalls("POST", "/api/v1/entities")).toHaveLength(0);
  });

  it("refuses an empty key before anything is sent", async () => {
    renderWithProviders();
    await openCreateNodeFor("unit");

    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText(/key is required/i)).toBeInTheDocument();
    expect(writeCalls("POST", "/api/v1/entities")).toHaveLength(0);
  });

  it("places a new node under the chosen parent by creating a relationship of the selected hierarchy type", async () => {
    stubApi({
      write: (path) =>
        path === "/api/v1/entities"
          ? Promise.resolve({ id: 42, entity_type_id: 2, key: "ops", label: null, sort_order: 0, active: true, attrs: {} })
          : Promise.resolve({ id: 77 }),
    });
    renderWithProviders({ hierarchyTypeId: 5 });
    await openCreateNodeFor("unit");

    fireEvent.change(screen.getByLabelText(/^Key/), { target: { value: "ops" } });
    fireEvent.change(screen.getByLabelText(/^Parent/), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(writeCalls("POST", "/api/v1/relationships")).toHaveLength(1));
    // from = parent, to = the new child: the hierarchy reads from_entity as
    // the parent of to_entity.
    expect(bodyOf(writeCalls("POST", "/api/v1/relationships")[0])).toEqual({
      relationship_type_id: 5,
      from_entity_id: 1,
      to_entity_id: 42,
    });
  });

  it("does not create a hierarchy relationship when no parent was chosen", async () => {
    renderWithProviders({ hierarchyTypeId: 5 });
    await openCreateNodeFor("unit");

    fireEvent.change(screen.getByLabelText(/^Key/), { target: { value: "ops" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(writeCalls("POST", "/api/v1/entities")).toHaveLength(1));
    expect(writeCalls("POST", "/api/v1/relationships")).toHaveLength(0);
  });

  it("offers no parent picker when no hierarchy is selected, because there is no relationship type to place it in", async () => {
    renderWithProviders({ hierarchyTypeId: null });
    await openCreateNodeFor("unit");

    expect(screen.queryByLabelText(/^Parent/)).not.toBeInTheDocument();
  });

  // --- creating an edge --------------------------------------------------

  it("opens a type-filtered relationship picker on drag-connect and creates the relationship on confirm", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    act(() => registeredHandlersRef.current["ehcomplete"](null, { id: () => "3" }, { id: () => "1" }));

    const picker = await screen.findByTestId("edge-type-picker");
    // employee -> unit: works_for only, and named once.
    expect(within(picker).getByRole("button", { name: "works_for" })).toBeInTheDocument();
    expect(within(picker).queryByRole("button", { name: "works_for (works_for)" })).not.toBeInTheDocument();
    expect(within(picker).queryByRole("button", { name: "reports_to" })).not.toBeInTheDocument();

    fireEvent.click(within(picker).getByRole("button", { name: "works_for" }));

    await waitFor(() => expect(writeCalls("POST", "/api/v1/relationships")).toHaveLength(1));
    expect(bodyOf(writeCalls("POST", "/api/v1/relationships")[0])).toEqual({
      relationship_type_id: 6,
      from_entity_id: 3,
      to_entity_id: 1,
    });
  });

  it("explains the dragged pair when no relationship type allows it", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    // unit -> employee: neither type allows that direction.
    act(() => registeredHandlersRef.current["ehcomplete"](null, { id: () => "1" }, { id: () => "3" }));

    expect(await screen.findByText("No relationship type allows unit → employee")).toBeInTheDocument();
  });

  it("shows a cardinality violation's own message, without repeating the relationship type as a field name", async () => {
    stubApi({
      write: () =>
        Promise.reject(
          new ApiError(
            422,
            JSON.stringify({
              detail: [
                {
                  loc: ["body", "works_for"],
                  msg: 'relationship "works_for": target already has a source',
                  kind: "cardinality",
                },
              ],
            })
          )
        ),
    });
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    act(() => registeredHandlersRef.current["ehcomplete"](null, { id: () => "3" }, { id: () => "1" }));
    fireEvent.click(await screen.findByRole("button", { name: "works_for" }));

    const banner = await screen.findByTestId("graph-error");
    expect(banner).toHaveTextContent('relationship "works_for": target already has a source');
    expect(banner.textContent).not.toContain('works_for: relationship "works_for"');
  });

  it("shows a cycle violation's own message the same way -- the branch is on loc, not on kind", async () => {
    stubApi({
      write: () =>
        Promise.reject(
          new ApiError(
            422,
            JSON.stringify({
              detail: [
                { loc: ["body", "works_for"], msg: 'relationship "works_for": would create a cycle', kind: "cycle" },
              ],
            })
          )
        ),
    });
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    act(() => registeredHandlersRef.current["ehcomplete"](null, { id: () => "3" }, { id: () => "1" }));
    fireEvent.click(await screen.findByRole("button", { name: "works_for" }));

    const banner = await screen.findByTestId("graph-error");
    expect(banner).toHaveTextContent('relationship "works_for": would create a cycle');
  });

  it("dismisses the error banner", async () => {
    stubApi({
      write: () =>
        Promise.reject(
          new ApiError(422, JSON.stringify({ detail: [{ loc: ["body", "works_for"], msg: "nope", kind: "cycle" }] }))
        ),
    });
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    act(() => registeredHandlersRef.current["ehcomplete"](null, { id: () => "3" }, { id: () => "1" }));
    fireEvent.click(await screen.findByRole("button", { name: "works_for" }));
    await screen.findByTestId("graph-error");

    fireEvent.click(screen.getByRole("button", { name: "Dismiss error" }));
    expect(screen.queryByTestId("graph-error")).not.toBeInTheDocument();
  });

  // --- filtering ---------------------------------------------------------

  it("filters by the node's label, the only text a v1 node carries", async () => {
    renderWithProviders({ filter: { selectedTypes: null, search: "ahm", highlightIds: null } });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    await waitFor(() => expect(elementStore.get("3")?.styles.display).toBe("element"));
    expect(elementStore.get("1")?.styles.display).toBe("none");
  });

  it("does not match an attribute's value, so a query that only an attribute holds matches nothing", async () => {
    // "E-1" is node 3's `code` ATTRIBUTE. v0 matched it because `code` was a
    // built-in column; in v1 it is an ordinary attribute an entity type may
    // or may not declare, so search is over labels only.
    renderWithProviders({ filter: { selectedTypes: null, search: "E-1", highlightIds: null } });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    await waitFor(() => expect(elementStore.get("1")?.styles.display).toBe("none"));
    expect(elementStore.get("3")?.styles.display).toBe("none");
  });

  it("filters by entity type using the type's name", async () => {
    renderWithProviders({ filter: { selectedTypes: ["unit"], search: "", highlightIds: null } });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    await waitFor(() => expect(elementStore.get("1")?.styles.display).toBe("element"));
    expect(elementStore.get("3")?.styles.display).toBe("none");
  });

  // --- behaviour carried over from the v0 editor --------------------------

  it("calls the latest onSelectionChange after a rerender, not the one captured at mount", async () => {
    const first = vi.fn();
    const second = vi.fn();
    const queryClient = client();
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <GraphEditor domainId={1} hierarchyTypeId={null} onHierarchyTypeChange={vi.fn()} onSelectionChange={first} />
      </QueryClientProvider>
    );
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    rerender(
      <QueryClientProvider client={queryClient}>
        <GraphEditor domainId={1} hierarchyTypeId={null} onHierarchyTypeChange={vi.fn()} onSelectionChange={second} />
      </QueryClientProvider>
    );

    act(() => registeredHandlersRef.current["tap:node"]({ target: { id: () => "3" } }));
    expect(second).toHaveBeenCalledWith({ kind: "node", id: "3" });
    expect(first).not.toHaveBeenCalled();
  });

  it("passes ELK options that request hierarchy-safe layout to cy.layout", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscapeInstance.layout).toHaveBeenCalled());
    const options = mockCytoscapeInstance.layout.mock.calls[0][0];
    expect(options.name).toBe("elk");
    expect(options.elk["elk.hierarchyHandling"]).toBe("INCLUDE_CHILDREN");
  });

  it("toggles edgehandles draw mode and autoungrabify when the Connect button is clicked", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscapeInstance.edgehandles).toHaveBeenCalled());
    const eh = mockCytoscapeInstance.edgehandles.mock.results[0].value;

    fireEvent.click(screen.getByTestId("toggle-connect"));
    expect(eh.enableDrawMode).toHaveBeenCalled();
    expect(mockCytoscapeInstance.autoungrabify).toHaveBeenLastCalledWith(true);

    fireEvent.click(screen.getByTestId("toggle-connect"));
    expect(eh.disableDrawMode).toHaveBeenCalled();
    expect(mockCytoscapeInstance.autoungrabify).toHaveBeenLastCalledWith(false);
  });

  it("shows Layout failed in the error banner when the layout run rejects instead of throwing", async () => {
    mockCytoscapeInstance.layout.mockImplementation(() => ({
      run: vi.fn(() => Promise.reject(new Error("elk exploded"))),
      on: vi.fn(),
      promiseOn: vi.fn(() => Promise.resolve()),
    }));
    renderWithProviders();
    expect(await screen.findByText("Layout failed")).toBeInTheDocument();
  });

  it("clears the canvas when the graph query errors, so stale nodes aren't left drawn (I-2/M-5)", async () => {
    stubApi({ graphError: new ApiError(500, "boom") });
    renderWithProviders();
    expect(await screen.findByText("Failed to load graph")).toBeInTheDocument();
    expect(elementStore.size).toBe(0);
  });

  it("shows a Retry button next to a failed graph load that re-issues the request (D-4)", async () => {
    stubApi({ graphError: new ApiError(500, "boom") });
    renderWithProviders();
    await screen.findByText("Failed to load graph");
    const graphCalls = () =>
      (apiFetch as any).mock.calls.filter((c: any[]) => String(c[0]).startsWith("/api/v1/graph")).length;
    const before = graphCalls();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(graphCalls()).toBeGreaterThan(before));
  });

  it("gives every toolbar control an accessible name and a title, and renders a help line that changes with Connect (F-2)", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    expect(screen.getByTestId("hierarchy-select")).toHaveAccessibleName();
    expect(screen.getByRole("button", { name: "Re-run automatic layout" })).toHaveAttribute("title");
    expect(screen.getByRole("button", { name: "Fit the whole graph in view" })).toHaveAttribute("title");
    expect(screen.getByTestId("graph-help")).toHaveTextContent(/Boxes group nodes by hierarchy/);

    fireEvent.click(screen.getByTestId("toggle-connect"));
    expect(screen.getByTestId("graph-help")).toHaveTextContent("Drag from one node to another to connect them.");
  });

  it("gives node labels their own colour (distinct from the node background) and a text outline (F-3)", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    const style = mockCytoscape.mock.calls[0][0].style.find((s: any) => s.selector === "node").style;
    expect(style.color).not.toBe(style["background-color"]);
    expect(style["text-outline-width"]).toBeGreaterThan(0);
  });

  it("sizes the canvas container from its flex parent rather than a fixed pixel height (F-4)", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    const container = screen.getByTestId("cytoscape-container");
    expect(container.className).toContain("h-full");
    expect(container.className).not.toMatch(/h-\[600px\]/);
  });

  it("shows an empty-state overlay with a 'Create the first node' button when the graph has no nodes", async () => {
    stubApi({ graph: { ...GRAPH, nodes: [], edges: [] } });
    renderWithProviders();
    expect(await screen.findByTestId("graph-empty-state")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create the first node" }));
    expect(screen.getByTestId("create-node-form")).toBeInTheDocument();
  });

  it("does not show the empty-state overlay once the graph has nodes", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscapeInstance.add).toHaveBeenCalled());
    expect(screen.queryByTestId("graph-empty-state")).not.toBeInTheDocument();
  });

  it("closes the create-node form on Escape and returns focus to the '+ New Node' trigger (H-7)", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("toggle-create-node"));
    const form = screen.getByTestId("create-node-form");

    fireEvent.keyDown(form, { key: "Escape" });

    expect(screen.queryByTestId("create-node-form")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByTestId("toggle-create-node"));
  });

  it("makes the canvas focusable with an accessible name naming the node count and arrow-key usage (H-1)", async () => {
    renderWithProviders();
    const container = screen.getByTestId("cytoscape-container");
    expect(container).toHaveAttribute("role", "application");
    expect(container).toHaveAttribute("tabindex", "0");
    await waitFor(() => expect(container.getAttribute("aria-label")).toContain("3 nodes"));
    expect(container.getAttribute("aria-label")).toContain("arrow keys");
  });

  it("moves a roving keyboard focus between nodes with ArrowRight/ArrowLeft, ringed by .kb-focus, and centres the viewport (H-1)", async () => {
    renderWithProviders();
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
    elementStore.get("1")!.position = { x: 0, y: 0 };
    elementStore.get("2")!.position = { x: 10, y: 0 };
    elementStore.get("3")!.position = { x: 20, y: 0 };
    const container = screen.getByTestId("cytoscape-container");

    fireEvent.keyDown(container, { key: "ArrowRight" });
    expect(elementStore.get("1")!.classes.has("kb-focus")).toBe(true);
    expect(mockCytoscapeInstance.center).toHaveBeenCalled();

    fireEvent.keyDown(container, { key: "ArrowRight" });
    expect(elementStore.get("1")!.classes.has("kb-focus")).toBe(false);
    expect(elementStore.get("2")!.classes.has("kb-focus")).toBe(true);

    fireEvent.keyDown(container, { key: "ArrowLeft" });
    expect(elementStore.get("1")!.classes.has("kb-focus")).toBe(true);
  });

  it("calls onSelectionChange for the keyboard-focused node when Enter is pressed on the canvas (H-1)", async () => {
    const onSelectionChange = vi.fn();
    renderWithProviders({ onSelectionChange });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
    const container = screen.getByTestId("cytoscape-container");

    fireEvent.keyDown(container, { key: "ArrowRight" });
    fireEvent.keyDown(container, { key: "Enter" });

    expect(onSelectionChange).toHaveBeenCalledWith({ kind: "node", id: expect.any(String) });
  });

  it("returns focus to the toolbar's first control (hierarchy select) when Escape is pressed on the canvas (H-1)", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    fireEvent.keyDown(screen.getByTestId("cytoscape-container"), { key: "Escape" });

    expect(document.activeElement).toBe(screen.getByTestId("hierarchy-select"));
  });

  it("moves the roving keyboard focus to a node when focusRequest's token changes (H-1 fix round 1)", async () => {
    const queryClient = client();
    function view(focusRequest: { nodeId: string; token: number } | null) {
      return (
        <QueryClientProvider client={queryClient}>
          <GraphEditor
            domainId={1}
            hierarchyTypeId={null}
            onHierarchyTypeChange={vi.fn()}
            focusRequest={focusRequest}
          />
        </QueryClientProvider>
      );
    }
    const { rerender } = render(view(null));
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    rerender(view({ nodeId: "3", token: 1 }));
    await waitFor(() => expect(elementStore.get("3")!.classes.has("kb-focus")).toBe(true));

    // The SAME node again: keyed on the token, not the id, so it re-rings and
    // re-announces rather than being treated as no change.
    elementStore.get("3")!.classes.delete("kb-focus");
    rerender(view({ nodeId: "3", token: 2 }));
    await waitFor(() => expect(elementStore.get("3")!.classes.has("kb-focus")).toBe(true));
  });

  it("announces the keyboard-focused node's label in a polite live region (H-1)", async () => {
    renderWithProviders();
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
    elementStore.get("1")!.position = { x: 0, y: 0 };
    elementStore.get("2")!.position = { x: 10, y: 0 };
    elementStore.get("3")!.position = { x: 20, y: 0 };
    const live = screen.getByTestId("graph-live");
    expect(live).toHaveAttribute("aria-live", "polite");

    fireEvent.keyDown(screen.getByTestId("cytoscape-container"), { key: "ArrowRight" });

    await waitFor(() => expect(live).toHaveTextContent("hq"));
  });

  it("applies data changes incrementally without recreating the cytoscape instance", async () => {
    const queryClient = client();
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <GraphEditor domainId={1} hierarchyTypeId={null} onHierarchyTypeChange={vi.fn()} />
      </QueryClientProvider>
    );
    await waitFor(() => expect(mockCytoscapeInstance.add).toHaveBeenCalled());
    expect(mockCytoscape).toHaveBeenCalledTimes(1);

    rerender(
      <QueryClientProvider client={queryClient}>
        <GraphEditor
          domainId={1}
          hierarchyTypeId={null}
          onHierarchyTypeChange={vi.fn()}
          filter={{ selectedTypes: null, search: "hq", highlightIds: null }}
        />
      </QueryClientProvider>
    );
    expect(mockCytoscape).toHaveBeenCalledTimes(1);
  });
});

describe("applyGraphToCy", () => {
  const base = {
    entity_types: [],
    relationship_types: [],
    hierarchies: [],
    attribute_definitions: [],
  };

  function cyDouble() {
    const nodes = new Map<string, any>();
    const edges = new Map<string, any>();
    const added: any[] = [];
    function ele(id: string, store: Map<string, any>) {
      return {
        id: () => id,
        data: (arg?: any) => {
          const entry = store.get(id);
          if (arg === undefined) return { ...entry };
          if (typeof arg === "string") return entry[arg];
          Object.assign(entry, arg);
          return undefined;
        },
        move: (opts: { parent?: string | null }) => {
          store.get(id).parent = opts.parent ?? undefined;
        },
      };
    }
    return {
      _nodes: nodes,
      _edges: edges,
      added,
      seedNode: (data: any) => nodes.set(data.id, { ...data }),
      nodes: () => ({ forEach: (fn: any) => [...nodes.keys()].forEach((id) => fn(ele(id, nodes))) }),
      edges: () => ({ forEach: (fn: any) => [...edges.keys()].forEach((id) => fn(ele(id, edges))) }),
      getElementById: (id: string) => ele(id, nodes.has(id) ? nodes : edges),
      remove: (target: any) => {
        const id = target.id();
        nodes.delete(id);
        edges.delete(id);
      },
      extent: () => ({ x1: 0, y1: 0, x2: 100, y2: 100 }),
      add: (elements: any[]) => {
        elements.forEach((el) => {
          added.push(el);
          if ("source" in el.data) edges.set(el.data.id, { ...el.data });
          else nodes.set(el.data.id, { ...el.data });
        });
      },
    } as any;
  }

  it("returns structureChanged: false when only a label changed", () => {
    const cy = cyDouble();
    cy.seedNode({ id: "1", label: "old", type: "unit" });
    const result = applyGraphToCy(cy, {
      ...base,
      nodes: [{ id: "1", type: "unit", label: "new", parent: null, attributes: {} }],
      edges: [],
    } as any);
    expect(result.structureChanged).toBe(false);
    expect(cy._nodes.get("1").label).toBe("new");
  });

  it("returns structureChanged: true when a node is added", () => {
    const cy = cyDouble();
    const result = applyGraphToCy(cy, {
      ...base,
      nodes: [{ id: "1", type: "unit", label: "hq", parent: null, attributes: {} }],
      edges: [],
    } as any);
    expect(result.structureChanged).toBe(true);
  });

  it("re-parents an existing node at every generation when the hierarchy selection changes", () => {
    const cy = cyDouble();
    cy.seedNode({ id: "1", label: "hq", type: "unit" });
    cy.seedNode({ id: "2", label: "ops", type: "unit" });
    cy.seedNode({ id: "3", label: "ahmed", type: "employee" });

    const result = applyGraphToCy(cy, {
      ...base,
      nodes: [
        { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
        { id: "2", type: "unit", label: "ops", parent: "1", attributes: {} },
        { id: "3", type: "employee", label: "ahmed", parent: "2", attributes: {} },
      ],
      edges: [],
    } as any);

    expect(result.structureChanged).toBe(true);
    expect(cy._nodes.get("2").parent).toBe("1");
    // The grandchild too: code that only re-parents the first generation
    // leaves this undefined.
    expect(cy._nodes.get("3").parent).toBe("2");
  });

  it("returns structureChanged: false when only an edge is added", () => {
    const cy = cyDouble();
    cy.seedNode({ id: "1", label: "hq", type: "unit" });
    cy.seedNode({ id: "2", label: "ops", type: "unit" });
    const result = applyGraphToCy(cy, {
      ...base,
      nodes: [
        { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
        { id: "2", type: "unit", label: "ops", parent: null, attributes: {} },
      ],
      edges: [{ id: "10", source: "1", target: "2", type: "reports_to", label: "reports_to", attributes: {} }],
    } as any);
    expect(result.structureChanged).toBe(false);
    expect(cy._edges.has("10")).toBe(true);
  });

  it("gives every newly-added node its own position object, even though their coordinates are equal (M-2)", () => {
    const cy = cyDouble();
    applyGraphToCy(cy, {
      ...base,
      nodes: [
        { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
        { id: "2", type: "unit", label: "ops", parent: null, attributes: {} },
      ],
      edges: [],
    } as any);
    const positions = cy.added.filter((el: any) => el.position).map((el: any) => el.position);
    expect(positions).toHaveLength(2);
    expect(positions[0]).not.toBe(positions[1]);
    expect(positions[0]).toEqual(positions[1]);
  });

  it("skips an edge whose source or target node is not among the kept-or-added nodes", () => {
    const cy = cyDouble();
    expect(() =>
      applyGraphToCy(cy, {
        ...base,
        nodes: [{ id: "1", type: "unit", label: "hq", parent: null, attributes: {} }],
        edges: [{ id: "10", source: "1", target: "999", type: "reports_to", label: "reports_to", attributes: {} }],
      } as any)
    ).not.toThrow();
    expect(cy._edges.has("10")).toBe(false);
  });

  it("removes a node that is no longer in the graph", () => {
    const cy = cyDouble();
    cy.seedNode({ id: "1", label: "hq", type: "unit" });
    const result = applyGraphToCy(cy, { ...base, nodes: [], edges: [] } as any);
    expect(result.structureChanged).toBe(true);
    expect(cy._nodes.has("1")).toBe(false);
  });
});

describe("positionsAreDegenerate", () => {
  it("returns false for fewer than 2 positions", () => {
    expect(positionsAreDegenerate([])).toBe(false);
    expect(positionsAreDegenerate([{ x: 1, y: 1 }])).toBe(false);
  });

  it("returns false when positions are meaningfully spread out", () => {
    expect(
      positionsAreDegenerate([
        { x: 0, y: 0 },
        { x: 50, y: 20 },
      ])
    ).toBe(false);
  });

  it("returns true when every position is within 1px of every other", () => {
    expect(
      positionsAreDegenerate([
        { x: 10, y: 10 },
        { x: 10.2, y: 10.1 },
        { x: 10.4, y: 9.9 },
      ])
    ).toBe(true);
  });
});
