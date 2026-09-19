import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphDemo from "./GraphDemo";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";
import { GRAPH_MODE_STORAGE_KEY } from "../hooks/useGraphMode";

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
    { id: "1", code: "employee", name: "employee", is_abstract: false, colour: "#1f77b4" },
    { id: "2", code: "unit", name: "unit", is_abstract: false, colour: null },
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
      colour: "#1f77b4",
      attributes: [
        { id: 13, entity_type_id: 1, name: "grade", data_type: "integer", required: false, unit: null, enum_values: null, default_value: null },
      ],
    },
    { id: 2, domain_id: 1, name: "unit", role: "org", colour: null, attributes: [] },
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
      colour: null,
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
    // The LIST route and the single-row route are different answers; a stub
    // that returned the list for both would let a panel reading `.name` off
    // a page object look like it worked.
    const singleType = /^\/api\/v1\/entity-types\/(\d+)$/.exec(path);
    if (singleType) {
      return Promise.resolve(
        ENTITY_TYPES.items.find((item) => String(item.id) === singleType[1]) ?? {}
      );
    }
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve(ENTITY_TYPES);
    const singleRelType = /^\/api\/v1\/relationship-types\/(\d+)$/.exec(path);
    if (singleRelType) {
      return Promise.resolve(
        HIERARCHY_TYPES.items.find((item) => String(item.id) === singleRelType[1]) ?? {}
      );
    }
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
    localStorage.removeItem(GRAPH_MODE_STORAGE_KEY);
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

