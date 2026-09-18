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
        store.set(el.data.id, { data: { ...el.data }, isNode, styles: {}, classes: new Set() });
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

function renderWithProviders(props: Partial<ComponentProps<typeof GraphEditor>> = {}) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <GraphEditor organizationId="org-1" hierarchyId={null} onHierarchyChange={vi.fn()} {...props} />
    </QueryClientProvider>
  );
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
  });

  it("creates the cytoscape instance empty, then adds nodes and edges (with parent) via cy.add", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [
        { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
        { id: "e2", type: "employee", label: "Sara", parent: "e1", attributes: {} },
      ],
      edges: [{ id: "r1", source: "e1", target: "e2", type: "manages", label: "Manages", attributes: {} }],
      entity_types: [],
      relationship_types: [],
      hierarchies: [{ id: "h1", code: "org-chart", name: "Org Chart" }],
      attribute_definitions: [],
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledTimes(1));
    expect(mockCytoscape.mock.calls[0][0].elements).toEqual([]);

    await waitFor(() => expect(mockCytoscapeInstance.add).toHaveBeenCalled());
    const addedElements = mockCytoscapeInstance.add.mock.calls.flatMap((call: any[]) => call[0]);
    const nodeIds = addedElements.filter((el: any) => !("source" in el.data)).map((el: any) => el.data.id);
    const edgeIds = addedElements.filter((el: any) => "source" in el.data).map((el: any) => el.data.id);
    expect(nodeIds).toEqual(expect.arrayContaining(["e1", "e2"]));
    expect(edgeIds).toEqual(["r1"]);

    const childNode = addedElements.find((el: any) => el.data.id === "e2");
    expect(childNode.data.parent).toBe("e1");
  });

  it("renders a hierarchy-select option per hierarchy in the response", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [{ id: "h1", code: "org-chart", name: "Org Chart" }],
      attribute_definitions: [],
    });

    renderWithProviders();

    expect(screen.getByTestId("hierarchy-select")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Org Chart (org-chart)")).toBeInTheDocument());
  });

  it("opens a type-filtered relationship picker when edgehandles completes a drag-connect, and creates the edge on confirm", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [
            { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
            { id: "e2", type: "unit", label: "Unit A", parent: null, attributes: {} },
          ],
          edges: [],
          entity_types: [],
          relationship_types: [
            {
              id: "rt1",
              code: "works_for",
              name: "Works For",
              is_directed: true,
              source_entity_type: "employee",
              target_entity_type: "unit",
            },
            {
              id: "rt2",
              code: "manages",
              name: "Manages",
              is_directed: true,
              source_entity_type: "unit",
              target_entity_type: "employee",
            },
          ],
          hierarchies: [],
          attribute_definitions: [],
        });
      }
      if (path === "/api/graph/domain/edges" && options?.method === "POST") {
        return Promise.resolve({
          id: "r1",
          source: "e1",
          target: "e2",
          type: "works_for",
          label: "Works For",
          attributes: {},
        });
      }
      return Promise.resolve({});
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const ehcompleteHandler = registeredHandlersRef.current["ehcomplete"];
    act(() => ehcompleteHandler(null, { id: () => "e1" }, { id: () => "e2" }));

    await waitFor(() => expect(screen.getByTestId("edge-type-picker")).toBeInTheDocument());
    expect(screen.getByText("Works For (works_for)")).toBeInTheDocument();
    expect(screen.queryByText("Manages (manages)")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Works For (works_for)"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/edges",
        expect.objectContaining({ method: "POST" })
      )
    );
  });

  it("lists type-constrained relationship types before a divider, then unconstrained (any -> any) types", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [
        { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
        { id: "e2", type: "unit", label: "Unit A", parent: null, attributes: {} },
      ],
      edges: [],
      entity_types: [],
      relationship_types: [
        {
          id: "rt-any",
          code: "related_to",
          name: "Related To",
          is_directed: false,
          source_entity_type: null,
          target_entity_type: null,
        },
        {
          id: "rt1",
          code: "works_for",
          name: "Works For",
          is_directed: true,
          source_entity_type: "employee",
          target_entity_type: "unit",
        },
      ],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const ehcompleteHandler = registeredHandlersRef.current["ehcomplete"];
    act(() => ehcompleteHandler(null, { id: () => "e1" }, { id: () => "e2" }));

    await waitFor(() => expect(screen.getByTestId("edge-type-picker")).toBeInTheDocument());
    const divider = screen.getByTestId("picker-divider");
    const constrainedButton = screen.getByText("Works For (works_for)");
    const unconstrainedButton = screen.getByText("Related To (related_to)");

    // constrained button precedes the divider, which precedes the unconstrained button
    expect(
      constrainedButton.compareDocumentPosition(divider) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      divider.compareDocumentPosition(unconstrainedButton) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("submits the create-node form and calls the nodes endpoint", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [],
          edges: [],
          entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
          relationship_types: [],
          hierarchies: [],
          attribute_definitions: [],
        });
      }
      if (path === "/api/graph/domain/nodes" && options?.method === "POST") {
        return Promise.resolve({ id: "e1", type: "employee", label: "New Person", parent: null, attributes: {} });
      }
      return Promise.resolve({});
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("toggle-create-node"));
    await waitFor(() => expect(screen.getByTestId("create-node-form")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "t1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New Person" } });
    fireEvent.submit(screen.getByTestId("create-node-form"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/nodes",
        expect.objectContaining({ method: "POST" })
      )
    );
  });

  it("shows an input per attribute_definition of the chosen create-node type, typed by data_type, and sends attributes", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [],
          edges: [],
          entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
          relationship_types: [],
          hierarchies: [],
          attribute_definitions: [
            { id: "a1", entity_type_id: "t1", code: "rank", name: "Rank", data_type: "number" },
            { id: "a2", entity_type_id: "t1", code: "active", name: "Active", data_type: "boolean" },
          ],
        });
      }
      if (path === "/api/graph/domain/nodes" && options?.method === "POST") {
        return Promise.resolve({ id: "e1", type: "employee", label: "New Person", parent: null, attributes: {} });
      }
      return Promise.resolve({});
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("toggle-create-node"));
    await waitFor(() => expect(screen.getByTestId("create-node-form")).toBeInTheDocument());

    // No type chosen yet -- no attribute inputs.
    expect(screen.queryByLabelText("Rank")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "t1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New Person" } });

    const rankInput = screen.getByLabelText("Rank") as HTMLInputElement;
    expect(rankInput).toHaveAttribute("type", "number");
    const activeInput = screen.getByLabelText("Active") as HTMLInputElement;
    expect(activeInput).toHaveAttribute("type", "checkbox");

    fireEvent.change(rankInput, { target: { value: "3" } });
    fireEvent.click(activeInput);
    fireEvent.submit(screen.getByTestId("create-node-form"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/nodes",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"rank":3'),
        })
      )
    );
    // .filter(...).pop() rather than .find(...) -- apiFetch's call history isn't cleared
    // between tests in this file, so .find() could match a stale call from an earlier test.
    const body = JSON.parse(
      (apiFetch as any).mock.calls
        .filter((c: any[]) => c[0] === "/api/graph/domain/nodes" && c[1]?.method === "POST")
        .pop()[1].body
    );
    expect(body.attributes).toEqual({ rank: 3, active: true });
  });

  it("hides a create-node attribute definition whose code collides with a built-in field, with a note (M-9)", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [],
          edges: [],
          entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
          relationship_types: [],
          hierarchies: [],
          attribute_definitions: [
            { id: "a1", entity_type_id: "t1", code: "rank", name: "Rank", data_type: "number" },
            { id: "a2", entity_type_id: "t1", code: "status", name: "Shadow Status", data_type: "string" },
          ],
        });
      }
      if (path === "/api/graph/domain/nodes" && options?.method === "POST") {
        return Promise.resolve({ id: "e1", type: "employee", label: "New Person", parent: null, attributes: {} });
      }
      return Promise.resolve({});
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("toggle-create-node"));
    await waitFor(() => expect(screen.getByTestId("create-node-form")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "t1" } });

    expect(screen.getByLabelText("Rank")).toBeInTheDocument();
    expect(screen.queryByLabelText("Shadow Status")).not.toBeInTheDocument();
    expect(screen.getByText("attribute status hidden: collides with a built-in field")).toBeInTheDocument();
  });

  it("shows the Parent dropdown with '(root)' first and a hint, listing all nodes", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [
        { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
        { id: "e2", type: "employee", label: "Sara", parent: null, attributes: {} },
      ],
      edges: [],
      entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
      relationship_types: [],
      hierarchies: [{ id: "h1", code: "org-chart", name: "Org Chart" }],
      attribute_definitions: [],
    });

    renderWithProviders({ hierarchyId: "h1" });
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("toggle-create-node"));
    await waitFor(() => expect(screen.getByTestId("create-node-form")).toBeInTheDocument());

    const parentSelect = screen.getByLabelText(/^Parent/) as HTMLSelectElement;
    const optionLabels = Array.from(parentSelect.options).map((o) => o.textContent);
    expect(optionLabels[0]).toBe("(root)");
    expect(optionLabels).toEqual(expect.arrayContaining(["Ahmed", "Sara"]));
    expect(screen.getByText(/any node placed in this hierarchy will be used/i)).toBeInTheDocument();
  });

  it("matches attributes.code (not just label) when filtering by search", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [
        { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: { code: "nurse-74yg" } },
        { id: "e2", type: "employee", label: "Sara", parent: null, attributes: { code: "other-code" } },
      ],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders({ filter: { selectedTypes: null, search: "nurse-74yg", highlightIds: null } });
    await waitFor(() => expect(mockCytoscapeInstance.nodes).toHaveBeenCalled());

    const e1 = mockCytoscapeInstance.getElementById("e1");
    const e2 = mockCytoscapeInstance.getElementById("e2");
    await waitFor(() => expect(e1.style("display")).toBe("element"));
    expect(e2.style("display")).toBe("none");
  });

  it("calls the latest onSelectionChange after a rerender, not the one captured when the cytoscape instance was created", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [{ id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} }],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    const queryClient = new QueryClient();
    const firstOnSelectionChange = vi.fn();
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <GraphEditor
          organizationId="org-1"
          hierarchyId={null}
          onHierarchyChange={vi.fn()}
          onSelectionChange={firstOnSelectionChange}
        />
      </QueryClientProvider>
    );
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    // The cytoscape instance (and its tap handlers) is created once on mount; rerender with a
    // brand new onSelectionChange callback -- the mount effect does NOT rerun (deps are `[]`), so
    // this only passes if the handlers read the callback through a ref instead of a stale closure.
    const secondOnSelectionChange = vi.fn();
    rerender(
      <QueryClientProvider client={queryClient}>
        <GraphEditor
          organizationId="org-1"
          hierarchyId={null}
          onHierarchyChange={vi.fn()}
          onSelectionChange={secondOnSelectionChange}
        />
      </QueryClientProvider>
    );

    const tapNodeHandler = registeredHandlersRef.current["tap:node"];
    act(() => tapNodeHandler({ target: { id: () => "e1" } }));

    expect(secondOnSelectionChange).toHaveBeenCalledWith({ kind: "node", id: "e1" });
    expect(firstOnSelectionChange).not.toHaveBeenCalled();
  });

  it("passes ELK options that request hierarchy-safe layout to cy.layout", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [{ id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} }],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders();

    await waitFor(() => expect(mockCytoscapeInstance.layout).toHaveBeenCalled());
    const options = mockCytoscapeInstance.layout.mock.calls[0][0];
    expect(options.name).toBe("elk");
    expect(options.elk["elk.hierarchyHandling"]).toBe("INCLUDE_CHILDREN");
  });

  it("toggles edgehandles draw mode and autoungrabify when the Connect button is clicked", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscapeInstance.edgehandles).toHaveBeenCalled());
    const eh = mockCytoscapeInstance.edgehandles.mock.results[0].value;

    const button = screen.getByTestId("toggle-connect");
    expect(button).toHaveTextContent("Connect");

    fireEvent.click(button);
    expect(eh.enableDrawMode).toHaveBeenCalled();
    expect(mockCytoscapeInstance.autoungrabify).toHaveBeenCalledWith(true);
    expect(button).toHaveTextContent("Connecting: drag from one node to another");

    fireEvent.click(button);
    expect(eh.disableDrawMode).toHaveBeenCalled();
    expect(mockCytoscapeInstance.autoungrabify).toHaveBeenCalledWith(false);
    expect(button).toHaveTextContent("Connect");
  });

  it("applies data changes incrementally without recreating the cytoscape instance", async () => {
    let graphCallCount = 0;
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/graph/domain?")) {
        graphCallCount += 1;
        const nodes =
          graphCallCount === 1
            ? [{ id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} }]
            : [
                { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
                { id: "e2", type: "employee", label: "Sara", parent: null, attributes: {} },
              ];
        return Promise.resolve({
          nodes,
          edges: [],
          entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
          relationship_types: [],
          hierarchies: [],
          attribute_definitions: [],
        });
      }
      if (path === "/api/graph/domain/nodes" && options?.method === "POST") {
        return Promise.resolve({ id: "e2", type: "employee", label: "Sara", parent: null, attributes: {} });
      }
      return Promise.resolve({});
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscapeInstance.add).toHaveBeenCalled());
    expect(mockCytoscape).toHaveBeenCalledTimes(1);

    mockCytoscapeInstance.add.mockClear();

    fireEvent.click(screen.getByTestId("toggle-create-node"));
    await waitFor(() => expect(screen.getByTestId("create-node-form")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "t1" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Sara" } });
    fireEvent.submit(screen.getByTestId("create-node-form"));

    await waitFor(() => expect(mockCytoscapeInstance.add).toHaveBeenCalled());
    const addedElements = mockCytoscapeInstance.add.mock.calls.flatMap((call: any[]) => call[0]);
    expect(addedElements.some((el: any) => el.data.id === "e2")).toBe(true);
    expect(mockCytoscapeInstance.remove).not.toHaveBeenCalled();
    expect(mockCytoscape).toHaveBeenCalledTimes(1);
  });

  it("shows a dismissible error banner when the API rejects a new edge", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [
            { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
            { id: "e2", type: "unit", label: "Unit A", parent: null, attributes: {} },
          ],
          edges: [],
          entity_types: [],
          relationship_types: [
            {
              id: "rt1",
              code: "works_for",
              name: "Works For",
              is_directed: true,
              source_entity_type: "employee",
              target_entity_type: "unit",
            },
          ],
          hierarchies: [],
          attribute_definitions: [],
        });
      }
      if (path === "/api/graph/domain/edges" && options?.method === "POST") {
        return Promise.reject(new ApiError(409, JSON.stringify({ detail: "this relationship already exists" })));
      }
      return Promise.resolve({});
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const ehcompleteHandler = registeredHandlersRef.current["ehcomplete"];
    act(() => ehcompleteHandler(null, { id: () => "e1" }, { id: () => "e2" }));

    await waitFor(() => expect(screen.getByTestId("edge-type-picker")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Works For (works_for)"));

    await waitFor(() =>
      expect(screen.getByTestId("graph-error")).toHaveTextContent("this relationship already exists")
    );

    fireEvent.click(screen.getByLabelText("Dismiss error"));
    expect(screen.queryByTestId("graph-error")).not.toBeInTheDocument();
  });

  it("shows an explanatory message in the picker when no relationship type is valid for the dragged pair", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [
        { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
        { id: "e2", type: "unit", label: "Unit A", parent: null, attributes: {} },
      ],
      edges: [],
      entity_types: [
        { id: "t1", code: "employee", name: "Employee", is_abstract: false },
        { id: "t2", code: "unit", name: "Unit", is_abstract: false },
      ],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const ehcompleteHandler = registeredHandlersRef.current["ehcomplete"];
    act(() => ehcompleteHandler(null, { id: () => "e1" }, { id: () => "e2" }));

    await waitFor(() => expect(screen.getByTestId("edge-type-picker")).toBeInTheDocument());
    expect(screen.getByText("No relationship type allows Employee → Unit")).toBeInTheDocument();
  });

  it("shows Layout failed in the error banner when the layout run rejects instead of throwing", async () => {
    mockCytoscapeInstance.layout.mockReturnValueOnce({
      run: vi.fn(() => Promise.reject(new Error("elk exploded"))),
      on: vi.fn(),
      // promiseOn intentionally absent -- production code must guard with optional chaining
    });
    (apiFetch as any).mockResolvedValue({
      nodes: [{ id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} }],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders();

    await waitFor(() => expect(screen.getByTestId("graph-error")).toHaveTextContent("Layout failed"));
  });

  it("clears the canvas when the graph query errors, so stale nodes from a previous query aren't left drawn (I-2/M-5)", async () => {
    (apiFetch as any).mockResolvedValueOnce({
      nodes: [{ id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} }],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    // retry: false so the failed query settles into its error state
    // immediately instead of going through react-query's default retry/backoff.
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <GraphEditor organizationId="org-1" hierarchyId={null} onHierarchyChange={vi.fn()} />
      </QueryClientProvider>
    );

    await waitFor(() => expect(mockCytoscapeInstance.add).toHaveBeenCalled());
    expect(elementStore.has("e1")).toBe(true);

    (apiFetch as any).mockRejectedValue(new Error("network down"));
    // A hierarchy switch changes the query key, forcing a refetch that now rejects.
    rerender(
      <QueryClientProvider client={queryClient}>
        <GraphEditor organizationId="org-1" hierarchyId="h1" onHierarchyChange={vi.fn()} />
      </QueryClientProvider>
    );

    await waitFor(() => expect(screen.getByText("Failed to load graph")).toBeInTheDocument());
    expect(mockCytoscapeInstance.remove).not.toHaveBeenCalled(); // elements() batch-removed, not per-id remove
    expect(elementStore.size).toBe(0);
  });

  it("gives every toolbar control an accessible name and a title, and renders a help line that changes with Connect (F-2)", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const controls = [
      screen.getByTestId("hierarchy-select"),
      screen.getByText("Layout"),
      screen.getByText("Fit"),
      screen.getByTestId("toggle-connect"),
      screen.getByTestId("toggle-create-node"),
    ];
    for (const control of controls) {
      const accessibleName = control.getAttribute("aria-label") ?? control.textContent;
      expect(accessibleName).toBeTruthy();
      expect(control).toHaveAttribute("title");
    }

    const help = screen.getByTestId("graph-help");
    const helpTextBefore = help.textContent;
    expect(helpTextBefore).toBeTruthy();

    fireEvent.click(screen.getByTestId("toggle-connect"));
    expect(help.textContent).not.toBe(helpTextBefore);
    expect(help.textContent).toMatch(/drag/i);
  });

  it("gives node labels their own colour (distinct from the node background) and a text outline (F-3)", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const styleArg = mockCytoscape.mock.calls[0][0].style;
    const nodeStyle = styleArg.find((rule: any) => rule.selector === "node").style;
    expect(nodeStyle.color).toBeTruthy();
    expect(nodeStyle.color).not.toBe(nodeStyle["background-color"]);
    expect(nodeStyle["text-outline-width"]).toBeGreaterThan(0);
    expect(nodeStyle["text-outline-color"]).toBeTruthy();
  });

  it("sizes the canvas container with something other than a fixed 600px (F-4)", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders();
    const container = await screen.findByTestId("cytoscape-container");

    expect(container.getAttribute("style") ?? "").not.toContain("600px");
    expect(container.className).toMatch(/h-\[calc\(/);
  });

  it("shows an empty-state overlay with a 'Create the first node' button when the graph has no nodes", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [],
      edges: [],
      entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const emptyState = await screen.findByTestId("graph-empty-state");
    const createButton = within(emptyState).getByRole("button", { name: /create the first node/i });

    fireEvent.click(createButton);
    await waitFor(() => expect(screen.getByTestId("create-node-form")).toBeInTheDocument());
  });

  it("does not show the empty-state overlay once the graph has nodes", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [{ id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} }],
      edges: [],
      entity_types: [],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscapeInstance.add).toHaveBeenCalled());

    expect(screen.queryByTestId("graph-empty-state")).not.toBeInTheDocument();
  });

  it("closes the create-node form on Escape and returns focus to the '+ New Node' trigger (H-7)", async () => {
    (apiFetch as any).mockResolvedValue({
      nodes: [],
      edges: [],
      entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const toggle = screen.getByTestId("toggle-create-node");
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByTestId("create-node-form")).toBeInTheDocument());
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(screen.getByTestId("create-node-form"), { key: "Escape" });

    expect(screen.queryByTestId("create-node-form")).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(document.activeElement).toBe(toggle);
  });

  it("shows a Retry button next to a failed graph load that re-issues the request (D-4)", async () => {
    let graphCallCount = 0;
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/graph/domain?")) {
        graphCallCount += 1;
        return Promise.reject(new Error("network down"));
      }
      return Promise.resolve({});
    });

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <GraphEditor organizationId="org-1" hierarchyId={null} onHierarchyChange={vi.fn()} />
      </QueryClientProvider>
    );

    const retryButton = await screen.findByText("Retry");
    expect(screen.getByText("Failed to load graph")).toBeInTheDocument();
    expect(graphCallCount).toBe(1);

    fireEvent.click(retryButton);

    await waitFor(() => expect(graphCallCount).toBe(2));
  });
});

