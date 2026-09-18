import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphDemo from "./GraphDemo";

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
    nodes: vi.fn(() => ({ forEach: vi.fn() })),
    edges: vi.fn(() => ({ forEach: vi.fn() })),
    elements: vi.fn(() => ({ removeClass: vi.fn() })),
    getElementById: vi.fn(() => ({ style: vi.fn(() => "element") })),
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

function renderWithProviders() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <GraphDemo />
    </QueryClientProvider>
  );
}

describe("GraphDemo", () => {
  beforeEach(() => {
    mockCytoscape.mockClear();
    registeredHandlersRef.current = {};
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/iam/organization/")) {
        return Promise.resolve({ items: [{ id: "org-1", code: "default" }], total: 1 });
      }
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [{ id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} }],
          edges: [],
          entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
          relationship_types: [],
          hierarchies: [],
          attribute_definitions: [],
        });
      }
      return Promise.resolve({});
    });
  });

  it("resolves the default organization and renders the graph editor, filter bar, and property panel", async () => {
    renderWithProviders();

    // The cytoscape instance is created on mount, before the graph query
    // resolves, so wait on the data-dependent FilterBar instead.
    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());
    expect(mockCytoscape).toHaveBeenCalled();
    expect(screen.getByText(/select a node or edge/i)).toBeInTheDocument();
  });

  it("shows the newly-selected node's own values, not the previously-selected node's stale values", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/iam/organization/")) {
        return Promise.resolve({ items: [{ id: "org-1", code: "default" }], total: 1 });
      }
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [
            { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: { status: "ACTIVE" } },
            { id: "e2", type: "employee", label: "Sara", parent: null, attributes: { status: "ON_LEAVE" } },
          ],
          edges: [],
          entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
          relationship_types: [],
          hierarchies: [],
          attribute_definitions: [],
        });
      }
      return Promise.resolve({});
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const tapNodeHandler = registeredHandlersRef.current["tap:node"];

    tapNodeHandler({ target: { id: () => "e1" } });
    await waitFor(() => expect(screen.getByDisplayValue("Ahmed")).toBeInTheDocument());
    expect(screen.getByDisplayValue("ACTIVE")).toBeInTheDocument();

    tapNodeHandler({ target: { id: () => "e2" } });

    await waitFor(() => expect(screen.getByDisplayValue("Sara")).toBeInTheDocument());
    expect(screen.getByDisplayValue("ON_LEAVE")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Ahmed")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("ACTIVE")).not.toBeInTheDocument();
  });

  it("selects the first node matching the typed search when Enter is pressed in the filter search box, opening its property panel (H-1 fix round 1)", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/iam/organization/")) {
        return Promise.resolve({ items: [{ id: "org-1", code: "default" }], total: 1 });
      }
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [
            { id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} },
            { id: "e2", type: "employee", label: "Sara", parent: null, attributes: {} },
          ],
          edges: [],
          entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
          relationship_types: [],
          hierarchies: [],
          attribute_definitions: [],
        });
      }
      return Promise.resolve({});
    });

    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());

    // The audit finding: typing a node's label into this exact box and pressing Enter used to
    // select nothing at all -- it only filtered. "sar" matches "Sara", not "Ahmed".
    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "sar" } });
    fireEvent.keyDown(screen.getByTestId("filter-search"), { key: "Enter" });

    await waitFor(() => expect(screen.getByDisplayValue("Sara")).toBeInTheDocument());
    expect(screen.queryByDisplayValue("Ahmed")).not.toBeInTheDocument();
  });

  it("leaves the selection untouched when Enter is pressed in the filter search box and nothing matches (H-1 fix round 1)", async () => {
    renderWithProviders();
    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());

    const tapNodeHandler = registeredHandlersRef.current["tap:node"];
    tapNodeHandler({ target: { id: () => "e1" } });
    await waitFor(() => expect(screen.getByDisplayValue("Ahmed")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "no-such-node" } });
    fireEvent.keyDown(screen.getByTestId("filter-search"), { key: "Enter" });

    expect(screen.getByDisplayValue("Ahmed")).toBeInTheDocument();
  });

  it("keeps the filter bar's search text when the hierarchy is switched (state now lives in GraphDemo, not FilterBar)", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/iam/organization/")) {
        return Promise.resolve({ items: [{ id: "org-1", code: "default" }], total: 1 });
      }
      if (path.startsWith("/api/graph/domain?")) {
        const hierarchies = [{ id: "h1", code: "org-chart", name: "Org Chart" }];
        return Promise.resolve({
          nodes: [{ id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} }],
          edges: [],
          entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
          relationship_types: [],
          hierarchies,
          attribute_definitions: [],
        });
      }
      return Promise.resolve({});
    });

    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("Org Chart (org-chart)")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "ahmed" } });
    expect(screen.getByTestId("filter-search")).toHaveValue("ahmed");

    fireEvent.change(screen.getByTestId("hierarchy-select"), { target: { value: "h1" } });

    // Give the hierarchy-triggered refetch a tick to settle, then confirm the search text
    // (owned by GraphDemo's filterState, not FilterBar's own state) is still there. A plain
    // synchronous assertion here would race FilterBar's ~200ms debounced onChange (M-8) --
    // the hierarchy switch transiently unmounts/remounts FilterBar (graph goes undefined
    // mid-refetch), and if that happens before the debounce commits, the freshly-mounted
    // instance would briefly read GraphDemo's still-stale filterState.search. waitFor gives
    // the debounce time to land.
    await waitFor(() => expect(screen.getByTestId("hierarchy-select")).toHaveValue("h1"));
    await waitFor(() => expect(screen.getByTestId("filter-search")).toHaveValue("ahmed"));
  });

  it("defaults the organization selector to the org coded 'default' and switching orgs re-queries the graph and clears selection/hierarchy", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/iam/organization/")) {
        // Alphabetically, "Alpha Clinic" sorts before "Zeta Org" -- the default org
        // must still be picked by code, not by list order or alphabetical position.
        return Promise.resolve({
          items: [
            { id: "org-2", code: "north-clinic", name: "Alpha Clinic" },
            { id: "org-1", code: "default", name: "Zeta Org" },
          ],
          total: 2,
        });
      }
      if (path.startsWith("/api/graph/domain?")) {
        return Promise.resolve({
          nodes: [{ id: "e1", type: "employee", label: "Ahmed", parent: null, attributes: {} }],
          edges: [],
          entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
          relationship_types: [],
          hierarchies: [{ id: "h1", code: "org-chart", name: "Org Chart" }],
          attribute_definitions: [],
        });
      }
      return Promise.resolve({});
    });

    renderWithProviders();

    await waitFor(() => expect(screen.getByTestId("org-select")).toBeInTheDocument());
    expect(screen.getByTestId("org-select")).toHaveValue("org-1");
    const options = Array.from(
      screen.getByTestId("org-select").querySelectorAll("option")
    ) as HTMLOptionElement[];
    expect(options.map((option) => option.textContent)).toEqual([
      "Alpha Clinic (north-clinic)",
      "Zeta Org (default)",
    ]);

    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    const tapNodeHandler = registeredHandlersRef.current["tap:node"];
    tapNodeHandler({ target: { id: () => "e1" } });
    await waitFor(() => expect(screen.getByDisplayValue("Ahmed")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("hierarchy-select"), { target: { value: "h1" } });
    await waitFor(() => expect(screen.getByTestId("hierarchy-select")).toHaveValue("h1"));

    const cytoscapeCallsBeforeSwitch = mockCytoscape.mock.calls.length;

    fireEvent.change(screen.getByTestId("org-select"), { target: { value: "org-2" } });
    expect(screen.getByTestId("org-select")).toHaveValue("org-2");

    // Selection and hierarchy are reset on org change.
    expect(screen.queryByDisplayValue("Ahmed")).not.toBeInTheDocument();

    // GraphEditor is keyed by organizationId (I-2/M-5): switching orgs remounts it with a
    // brand new cytoscape instance rather than diffing the old org's nodes away, so a failed
    // or still-in-flight refetch for the new org can never leave the previous org's nodes
    // drawn and actionable.
    await waitFor(() => expect(mockCytoscape.mock.calls.length).toBeGreaterThan(cytoscapeCallsBeforeSwitch));

    await waitFor(() => {
      const graphCalls = (apiFetch as any).mock.calls.filter(([path]: [string]) =>
        path.startsWith("/api/graph/domain?")
      );
      expect(graphCalls.length).toBeGreaterThan(0);
      const lastPath = graphCalls[graphCalls.length - 1][0] as string;
      expect(lastPath).toContain("organization_id=org-2");
      expect(lastPath).not.toContain("hierarchy_id");
    });
  });

  it("stacks the canvas and property panel in a column below lg:, and shares a row at lg: and up (F-1)", async () => {
    renderWithProviders();

    await waitFor(() => expect(screen.getByTestId("filter-search")).toBeInTheDocument());

    const layout = screen.getByTestId("graph-layout");
    expect(layout.className).toMatch(/flex-col/);
    expect(layout.className).toMatch(/lg:flex-row/);
  });

  it("shows a message instead of a blank page when no organizations exist", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/iam/organization/")) {
        return Promise.resolve({ items: [], total: 0 });
      }
      return Promise.resolve({});
    });

    renderWithProviders();

    await waitFor(() => expect(screen.getByText(/no organizations/i)).toBeInTheDocument());
    expect(screen.queryByTestId("org-select")).not.toBeInTheDocument();
  });
});
