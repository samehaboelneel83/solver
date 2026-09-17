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

    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    expect(screen.getByTestId("filter-search")).toBeInTheDocument();
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

  it("resets the filter bar (and the applied filter) to defaults when the hierarchy is switched", async () => {
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
    await waitFor(() => expect(screen.getByText("Org Chart")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("filter-search"), { target: { value: "ahmed" } });
    expect(screen.getByTestId("filter-search")).toHaveValue("ahmed");

    fireEvent.change(screen.getByTestId("hierarchy-select"), { target: { value: "h1" } });

    await waitFor(() => expect(screen.getByTestId("filter-search")).toHaveValue(""));
  });
});
