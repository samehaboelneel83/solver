import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DataTable from "./DataTable";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const fields = [
  { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
  { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null },
];

const rows = [{ id: "1", code: "employee" }];

function renderTable(ui: React.ReactElement, initialEntry = "/") {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

const baseProps = {
  schema: "domain",
  table: "entity_type",
  tableLabel: "Entity types",
  newHref: "/domain/entity_type/new",
};

describe("DataTable", () => {
  it("renders rows and pagination info", () => {
    renderTable(
      <DataTable
        {...baseProps}
        fields={fields}
        rows={rows}
        total={1}
        limit={20}
        offset={0}
        onPageChange={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(screen.getByText("employee")).toBeInTheDocument();
    expect(screen.getByText("1-1 of 1")).toBeInTheDocument();
  });

  it("puts the row count text in a polite live region (H-9)", () => {
    renderTable(
      <DataTable
        {...baseProps}
        fields={fields}
        rows={rows}
        total={1}
        limit={20}
        offset={0}
        onPageChange={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent("1-1 of 1");
  });

  it("calls onPageChange with the next offset", () => {
    const onPageChange = vi.fn();
    renderTable(
      <DataTable
        {...baseProps}
        fields={fields}
        rows={rows}
        total={50}
        limit={20}
        offset={0}
        onPageChange={onPageChange}
        onDelete={vi.fn()}
      />
    );

    fireEvent.click(screen.getByText("Next"));
    expect(onPageChange).toHaveBeenCalledWith(20);
  });

  describe("the first cell as a link (E-1/H-2)", () => {
    it("renders the first visible cell as a link to the record, and the row remains clickable as a convenience", () => {
      const onRowClick = vi.fn();
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
          onRowClick={onRowClick}
        />
      );

      const link = screen.getByRole("link", { name: "employee" });
      expect(link).toHaveAttribute("href", "/domain/entity_type/1");

      fireEvent.click(link);
      expect(onRowClick).toHaveBeenCalledWith("1");
    });
  });

  describe("row actions menu (G-3)", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("keeps Delete out of the tab sequence except through a >=32px menu trigger, and the confirm still names the record (D-6)", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );

      expect(screen.queryByText("Delete")).not.toBeInTheDocument();

      const trigger = screen.getByTestId("row-actions");
      expect(trigger).toHaveAccessibleName("Actions for employee");
      const rect = trigger.className;
      expect(rect).toContain("h-8");
      expect(rect).toContain("w-8");

      fireEvent.click(trigger);
      const deleteItem = screen.getByRole("menuitem", { name: "Delete" });
      fireEvent.click(deleteItem);

      expect(window.confirm).toHaveBeenCalledWith('Delete "employee"? This cannot be undone.');
      expect(onDelete).toHaveBeenCalledWith("1", "employee");
    });

    it("does not trigger onRowClick when the actions menu is opened or Delete is chosen", () => {
      const onRowClick = vi.fn();
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
          onRowClick={onRowClick}
        />
      );

      fireEvent.click(screen.getByTestId("row-actions"));
      expect(onRowClick).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
      expect(onRowClick).not.toHaveBeenCalled();
      expect(onDelete).toHaveBeenCalledWith("1", "employee");
    });

    it("names the record from `name` when there is no `code`, and falls back to 'this row' when neither is present (D-6)", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={[{ id: "2", name: "Acme Corp" }]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );
      fireEvent.click(screen.getByTestId("row-actions"));
      fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
      expect(window.confirm).toHaveBeenCalledWith('Delete "Acme Corp"? This cannot be undone.');
      expect(onDelete).toHaveBeenCalledWith("2", "Acme Corp");

      (window.confirm as any).mockClear();
      onDelete.mockClear();
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={[{ id: "3" }]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );
      fireEvent.click(screen.getByRole("button", { name: "Actions for this row" }));
      fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
      expect(window.confirm).toHaveBeenCalledWith('Delete "this row"? This cannot be undone.');
      expect(onDelete).toHaveBeenCalledWith("3", "this row");
    });

    it("skips onDelete when the confirmation is cancelled", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(false);
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );

      fireEvent.click(screen.getByTestId("row-actions"));
      fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));

      expect(window.confirm).toHaveBeenCalled();
      expect(onDelete).not.toHaveBeenCalled();
    });

    it("closes the menu on an outside click", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      fireEvent.click(screen.getByTestId("row-actions"));
      expect(screen.getByRole("menuitem", { name: "Delete" })).toBeInTheDocument();

      fireEvent.mouseDown(document.body);
      expect(screen.queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
    });
  });

  describe("sort affordance (E-2)", () => {
    it("exposes aria-sort and a caret on the active column, and an accessible name on sort buttons", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          orderBy="code"
          order="asc"
          onSort={vi.fn()}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const codeHeader = screen.getByText("code").closest("th") as HTMLElement;
      expect(codeHeader).toHaveAttribute("aria-sort", "ascending");

      const sortButton = screen.getByRole("button", { name: "Sort by code" });
      expect(sortButton).toBeInTheDocument();
      expect(sortButton.className).toContain("h-6");
    });

    it("switches aria-sort to descending and flips the caret", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          orderBy="code"
          order="desc"
          onSort={vi.fn()}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const codeHeader = screen.getByText("code").closest("th") as HTMLElement;
      expect(codeHeader).toHaveAttribute("aria-sort", "descending");
    });

    it("calls onSort with the column name when a sortable header is clicked", () => {
      const onSort = vi.fn();
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onSort={onSort}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      fireEvent.click(screen.getByRole("button", { name: "Sort by code" }));
      expect(onSort).toHaveBeenCalledWith("code");
    });
  });

  describe("table semantics (H-9/H-12)", () => {
    it("has a visually-hidden caption naming the table, scope=col on every header, and an accessible name on the actions column", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const caption = screen.getByText("Entity types", { selector: "caption" });
      expect(caption).toHaveClass("sr-only");

      const headers = screen.getAllByRole("columnheader");
      expect(headers.length).toBeGreaterThan(0);
      for (const header of headers) {
        expect(header).toHaveAttribute("scope", "col");
      }

      const actionsHeader = headers[headers.length - 1];
      expect(actionsHeader).toHaveTextContent("Actions");
    });
  });

  describe("identifier columns hidden behind a toggle (E-4)", () => {
    it("hides the id column by default and shows it after toggling, syncing ?ids=1 in the URL", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      // "id" column header isn't rendered at all by default.
      expect(screen.queryByText("id")).not.toBeInTheDocument();

      const toggle = screen.getByRole("button", { name: "Show identifiers" });
      fireEvent.click(toggle);

      expect(screen.getByText("id")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Hide identifiers" })).toBeInTheDocument();
    });

    it("reads the toggle's initial state from ?ids=1 in the URL", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />,
        "/?ids=1"
      );

      expect(screen.getByText("id")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Hide identifiers" })).toBeInTheDocument();
    });
  });

  describe("empty state (A-5)", () => {
    it("renders a named empty state with the New action instead of a bare header row", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={[]}
          total={0}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      expect(screen.getByText("No entity types yet")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "New" })).toHaveAttribute("href", "/domain/entity_type/new");
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
    });
  });

  describe("human-readable column headers (B-1)", () => {
    const labeledFields = [
      { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
      {
        name: "organization_id",
        type: "uuid" as const,
        required: true,
        writable: true,
        is_fk: true,
        fk_table: "iam.organization",
        label: "Organization",
      },
      { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null, label: "Code" },
    ];

    it("renders field labels as column headers instead of raw snake_case names", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={labeledFields}
          rows={[{ id: "1", code: "employee" }]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />,
        "/?ids=1"
      );

      expect(screen.getByText("Organization")).toBeInTheDocument();
      expect(screen.getByText("Code")).toBeInTheDocument();
      expect(screen.queryByText("organization_id")).not.toBeInTheDocument();
    });

    it("falls back to the raw field name when a column has no label", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      expect(screen.getByText("code")).toBeInTheDocument();
    });
  });

  describe("foreign key columns", () => {
    beforeEach(() => {
      (apiFetch as any).mockReset();
    });

    it("renders the resolved label instead of the raw UUID", async () => {
      (apiFetch as any).mockImplementation((path: string) => {
        if (path.includes("/options")) {
          return Promise.resolve([{ id: "11111111-1111-1111-1111-111111111111", label: "Acme Corp" }]);
        }
        return Promise.reject(new Error(`unexpected path ${path}`));
      });

      const fkFields = [
        { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
        {
          name: "organization_id",
          type: "uuid" as const,
          required: true,
          writable: true,
          is_fk: true,
          fk_table: "iam.organization",
        },
      ];
      const fkRows = [{ id: "1", organization_id: "11111111-1111-1111-1111-111111111111" }];

      renderTable(
        <DataTable
          {...baseProps}
          fields={fkFields}
          rows={fkRows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />,
        // organization_id is an identifier-shaped column, so show it: the
        // FK-label resolution behavior under test is independent of the
        // show/hide-identifiers toggle.
        "/?ids=1"
      );

      expect(screen.getByText("11111111-1111-1111-1111-111111111111")).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.getByText("Acme Corp")).toBeInTheDocument();
      });

      const call = (apiFetch as any).mock.calls.find(([path]: [string]) => path.includes("/options"));
      expect(call[0]).toContain("/api/iam/organization/options");
      expect(call[0]).toContain("ids=11111111-1111-1111-1111-111111111111");

      const cell = screen.getByText("Acme Corp");
      expect(cell.getAttribute("title")).toBe("11111111-1111-1111-1111-111111111111");
    });

    it("does not throw when the number of FK tables changes between renders without a key change", async () => {
      (apiFetch as any).mockResolvedValue([]);

      const queryClient = new QueryClient();
      const zeroFkFields = [
        { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
      ];
      const twoFkFields = [
        { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
        {
          name: "organization_id",
          type: "uuid" as const,
          required: true,
          writable: true,
          is_fk: true,
          fk_table: "iam.organization",
        },
        {
          name: "role_type_id",
          type: "uuid" as const,
          required: true,
          writable: true,
          is_fk: true,
          fk_table: "domain.role_type",
        },
      ];
      const zeroFkRows = [{ id: "1" }];
      const twoFkRows = [
        {
          id: "1",
          organization_id: "11111111-1111-1111-1111-111111111111",
          role_type_id: "22222222-2222-2222-2222-222222222222",
        },
      ];

      const { rerender } = render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/?ids=1"]}>
            <DataTable
              {...baseProps}
              fields={zeroFkFields}
              rows={zeroFkRows}
              total={1}
              limit={20}
              offset={0}
              onPageChange={vi.fn()}
              onDelete={vi.fn()}
            />
          </MemoryRouter>
        </QueryClientProvider>
      );

      expect(() => {
        rerender(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={["/?ids=1"]}>
              <DataTable
                {...baseProps}
                fields={twoFkFields}
                rows={twoFkRows}
                total={1}
                limit={20}
                offset={0}
                onPageChange={vi.fn()}
                onDelete={vi.fn()}
              />
            </MemoryRouter>
          </QueryClientProvider>
        );
      }).not.toThrow();

      // The FK ids render (falling back to the raw id, since the mock
      // resolves no labels) once the new queries settle.
      await waitFor(() => {
        expect(screen.getByText("11111111-1111-1111-1111-111111111111")).toBeInTheDocument();
        expect(screen.getByText("22222222-2222-2222-2222-222222222222")).toBeInTheDocument();
      });
    });
  });
});
