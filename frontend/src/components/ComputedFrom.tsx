/**
 * How a parameter was made from the map, and "compute it again" -- as it was, or with a new limit
 * ("within 25 min, not 15") or a wider join to an imported lines layer. Shown only for data that
 * remembers its ask; typed or uploaded data has nothing to recompute.
 */
import { useId, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import type { ComputedSource, Id } from "../api/v1";
import { leftOut } from "./MeasureFromMap";

type Ask = {
  metric?: string; max_m?: number; max_min?: number; nearest?: number; unit?: string;
  network?: { layer?: string; join_m?: number; speed_field?: string };
};
export type MadeSource = ComputedSource & { request?: Ask };

/** One line on how it was made: "travel time within 15 min along layer ROADS, yard → hotspot, 1 Oct 2026". */
export function madeIn(source: MadeSource): string {
  const ask = source.request ?? {};
  const limit = ask.max_min != null ? `within ${ask.max_min} min` : ask.max_m != null ? `within ${ask.max_m} m` : "";
  const what = source.kind === "within" ? `0/1 ${limit}`.trim() : `${source.unit ?? ""} ${ask.nearest ? `(nearest ${ask.nearest})` : ""}`.trim();
  const when = source.computed_at ? new Date(source.computed_at).toLocaleString() : "";
  return [what, source.metric, `${source.from} → ${source.to}`, when].filter(Boolean).join(" · ");
}

export default function ComputedFrom({ parameterId, source }: { parameterId: Id; source: MadeSource | null | undefined }) {
  const id = useId();
  const client = useQueryClient();
  const ask = source?.request;
  const [limit, setLimit] = useState(String(ask?.max_min ?? ask?.max_m ?? ""));
  const [join, setJoin] = useState(String(ask?.network?.join_m ?? 500));
  const [said, setSaid] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!source || !ask) return null;
  const timed = ask.max_min != null;
  const within = source.kind === "within";

  async function again(event: FormEvent) {
    event.preventDefault();
    setSaid(null);
    const body: Record<string, number> = {};
    if (within && Number(limit) > 0) body[timed ? "max_min" : "max_m"] = Number(limit);
    if (ask?.network && Number(join) > 0) body.join_m = Number(join);
    setBusy(true);
    try {
      const done = await apiFetch<{ kind: string; pairs?: number; edges?: number; missing: string[]; source: ComputedSource }>(
        `/api/v1/parameters/${parameterId}/recompute`, { method: "POST", body: JSON.stringify(body) });
      void client.invalidateQueries();
      const count = done.kind === "within" ? `${done.edges ?? 0} pairs marked 1` : `${done.pairs ?? 0} values`;
      const gaps = leftOut(done.source, Number(join) || 500);
      setSaid(`Computed again: ${count}.${gaps ? ` ${gaps}` : ""}`);
    } catch (e) {
      setSaid(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={again} aria-labelledby={`${id}-h`} className="mb-4 rounded-md border border-sky-200 bg-sky-50 p-3 text-sm">
      <p id={`${id}-h`} className="text-slate-800">
        <span className="font-semibold">Made from the map:</span> {madeIn(source)}
      </p>
      <div className="mt-2 flex flex-wrap items-end gap-3">
        {within && (
          <label className="text-xs text-slate-600">
            Within ({timed ? "min" : "m"})
            <input className="ml-1 w-20 rounded border px-2 py-1 text-sm" inputMode="decimal" value={limit}
                   onChange={(e) => setLimit(e.target.value)} />
          </label>
        )}
        {ask.network && (
          <label className="text-xs text-slate-600">
            Join places up to (m)
            <input className="ml-1 w-20 rounded border px-2 py-1 text-sm" inputMode="decimal" value={join}
                   onChange={(e) => setJoin(e.target.value)} />
          </label>
        )}
        <button type="submit" disabled={busy}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60">
          {busy ? "Computing…" : "Compute again"}
        </button>
      </div>
      {said && <p role="status" className="mt-2 text-slate-800">{said}</p>}
    </form>
  );
}
