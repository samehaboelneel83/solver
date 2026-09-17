import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RelatedRecords from "./RelatedRecords";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderRelated(schema: string, table: string, id: string) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <RelatedRecords schema={schema} table={table} id={id} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const SCHEMA_WITH_CHILDREN = [
  {
    schema: "problem",
    table: "problem",
    fields: [{ name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null }],
  },
  {
    schema: "problem",
    table: "variable_definition",
    fields: [
      { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
      {
        name: "problem_id",
        type: "uuid",
        required: true,
        writable: true,
        is_fk: true,
        fk_table: "problem.problem",
      },
    ],
  },
  {
    schema: "problem",
    table: "constraint_definition",
    fields: [
      { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
      {
        name: "problem_id",
        type: "uuid",
        required: true,
        writable: true,
        is_fk: true,
        fk_table: "problem.problem",
      },
    ],
  },
];

describe("RelatedRecords", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve(SCHEMA_WITH_CHILDREN);
      }
      if (path === "/api/problem/variable_definition/?f_problem_id=p1&limit=1") {
        return Promise.resolve({ items: [{ id: "v1" }], total: 3 });
      }
      if (path === "/api/problem/constraint_definition/?f_problem_id=p1&limit=1") {
        return Promise.resolve({ items: [], total: 0 });
      }
      return Promise.resolve({ items: [], total: 0 });
    });
  });

  it("lists child tables with counts, list links, and new links", async () => {
    renderRelated("problem", "problem", "p1");

    expect(await screen.findByText("variable_definition (3)")).toBeInTheDocument();
    expect(screen.getByText("constraint_definition (0)")).toBeInTheDocument();

    const varRow = screen.getByText("variable_definition (3)").closest("li") as HTMLElement;
    expect(within(varRow).getByText("variable_definition (3)")).toHaveAttribute(
      "href",
      "/problem/variable_definition?f_problem_id=p1"
    );
    expect(within(varRow).getByText("New")).toHaveAttribute(
      "href",
      "/problem/variable_definition/new?problem_id=p1"
    );

    const constraintRow = screen.getByText("constraint_definition (0)").closest("li") as HTMLElement;
    expect(within(constraintRow).getByText("New")).toHaveAttribute(
      "href",
      "/problem/constraint_definition/new?problem_id=p1"
    );
  });

  it("shows a placeholder count while counts are loading", async () => {
    let resolveCount: ((value: { items: unknown[]; total: number }) => void) | undefined;
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve(SCHEMA_WITH_CHILDREN);
      }
      if (path === "/api/problem/variable_definition/?f_problem_id=p1&limit=1") {
        return new Promise((resolve) => {
          resolveCount = resolve;
        });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    renderRelated("problem", "problem", "p1");

    expect(await screen.findByText("variable_definition (…)")).toBeInTheDocument();

    resolveCount?.({ items: [{ id: "v1" }, { id: "v2" }, { id: "v3" }], total: 3 });

    await waitFor(() => {
      expect(screen.getByText("variable_definition (3)")).toBeInTheDocument();
    });
  });

  it("renders nothing when the table has no child tables", async () => {
    renderRelated("problem", "variable_definition", "v1");
    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith("/api/meta/schema");
    });
    expect(screen.queryByText(/Related records/)).not.toBeInTheDocument();
  });

  it("includes self-references labelled by the field name", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity_type",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              {
                name: "parent_type_id",
                type: "uuid",
                required: false,
                writable: true,
                is_fk: true,
                fk_table: "domain.entity_type",
              },
            ],
          },
        ]);
      }
      return Promise.resolve({ items: [], total: 1 });
    });

    renderRelated("domain", "entity_type", "et1");

    expect(await screen.findByText("entity_type via parent_type_id (1)")).toBeInTheDocument();
    expect(screen.getByText("entity_type via parent_type_id (1)")).toHaveAttribute(
      "href",
      "/domain/entity_type?f_parent_type_id=et1"
    );
  });
});
