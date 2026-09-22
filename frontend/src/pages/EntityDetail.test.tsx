import { onlineManager, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EntityDetail, { mapConstraintError } from "./EntityDetail";
import { ToastProvider } from "../components/ToastProvider";
import { UnsavedChangesProvider } from "../hooks/useUnsavedChangesGuard";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { editorQueryClient } from "../test/me";
import { ApiError, apiFetch } from "../api/client";

function renderAtNew() {
  const queryClient = editorQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/domain/entity_type/new"]}>
          <Routes>
            <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

function renderAtId(id: string) {
  const queryClient = editorQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[`/domain/entity_type/${id}`]}>
          <Routes>
            <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

describe("EntityDetail (create mode)", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      if (path === "/api/domain/entity_type/" && options?.method === "POST") {
        return Promise.resolve({ id: "new-id", code: "employee" });
      }
      return Promise.resolve({ items: [], total: 0 });
    });
  });

  it("submits a create request with the entered values", async () => {
    renderAtNew();

    fireEvent.change(await screen.findByTestId("field-code"), { target: { value: "employee" } });
    fireEvent.click(screen.getByText("Create"));

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/domain/entity_type/",
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  it("disables the submit button and shows 'Saving…' while the create mutation is pending (C-4)", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      if (path === "/api/domain/entity_type/" && options?.method === "POST") {
        // Never resolves -- the mutation stays pending so the test can
        // inspect the button while it's in flight.
        return new Promise(() => {});
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    renderAtNew();

    fireEvent.change(await screen.findByTestId("field-code"), { target: { value: "employee" } });
    fireEvent.click(screen.getByText("Create"));

    const button = await screen.findByText("Saving…");
    expect(button).toBeDisabled();
  });
});

describe("EntityDetail (edit mode)", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      if (path === "/api/domain/entity_type/existing-id" && options?.method === "PUT") {
        return Promise.resolve({ id: "existing-id", code: "updated-code" });
      }
      if (path === "/api/domain/entity_type/existing-id") {
        return Promise.resolve({ id: "existing-id", code: "existing-code" });
      }
      return Promise.resolve({ items: [], total: 0 });
    });
  });

  it("pre-populates the form from the existing row and submits a PUT with the updated values", async () => {
    renderAtId("existing-id");

    const codeField = (await screen.findByTestId("field-code")) as HTMLInputElement;
    await waitFor(() => {
      expect(codeField.value).toBe("existing-code");
    });

    fireEvent.change(codeField, { target: { value: "updated-code" } });
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/domain/entity_type/existing-id",
        expect.objectContaining({ method: "PUT" })
      );
    });
  });
});

describe("EntityDetail (missing record)", () => {
  it("shows '<table> not found' using the raw table name as a fallback when no label is present", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      if (path === "/api/domain/entity_type/missing-id") {
        return Promise.reject(new ApiError(404, "not found"));
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    // retry: false so the 404 error state settles immediately instead of
    // going through react-query's default retry/backoff.
    const queryClient = editorQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/domain/entity_type/missing-id"]}>
          <Routes>
            <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByText("entity_type not found")).toBeInTheDocument();
    expect(screen.getByText("Back to list")).toHaveAttribute("href", "/domain/entity_type");
    // Same page, no level-1 heading: an axe `page-has-heading-one`
    // violation, and nothing for a screen-reader user to land on.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("entity_type not found");
  });

  it("shows '<table label> not found' when the backend has sent a label", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            label: "Entity type",
            label_plural: "Entity types",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      if (path === "/api/domain/entity_type/missing-id") {
        return Promise.reject(new ApiError(404, "not found"));
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    const queryClient = editorQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/domain/entity_type/missing-id"]}>
          <Routes>
            <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByText("Entity type not found")).toBeInTheDocument();
    expect(screen.getByText("Back to list")).toHaveAttribute("href", "/domain/entity_type");
  });
});

