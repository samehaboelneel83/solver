import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphDemo from "./GraphDemo";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";

const { mockCytoscape, registeredHandlersRef } = vi.hoisted(() => {
  const handlersRef: { current: Record<string, (...args: any[]) => void> } = { current: {} };
  const instance: any = {
    layout: vi.fn(() => ({ run: vi.fn() })),
    fit: vi.fn(),
    destroy: vi.fn(),
    edgehandles: vi.fn(() => ({ destroy: vi.fn() })),
    on: vi.fn((event: string, selectorOrHandler: any, maybeHandler?: any) => {
      if (typeof selectorOrHandler === "function") {
        handlersRef.current[event] = selectorOrHandler;
      } else {
        handlersRef.current[`${event}:${selectorOrHandler}`] = maybeHandler;
      }
    }),
    nodes: vi.fn(() => ({ forEach: vi.fn(), map: vi.fn(() => []) })),
    edges: vi.fn(() => ({ forEach: vi.fn() })),
    elements: vi.fn(() => ({ removeClass: vi.fn(), remove: vi.fn() })),
    getElementById: vi.fn(() => ({ style: vi.fn(() => "element"), addClass: vi.fn(), removeClass: vi.fn(), length: 1 })),
    center: vi.fn(),
    add: vi.fn(),
    extent: vi.fn(() => ({ x1: 0, y1: 0, x2: 10, y2: 10 })),
  };
  const constructor: any = vi.fn(() => instance);
  constructor.use = vi.fn();
  return { mockCytoscape: constructor, registeredHandlersRef: handlersRef };
});

