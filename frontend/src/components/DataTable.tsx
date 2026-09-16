import type { FieldMeta } from "../types/meta";

type Row = Record<string, unknown>;

type DataTableProps = {
  fields: FieldMeta[];
  rows: Row[];
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
  onDelete: (id: string) => void;
  onRowClick?: (id: string) => void;
};

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function DataTable({
  fields,
  rows,
  total,
  limit,
  offset,
  onPageChange,
  onDelete,
  onRowClick,
}: DataTableProps) {
  const columns = fields.map((f) => f.name);

  return (
    <div>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-slate-500">
            {columns.map((col) => (
              <th key={col} className="px-3 py-2 font-medium">
                {col}
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
              {columns.map((col) => (
                <td key={col} className="px-3 py-2">
                  {formatCell(row[col])}
                </td>
              ))}
              <td className="px-3 py-2 text-right">
                <button
                  className="text-xs text-red-600 hover:underline"
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete(String(row.id));
                  }}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