describe("EntityDetail (load error other than 404)", () => {
  it("shows the formatted error and a link back to the list on a 500", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      if (path === "/api/domain/entity_type/broken-id") {
        return Promise.reject(new ApiError(500, "internal error"));
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    // retry: false so the error state settles immediately instead of going
    // through react-query's default retry/backoff.
    const queryClient = editorQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/domain/entity_type/broken-id"]}>
          <Routes>
            <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByText("Server error (500). Please try again.")).toBeInTheDocument();
    expect(screen.getByText("Back to list")).toHaveAttribute("href", "/domain/entity_type");
  });

  it("shows a Retry button next to the error that re-issues the entity request (D-4)", async () => {
    let entityCallCount = 0;
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      if (path === "/api/domain/entity_type/broken-id") {
        entityCallCount += 1;
        return Promise.reject(new ApiError(500, "internal error"));
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    const queryClient = editorQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/domain/entity_type/broken-id"]}>
          <Routes>
            <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    const retryButton = await screen.findByText("Retry");
    expect(entityCallCount).toBe(1);

    fireEvent.click(retryButton);

    await waitFor(() => expect(entityCallCount).toBe(2));
  });
});

describe("EntityDetail human-readable titles (B-1)", () => {
  const labeledSchema = [
    {
      schema: "domain",
      table: "entity_type",
      label: "Entity type",
      label_plural: "Entity types",
      fields: [
        { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
        {
          name: "code",
          type: "string",
          required: true,
          writable: true,
          is_fk: false,
          fk_table: null,
          label_field: true,
        },
      ],
    },
  ];

  it("renders the create page's <h1> as 'New entity type', lower-cased mid-sentence, with the schema.table subtitle", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") return Promise.resolve(labeledSchema);
      return Promise.resolve({ items: [], total: 0 });
    });

    render(
      <QueryClientProvider client={editorQueryClient()}>
        <MemoryRouter initialEntries={["/domain/entity_type/new"]}>
          <Routes>
            <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByRole("heading", { name: "New entity type" })).toBeInTheDocument();
    // B-1: the raw schema.table pair is now hidden by default -- see the dedicated
    // "Show identifiers" describe block below for the gated-visibility coverage.
    expect(screen.queryByText("domain.entity_type")).not.toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe("New entity type · Problem Solver"));
  });

  it("renders the edit page's <h1> using the record's own name, not the generic table label (C-6)", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") return Promise.resolve(labeledSchema);
      if (path === "/api/domain/entity_type/existing-id") {
        return Promise.resolve({ id: "existing-id", code: "existing-code" });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    render(
      <QueryClientProvider client={editorQueryClient()}>
        <MemoryRouter initialEntries={["/domain/entity_type/existing-id"]}>
          <Routes>
            <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    // Every edit page used to be headed "Edit entity type" -- identical for
    // every row, with nothing telling the two apart. It now names the
    // record itself (its `label_field` column, "existing-code"); the
    // generic table name is still available in the subtitle/breadcrumb.
    expect(await screen.findByRole("heading", { name: "Edit existing-code" })).toBeInTheDocument();
    expect(screen.queryByText("domain.entity_type")).not.toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe("Edit existing-code · Problem Solver"));
  });

  it("shows an 'Entity type created' toast after a successful create (D-1)", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") return Promise.resolve(labeledSchema);
      if (path === "/api/domain/entity_type/" && options?.method === "POST") {
        return Promise.resolve({ id: "new-id", code: "employee" });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    render(
      <QueryClientProvider client={editorQueryClient()}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/domain/entity_type/new"]}>
            <Routes>
              <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );

    fireEvent.change(await screen.findByTestId("field-code"), { target: { value: "employee" } });
    fireEvent.click(screen.getByText("Create"));

    expect(await screen.findByRole("status")).toHaveTextContent("Entity type created");
  });

  it("opens the record it just created so related records are one click away", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") return Promise.resolve(labeledSchema);
      if (path === "/api/domain/entity_type/" && options?.method === "POST") {
        return Promise.resolve({ id: "new-id", code: "employee" });
      }
      if (path === "/api/domain/entity_type/new-id") {
        return Promise.resolve({ id: "new-id", code: "employee" });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    render(
      <QueryClientProvider client={editorQueryClient()}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/domain/entity_type/new"]}>
            <Routes>
              <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
              <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );

    fireEvent.change(await screen.findByTestId("field-code"), { target: { value: "employee" } });
    fireEvent.click(screen.getByText("Create"));

    expect(await screen.findByRole("heading", { name: "Edit employee" })).toBeInTheDocument();
  });

  it("shows an 'Entity type saved' toast after a successful update (D-1)", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") return Promise.resolve(labeledSchema);
      if (path === "/api/domain/entity_type/existing-id" && options?.method === "PUT") {
        return Promise.resolve({ id: "existing-id", code: "updated-code" });
      }
      if (path === "/api/domain/entity_type/existing-id") {
        return Promise.resolve({ id: "existing-id", code: "existing-code" });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    render(
      <QueryClientProvider client={editorQueryClient()}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/domain/entity_type/existing-id"]}>
            <Routes>
              <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );

    const codeField = (await screen.findByTestId("field-code")) as HTMLInputElement;
    await waitFor(() => expect(codeField.value).toBe("existing-code"));
    fireEvent.click(screen.getByText("Save"));

    expect(await screen.findByRole("status")).toHaveTextContent("Entity type saved");
  });
});

