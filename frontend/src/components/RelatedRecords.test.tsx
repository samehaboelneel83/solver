import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RelatedRecords from "./RelatedRecords";
import { editorQueryClient, EDITOR_ME } from "../test/me";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderRelated(schema: string, table: string, id: string, queryClient = editorQueryClient()) {
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

  it("hides New when the account lacks the child table's write_capability", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "iam",
            table: "user_account",
            write_capability: "iam.manage",
            fields: [{ name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null }],
          },
          {
            schema: "iam",
            table: "user_role",
            write_capability: "iam.manage",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              {
                name: "user_id",
                type: "uuid",
                required: true,
                writable: true,
                is_fk: true,
                fk_table: "iam.user_account",
              },
            ],
          },
        ]);
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    renderRelated("iam", "user_account", "u1");

    expect(await screen.findByText("user_role (0)")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Roles on this user" })).toBeInTheDocument();
    expect(screen.queryByText("New")).not.toBeInTheDocument();
    expect(screen.getByText("user_role (0)")).toHaveAttribute("href", "/iam/user_role?f_user_id=u1");
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

  it("labels each FK field 'via' when a child table has more than one FK to the same parent", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "domain",
            table: "entity",
            fields: [{ name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null }],
          },
          {
            schema: "domain",
            table: "relationship",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              {
                name: "source_entity_id",
                type: "uuid",
                required: true,
                writable: true,
                is_fk: true,
                fk_table: "domain.entity",
              },
              {
                name: "target_entity_id",
                type: "uuid",
                required: true,
                writable: true,
                is_fk: true,
                fk_table: "domain.entity",
              },
            ],
          },
        ]);
      }
      if (path === "/api/domain/relationship/?f_source_entity_id=e1&limit=1") {
        return Promise.resolve({ items: [{ id: "r1" }], total: 2 });
      }
      if (path === "/api/domain/relationship/?f_target_entity_id=e1&limit=1") {
        return Promise.resolve({ items: [{ id: "r2" }], total: 5 });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    renderRelated("domain", "entity", "e1");

    const sourceRow = (await screen.findByText("relationship via source_entity_id (2)")).closest(
      "li"
    ) as HTMLElement;
    expect(within(sourceRow).getByText("relationship via source_entity_id (2)")).toHaveAttribute(
      "href",
      "/domain/relationship?f_source_entity_id=e1"
    );
    expect(within(sourceRow).getByText("New")).toHaveAttribute(
      "href",
      "/domain/relationship/new?source_entity_id=e1"
    );

    const targetRow = screen.getByText("relationship via target_entity_id (5)").closest("li") as HTMLElement;
    expect(within(targetRow).getByText("relationship via target_entity_id (5)")).toHaveAttribute(
      "href",
      "/domain/relationship?f_target_entity_id=e1"
    );
    expect(within(targetRow).getByText("New")).toHaveAttribute(
      "href",
      "/domain/relationship/new?target_entity_id=e1"
    );
  });

  it("labels rows with the child table's plural label instead of the raw table name, e.g. 'Variable definitions (1)' (B-1)", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          {
            schema: "problem",
            table: "problem",
            label: "Problem",
            label_plural: "Problems",
            fields: [{ name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null }],
          },
          {
            schema: "problem",
            table: "variable_definition",
            label: "Variable definition",
            label_plural: "Variable definitions",
            fields: [
              { name: "id", type: "uuid", required: true, writable: false, is_fk: false, fk_table: null },
              {
                name: "problem_id",
                type: "uuid",
                required: true,
                writable: true,
                is_fk: true,
                fk_table: "problem.problem",
                label: "Problem",
              },
            ],
          },
        ]);
      }
      if (path === "/api/problem/variable_definition/?f_problem_id=p1&limit=1") {
        return Promise.resolve({ items: [{ id: "v1" }], total: 1 });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    renderRelated("problem", "problem", "p1");

    expect(await screen.findByText("Variable definitions (1)")).toBeInTheDocument();
    expect(screen.queryByText(/variable_definition \(/)).not.toBeInTheDocument();
  });

  it("keeps empty children in the main list when every child is empty", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve(SCHEMA_WITH_CHILDREN);
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    renderRelated("problem", "problem", "p1");

    expect(await screen.findByText("variable_definition (0)")).toBeInTheDocument();
    expect(screen.getByText("constraint_definition (0)")).toBeInTheDocument();
    expect(screen.queryByText(/Show \d+ empty/)).not.toBeInTheDocument();
    expect(screen.getByText("variable_definition (0)")).toHaveAttribute(
      "href",
      "/problem/variable_definition?f_problem_id=p1"
    );
  });

  it("sorts non-empty children first and collapses confirmed-empty ones behind a 'Show N empty' disclosure (E-6)", async () => {
    renderRelated("problem", "problem", "p1");

    const nonEmptyLink = await screen.findByText("variable_definition (3)");
    const summary = await screen.findByText("Show 1 empty");

    // The non-empty child appears before the disclosure in document order.
     
    expect(nonEmptyLink.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const details = summary.closest("details") as HTMLDetailsElement;
    expect(details).not.toBeNull();
    expect(details.open).toBe(false);

    // The empty child is still in the DOM (available to assistive tech and
    // to this assertion), just tucked behind the closed disclosure.
    expect(screen.getByText("constraint_definition (0)")).toBeInTheDocument();
  });

  it("keeps a still-loading child in the main list rather than provisionally hiding it", async () => {
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
      if (path === "/api/problem/constraint_definition/?f_problem_id=p1&limit=1") {
        return Promise.resolve({ items: [], total: 0 });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    renderRelated("problem", "problem", "p1");

    // The still-loading child (variable_definition) is not behind the
    // disclosure -- only the confirmed-empty constraint_definition is.
    expect(await screen.findByText("variable_definition (…)")).toBeInTheDocument();
    expect(await screen.findByText("Show 1 empty")).toBeInTheDocument();

    resolveCount?.({ items: [{ id: "v1" }], total: 2 });
    await waitFor(() => {
      expect(screen.getByText("variable_definition (2)")).toBeInTheDocument();
    });
  });

  it("shows a '?' with a title when a count query fails, instead of the loading placeholder forever", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve(SCHEMA_WITH_CHILDREN);
      }
      if (path === "/api/problem/variable_definition/?f_problem_id=p1&limit=1") {
        return Promise.reject(new Error("boom"));
      }
      if (path === "/api/problem/constraint_definition/?f_problem_id=p1&limit=1") {
        return Promise.resolve({ items: [], total: 0 });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    // retry: false so the failed query settles into its error state
    // immediately instead of going through react-query's default retries.
    const queryClient = editorQueryClient(EDITOR_ME, {
      defaultOptions: { queries: { retry: false } },
    });
    renderRelated("problem", "problem", "p1", queryClient);

    const marker = await screen.findByTitle("Count unavailable");
    expect(marker).toHaveTextContent("?");

    const row = marker.closest("li") as HTMLElement;
    expect(within(row).getByRole("link", { name: /variable_definition/ })).toHaveAttribute(
      "href",
      "/problem/variable_definition?f_problem_id=p1"
    );
    expect(within(row).getByText("New")).toHaveAttribute(
      "href",
      "/problem/variable_definition/new?problem_id=p1"
    );

    // the healthy sibling row still resolves normally
    expect(await screen.findByText("constraint_definition (0)")).toBeInTheDocument();
  });
});