describe("applyGraphToCy", () => {
  beforeEach(() => {
    elementStore.clear();
    mockCytoscapeInstance.add.mockClear();
    mockCytoscapeInstance.remove.mockClear();
  });

  const baseGraph = (): any => ({
    nodes: [{ id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} }],
    edges: [],
    entity_types: [],
    relationship_types: [],
    hierarchies: [],
    attribute_definitions: [],
  });

  it("returns structureChanged: false when only a label changed", () => {
    const graphA = baseGraph();
    applyGraphToCy(mockCytoscapeInstance, graphA);

    const graphB = { ...graphA, nodes: [{ ...graphA.nodes[0], label: "Ahmed M." }] };
    const result = applyGraphToCy(mockCytoscapeInstance, graphB);

    expect(result.structureChanged).toBe(false);
    expect(mockCytoscapeInstance.getElementById("e1").data("label")).toBe("Ahmed M.");
  });

  it("returns structureChanged: true when a node is added", () => {
    const graphA = baseGraph();
    applyGraphToCy(mockCytoscapeInstance, graphA);

    const graphB = {
      ...graphA,
      nodes: [...graphA.nodes, { id: "e2", type: "employee", label: "Sara", parent: null, attributes: {} }],
    };
    const result = applyGraphToCy(mockCytoscapeInstance, graphB);

    expect(result.structureChanged).toBe(true);
  });

  it("returns structureChanged: true when a node's parent changes", () => {
    const graphA = {
      ...baseGraph(),
      nodes: [
        { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
        { id: "e2", type: "employee", label: "Sara", parent: null, attributes: {} },
      ],
    };
    applyGraphToCy(mockCytoscapeInstance, graphA);

    const graphB = { ...graphA, nodes: [graphA.nodes[0], { ...graphA.nodes[1], parent: "e1" }] };
    const result = applyGraphToCy(mockCytoscapeInstance, graphB);

    expect(result.structureChanged).toBe(true);
  });

  it("returns structureChanged: false when only an edge is added", () => {
    const graphA = {
      ...baseGraph(),
      nodes: [
        { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
        { id: "e2", type: "employee", label: "Sara", parent: null, attributes: {} },
      ],
    };
    applyGraphToCy(mockCytoscapeInstance, graphA);

    const graphB = {
      ...graphA,
      edges: [{ id: "r1", source: "e1", target: "e2", type: "manages", label: "Manages", attributes: {} }],
    };
    const result = applyGraphToCy(mockCytoscapeInstance, graphB);

    expect(result.structureChanged).toBe(false);
  });

  it("gives every newly-added node its own position object, even though their coordinates are equal (M-2)", () => {
    const graphA = {
      ...baseGraph(),
      nodes: [
        { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
        { id: "e2", type: "employee", label: "Sara", parent: null, attributes: {} },
        { id: "e3", type: "employee", label: "Lina", parent: null, attributes: {} },
      ],
    };

    applyGraphToCy(mockCytoscapeInstance, graphA);

    const addedElements = mockCytoscapeInstance.add.mock.calls.flatMap((call: any[]) => call[0]);
    const nodeElements = addedElements.filter((el: any) => !("source" in el.data));
    expect(nodeElements).toHaveLength(3);

    const positions = nodeElements.map((el: any) => el.position);
    // Same coordinates (all three are new, so all land at the viewport
    // centre)...
    expect(positions.every((p: any) => p.x === positions[0].x && p.y === positions[0].y)).toBe(true);
    // ...but distinct object references. Cytoscape stores `position` by
    // reference and mutates it in place during layout, so nodes sharing one
    // object would all end up wherever the layout wrote last, collapsing
    // the whole graph onto a single point -- reverting the per-node
    // `{ x: center.x, y: center.y }` object literal to a single shared
    // `center` object makes this assertion fail.
    expect(new Set(positions).size).toBe(positions.length);
  });

  it("does not throw and skips an edge whose source/target node is not among the kept-or-added nodes", () => {
    const graphA = baseGraph(); // just node e1
    applyGraphToCy(mockCytoscapeInstance, graphA);

    const graphWithDanglingEdge = {
      ...graphA,
      edges: [
        { id: "r-bad", source: "e1", target: "does-not-exist", type: "manages", label: "Manages", attributes: {} },
      ],
    };

    expect(() => applyGraphToCy(mockCytoscapeInstance, graphWithDanglingEdge)).not.toThrow();

    const addedElements = mockCytoscapeInstance.add.mock.calls.flatMap((call: any[]) => call[0]);
    expect(addedElements.some((el: any) => el.data.id === "r-bad")).toBe(false);
  });
});

describe("positionsAreDegenerate", () => {
  it("returns false for fewer than 2 positions", () => {
    expect(positionsAreDegenerate([])).toBe(false);
    expect(positionsAreDegenerate([{ x: 5, y: 5 }])).toBe(false);
  });

  it("returns false when positions are meaningfully spread out", () => {
    expect(
      positionsAreDegenerate([
        { x: 0, y: 0 },
        { x: 100, y: 0 },
        { x: 50, y: 80 },
      ])
    ).toBe(false);
  });

  it("returns true when every position is within 1px of every other (e.g. a layout that never moved anything)", () => {
    expect(
      positionsAreDegenerate([
        { x: 27, y: 13877 },
        { x: 27, y: 13877 },
        { x: 27.4, y: 13877.2 },
      ])
    ).toBe(true);
  });
});
