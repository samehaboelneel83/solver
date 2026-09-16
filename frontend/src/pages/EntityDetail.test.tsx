import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntityDetail from "./EntityDetail";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderAtNew() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/domain/entity_type/new"]}>
        <Routes>
          <Route path=":schemaName/:tableName/new" element={<EntityDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderAtId(id: string) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/domain/entity_type/${id}`]}>
        <Routes>
          <Route path=":schemaName/:tableName/:id" element={<EntityDetail />} />
        </Routes>
      </MemoryRouter>
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