describe("EntityDetail (create a problem)", () => {
  it("prefills owner from the signed-in account", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "public",
            table: "problem",
            write_capability: "model.publish",
            fields: [
              { name: "id", type: "integer", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "name", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
              { name: "owner", type: "string", required: false, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    const queryClient = editorQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/public/problem/new"]}>
          <Routes>
            <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByTestId("field-owner")).toHaveValue("admin");
  });
});

describe("EntityDetail (create mode with query-string prefill)", () => {
  it("prefills a foreign-key field from the query string and resolves its label", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
              {
                name: "organization_id",
                type: "uuid",
                required: false,
                writable: true,
                is_fk: true,
                fk_table: "iam.organization",
              },
            ],
          },
        ]);
      }
      if (path === "/api/iam/organization/options?ids=org-1") {
        return Promise.resolve([{ id: "org-1", label: "Acme" }]);
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    const queryClient = editorQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/domain/entity_type/new?organization_id=org-1"]}>
          <Routes>
            <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect((screen.getByTestId("field-organization_id") as HTMLInputElement).value).toBe("Acme");
    });
  });

  it("keeps the parent id when Related records New reuses EntityDetail", async () => {
    // Same component instance: /iam/role/:id → /iam/role_capability/new.
    // EntityForm's state is only initialized on mount, so a key that does
    // not change with the table leaves role_id empty and Create says
    // "Role is required."
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "iam",
            table: "role",
            label: "Role",
            label_plural: "Roles",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null, label_field: true },
              { name: "name", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
          {
            schema: "iam",
            table: "role_capability",
            label: "Role capability",
            label_plural: "Role capabilities",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              {
                name: "role_id",
                type: "uuid",
                required: true,
                writable: true,
                is_fk: true,
                fk_table: "iam.role",
              },
              { name: "capability_code", type: "string", required: true, writable: true, is_fk: true, fk_table: "iam.capability" },
            ],
          },
        ]);
      }
      if (path === "/api/iam/role/role-1") {
        return Promise.resolve({ id: "role-1", code: "planner", name: "Planner" });
      }
      if (path === "/api/iam/role/options?ids=role-1") {
        return Promise.resolve([{ id: "role-1", label: "planner" }]);
      }
      if (path.startsWith("/api/iam/capability/options")) {
        return Promise.resolve([{ id: "run.submit", label: "run.submit — Solve a scenario" }]);
      }
      if (path.startsWith("/api/iam/role_capability/") && options?.method === "POST") {
        return Promise.resolve({ id: "grant-1", role_id: "role-1", capability_code: "run.submit" });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    render(
      <QueryClientProvider client={editorQueryClient()}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/iam/role/role-1"]}>
            <Routes>
              <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
              <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );

    const related = await screen.findByRole("heading", { name: /related records/i });
    const row = related.parentElement?.parentElement ?? related.closest("section") ?? document.body;
    fireEvent.click(within(row instanceof HTMLElement ? row : document.body).getByRole("link", { name: "New" }));

    const capability = await screen.findByTestId("field-capability_code");
    fireEvent.focus(capability);
    fireEvent.change(capability, { target: { value: "run" } });
    fireEvent.mouseDown(await screen.findByRole("option", { name: /run\.submit/ }));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      const posted = (apiFetch as any).mock.calls.find(
        (call: [string, RequestInit?]) => call[0] === "/api/iam/role_capability/" && call[1]?.method === "POST"
      );
      expect(posted).toBeTruthy();
      expect(JSON.parse(posted[1].body)).toEqual(
        expect.objectContaining({ role_id: "role-1", capability_code: "run.submit" })
      );
    });
  });
});

