import { useState } from "react";
import { formatApiError } from "../api/errors";
import { useDeriveFields, useEntityTypes, type EntityType } from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";

type How = "count" | "sum" | "mean" | "max" | "min";
const HOW_WORDS: Record<How, string> = { count: "how many", sum: "the total of", mean: "the average of", max: "the largest", min: "the smallest" };

/**
 * A number field on each record totalled over the records of another kind that link to it: calls
 * per district, demand per warehouse (benchmark, October 2026: counted in a spreadsheet and typed
 * back in). Computed now; pressed again after the data changes.
 */
export default function LinkedTotalField({ kind }: { kind: EntityType }) {
  const { can } = useCapabilities();
  const derive = useDeriveFields();
  const kinds = useEntityTypes(kind.domain_id, { limit: 500 });
  const [pick, setPick] = useState("");
  const [how, setHow] = useState<How>("count");
  const [of, setOf] = useState("");
  const [name, setName] = useState("");
  const [said, setSaid] = useState<{ error: boolean; text: string } | null>(null);
  // Every link field of another kind that names this one: "call.district".
  const links = (kinds.data?.items ?? []).flatMap((k) =>
    (k.attributes ?? []).filter((a) => a.data_type === "reference" && a.target_type_id === kind.id)
      .map((a) => ({ value: `${k.name}.${a.name}`, kind: k, link: a.name })));
  if (!can("domain.edit") || links.length === 0) return null;
  const chosen = links.find((l) => l.value === pick) ?? links[0];
  const numbers = (chosen.kind.attributes ?? []).filter((a) => a.data_type === "number" || a.data_type === "integer").map((a) => a.name);
  const field = name.trim() || (how === "count" ? `${chosen.kind.name}_count` : `${chosen.kind.name}_${of || "value"}_${how}`);
  const ready = /^[a-z][a-z0-9_]*$/.test(field) && (how === "count" || numbers.includes(of));
  return (
    <form aria-label="A total of linked records" className="mt-4 rounded-md border border-slate-200 bg-white p-4 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        setSaid(null);
        derive.mutate({ entityTypeId: kind.id, body: { op: "linked_total", field, from_kind: chosen.kind.name, link: chosen.link, how,
          ...(how === "count" ? {} : { of }) } }, {
          onSuccess: (done) => setSaid({ error: false, text: `${field} computed on ${done.records} ${kind.name} records.` }),
          onError: (err) => setSaid({ error: true, text: formatApiError(err) }),
        });
      }}>
      <h2 className="mb-1 text-base font-semibold text-slate-900">A total of linked records</h2>
      <p className="mb-2 text-xs text-slate-600">
        For each {kind.name}: {HOW_WORDS[how]} {how === "count" ? `${chosen.kind.name} records` : `${of || "…"} of the ${chosen.kind.name} records`} that
        link to it by <span className="font-mono">{chosen.link}</span>. A {kind.name} nothing links to gets {how === "count" || how === "sum" ? "0" : "no value"}.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-slate-600">From
          <select aria-label="Records that link here" className="ml-1 rounded border border-slate-300 px-2 py-1 font-mono text-sm"
            value={chosen.value} onChange={(e) => { setPick(e.target.value); setOf(""); }}>
            {links.map((l) => <option key={l.value} value={l.value}>{l.value}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-600">Total
          <select aria-label="How to total" className="ml-1 rounded border border-slate-300 px-2 py-1 text-sm"
            value={how} onChange={(e) => setHow(e.target.value as How)}>
            {(Object.keys(HOW_WORDS) as How[]).map((h) => <option key={h} value={h}>{HOW_WORDS[h]}</option>)}
          </select>
        </label>
        {how !== "count" && (
          <label className="text-xs text-slate-600">Of
            <select aria-label="Number totalled" className="ml-1 rounded border border-slate-300 px-2 py-1 font-mono text-sm"
              value={of} onChange={(e) => setOf(e.target.value)}>
              <option value="">choose…</option>
              {numbers.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        )}
        <label className="text-xs text-slate-600">Name
          <input aria-label="Name of the total" className="ml-1 w-44 rounded border border-slate-300 px-2 py-1 font-mono text-sm"
            value={name} onChange={(e) => setName(e.target.value)} placeholder={field} />
        </label>
        <button type="submit" disabled={derive.isPending || !ready}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-white disabled:opacity-60">
          {derive.isPending ? "Computing…" : "Compute"}
        </button>
      </div>
      {said && <p role={said.error ? "alert" : "status"} className={`mt-2 ${said.error ? "text-red-700" : "text-green-800"}`}>{said.text}</p>}
    </form>
  );
}
