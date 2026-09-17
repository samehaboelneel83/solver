import { useOptionLabels } from "../api/options";
import type { FieldMeta } from "../types/meta";

type Row = Record<string, unknown>;

type DataTableProps = {
  fields: FieldMeta[];
  rows: Row[];
  total: number;
  limit: number;
  offset: number;
  orderBy?: string;
  order?: "asc" | "desc";
  onSort?: (column: string) => void;
  onPageChange: (offset: number) => void;
  onDelete: (id: string) => void;
  onRowClick?: (id: string) => void;
};

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
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
  const columns = fields.map((f) => f.name);

  // FK columns, grouped by the table they reference. `fields` comes from
  // table metadata and is stable for the lifetime of this component
  // instance (callers remount DataTable when the schema/table changes),
  // so this loop calls useOptionLabels the same number of times on every
  // render of a given instance.
  const fkFields = fields.filter((f) => f.is_fk && f.fk_table) as (FieldMeta & { fk_table: string })[];
  const fkTables = Array.from(new Set(fkFields.map((f) => f.fk_table)));
  const labelQueries = fkTables.map((fkTable) => {
    const columnsForTable = fkFields.filter((f) => f.fk_table === fkTable).map((f) => f.name);
    const ids = idsForColumns(rows, columnsForTable);
    return { fkTable, query: useOptionLabels(fkTable, ids) };
  });

  function labelFor(col: string, id: string): string {
    const fkTable = fkFields.find((f) => f.name === col)?.fk_table;
    if (!fkTable) return id;
    const labels = labelQueries.find((entry) => entry.fkTable === fkTable)?.query.data;
    return labels?.[id] ?? id;
  }

  function handleDeleteClick(id: string) {
    if (window.confirm("Delete this row? This cannot be undone.")) {
      onDelete(id);
    }
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              {columns.map((col) => (
                <th key={col} className="px-3 py-2 font-medium">
                  {onSort ? (
                    <button
                      type="button"
                      onClick={() => onSort(col)}
                      className="flex items-center gap-1 hover:text-slate-900"
                    >
                      <span>{col}</span>
                      {orderBy === col && <span aria-hidden="true">{order === "desc" ? "↓" : "↑"}</span>}
                    </button>
                  ) : (
                    col
                  )}
                </th>
              ))}
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={String(row.id)}
                onClick={() => onRowClick?.(String(row.id))}
                className={`border-b border-slate-100 hover:bg-slate-50 ${onRowClick ? "cursor-pointer" : ""}`}
              >
                {columns.map((col) => {
                  const value = row[col];
                  const isFk = fkFields.some((f) => f.name === col);
                  if (isFk && value !== null && value !== undefined && value !== "") {
                    const id = String(value);
                    return (
                      <td key={col} className="px-3 py-2" title={id}>
                        {labelFor(col, id)}
                      </td>
                    );
                  }
                  return (
                    <td key={col} className="px-3 py-2">
                      {formatCell(value)}
                    </td>
                  );
                })}
                <td className="px-3 py-2 text-right">
                  <button
                    className="text-xs text-red-600 hover:underline"
                    onClick={(event) => {
                      event.stopPropagation();
                      handleDeleteClick(String(row.id));
                    }}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between text-sm text-slate-500">
        <span>
          {total === 0 ? "0 rows" : `${offset + 1}-${Math.min(offset + limit, total)} of ${total}`}
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
