import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphEditor from "./GraphEditor";

const { mockCytoscapeInstance, mockCytoscape, registeredHandlersRef } = vi.hoisted(() => {
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
  };
  const constructor: any = vi.fn(() => instance);
  constructor.use = vi.fn();
  return { mockCytoscapeInstance: instance, mockCytoscape: constructor, registeredHandlersRef: handlersRef };
});

vi.mock("cytoscape", () => ({ default: mockCytoscape }));
vi.mock("cytoscape-elk", () => ({ default: {} }));
vi.mock("cytoscape-edgehandles", () => ({ default: {} }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderWithProviders(organizationId = "org-1") {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <GraphEditor organizationId={organizationId} />
    </QueryClientProvider>
  );
}

describe("GraphEditor", () => {
  beforeEach(() => {
    mockCytoscape.mockClear();
    registeredHandlersRef.current = {};
  });

  it("initializes Cytoscape with nodes and edges mapped from the graph response", async () => {
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
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    const callArgs = mockCytoscape.mock.calls[0][0];
    const nodeIds = callArgs.elements.filter((el: any) => !el.data.source).map((el: any) => el.data.id);
    const edgeIds = callArgs.elements.filter((el: any) => el.data.source).map((el: any) => el.data.id);
    expect(nodeIds).toEqual(["e1", "e2"]);
    expect(edgeIds).toEqual(["r1"]);

    const childNode = callArgs.elements.find((el: any) => el.data.id === "e2");
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
    await waitFor(() => expect(screen.getByText("Org Chart")).toBeInTheDocument());
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
    ehcompleteHandler(null, { id: () => "e1" }, { id: () => "e2" });

    await waitFor(() => expect(screen.getByTestId("edge-type-picker")).toBeInTheDocument());
    expect(screen.getByText("Works For")).toBeInTheDocument();
    expect(screen.queryByText("Manages")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Works For"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/edges",
        expect.objectContaining({ method: "POST" })
      )
    );
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
});
