import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphDemo from "./GraphDemo";

const { mockCytoscape } = vi.hoisted(() => {
  const instance: any = {
    layout: vi.fn(() => ({ run: vi.fn() })),
    fit: vi.fn(),
    destroy: vi.fn(),
    edgehandles: vi.fn(() => ({ destroy: vi.fn() })),
    on: vi.fn(),
    nodes: vi.fn(() => ({ forEach: vi.fn() })),
    edges: vi.fn(() => ({ forEach: vi.fn() })),
    elements: vi.fn(() => ({ removeClass: vi.fn() })),
    getElementById: vi.fn(() => ({ style: vi.fn(() => "element") })),
  };
  const constructor: any = vi.fn(() => instance);
  constructor.use = vi.fn();
  return { mockCytoscape: constructor };
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
});