describe("EntityDetail breadcrumb and Cancel (C-6, C-8)", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            label_plural: "Entity types",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      if (path === "/api/domain/entity_type/existing-id") {
        return Promise.resolve({ id: "existing-id", code: "existing-code" });
      }
      return Promise.resolve({ items: [], total: 0 });
    });
  });

  it("shows a breadcrumb link and a Cancel link, both back to the list -- the only controls used to be Save/Create", async () => {
    render(
      <QueryClientProvider client={editorQueryClient()}>
        <MemoryRouter initialEntries={["/domain/entity_type/existing-id"]}>
          <Routes>
            <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await screen.findByTestId("field-code");

    expect(screen.getByRole("link", { name: "Entity types" })).toHaveAttribute("href", "/domain/entity_type");
    expect(screen.getByRole("link", { name: "Cancel" })).toHaveAttribute("href", "/domain/entity_type");
  });
});

describe("EntityDetail unsaved-changes guard (C-3)", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      return Promise.resolve({ items: [], total: 0 });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function renderNewWithGuard() {
    const queryClient = editorQueryClient();
    return render(
      <QueryClientProvider client={queryClient}>
        <UnsavedChangesProvider>
          <MemoryRouter initialEntries={["/domain/entity_type/new"]}>
            <Routes>
              <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
              <Route path=":schemaName/:tableName" element={<div>Entity type list page</div>} />
            </Routes>
          </MemoryRouter>
        </UnsavedChangesProvider>
      </QueryClientProvider>
    );
  }

  it("confirms before the Cancel link discards an edited, unsaved form (C-3) -- a sidebar/Cancel click used to discard silently", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderNewWithGuard();

    fireEvent.change(await screen.findByTestId("field-code"), { target: { value: "employee" } });
    fireEvent.click(screen.getByText("Cancel"));

    expect(confirmSpy).toHaveBeenCalled();
    // window.confirm returned false ("stay") -- still on the form.
    expect(screen.getByTestId("field-code")).toBeInTheDocument();
  });

  it("navigates without prompting when nothing has been edited", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderNewWithGuard();

    await screen.findByTestId("field-code");
    fireEvent.click(screen.getByText("Cancel"));

    await waitFor(() => expect(screen.getByText("Entity type list page")).toBeInTheDocument());
    expect(confirmSpy).not.toHaveBeenCalled();
  });
});

