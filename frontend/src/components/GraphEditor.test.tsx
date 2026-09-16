import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphEditor from "./GraphEditor";

const { mockCytoscapeInstance, mockCytoscape } = vi.hoisted(() => {
  const instance = {
    layout: vi.fn(() => ({ run: vi.fn() })),
    fit: vi.fn(),
    destroy: vi.fn(),
    on: vi.fn(),
  };
  const constructor: any = vi.fn(() => instance);
  constructor.use = vi.fn();
  return { mockCytoscapeInstance: instance, mockCytoscape: constructor };
});

vi.mock("cytoscape", () => ({ default: mockCytoscape }));
vi.mock("cytoscape-elk", () => ({ default: {} }));

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
  });

  it("initializes Cytoscape with nodes and edges mapped from the graph response", async () => {
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
    renderWithProviders();

    expect(screen.getByTestId("hierarchy-select")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Org Chart")).toBeInTheDocument());
  });
});
