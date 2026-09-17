import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntityList from "./EntityList";
import { ToastProvider } from "../components/ToastProvider";

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

function renderWithProviders(initialEntry: string, options: { retry?: boolean } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: options.retry ?? false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route path=":schemaName/:tableName" element={<EntityList />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
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

  it("shows a toast naming the deleted record (D-1/D-6)", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve(schemaResponse);
      }
      if (options?.method === "DELETE") {
        return Promise.resolve(undefined);
      }
      return Promise.resolve({ items: [{ id: "1", code: "employee" }], total: 1 });
    });

    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders("/domain/entity_type");
    await screen.findByText("employee");

    fireEvent.click(screen.getByText("Delete"));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("employee deleted");
    (window.confirm as any).mockRestore();
  });

  it("shows a Retry button on a failed list load, and clicking it re-issues the request (D-4)", async () => {
    let listCallCount = 0;
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve(schemaResponse);
      }
      listCallCount += 1;
      return Promise.reject(new ApiError(500, "internal error"));
    });

    renderWithProviders("/domain/entity_type");

    const retryButton = await screen.findByText("Retry");
    expect(screen.getByText("Server error (500). Please try again.")).toBeInTheDocument();
    expect(listCallCount).toBe(1);

    fireEvent.click(retryButton);

    await waitFor(() => expect(listCallCount).toBe(2));
  });

  it("renders skeleton rows instead of the text 'Loading…' while the list is loading (D-5)", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve(schemaResponse);
      }
      // Never resolves -- the list query stays in its loading state.
      return new Promise(() => {});
    });

    renderWithProviders("/domain/entity_type");

    expect(await screen.findAllByTestId("skeleton-row")).not.toHaveLength(0);
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
  });

  it("renders skeleton rows on a cold navigation, while the schema (table) query is still pending (D-5 regression)", async () => {
    // Mirrors the real race: the meta/schema fetch and the list fetch run
    // concurrently, so there is a window where `table` (derived from the
    // schema) isn't resolved yet even though this isn't the "unknown table"
    // terminal state -- it just hasn't loaded. A pre-existing early return
    // on `!table` used to render a plain "Loading table definition…" string
    // here instead of the skeleton, with no window in which skeleton rows
    // were ever on screen.
    (apiFetch as any).mockImplementation(() => new Promise(() => {}));

    renderWithProviders("/domain/entity_type");

    expect(await screen.findAllByTestId("skeleton-row")).not.toHaveLength(0);
    expect(screen.queryByText("Loading table definition…")).not.toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    // There's still a heading -- the raw schema.table fallback -- even
    // though the labeled schema hasn't loaded.
    expect(screen.getByRole("heading", { name: "domain.entity_type" })).toBeInTheDocument();
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