describe("EntityDetail duplicate-value error mapping (C-5)", () => {
  const fieldsWithFk = [
    { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
    { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
    {
      name: "organization_id",
      type: "uuid",
      required: false,
      writable: true,
      is_fk: true,
      fk_table: "iam.organization",
    },
  ] as Parameters<typeof mapConstraintError>[1];

  it("mapConstraintError picks the non-FK field named in the constraint over an FK field that also matches", () => {
    const mapped = mapConstraintError(
      "a entity_type row with the same organization_id_code already exists",
      fieldsWithFk
    );

    expect(mapped).toEqual({ field: "code", label: "code" });
  });

  it("mapConstraintError returns null when no writable field name appears in the detail text", () => {
    expect(mapConstraintError("something went wrong", fieldsWithFk)).toBeNull();
  });

  it("marks the mapped field and does not leak the raw constraint name, on a 409 from Create", async () => {
    (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: fieldsWithFk,
          },
        ]);
      }
      if (path === "/api/domain/entity_type/" && options?.method === "POST") {
        return Promise.reject(
          new ApiError(
            409,
            JSON.stringify({ detail: "a entity_type row with the same organization_id_code already exists" })
          )
        );
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    renderAtNew();

    fireEvent.change(await screen.findByTestId("field-code"), { target: { value: "acme" } });
    fireEvent.click(screen.getByText("Create"));

    const summary = await screen.findByTestId("form-errors");
    expect(summary.textContent).toContain("code");
    expect(summary.textContent).not.toContain("organization_id_code");
    expect(screen.getByTestId("field-code")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("EntityDetail 'Show identifiers' toggle (B-1)", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            label: "Entity type",
            label_plural: "Entity types",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      return Promise.resolve({ items: [], total: 0 });
    });
  });

  it("hides the schema.table subtitle by default and shows it after clicking 'Show identifiers'", async () => {
    renderAtNew();

    await screen.findByTestId("field-code");
    expect(screen.queryByTestId("schema-subtitle")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show identifiers" }));

    expect(screen.getByTestId("schema-subtitle")).toHaveTextContent("domain.entity_type");
    expect(screen.getByRole("button", { name: "Hide identifiers" })).toBeInTheDocument();
  });

  it("reads the toggle's initial state from ?ids=1, matching the list page's toggle (E-4)", async () => {
    const queryClient = editorQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/domain/entity_type/new?ids=1"]}>
          <Routes>
            <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await screen.findByTestId("field-code");
    expect(screen.getByTestId("schema-subtitle")).toHaveTextContent("domain.entity_type");
  });
});

describe("EntityDetail 'Open in graph' link (B-3)", () => {
  const entitySchema = [
    {
      schema: "domain",
      table: "entity",
      label: "Entity",
      label_plural: "Entities",
      fields: [
        { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
        { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
        {
          name: "organization_id",
          type: "uuid",
          required: true,
          writable: true,
          is_fk: true,
          fk_table: "iam.organization",
        },
      ],
    },
  ];

  it("links to the graph page with the entity id and its organization in the query string", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") return Promise.resolve(entitySchema);
      if (path === "/api/domain/entity/entity-1") {
        return Promise.resolve({ id: "entity-1", code: "acme", organization_id: "org-1" });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    render(
      <QueryClientProvider client={editorQueryClient()}>
        <MemoryRouter initialEntries={["/domain/entity/entity-1"]}>
          <Routes>
            <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    const link = await screen.findByTestId("open-in-graph-link");
    expect(link).toHaveAttribute("href", "/graph?focus=entity-1&org=org-1");
  });

  it("does not render the link for a table other than domain.entity", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      if (path === "/api/domain/entity_type/existing-id") {
        return Promise.resolve({ id: "existing-id", code: "existing-code" });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    render(
      <QueryClientProvider client={editorQueryClient()}>
        <MemoryRouter initialEntries={["/domain/entity_type/existing-id"]}>
          <Routes>
            <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await screen.findByTestId("field-code");
    expect(screen.queryByTestId("open-in-graph-link")).not.toBeInTheDocument();
  });

  it("does not render the link on the create ('new') page, which has no record yet", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") return Promise.resolve(entitySchema);
      return Promise.resolve({ items: [], total: 0 });
    });

    render(
      <QueryClientProvider client={editorQueryClient()}>
        <MemoryRouter initialEntries={["/domain/entity/new"]}>
          <Routes>
            <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

    await screen.findByTestId("field-code");
    expect(screen.queryByTestId("open-in-graph-link")).not.toBeInTheDocument();
  });
});

describe("EntityDetail goes offline (D-7)", () => {
  afterEach(() => {
    onlineManager.setOnline(true);
  });

  it("shows an offline notice instead of an indefinite 'Loading…' when the entity query is paused", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              { name: "code", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
            ],
          },
        ]);
      }
      // Never resolves -- a genuinely paused query never calls this at all.
      return new Promise(() => {});
    });
    onlineManager.setOnline(false);

    renderAtId("existing-id");

    expect(await screen.findByTestId("offline-notice")).toHaveTextContent(/offline/i);
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
  });
});