vi.mock("cytoscape", () => ({ default: mockCytoscape }));
vi.mock("cytoscape-elk", () => ({ default: {} }));
vi.mock("cytoscape-edgehandles", () => ({ default: {} }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const GRAPH = {
  nodes: [
    { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
    { id: "2", type: "employee", label: "ahmed", parent: "1", attributes: { grade: 3 } },
    { id: "3", type: "employee", label: "sara", parent: "1", attributes: { grade: 4 } },
  ],
  edges: [],
  entity_types: [
    { id: "1", code: "employee", name: "employee", is_abstract: false },
    { id: "2", code: "unit", name: "unit", is_abstract: false },
  ],
  relationship_types: [],
  hierarchies: [{ id: "5", code: "reports_to", name: "reports_to" }],
  attribute_definitions: [],
};

const ENTITY_TYPES = {
  items: [
    {
      id: 1,
      domain_id: 1,
      name: "employee",
      role: "agent",
      attributes: [
        { id: 13, entity_type_id: 1, name: "grade", data_type: "integer", required: false, unit: null, enum_values: null, default_value: null },
      ],
    },
    { id: 2, domain_id: 1, name: "unit", role: "org", attributes: [] },
  ],
  total: 2,
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

const ENTITIES: Record<string, unknown> = {
  "2": { id: 2, entity_type_id: 1, key: "ahmed", label: "Ahmed Z", sort_order: 0, active: true, attrs: { grade: 3 } },
  "3": { id: 3, entity_type_id: 1, key: "sara", label: "Sara Q", sort_order: 0, active: true, attrs: { grade: 4 } },
};

function stubApi() {
  (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
    if (options?.method && options.method !== "GET") return Promise.resolve({});
    if (path.startsWith("/api/v1/graph")) return Promise.resolve(GRAPH);
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve(ENTITY_TYPES);
    if (path.startsWith("/api/v1/relationship-types")) return Promise.resolve(HIERARCHY_TYPES);
    if (path.startsWith("/api/v1/entities/")) {
      return Promise.resolve(ENTITIES[path.split("/").pop() as string] ?? {});
    }
    return Promise.resolve({});
  });
}

function graphCalls(): string[] {
  return (apiFetch as any).mock.calls
    .map((call: any[]) => String(call[0]))
    .filter((path: string) => path.startsWith("/api/v1/graph"));
}

function renderWithProviders(initialEntries: string[] = ["/graph"]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <GraphDemo />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("GraphDemo", () => {
  beforeEach(() => {
    mockCytoscape.mockClear();
    registeredHandlersRef.current = {};
    localStorage.setItem(DOMAIN_STORAGE_KEY, "1");
    (apiFetch as any).mockReset();
    stubApi();
  });

  it("asks for the selected domain's graph and renders the canvas, filter bar and property panel", async () => {
    renderWithProviders();

    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());
    expect(graphCalls()).toContain("/api/v1/graph?domain_id=1");
    expect(mockCytoscape).toHaveBeenCalled();
    expect(screen.getByText(/select a node or edge/i)).toBeInTheDocument();
  });

  it("points at the domain selector instead of drawing an empty canvas when no domain is chosen", async () => {
    localStorage.removeItem(DOMAIN_STORAGE_KEY);
    renderWithProviders();

    expect(await screen.findByText(/choose a domain/i)).toBeInTheDocument();
    expect(graphCalls()).toHaveLength(0);
  });

  it("shows the newly-selected node's own values, not the previously-selected node's stale values", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    const tapNode = registeredHandlersRef.current["tap:node"];

    tapNode({ target: { id: () => "2" } });
    await waitFor(() => expect(screen.getByLabelText(/^Label/)).toHaveValue("Ahmed Z"));
    expect(screen.getByTestId("attr-grade")).toHaveValue("3");

    tapNode({ target: { id: () => "3" } });
    await waitFor(() => expect(screen.getByLabelText(/^Label/)).toHaveValue("Sara Q"));
    expect(screen.getByTestId("attr-grade")).toHaveValue("4");
  });

  it("selects the first node whose label matches when Enter is pressed in the search box (H-1 fix round 1)", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "sara" } });
    fireEvent.keyDown(screen.getByTestId("filter-search"), { key: "Enter" });

    await waitFor(() => expect(screen.getByLabelText(/^Label/)).toHaveValue("Sara Q"));
  });

  it("leaves the selection untouched when the search matches nothing", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "nobody" } });
    fireEvent.keyDown(screen.getByTestId("filter-search"), { key: "Enter" });

    await waitFor(() => expect(screen.getByText(/select a node or edge/i)).toBeInTheDocument());
  });

  it("re-reads the graph with the chosen hierarchy type and keeps the filter text across the switch", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "sara" } });

    const select = screen.getByTestId("hierarchy-select");
    await waitFor(() => expect(select).toHaveTextContent("reports_to"));
    fireEvent.change(select, { target: { value: "5" } });

    await waitFor(() => expect(graphCalls()).toContain("/api/v1/graph?domain_id=1&hierarchy_type_id=5"));
    // The search text lives in GraphDemo, so it survives FilterBar being
    // unmounted and remounted while the re-keyed graph query is in flight.
    await waitFor(() => expect(screen.getByTestId("filter-search")).toHaveValue("sara"));
  });

  it("stacks the canvas and property panel in a column below lg:, and shares a row at lg: and up (F-1)", async () => {
    renderWithProviders();
    const layout = await screen.findByTestId("graph-layout");
    expect(layout.className).toContain("flex-col");
    expect(layout.className).toContain("lg:flex-row");
  });

  describe("deep-linked focus (B-3)", () => {
    it("selects the node named by ?focus=, then clears it from the URL", async () => {
      renderWithProviders(["/graph?focus=3"]);

      await waitFor(() => expect(screen.getByLabelText(/^Label/)).toHaveValue("Sara Q"));
    });

    it("switches to the domain named by ?domain= before resolving the focus", async () => {
      // The v1 successor of v0's `&org=`: an entity page links here with its
      // own domain, which may not be the one currently selected. Without the
      // switch, the focused node is looked for in the wrong domain's graph and
      // the link silently does nothing.
      renderWithProviders(["/graph?domain=2&focus=3"]);

      await waitFor(() => expect(graphCalls()).toContain("/api/v1/graph?domain_id=2"));
      expect(graphCalls()).not.toContain("/api/v1/graph?domain_id=1");
      expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("2");
      await waitFor(() => expect(screen.getByLabelText(/^Label/)).toHaveValue("Sara Q"));
    });

    it("ignores a ?domain= that is not a positive integer", async () => {
      renderWithProviders(["/graph?domain=abc"]);

      await waitFor(() => expect(graphCalls()).toContain("/api/v1/graph?domain_id=1"));
      expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("1");
    });

    it("leaves the selection alone when the focused node is not in this domain's graph", async () => {
      renderWithProviders(["/graph?focus=999"]);

      await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());
      expect(screen.getByText(/select a node or edge/i)).toBeInTheDocument();
    });
  });
});
