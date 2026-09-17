import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntityList from "./EntityList";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../api/client";

const schemaResponse = [
  {
    schema: "domain",
    table: "entity_type",
    fields: [
      { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
      { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
    ],
  },
];

function renderWithProviders(initialEntry: string) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path=":schemaName/:tableName" element={<EntityList />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("EntityList", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve(schemaResponse);
      }
      return Promise.resolve({ items: [{ id: "1", code: "employee" }], total: 50 });
    });
  });

  it("renders rows using the metadata field list", async () => {
    renderWithProviders("/domain/entity_type");

    expect(await screen.findByText("employee")).toBeInTheDocument();
    expect(screen.getByText("domain.entity_type")).toBeInTheDocument();
  });

  it("updates the URL and request when typing in the search box", async () => {
    renderWithProviders("/domain/entity_type");
    await screen.findByText("employee");

    fireEvent.change(screen.getByTestId("list-search"), { target: { value: "alpha" } });

    await waitFor(
      () => {
        const call = (apiFetch as any).mock.calls.find(
          ([path]: [string]) => path.startsWith("/api/domain/entity_type/") && path.includes("q=alpha")
        );
        expect(call).toBeTruthy();
      },
      { timeout: 2000 }
    );
  });

  it("puts offset=20 in the URL when Next is clicked", async () => {
    renderWithProviders("/domain/entity_type");
    await screen.findByText("employee");

    fireEvent.click(screen.getByText("Next"));

    await waitFor(() => {
      const call = (apiFetch as any).mock.calls.find(
        ([path]: [string]) => path.startsWith("/api/domain/entity_type/") && path.includes("offset=20")
      );
      expect(call).toBeTruthy();
    });
  });

  it("renders a filter chip from the URL and includes it in the request", async () => {
    renderWithProviders("/domain/entity_type?f_entity_type_id=abc");
    await screen.findByText("employee");

    expect(screen.getByText("entity_type_id = abc")).toBeInTheDocument();

    await waitFor(() => {
      const call = (apiFetch as any).mock.calls.find(
        ([path]: [string]) => path.startsWith("/api/domain/entity_type/") && path.includes("f_entity_type_id=abc")
      );
      expect(call).toBeTruthy();
    });
  });

  it("removes a filter chip when its × is clicked", async () => {
    renderWithProviders("/domain/entity_type?f_entity_type_id=abc");
    await screen.findByText("employee");
    (apiFetch as any).mockClear();

    fireEvent.click(screen.getByLabelText("Remove filter entity_type_id"));

    expect(screen.queryByText("entity_type_id = abc")).not.toBeInTheDocument();
    await waitFor(() => {
      const call = (apiFetch as any).mock.calls.find(([path]: [string]) =>
        path.startsWith("/api/domain/entity_type/")
      );
      expect(call).toBeTruthy();
      expect(call[0]).not.toContain("f_entity_type_id");
    });
  });

  it("shows the formatted error above the table when delete fails", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve(schemaResponse);
      }
      if (options?.method === "DELETE") {
        return Promise.reject(new ApiError(409, JSON.stringify({ detail: "row is referenced elsewhere" })));
      }
      return Promise.resolve({ items: [{ id: "1", code: "employee" }], total: 1 });
    });

    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders("/domain/entity_type");
    await screen.findByText("employee");

    fireEvent.click(screen.getByText("Delete"));

    expect(await screen.findByText("row is referenced elsewhere")).toBeInTheDocument();
    (window.confirm as any).mockRestore();
  });

  it("renders an unknown-table message when the schema has no matching table", async () => {
    renderWithProviders("/domain/does_not_exist");

    expect(await screen.findByText("Unknown table domain.does_not_exist")).toBeInTheDocument();
  });
});

describe("EntityList human-readable titles and headers (B-1)", () => {
  const labeledSchemaResponse = [
    {
      schema: "domain",
      table: "entity_type",
      label: "Entity type",
      label_plural: "Entity types",
      fields: [
        { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
        {
          name: "organization_id",
          type: "uuid",
          required: true,
          writable: true,
          is_fk: true,
          fk_table: "iam.organization",
          label: "Organization",
        },
        { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null, label: "Code" },
        {
          name: "is_abstract",
          type: "boolean",
          required: true,
          writable: true,
          is_fk: false,
          fk_table: null,
          label: "Abstract type",
        },
      ],
    },
  ];

  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve(labeledSchemaResponse);
      }
      return Promise.resolve({ items: [{ id: "1", organization_id: "org-1", code: "employee", is_abstract: false }], total: 1 });
    });
  });

  it("renders the <h1> as the plural label with the raw schema.table kept as a subtitle", async () => {
    renderWithProviders("/domain/entity_type");

    expect(await screen.findByRole("heading", { name: "Entity types" })).toBeInTheDocument();
    expect(screen.getByText("domain.entity_type")).toBeInTheDocument();
  });

  it("renders column headers using field labels instead of raw snake_case names", async () => {
    renderWithProviders("/domain/entity_type");
    await screen.findByRole("heading", { name: "Entity types" });

    expect(screen.getByText("Organization")).toBeInTheDocument();
    expect(screen.getByText("Code")).toBeInTheDocument();
    expect(screen.getByText("Abstract type")).toBeInTheDocument();
    expect(screen.queryByText("organization_id")).not.toBeInTheDocument();
    expect(screen.queryByText("is_abstract")).not.toBeInTheDocument();
  });

  it("sets document.title to the plural label once the schema loads", async () => {
    renderWithProviders("/domain/entity_type");

    await waitFor(() => {
      expect(document.title).toBe("Entity types · Problem Solver");
    });
  });
});
