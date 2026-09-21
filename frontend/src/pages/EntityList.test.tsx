import { onlineManager, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EntityList from "./EntityList";
import { ToastProvider } from "../components/ToastProvider";
import { editorQueryClient, EDITOR_ME } from "../test/me";

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
      // label_field: true mirrors real schema metadata -- DataTable's record label
      // (D-6) is metadata-driven (lib/labels.ts's recordLabel), not hardcoded to
      // `code`/`name`, so the fixture needs to flag it explicitly for the delete
      // toast/confirm tests below to see "employee" rather than the generic fallback.
      { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null, label_field: true },
    ],
  },
];

function renderWithProviders(initialEntry: string, options: { retry?: boolean } = {}) {
  const queryClient = editorQueryClient(EDITOR_ME, {
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

    const table = await screen.findByRole("table");
    // Also rendered in the small-screen card layout (G-4) -- scope to the table.
    expect(within(table).getByText("employee")).toBeInTheDocument();
  });

  it("updates the URL and request when typing in the search box", async () => {
    renderWithProviders("/domain/entity_type");
    await screen.findByRole("table");

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
    await screen.findByRole("table");

    fireEvent.click(screen.getByText("Next"));

    await waitFor(() => {
      const call = (apiFetch as any).mock.calls.find(
        ([path]: [string]) => path.startsWith("/api/domain/entity_type/") && path.includes("offset=20")
      );
      expect(call).toBeTruthy();
    });
  });

  it("keeps the row-count live region as the same DOM node across a sort change, instead of flashing the skeleton (H-9, fix round 2)", async () => {
    renderWithProviders("/domain/entity_type");
    await screen.findByRole("table");

    const before = screen.getByText("1-20 of 50");

    fireEvent.click(screen.getByRole("button", { name: "Sort by code" }));

    await waitFor(() => {
      const call = (apiFetch as any).mock.calls.find(
        ([path]: [string]) => path.startsWith("/api/domain/entity_type/") && path.includes("order_by=code")
      );
      expect(call).toBeTruthy();
    });

    // Same DOM node, not destroyed and recreated -- `keepPreviousData` keeps
    // the previous rows (and this element) mounted while the new page/sort
    // fetches, instead of dropping into the loading skeleton on every
    // sort/page/search and starting a fresh aria-live region each time.
    const after = screen.getByText("1-20 of 50");
    expect(after).toBe(before);
    expect(screen.queryAllByTestId("skeleton-row")).toHaveLength(0);
  });

  it("renders a filter chip from the URL and includes it in the request", async () => {
    renderWithProviders("/domain/entity_type?f_entity_type_id=abc");
    await screen.findByRole("table");

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
    await screen.findByRole("table");
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
    const table = within(await screen.findByRole("table"));

    // The card layout (G-4) renders an equivalent trigger -- scope to the table.
    fireEvent.click(table.getByTestId("row-actions"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));

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
    const table = within(await screen.findByRole("table"));

    // The card layout (G-4) renders an equivalent trigger -- scope to the table.
    fireEvent.click(table.getByTestId("row-actions"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));

    const status = await screen.findByText("employee deleted");
    expect(status).toBeInTheDocument();
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

  describe("goes offline (D-7)", () => {
    afterEach(() => {
      onlineManager.setOnline(true);
    });

    it("shows an offline notice instead of an indefinite skeleton when the list query is paused", async () => {
      // React Query's default networkMode pauses a query (never calling queryFn, so it never
      // errors) whenever the shared onlineManager reports offline -- the real cause of the
      // "silent spinner" finding. Drive it directly rather than faking fetchStatus.
      onlineManager.setOnline(false);
      (apiFetch as any).mockImplementation(() => new Promise(() => {}));

      renderWithProviders("/domain/entity_type");

      expect(await screen.findByTestId("offline-notice")).toHaveTextContent(/offline/i);
      expect(screen.queryAllByTestId("skeleton-row")).toHaveLength(0);
    });
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

  it("renders the <h1> as the plural label, with the raw schema.table hidden by default (B-1)", async () => {
    renderWithProviders("/domain/entity_type");

    expect(await screen.findByRole("heading", { name: "Entity types" })).toBeInTheDocument();
    // B-1: the jargon scan's central complaint -- this used to render unconditionally.
    expect(screen.queryByText("domain.entity_type")).not.toBeInTheDocument();
  });

  it("shows the raw schema.table subtitle once 'Show identifiers' is on, via ?ids=1 (B-1)", async () => {
    renderWithProviders("/domain/entity_type?ids=1");

    expect(await screen.findByRole("heading", { name: "Entity types" })).toBeInTheDocument();
    expect(screen.getByTestId("schema-subtitle")).toHaveTextContent("domain.entity_type");
  });

  it("renders column headers using field labels instead of raw snake_case names", async () => {
    // organization_id is an identifier-shaped column (E-4), hidden by
    // default behind "Show identifiers" -- show it via the URL so this test
    // can assert its label independently of that toggle.
    renderWithProviders("/domain/entity_type?ids=1");
    await screen.findByRole("heading", { name: "Entity types" });
    const table = await screen.findByRole("table");

    // With ?ids=1, `id` becomes the first (linked) column, so organization_id/
    // code/is_abstract are all "rest" fields -- rendered as labelled pairs in
    // the small-screen card layout too (G-4). Scope to the table.
    expect(within(table).getByText("Organization")).toBeInTheDocument();
    expect(within(table).getByText("Code")).toBeInTheDocument();
    expect(within(table).getByText("Abstract type")).toBeInTheDocument();
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
