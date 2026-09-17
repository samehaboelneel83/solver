import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient();
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("DataTable", () => {
  it("renders rows and pagination info", () => {
    renderWithQueryClient(
      <DataTable
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

  it("calls onPageChange with the next offset", () => {
    const onPageChange = vi.fn();
    renderWithQueryClient(
      <DataTable
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

  it("calls onRowClick when a row is clicked, but not when Delete is clicked", () => {
    const onRowClick = vi.fn();
    const onDelete = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithQueryClient(
      <DataTable
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

    fireEvent.click(screen.getByText("employee"));
    expect(onRowClick).toHaveBeenCalledWith("1");

    onRowClick.mockClear();
    fireEvent.click(screen.getByText("Delete"));
    expect(onRowClick).not.toHaveBeenCalled();
    expect(onDelete).toHaveBeenCalledWith("1");
    (window.confirm as any).mockRestore();
  });

  describe("delete confirmation", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("calls onDelete when the confirmation is accepted", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderWithQueryClient(
        <DataTable
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );

      fireEvent.click(screen.getByText("Delete"));

      expect(window.confirm).toHaveBeenCalledWith("Delete this row? This cannot be undone.");
      expect(onDelete).toHaveBeenCalledWith("1");
    });

    it("skips onDelete when the confirmation is cancelled", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(false);
      renderWithQueryClient(
        <DataTable
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );

      fireEvent.click(screen.getByText("Delete"));

      expect(window.confirm).toHaveBeenCalled();
      expect(onDelete).not.toHaveBeenCalled();
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
      renderWithQueryClient(
        <DataTable
          fields={labeledFields}
          rows={[]}
          total={0}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      expect(screen.getByText("Organization")).toBeInTheDocument();
      expect(screen.getByText("Code")).toBeInTheDocument();
      expect(screen.queryByText("organization_id")).not.toBeInTheDocument();
    });

    it("falls back to the raw field name when a column has no label", () => {
      renderWithQueryClient(
        <DataTable
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

      renderWithQueryClient(
        <DataTable
          fields={fkFields}
          rows={fkRows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
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
          <DataTable
            fields={zeroFkFields}
            rows={zeroFkRows}
            total={1}
            limit={20}
            offset={0}
            onPageChange={vi.fn()}
            onDelete={vi.fn()}
          />
        </QueryClientProvider>
      );

      expect(() => {
        rerender(
          <QueryClientProvider client={queryClient}>
            <DataTable
              fields={twoFkFields}
              rows={twoFkRows}
              total={1}
              limit={20}
              offset={0}
              onPageChange={vi.fn()}
              onDelete={vi.fn()}
            />
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
