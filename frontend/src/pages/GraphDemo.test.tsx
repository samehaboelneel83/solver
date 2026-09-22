import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphDemo from "./GraphDemo";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";
import { GRAPH_MODE_STORAGE_KEY } from "../hooks/useGraphMode";
import { editorQueryClient } from "../test/me";

/**
 * The cytoscape double.
 *
 * It used to be a set of no-ops with `add: vi.fn()` (so nothing was ever
 * on the canvas) and `getElementById: () => ({ ..., length: 1 })` -- which
 * claimed every id existed, including ones this graph has never held. That
 * is the shape Ruling 39 was about: a double that cannot express the
 * library's constraint cannot fail on it, and here it made
 * "?focus=<something not in this graph>" indistinguishable from
 * "?focus=<a real node>" at the cytoscape boundary.
 *
 * It now keeps a real element store under the same four rules as
 * `GraphEditor.test.tsx`'s double -- one id space with first-writer-wins,
 * a throw for an edge with a missing endpoint, removal cascading from a
 * node to its edges, and `getElementById` returning a collection whose
 * `length` is 0 when nothing matches. Each is verified against
 * cytoscape@3.34.3; `GraphEditor.test.tsx` holds the tests that pin them,
 * and this file's fixtures are colliding so the constraint is live here
 * too.
 */
const { mockCytoscape, registeredHandlersRef, elementStore } = vi.hoisted(() => {
  const handlersRef: { current: Record<string, (...args: any[]) => void> } = { current: {} };
  type Entry = { data: Record<string, any>; isNode: boolean; styles: Record<string, any>; classes: Set<string> };
  const store = new Map<string, Entry>();

  const wrap = (id: string) => ({
    length: store.has(id) ? 1 : 0,
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
      if (entry) entry.data.parent = opts.parent ?? undefined;
    },
    style: (key: string, value?: any) => {
      const entry = store.get(id);
      if (!entry) return undefined;
      if (value === undefined) return entry.styles[key];
      entry.styles[key] = value;
      return undefined;
    },
    position: () => ({ x: 0, y: 0 }),
    addClass: (cls: string) => store.get(id)?.classes.add(cls),
    removeClass: (cls: string) => cls.split(" ").forEach((c) => store.get(id)?.classes.delete(c)),
  });

  function removeWithEdges(id: string) {
    const entry = store.get(id);
    if (!entry) return;
    store.delete(id);
    if (!entry.isNode) return;
    for (const [edgeId, edge] of [...store.entries()]) {
      if (!edge.isNode && (edge.data.source === id || edge.data.target === id)) store.delete(edgeId);
    }
  }

  const collection = (ids: string[]) => ({
    forEach: (fn: (ele: any) => void) => ids.forEach((id) => fn(wrap(id))),
    map: (fn: (ele: any) => any) => ids.map((id) => fn(wrap(id))),
    removeClass: (cls: string) => ids.forEach((id) => wrap(id).removeClass(cls)),
    remove: () => ids.forEach(removeWithEdges),
    length: ids.length,
  });

  const idsWhere = (isNode: boolean) =>
    [...store.entries()].filter(([, e]) => e.isNode === isNode).map(([id]) => id);

  const instance: any = {
    layout: vi.fn(() => ({ run: vi.fn(), on: vi.fn(), promiseOn: vi.fn(() => Promise.resolve()) })),
    fit: vi.fn(),
    destroy: vi.fn(),
    autoungrabify: vi.fn(),
    edgehandles: vi.fn(() => ({ destroy: vi.fn(), enableDrawMode: vi.fn(), disableDrawMode: vi.fn(), start: vi.fn() })),
    on: vi.fn((event: string, selectorOrHandler: any, maybeHandler?: any) => {
      if (typeof selectorOrHandler === "function") {
        handlersRef.current[event] = selectorOrHandler;
      } else {
        handlersRef.current[`${event}:${selectorOrHandler}`] = maybeHandler;
      }
    }),
    nodes: vi.fn(() => collection(idsWhere(true))),
    edges: vi.fn(() => collection(idsWhere(false))),
    elements: vi.fn(() => collection([...store.keys()])),
    getElementById: vi.fn((id: string) => wrap(id)),
    center: vi.fn(),
    add: vi.fn((elements: any[]) => {
      (elements ?? []).forEach((el: any) => {
        const isNode = !("source" in el.data);
        if (store.has(el.data.id)) return; // first writer wins, silently
        if (!isNode) {
          for (const end of ["source", "target"] as const) {
            const endId = el.data[end];
            if (!store.has(endId) || !store.get(endId)!.isNode) {
              throw new Error(
                `Can not create edge \`${el.data.id}\` with nonexistent ${end} \`${endId}\``
              );
            }
          }
        }
        store.set(el.data.id, { data: { ...el.data }, isNode, styles: {}, classes: new Set() });
      });
      return collection([]);
    }),
    remove: vi.fn((target: any) => {
      if (target && typeof target.id === "function") removeWithEdges(target.id());
    }),
    extent: vi.fn(() => ({ x1: 0, y1: 0, x2: 10, y2: 10 })),
  };
  const constructor: any = vi.fn(() => instance);
  constructor.use = vi.fn();
  return { mockCytoscape: constructor, registeredHandlersRef: handlersRef, elementStore: store };
});

