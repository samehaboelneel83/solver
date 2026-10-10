import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import type { EntityType } from "../api/v1";

type Totals = { groups: { group: string | null; rows: number; sums: Record<string, number | null> }[];
  truncated: boolean; total: Record<string, number | null> & { rows: number } };

/** Exact counts and totals over a kind of record, grouped by a field -- what the Assistant's file queries give. */
export function RecordTotals({ type }: { type: EntityType }) {
  const [open, setOpen] = useState(false);
  const [by, setBy] = useState("");
  const numeric = type.attributes.filter((a) => a.data_type === "integer" || a.data_type === "number").map((a) => a.name);
  const [added, setAdded] = useState<string[]>([]);
  const query = new URLSearchParams([...(by ? [["by", by]] : []), ...added.map((name) => ["sum", name])]);
  const totals = useQuery({
    queryKey: ["entity-totals", type.id, by, added.join(",")],
    queryFn: () => apiFetch<Totals>(`/api/v1/entity-types/${type.id}/totals?${query}`),
    enabled: open,
  });
  const show = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: 6 }));
  return (
    <details className="mt-4 rounded-lg border border-slate-200 bg-white p-3 text-sm"
      onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer font-semibold text-slate-900">Totals of {type.name}</summary>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <label>Grouped by{" "}
          <select className="rounded border border-slate-300 px-2 py-1" value={by} onChange={(e) => setBy(e.target.value)}>
            <option value="">nothing (all records)</option><option value="key">key</option><option value="label">name</option>
            {type.attributes.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
          </select></label>
        {numeric.length > 0 && <fieldset className="flex flex-wrap gap-2"><legend className="sr-only">Add up</legend>
          <span>Add up:</span>
          {numeric.map((name) => <label key={name}><input type="checkbox" className="mr-1" checked={added.includes(name)}
            onChange={(e) => setAdded(e.target.checked ? [...added, name] : added.filter((n) => n !== name))} />{name}</label>)}
        </fieldset>}
      </div>
      {totals.isError && <p role="alert" className="mt-2 text-red-700">{formatApiError(totals.error)}</p>}
      {totals.data && <table aria-label={`Totals of ${type.name}`} className="mt-2 text-left">
        <thead><tr className="text-xs text-slate-500"><th className="pr-4">{by || "All"}</th><th className="pr-4">Records</th>
          {added.map((name) => <th key={name} className="pr-4">{name}</th>)}</tr></thead>
        <tbody>{totals.data.groups.map((g, n) => <tr key={n}>
          <td className="pr-4">{by ? g.group ?? "(empty)" : "all"}</td><td className="pr-4">{g.rows.toLocaleString("en-US")}</td>
          {added.map((name) => <td key={name} className="pr-4">{show(g.sums[name])}</td>)}</tr>)}
          {by && <tr className="border-t border-slate-200 font-medium"><td className="pr-4">Total</td>
            <td className="pr-4">{totals.data.total.rows.toLocaleString("en-US")}</td>
            {added.map((name) => <td key={name} className="pr-4">{show(totals.data!.total[name])}</td>)}</tr>}
        </tbody></table>}
      {totals.data?.truncated && <p className="text-xs text-amber-800">The first 500 groups, largest first.</p>}
    </details>
  );
}