describe("EntityDetail: a concurrent edit (Ruling 42)", () => {
  const TS = "2026-09-20T09:00:00+00:00";
  const STALE = {
    detail:
      "This domain was changed by someone else after this form loaded it. " +
      "Reload the domain and apply your changes to the current version.",
  };
  const DOMAIN = {
    id: 7,
    name: "Workforce",
    created_at: TS,
    updated_at: TS,
  };
  const schema = [
    {
      schema: "public",
      table: "domain",
      label: "Domain",
      label_plural: "Domains",
      fields: [
        { name: "id", type: "integer", required: true, writable: false, is_fk: false, fk_table: null },
        { name: "name", type: "string", required: true, writable: true, is_fk: false, fk_table: null },
        { name: "created_at", type: "datetime", required: false, writable: false, is_fk: false, fk_table: null },
        { name: "updated_at", type: "datetime", required: false, writable: false, is_fk: false, fk_table: null },
      ],
    },
  ];

  // `puts()` counts every PUT the mock has seen, so it must start from none:
  // without this, a test elsewhere in the file that saved a domain and ran
  // first (as a shuffled order can have it) left its PUTs to be counted here.
  beforeEach(() => {
    (apiFetch as unknown as ReturnType<typeof vi.fn>).mockReset();
  });

  function puts(): Record<string, unknown>[] {
    return (apiFetch as unknown as ReturnType<typeof vi.fn>).mock.calls
      .filter((call) => (call[1] as RequestInit | undefined)?.method === "PUT")
      .map((call) => JSON.parse((call[1] as RequestInit).body as string));
  }

  function renderDomain() {
    const queryClient = editorQueryClient();
    return render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/public/domain/7"]}>
            <Routes>
              <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
  }

  it("sends the updated_at it read, which is what lets the server refuse", async () => {
    (apiFetch as ReturnType<typeof vi.fn>).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") return Promise.resolve(schema);
      if (path === "/api/domain/7" && options?.method === "PUT") return Promise.resolve(DOMAIN);
      if (path === "/api/domain/7") return Promise.resolve(DOMAIN);
      return Promise.resolve({ items: [], total: 0 });
    });
    renderDomain();
    fireEvent.change(await screen.findByTestId("field-name"), { target: { value: "Workforce (edited)" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].updated_at).toBe(TS);
    expect(puts()[0].name).toBe("Workforce (edited)");
  });

  it("does not send updated_at when creating, because there is nothing to compare", async () => {
    (apiFetch as ReturnType<typeof vi.fn>).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") return Promise.resolve(schema);
      if (path === "/api/domain/" && options?.method === "POST") {
        return Promise.resolve({ ...DOMAIN, id: 99 });
      }
      return Promise.resolve({ items: [], total: 0 });
    });
    const queryClient = editorQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/public/domain/new"]}>
            <Routes>
              <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
    fireEvent.change(await screen.findByTestId("field-name"), { target: { value: "New domain" } });
    fireEvent.click(screen.getByText("Create"));
    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/domain/",
        expect.objectContaining({ method: "POST" })
      );
    });
    const body = JSON.parse(
      ((apiFetch as ReturnType<typeof vi.fn>).mock.calls.find((call) => (call[1] as RequestInit)?.method === "POST")?.[1] as RequestInit)
        .body as string
    );
    expect(body).not.toHaveProperty("updated_at");
  });

  it("shows the refusal with a way out instead of a red line under a control", async () => {
    (apiFetch as ReturnType<typeof vi.fn>).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") return Promise.resolve(schema);
      if (path === "/api/domain/7" && options?.method === "PUT") {
        return Promise.reject(new ApiError(409, JSON.stringify(STALE)));
      }
      if (path === "/api/domain/7") return Promise.resolve(DOMAIN);
      return Promise.resolve({ items: [], total: 0 });
    });
    renderDomain();
    fireEvent.change(await screen.findByTestId("field-name"), { target: { value: "Workforce (edited)" } });
    fireEvent.click(screen.getByText("Save"));

    const notice = await screen.findByTestId("stale-record");
    expect(notice).toHaveAttribute("role", "alert");
    expect(notice).toHaveTextContent(/changed by someone else/i);
    expect(within(notice).getByRole("button", { name: /reload and keep my changes/i })).toBeInTheDocument();
    expect(screen.getByTestId("field-name")).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByTestId("form-errors")).toBeNull();
  });

  it("keeps what the user typed when it reloads, and takes the other change for what they did not touch", async () => {
    const changed = {
      ...DOMAIN,
      name: "Written by B",
      updated_at: "2026-09-20T09:05:00+00:00",
    };
    (apiFetch as ReturnType<typeof vi.fn>).mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/api/meta/schema") return Promise.resolve(schema);
      if (path === "/api/domain/7" && options?.method === "PUT") {
        return Promise.reject(new ApiError(409, JSON.stringify(STALE)));
      }
      if (path === "/api/domain/7") return Promise.resolve(DOMAIN);
      return Promise.resolve({ items: [], total: 0 });
    });
    renderDomain();
    fireEvent.change(await screen.findByTestId("field-name"), { target: { value: "Workforce (edited)" } });
    fireEvent.click(screen.getByText("Save"));
    await screen.findByTestId("stale-record");

    (apiFetch as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") return Promise.resolve(schema);
      if (path === "/api/domain/7") return Promise.resolve(changed);
      return Promise.resolve({ items: [], total: 0 });
    });
    fireEvent.click(screen.getByRole("button", { name: /reload and keep my changes/i }));

    await waitFor(() => expect(screen.queryByTestId("stale-record")).toBeNull());
    expect((screen.getByTestId("field-name") as HTMLInputElement).value).toBe("Workforce (edited)");
  });
});
