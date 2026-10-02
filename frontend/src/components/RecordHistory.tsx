import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import { formatAttrValue } from "./AttrsForm";
import type { Id } from "../api/v1";

export type HistoryEntry = {
  id: Id;
  at: string;
  actor: string | null;
  op: "insert" | "update" | "delete";
  changes: { field: string; before: unknown; after: unknown }[];
};

const PAGE = 20;
const WHAT: Record<HistoryEntry["op"], string> = { insert: "Created", update: "Changed", delete: "Deleted" };

function when(at: string): string {
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? at : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** A value as the form shows it; a point by where it is, any other shape by what it is. */
function shown(value: unknown): string {
  const shape = value as { type?: string; coordinates?: number[] } | null;
  if (shape && typeof shape === "object" && shape.type === "Point" && Array.isArray(shape.coordinates)) {
    return `${shape.coordinates[1].toFixed(5)}, ${shape.coordinates[0].toFixed(5)}`;
  }
  if (shape && typeof shape === "object" && "type" in shape) return `a ${shape.type}`;
  return formatAttrValue(value);
}

/**
 * Who changed this record, when, and each field from what to what (`GET /entities/{id}/history`).
 * Kept by the database for every writer -- the form, the grid, a workbook, an import -- so a value
 * that changed can always be traced, and put back by hand.
 */
export default function RecordHistory({ entityId }: { entityId: Id }) {
  const [limit, setLimit] = useState(PAGE);
  const history = useQuery({
    queryKey: ["v1", "entity-history", entityId, limit],
    queryFn: () => apiFetch<{ total: number; items: HistoryEntry[] }>(`/api/v1/entities/${entityId}/history?limit=${limit}`),
  });
  if (history.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (history.isError) return <p className="text-sm text-red-700">Could not read the history: {formatApiError(history.error)}</p>;
  const items = history.data?.items ?? [];
  if (items.length === 0) {
    return <p className="text-sm text-slate-500">No change kept yet. Changes are kept from now on, whoever makes them.</p>;
  }
  return (
    <div className="space-y-2">
      <ol className="space-y-2" aria-label="Changes, newest first">
        {items.map((h) => (
          <li key={h.id} className="rounded-md border border-slate-200 p-2 text-sm">
            <p>
              <span className={`font-medium ${h.op === "delete" ? "text-red-700" : "text-slate-900"}`}>{WHAT[h.op]}</span>
              <span className="ml-2 text-slate-500">
                {when(h.at)} · {h.actor ?? "the system"}
              </span>
            </p>
            {h.op === "update" && (
              <table className="mt-1 w-full text-xs">
                <tbody>
                  {h.changes.map((c) => (
                    <tr key={c.field} className="align-top">
                      <th scope="row" className="w-1/3 py-0.5 pr-2 text-left font-mono font-normal text-slate-600">
                        {c.field}
                      </th>
                      <td className="py-0.5">
                        <span className="text-slate-500 line-through">{shown(c.before)}</span>
                        <span aria-hidden="true" className="mx-1 text-slate-400">
                          →
                        </span>
                        <span className="sr-only"> became </span>
                        <span className="text-slate-900">{shown(c.after)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </li>
        ))}
      </ol>
      {(history.data?.total ?? 0) > items.length && (
        <button type="button" className="text-xs text-blue-700 underline" onClick={() => setLimit(limit + PAGE)}>
          Older changes ({(history.data?.total ?? 0) - items.length})
        </button>
      )}
    </div>
  );
}
