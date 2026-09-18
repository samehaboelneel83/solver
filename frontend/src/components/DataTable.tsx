import { useEffect, useRef, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { optionLabelsQuery } from "../api/options";
import { fieldLabel, lowerFirst } from "../lib/labels";
import { formatCellValue } from "../lib/format";
import type { FieldMeta } from "../types/meta";

type Row = Record<string, unknown>;

type DataTableProps = {
  /** Schema/table names (raw, not the human label) used to build each row's link. */
  schema: string;
  table: string;
  /** Human, plural table name, e.g. "Entity types" -- used for the caption
   * and the empty state ("No entity types yet"). */
  tableLabel: string;
  /** Link target for "create a new record", reused by the empty state. */
  newHref: string;
  fields: FieldMeta[];
  rows: Row[];
  total: number;
  limit: number;
  offset: number;
  orderBy?: string;
  order?: "asc" | "desc";
  onSort?: (column: string) => void;
  onPageChange: (offset: number) => void;
  onDelete: (id: string, label: string) => void;
  onRowClick?: (id: string) => void;
};

/**
 * Human-readable name for a row, so the delete confirmation (D-6) can say
 * "Delete "employee"?" instead of the anonymous "Delete this row?" that reads
 * identically for every row in the table. Prefers `code` (usually the
 * stable, human-assigned identifier) over `name`, then falls back to a
 * generic phrase when neither is present.
 */
function recordLabel(row: Row): string {
  if (typeof row.code === "string" && row.code) return row.code;
  if (typeof row.name === "string" && row.name) return row.name;
  return "this row";
}

/**
 * A column that shows a raw or resolved identifier rather than the record's
 * own business data: the primary key, and any `*_id` foreign-key field
 * (E-4). Hidden by default (behind "Show identifiers") so a wrapped
 * 36-character UUID doesn't push meaningful columns out of view.
 */
function isIdentifierColumn(name: string): boolean {
  return name === "id" || name.endsWith("_id");
}

function idsForColumns(rows: Row[], columns: string[]): string[] {
  const values = new Set<string>();
  for (const row of rows) {
    for (const col of columns) {
      const value = row[col];
      if (value !== null && value !== undefined && value !== "") {
        values.add(String(value));
      }
    }
  }
  return Array.from(values);
}

export default function DataTable({
  schema,
  table,
  tableLabel,
  newHref,
  fields,
  rows,
  total,
  limit,
  offset,
  orderBy,
  order,
  onSort,
  onPageChange,
  onDelete,
  onRowClick,
}: DataTableProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const showIds = searchParams.get("ids") === "1";

  function toggleShowIds() {
    const next = new URLSearchParams(searchParams);
    if (showIds) {
      next.delete("ids");
    } else {
      next.set("ids", "1");
    }
    setSearchParams(next);
  }

  const displayFields = showIds ? fields : fields.filter((f) => !isIdentifierColumn(f.name));

  const [openMenuRowId, setOpenMenuRowId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Close the open row-actions menu on an outside click.
  useEffect(() => {
    if (!openMenuRowId) return;
    function handleClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setOpenMenuRowId(null);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [openMenuRowId]);

  // FK columns, grouped by the table they reference: one label query per
  // distinct FK table on the page. useQueries (rather than calling
  // useOptionLabels in a loop) is safe even if the number of FK tables
  // changes between renders of the same DataTable instance. Computed from
  // every field (not just the currently-displayed ones) so toggling
  // identifiers on doesn't have to wait out a fresh fetch.
  const fkFields = fields.filter((f) => f.is_fk && f.fk_table) as (FieldMeta & { fk_table: string })[];
  const fkTables = Array.from(new Set(fkFields.map((f) => f.fk_table)));
  const labelResults = useQueries({
    queries: fkTables.map((fkTable) => {
      const columnsForTable = fkFields.filter((f) => f.fk_table === fkTable).map((f) => f.name);
      const ids = idsForColumns(rows, columnsForTable);
      return optionLabelsQuery(fkTable, ids);
    }),
  });

  function labelFor(col: string, id: string): string {
    const fkTable = fkFields.find((f) => f.name === col)?.fk_table;
    if (!fkTable) return id;
    const index = fkTables.indexOf(fkTable);
    const labels = index >= 0 ? labelResults[index]?.data : undefined;
    return labels?.[id] ?? id;
  }

  function handleDeleteClick(row: Row) {
    const label = recordLabel(row);
    if (window.confirm(`Delete "${label}"? This cannot be undone.`)) {
      onDelete(String(row.id), label);
    }
  }

  if (total === 0) {
    return (
      <div>
        <div className="rounded-md border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500">
          <p>{`No ${lowerFirst(tableLabel)} yet`}</p>
          <Link to={newHref} className="mt-2 inline-block text-sm font-medium text-blue-700 hover:underline">
            New
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <button
          type="button"
          onClick={toggleShowIds}
          aria-pressed={showIds}
          className="text-xs text-slate-500 underline hover:text-slate-700"
        >
          {showIds ? "Hide identifiers" : "Show identifiers"}
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{tableLabel}</caption>
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              {displayFields.map((field) => {
                const isActive = orderBy === field.name;
                const label = fieldLabel(field);
                return (
                  <th
                    key={field.name}
                    scope="col"
                    className="px-3 py-2 font-medium"
                    aria-sort={onSort ? (isActive ? (order === "desc" ? "descending" : "ascending") : "none") : undefined}
                  >
                    {onSort ? (
                      <button
                        type="button"
                        onClick={() => onSort(field.name)}
                        aria-label={`Sort by ${label}`}
                        className="flex h-6 items-center gap-1 px-1 hover:text-slate-900"
                      >
                        <span>{label}</span>
                        {isActive && <span aria-hidden="true">{order === "desc" ? "▼" : "▲"}</span>}
                      </button>
                    ) : (
                      label
                    )}
                  </th>
                );
              })}
              <th scope="col" className="px-3 py-2">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const rowId = String(row.id);
              const rowHref = `/${schema}/${table}/${rowId}`;
              const label = recordLabel(row);
              return (
                <tr
                  key={rowId}
                  onClick={() => onRowClick?.(rowId)}
                  className={`border-b border-slate-100 hover:bg-slate-50 ${onRowClick ? "cursor-pointer" : ""}`}
                >
                  {displayFields.map((field, index) => {
                    const value = row[field.name];
                    const isFk = fkFields.some((f) => f.name === field.name);
                    let content: React.ReactNode;
                    let title: string | undefined;
                    if (isFk && value !== null && value !== undefined && value !== "") {
                      const id = String(value);
                      content = labelFor(field.name, id);
                      title = id;
                    } else {
                      const formatted = formatCellValue(field, value);
                      title = formatted.title;
                      content = formatted.ariaLabel ? (
                        <span aria-label={formatted.ariaLabel}>{formatted.text}</span>
                      ) : (
                        formatted.text
                      );
                    }
                    if (index === 0) {
                      return (
                        <td key={field.name} className="px-3 py-2" title={title}>
                          <Link to={rowHref} className="font-medium text-blue-700 hover:underline">
                            {content}
                          </Link>
                        </td>
                      );
                    }
                    return (
                      <td key={field.name} className="px-3 py-2" title={title}>
                        {content}
                      </td>
                    );
                  })}
                  <td className="px-3 py-2 text-right">
                    <div
                      className="relative inline-block"
                      ref={rowId === openMenuRowId ? menuRef : undefined}
                    >
                      <button
                        type="button"
                        data-testid="row-actions"
                        aria-haspopup="menu"
                        aria-expanded={rowId === openMenuRowId}
                        aria-label={`Actions for ${label}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenMenuRowId((current) => (current === rowId ? null : rowId));
                        }}
                        className="flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                      >
                        <span aria-hidden="true">⋮</span>
                      </button>
                      {rowId === openMenuRowId && (
                        <div
                          role="menu"
                          className="absolute right-0 z-10 mt-1 min-w-[8rem] rounded-md border border-slate-200 bg-white py-1 shadow-md"
                        >
                          <button
                            type="button"
                            role="menuitem"
                            onClick={(event) => {
                              event.stopPropagation();
                              setOpenMenuRowId(null);
                              handleDeleteClick(row);
                            }}
                            className="block w-full px-3 py-1.5 text-left text-sm text-red-600 hover:bg-red-50"
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between text-sm text-slate-500">
        <span role="status" aria-live="polite">
          {`${offset + 1}-${Math.min(offset + limit, total)} of ${total}`}
        </span>
        <div className="space-x-2">
          <button
            disabled={offset === 0}
            onClick={() => onPageChange(Math.max(0, offset - limit))}
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
          >
            Previous
          </button>
          <button
            disabled={offset + limit >= total}
            onClick={() => onPageChange(offset + limit)}
            className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
