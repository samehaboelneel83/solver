import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PropertyPanel from "./PropertyPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const graph = {
  nodes: [
    {
      id: "e1",
      type: "employee",
      label: "Ahmed",
      parent: null,
      attributes: { code: "ahmed-1", status: "ACTIVE", description: null, rank: "Captain" },
    },
  ],
  edges: [{ id: "r1", source: "e1", target: "e1", type: "self", label: "Self", attributes: { weight: 1 } }],
  entity_types: [{ id: "t1", code: "employee", name: "Employee", is_abstract: false }],
  relationship_types: [],
  hierarchies: [],
  attribute_definitions: [{ id: "a1", entity_type_id: "t1", code: "rank", name: "Rank", data_type: "string" }],
};

function renderWithProviders(props: Record<string, unknown> = {}) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <PropertyPanel
        organizationId="org-1"
        hierarchyId={null}
        graph={graph as any}
        selection={{ kind: "node", id: "e1" }}
        onClose={vi.fn()}
        {...props}
      />
    </QueryClientProvider>
  );
}

describe("PropertyPanel", () => {
  beforeEach(() => {
    (apiFetch as any).mockResolvedValue({});
  });

  it("shows a prompt when nothing is selected", () => {
    renderWithProviders({ selection: null });
    expect(screen.getByText(/select a node or edge/i)).toBeInTheDocument();
  });

  it("renders fixed fields and matching attribute_definitions for a selected node", () => {
    renderWithProviders();
    expect(screen.getByDisplayValue("Ahmed")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Captain")).toBeInTheDocument();
  });

  it("submits node edits via PATCH", async () => {
    renderWithProviders();
    fireEvent.change(screen.getByDisplayValue("Ahmed"), { target: { value: "Ahmed Updated" } });
    fireEvent.submit(screen.getByTestId("node-property-form"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/nodes/e1",
        expect.objectContaining({ method: "PATCH" })
      )
    );
  });

  it("renders the edge attributes as JSON and submits edits via PATCH", async () => {
    renderWithProviders({ selection: { kind: "edge", id: "r1" } });
    expect(screen.getByTestId("edge-property-form")).toBeInTheDocument();

    fireEvent.submit(screen.getByTestId("edge-property-form"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/edges/r1",
        expect.objectContaining({ method: "PATCH" })
      )
    );
  });

  it("calls DELETE when the node Delete button is clicked", async () => {
    renderWithProviders();
    fireEvent.click(screen.getByText("Delete"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/nodes/e1",
        expect.objectContaining({ method: "DELETE" })
      )
    );
  });
});