vi.mock("cytoscape", () => ({ default: mockCytoscape }));
// Named rather than two indistinguishable `{}`s -- see GraphEditor.test.tsx.
vi.mock("cytoscape-elk", () => ({ default: { extension: "elk" } }));
vi.mock("cytoscape-edgehandles", () => ({ default: { extension: "edgehandles" } }));
// The ER layout drives real cytoscape (sizes, collections, a force layout)
// that this fake does not model; it has its own tests in lib/erLayout.
vi.mock("../lib/erLayout", () => ({ runErLayout: vi.fn(() => Promise.resolve()) }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../api/client";
// The two extension objects the mocks above hand to `cytoscape.use`.
// @ts-expect-error -- cytoscape-elk ships no bundled type declarations
import elkExtension from "cytoscape-elk";
// @ts-expect-error -- cytoscape-edgehandles ships no bundled type declarations
import edgehandlesExtension from "cytoscape-edgehandles";

const GRAPH = {
  nodes: [
    { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
    { id: "2", type: "employee", label: "ahmed", parent: "1", attributes: { grade: 3 } },
    { id: "3", type: "employee", label: "sara", parent: "1", attributes: { grade: 4 } },
  ],
  // `relationship.id = 1` and `entity.id = 1`: the collision Ruling 39 is
  // about, now in this page's fixture too. With an empty `edges` array the
  // page could not tell a graph that drew its edges from one that silently
  // dropped every one of them.
  edges: [{ id: "1", source: "1", target: "2", type: "reports_to", label: "reports_to", attributes: {} }],
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

/**
 * The API double. Both halves used to be unconditional: any unrecognised
 * GET resolved as `{}` and any write resolved as success, so all 31 tests
 * in this file had no way to fail on a request going to the wrong place.
 * Every other page test in the branch rejects an unknown path; this one
 * now does too, and a write has to be opted into per test.
 */
function stubApi(write?: (path: string, options: RequestInit) => unknown) {
  (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
    if (options?.method && options.method !== "GET") {
      if (!write) {
        return Promise.reject(
          new Error(`unexpected ${options.method} ${path} -- pass a write handler to stubApi`)
        );
      }
      return write(path, options) ?? Promise.reject(new Error(`unanswered ${options.method} ${path}`));
    }
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
      const entity = ENTITIES[path.split("/").pop() as string];
      return entity
        ? Promise.resolve(entity)
        : Promise.reject(new ApiError(404, JSON.stringify({ detail: "entity not found" })));
    }
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

function graphCalls(): string[] {
  return (apiFetch as any).mock.calls
    .map((call: any[]) => String(call[0]))
    .filter((path: string) => path.startsWith("/api/v1/graph"));
}

function renderWithProviders(initialEntries: string[] = ["/graph"]) {
  const queryClient = editorQueryClient();
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
    elementStore.clear();
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

  it("registers the layout and edge-handle extensions", () => {
    // Dropping either is invisible in the DOM: `elk` missing is "Layout
    // failed" in the browser, `edgehandles` missing is a Connect button
    // that does nothing.
    expect(mockCytoscape.use).toHaveBeenCalledWith(elkExtension);
    expect(mockCytoscape.use).toHaveBeenCalledWith(edgehandlesExtension);
  });

  it("actually draws the payload, edges included, onto the canvas", async () => {
    // The double keeps one id space now, so this can fail. The fixture's
    // edge id collides with a node id (Ruling 39): without the canvas-side
    // namespacing the edge is silently dropped and the store holds 3
    // elements instead of 4.
    renderWithProviders();
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
    await waitFor(() => {
      const nodes = [...elementStore.values()].filter((e) => e.isNode);
      const edges = [...elementStore.values()].filter((e) => !e.isNode);
      expect(nodes).toHaveLength(3);
      expect(edges).toHaveLength(1);
    });
  });

  it("answers getElementById for an id this graph does not hold with an empty collection", async () => {
    // The double used to hardcode `length: 1`, which is what made
    // "?focus=<not in this graph>" indistinguishable from a real node at
    // the cytoscape boundary.
    renderWithProviders();
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
    const instance = mockCytoscape.mock.results[0].value;
    expect(instance.getElementById("999").length).toBe(0);
    expect(instance.getElementById("1").length).toBe(1);
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
  const queryClient = editorQueryClient();
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
    elementStore.clear();
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

  it("puts the optimization view in the URL too, and asks for the domain's problems", async () => {
    renderAt();
    await waitFor(() => expect(screen.getByTestId("graph-mode-model")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("graph-mode-model"));

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/graph?mode=model"));
    expect(screen.getByTestId("graph-mode-model")).toHaveAttribute("aria-pressed", "true");
    // Which problem's model to draw comes from the domain's problems -- and
    // only once this view is showing.
    await waitFor(() =>
      expect(
        (apiFetch as any).mock.calls.some((call: any[]) => String(call[0]).startsWith("/api/problem/"))
      ).toBe(true)
    );
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
    elementStore.clear();
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
    // The builder is code-split, so it arrives a tick after the panel
    // opens -- a dynamic import, resolved by vite, not a microtask. On a
    // loaded machine that can take longer than testing-library's 1000 ms
    // default, which is what made this helper flake (once in eleven full
    // runs). `EntitiesExpression.test.tsx` already waits 3000 ms in four
    // places for the same boundary; match it rather than invent a number.
    fireEvent.click(await screen.findByTestId("expression-add-rule", undefined, { timeout: 3000 }));
    await waitFor(() => expect(screen.getAllByTestId("expression-field")).toHaveLength(1), {
      timeout: 3000,
    });
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

  it("filters nothing until a new condition is touched", async () => {
    // "+ Condition" creates a complete rule, so the canvas used to drop
    // from 23 nodes to 2 the moment the button was pressed. Nothing is
    // hidden and nothing is announced until one of the rule's controls is
    // changed.
    await openBuilder();
    await new Promise((resolve) => setTimeout(resolve, 100));
    const displays = [...elementStore.values()]
      .filter((e) => e.isNode)
      .map((e) => e.styles.display ?? "element");
    expect(displays).toEqual(["element", "element", "element"]);
    expect(screen.getByTestId("graph-live")).not.toHaveTextContent("of 3");
  });

  it("starts a new condition on a plain attribute, not on a generated call", async () => {
    // The graph's catalogue has no entity columns (graphFilter.ts), so the
    // default is the first plain attribute -- never `abs(...)`.
    await openBuilder();
    const value = (screen.getAllByTestId("expression-field")[0] as HTMLSelectElement).value;
    expect(value).toBe(GRADE);
    expect(value.startsWith("fn:")).toBe(false);
  });

  it("filters the canvas by the expression and announces how many nodes are left", async () => {
    await openBuilder();
    setRule(">", "3");
    // Of the two employees, only sara (grade 4) matches; hq is a unit, so
    // an employee rule leaves it drawn. Ahmed (grade 3) is the one hidden.
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("2 of 3"));
  });

  it("filters nothing and says what is wrong when the expression is invalid", async () => {
    await openBuilder();
    setRule(">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("2 of 3"));

    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value: "abc" } });

    expect(screen.getByTestId("expression-problems")).toHaveTextContent(/whole number/i);
    await waitFor(() => expect(screen.getByTestId("graph-live")).not.toHaveTextContent(/of 3/));
  });

  it("stops filtering when the last condition is removed, not only when there is no document", async () => {
    // Removing the rule leaves a document that is present but EMPTY. A
    // consumer that only checked for null would go on filtering by it.
    await openBuilder();
    setRule(">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("2 of 3"));

    fireEvent.click(screen.getAllByTestId("expression-remove-rule")[0]);

    await waitFor(() => expect(screen.getByTestId("graph-live")).not.toHaveTextContent(/of 3/));
    expect(screen.getByTestId("filter-expression-toggle")).toHaveTextContent(/no conditions/i);
  });

  it("ANDs the expression with the entity-type checkboxes", async () => {
    await openBuilder();
    setRule(">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("2 of 3"));

    fireEvent.click(screen.getByTestId("filter-types-toggle"));
    fireEvent.click(screen.getByTestId("filter-type-employee"));

    // sara is the matching employee; hiding employees leaves hq, and the
    // count changes only if both filters are being applied.
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("1 of 3"));
  });

  it("ANDs the expression with the search box", async () => {
    await openBuilder();
    setRule(">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("2 of 3"));

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "sara" } });
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("1 of 3"));
  });

  it("keeps Enter-to-select working while an expression is active", async () => {
    await openBuilder();
    setRule(">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("2 of 3"));

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "sara" } });
    fireEvent.keyDown(screen.getByTestId("filter-search"), { key: "Enter" });

    await waitFor(() => expect(screen.getByLabelText(/^Label/)).toHaveValue("Sara Q"));
  });

  it("drops the expression when the view is switched, so it cannot filter a canvas it was not written for", async () => {
    await openBuilder();
    setRule(">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("2 of 3"));

    fireEvent.click(screen.getByRole("button", { name: /^ERD View$/ }));

    await waitFor(() => expect(screen.queryByTestId("filter-expression-toggle")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^Graph View$/ }));
    await waitFor(() => expect(screen.getByTestId("filter-expression-toggle")).toBeInTheDocument());
    expect(screen.getByTestId("filter-expression-toggle")).toHaveTextContent(/no conditions/i);
  });
});

/**
 * The search box drops the canvas from 23 nodes to 1 while you type, with
 * nothing on screen saying so -- next to a condition filter that reports
 * exactly that ("Filter conditions: 2 of 23 nodes shown"). The one action
 * that answers "where is this person" silently destroyed the picture of
 * who they work with, and never said it had.
 */
describe("GraphDemo search announcement", () => {
  beforeEach(() => {
    mockCytoscape.mockClear();
    registeredHandlersRef.current = {};
    elementStore.clear();
    localStorage.setItem(DOMAIN_STORAGE_KEY, "1");
    localStorage.removeItem(GRAPH_MODE_STORAGE_KEY);
    (apiFetch as any).mockReset();
    stubApi();
  });

  const GRADE = "attr:1:grade";

  async function openBuilder() {
    await waitFor(() => expect(screen.getByTestId("filter-expression-toggle")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("filter-expression-toggle"));
    fireEvent.click(await screen.findByTestId("expression-add-rule", undefined, { timeout: 3000 }));
    await waitFor(() => expect(screen.getAllByTestId("expression-field")).toHaveLength(1), {
      timeout: 3000,
    });
  }

  it("says what the search hid, in the same words the condition filter uses", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());
    expect(screen.getByTestId("graph-live")).not.toHaveTextContent(/of 3/);

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "sara" } });

    await waitFor(() =>
      expect(screen.getByTestId("graph-live")).toHaveTextContent('Search "sara": 1 of 3 nodes shown')
    );
  });

  it("says so when the search is cleared, rather than leaving the last count standing", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "sara" } });
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("1 of 3"));

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "" } });

    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("Search cleared"));
    expect(screen.getByTestId("graph-live")).not.toHaveTextContent(/of 3/);
  });

  it("reports a search that matches nothing, which is the case that looks most like a broken page", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "nobody" } });

    await waitFor(() =>
      expect(screen.getByTestId("graph-live")).toHaveTextContent('Search "nobody": 0 of 3 nodes shown')
    );
  });

  it("names both filters when both are on, and neither is lost when one is cleared", async () => {
    renderWithProviders();
    await openBuilder();
    setRuleOn(GRADE, ">", "3");
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("2 of 3"));

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "sara" } });
    await waitFor(() =>
      expect(screen.getByTestId("graph-live")).toHaveTextContent(
        'Search "sara" and filter conditions: 1 of 3 nodes shown'
      )
    );

    // Clearing the search must not announce "cleared" while the conditions
    // are still hiding a node.
    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "" } });
    await waitFor(() =>
      expect(screen.getByTestId("graph-live")).toHaveTextContent("Filter conditions: 2 of 3 nodes shown")
    );
  });

  function setRuleOn(field: string, operator: string, value: string) {
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: field } });
    fireEvent.change(screen.getAllByTestId("expression-operator")[0], { target: { value: operator } });
    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value } });
  }
});
