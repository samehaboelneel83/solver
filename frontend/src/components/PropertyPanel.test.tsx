import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PropertyPanel from "./PropertyPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch, ApiError } from "../api/client";

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

const typedGraph = {
  ...graph,
  nodes: [
    {
      id: "e1",
      type: "employee",
      label: "Ahmed",
      parent: null,
      attributes: { code: "ahmed-1", status: "ACTIVE", description: "On duty", rank: 3, active: true, hired: "2024-01-15" },
    },
  ],
  attribute_definitions: [
    { id: "a1", entity_type_id: "t1", code: "rank", name: "Rank", data_type: "number" },
    { id: "a2", entity_type_id: "t1", code: "active", name: "Active", data_type: "boolean" },
    { id: "a3", entity_type_id: "t1", code: "hired", name: "Hired", data_type: "date" },
  ],
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

  it("shows the heading as '<Type name>: <label>', not the type code", () => {
    renderWithProviders();
    expect(screen.getByText("Employee: Ahmed")).toBeInTheDocument();
  });

  it("falls back to the type code in the heading when no matching entity_type is found", () => {
    renderWithProviders({ graph: { ...graph, entity_types: [] } as any });
    expect(screen.getByText("employee: Ahmed")).toBeInTheDocument();
  });

  it("renders a number attribute as type=number, a boolean as a checkbox, and a date as type=date", () => {
    renderWithProviders({ graph: typedGraph as any });

    expect(screen.getByLabelText("Rank")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("Rank")).toHaveValue(3);
    expect(screen.getByLabelText("Active")).toHaveAttribute("type", "checkbox");
    expect(screen.getByLabelText("Active")).toBeChecked();
    expect(screen.getByLabelText("Hired")).toHaveAttribute("type", "date");
  });

  it("submits a number attribute as a JSON number and a boolean as true/false", async () => {
    renderWithProviders({ graph: typedGraph as any });

    fireEvent.change(screen.getByLabelText("Rank"), { target: { value: "5" } });
    fireEvent.submit(screen.getByTestId("node-property-form"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/nodes/e1",
        expect.objectContaining({ method: "PATCH" })
      )
    );
    // .filter(...).pop() rather than .find(...) -- apiFetch's call history isn't cleared
    // between tests in this file, so .find() could match a stale call from an earlier test.
    const call = (apiFetch as any).mock.calls
      .filter((c: any[]) => c[0] === "/api/graph/domain/nodes/e1" && c[1]?.method === "PATCH")
      .pop();
    const body = JSON.parse(call[1].body);
    expect(body.attributes).toEqual({ rank: 5, active: true, hired: "2024-01-15" });
  });

  it("sends status: null and description: null when those fields are cleared", async () => {
    renderWithProviders();

    fireEvent.change(screen.getByDisplayValue("ACTIVE"), { target: { value: "" } });
    fireEvent.submit(screen.getByTestId("node-property-form"));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/graph/domain/nodes/e1",
        expect.objectContaining({ method: "PATCH" })
      )
    );
    const call = (apiFetch as any).mock.calls
      .filter((c: any[]) => c[0] === "/api/graph/domain/nodes/e1" && c[1]?.method === "PATCH")
      .pop();
    const body = JSON.parse(call[1].body);
    expect(body.status).toBeNull();
    expect(body.description).toBeNull();
  });

  it("renders a formatted error when the save is rejected with a 409", async () => {
    (apiFetch as any).mockRejectedValue(new ApiError(409, JSON.stringify({ detail: "a conflicting entity exists" })));
    renderWithProviders();

    fireEvent.submit(screen.getByTestId("node-property-form"));

    await waitFor(() => expect(screen.getByText("a conflicting entity exists")).toBeInTheDocument());
  });
});
