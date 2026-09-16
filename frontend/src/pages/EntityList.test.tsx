import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EntityList from "./EntityList";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderWithProviders() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/domain/entity_type"]}>
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
      return Promise.resolve({ items: [{ id: "1", code: "employee" }], total: 1 });
    });
  });

  it("renders rows using the metadata field list", async () => {
    renderWithProviders();

    expect(await screen.findByText("employee")).toBeInTheDocument();
    expect(screen.getByText("domain.entity_type")).toBeInTheDocument();
  });
});