// --- Task 14b: the types/objects toggle, its URL and its persistence -----

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderAt(initialEntries: string[] = ["/graph"]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <GraphDemo />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("GraphDemo view mode", () => {
  beforeEach(() => {
    mockCytoscape.mockClear();
    registeredHandlersRef.current = {};
    localStorage.clear();
    localStorage.setItem(DOMAIN_STORAGE_KEY, "1");
    (apiFetch as any).mockReset();
    stubApi();
  });

  it("opens in the objects view and leaves the URL alone", async () => {
    renderAt();
    await waitFor(() => expect(screen.getByTestId("graph-mode-objects")).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByTestId("location")).toHaveTextContent("/graph");
    expect(screen.getByTestId("location").textContent).not.toContain("mode=");
    expect(graphCalls().length).toBeGreaterThan(0);
  });

  it("puts the view in the URL when it is switched, so it can be linked", async () => {
    renderAt();
    await waitFor(() => expect(screen.getByTestId("graph-mode-types")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("graph-mode-types"));

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/graph?mode=types"));
    expect(screen.getByTestId("graph-mode-types")).toHaveAttribute("aria-pressed", "true");
    // `objects` is the default and leaves no parameter, so every existing
    // link keeps working.
    fireEvent.click(screen.getByTestId("graph-mode-objects"));
    await waitFor(() => expect(screen.getByTestId("location").textContent).not.toContain("mode="));
  });

  it("honours ?mode=types on arrival and stops asking for the objects graph", async () => {
    renderAt(["/graph?mode=types"]);
    await waitFor(() => expect(screen.getByTestId("graph-mode-types")).toHaveAttribute("aria-pressed", "true"));
    // The types view is built from the two type lists, not from /api/v1/graph.
    expect(graphCalls()).toHaveLength(0);
    const typeCalls = (apiFetch as any).mock.calls
      .map((call: any[]) => String(call[0]))
      .filter((path: string) => path.startsWith("/api/v1/entity-types"));
    expect(typeCalls.length).toBeGreaterThan(0);
  });

  it("ignores a mode it does not recognise rather than drawing nothing", async () => {
    renderAt(["/graph?mode=schema"]);
    await waitFor(() => expect(screen.getByTestId("graph-mode-objects")).toHaveAttribute("aria-pressed", "true"));
  });

  it("remembers the view across a reload", async () => {
    // A real reload: nothing but localStorage survives it, and this render
    // has no `?mode=` to fall back on.
    const first = renderAt();
    await waitFor(() => expect(screen.getByTestId("graph-mode-types")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("graph-mode-types"));
    await waitFor(() => expect(localStorage.getItem(GRAPH_MODE_STORAGE_KEY)).toBe("types"));
    first.unmount();

    renderAt();
    await waitFor(() => expect(screen.getByTestId("graph-mode-types")).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByTestId("location")).toHaveTextContent("/graph?mode=types");
  });

  it("a link's ?mode= wins over the stored choice, and is then stored", async () => {
    localStorage.setItem(GRAPH_MODE_STORAGE_KEY, "objects");
    renderAt(["/graph?mode=types"]);
    await waitFor(() => expect(screen.getByTestId("graph-mode-types")).toHaveAttribute("aria-pressed", "true"));
    await waitFor(() => expect(localStorage.getItem(GRAPH_MODE_STORAGE_KEY)).toBe("types"));
  });

  it("a ?focus= deep link lands in the objects view even if types was stored (Ruling 31)", async () => {
    localStorage.setItem(GRAPH_MODE_STORAGE_KEY, "types");
    renderAt(["/graph?focus=2"]);

    await waitFor(() => expect(screen.getByTestId("graph-mode-objects")).toHaveAttribute("aria-pressed", "true"));
    // The link still does what Ruling 31 restored: one graph request, the
    // focused entity selected, and the parameter consumed.
    expect(graphCalls()).toContain("/api/v1/graph?domain_id=1");
    await waitFor(() => expect(screen.getByLabelText(/^Label/)).toHaveValue("Ahmed Z"));
    await waitFor(() => expect(screen.getByTestId("location").textContent).not.toContain("focus="));
  });

  it("a ?focus= link beats an explicit ?mode=types, because what it focuses is an entity", async () => {
    renderAt(["/graph?focus=2&mode=types"]);
    await waitFor(() => expect(screen.getByTestId("graph-mode-objects")).toHaveAttribute("aria-pressed", "true"));
    await waitFor(() => expect(screen.getByLabelText(/^Label/)).toHaveValue("Ahmed Z"));
  });

  it("still consumes ?domain= alongside the view (Ruling 31)", async () => {
    renderAt(["/graph?domain=2&mode=types"]);
    await waitFor(() => expect(screen.getByTestId("graph-mode-types")).toHaveAttribute("aria-pressed", "true"));
    await waitFor(() => expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("2"));
    await waitFor(() => expect(screen.getByTestId("location").textContent).not.toContain("domain="));
    expect(screen.getByTestId("location")).toHaveTextContent("mode=types");
  });

  it("filters by ROLE in the types view and by entity type in the objects view", async () => {
    renderAt();
    await waitFor(() => expect(screen.getByTestId("filter-types-toggle")).toHaveTextContent("Types: 2 of 2"));

    fireEvent.click(screen.getByTestId("graph-mode-types"));
    // The fixture's two entity types have different roles (agent, org), so
    // the count is the same but the noun -- and what a checkbox means --
    // is not.
    await waitFor(() => expect(screen.getByTestId("filter-types-toggle")).toHaveTextContent("Roles: 2 of 2"));
    fireEvent.click(screen.getByTestId("filter-types-toggle"));
    expect(screen.getByTestId("filter-type-agent")).toBeInTheDocument();
    expect(screen.getByTestId("filter-type-org")).toBeInTheDocument();
    expect(screen.queryByTestId("filter-type-employee")).not.toBeInTheDocument();
  });

  it("opens the entity type's panel when a types node is tapped", async () => {
    renderAt(["/graph?mode=types"]);
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    registeredHandlersRef.current["tap:node"]({ target: { id: () => "type-1" } });
    expect(await screen.findByTestId("entity-type-panel")).toHaveTextContent("employee");
  });
});

// --- Task 14c: the expression filter, end to end through the page --------

describe("GraphDemo expression filter", () => {
  beforeEach(() => {
    mockCytoscape.mockClear();
    registeredHandlersRef.current = {};
    localStorage.setItem(DOMAIN_STORAGE_KEY, "1");
    localStorage.removeItem(GRAPH_MODE_STORAGE_KEY);
    (apiFetch as any).mockReset();
    stubApi();
  });

  const GRADE = "attr:1:grade";

  async function openBuilder() {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("filter-expression-toggle")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("filter-expression-toggle"));
    // The builder is code-split, so it arrives a tick after the panel opens.
    fireEvent.click(await screen.findByTestId("expression-add-rule"));
    await waitFor(() => expect(screen.getAllByTestId("expression-field")).toHaveLength(1));
  }

  /** Sets the one rule on screen to `grade <op> <value>`. */
  function setRule(operator: string, value: string) {
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: GRADE } });
    fireEvent.change(screen.getAllByTestId("expression-operator")[0], { target: { value: operator } });
    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value } });
  }

  it("offers the builder in the objects view and not in the types view", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("filter-expression-toggle")).toBeInTheDocument());
    cleanup();

    renderWithProviders(["/graph?mode=types"]);
    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());
    expect(screen.queryByTestId("filter-expression-toggle")).not.toBeInTheDocument();
  });

  it("builds the field list from the domain's attribute definitions", async () => {
    await openBuilder();
    const options = Array.from(screen.getAllByTestId("expression-field")[0].querySelectorAll("option")).map(
      (o) => o.getAttribute("value")
    );
    expect(options).toContain(GRADE);
  });

  it("filters the canvas by the expression and announces how many nodes are left", async () => {
    await openBuilder();
    setRule(">", "3");
    // Of hq (a unit), ahmed (grade 3) and sara (grade 4), only sara matches.
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("1 of 3"));
  });

  it("filters nothing and says what is wrong when the expression is invalid", async () => {
    await openBuilder();
    setRule(">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("1 of 3"));

    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value: "abc" } });

    expect(screen.getByTestId("expression-problems")).toHaveTextContent(/whole number/i);
    await waitFor(() => expect(screen.getByTestId("graph-live")).not.toHaveTextContent(/of 3/));
  });

  it("stops filtering when the last condition is removed, not only when there is no document", async () => {
    // Removing the rule leaves a document that is present but EMPTY. A
    // consumer that only checked for null would go on filtering by it.
    await openBuilder();
    setRule(">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("1 of 3"));

    fireEvent.click(screen.getAllByTestId("expression-remove-rule")[0]);

    await waitFor(() => expect(screen.getByTestId("graph-live")).not.toHaveTextContent(/of 3/));
    expect(screen.getByTestId("filter-expression-toggle")).toHaveTextContent(/no conditions/i);
  });

  it("ANDs the expression with the entity-type checkboxes", async () => {
    await openBuilder();
    setRule(">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("1 of 3"));

    fireEvent.click(screen.getByTestId("filter-types-toggle"));
    fireEvent.click(screen.getByTestId("filter-type-employee"));

    // sara is an employee; with employees hidden nothing is left, and the
    // count changes only if both filters are being applied.
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("0 of 3"));
  });

  it("ANDs the expression with the search box", async () => {
    await openBuilder();
    setRule(">=", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("2 of 3"));

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "sara" } });
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("1 of 3"));
  });

  it("keeps Enter-to-select working while an expression is active", async () => {
    await openBuilder();
    setRule(">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("1 of 3"));

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "sara" } });
    fireEvent.keyDown(screen.getByTestId("filter-search"), { key: "Enter" });

    await waitFor(() => expect(screen.getByLabelText(/^Label/)).toHaveValue("Sara Q"));
  });

  it("drops the expression when the view is switched, so it cannot filter a canvas it was not written for", async () => {
    await openBuilder();
    setRule(">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("1 of 3"));

    fireEvent.click(screen.getByRole("button", { name: /^Types$/ }));

    await waitFor(() => expect(screen.queryByTestId("filter-expression-toggle")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^Objects$/ }));
    await waitFor(() => expect(screen.getByTestId("filter-expression-toggle")).toBeInTheDocument());
    expect(screen.getByTestId("filter-expression-toggle")).toHaveTextContent(/no conditions/i);
  });
});
