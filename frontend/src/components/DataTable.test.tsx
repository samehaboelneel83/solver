import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DataTable from "./DataTable";

const fields = [
  { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
  { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null },
];

const rows = [{ id: "1", code: "employee" }];

describe("DataTable", () => {
  it("renders rows and pagination info", () => {
    render(
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

  it("calls onDelete with the row id when Delete is clicked", () => {
    const onDelete = vi.fn();
    render(
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
    expect(onDelete).toHaveBeenCalledWith("1");
  });

  it("calls onPageChange with the next offset", () => {
    const onPageChange = vi.fn();
    render(
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
    render(
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
  });
});
