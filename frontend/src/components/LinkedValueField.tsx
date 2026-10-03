import { useState } from "react";
import { formatApiError } from "../api/errors";
import { useDeriveFields, useEntityTypes, type EntityType } from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";

/**
 * A number of the record each one links to, copied onto it: a district's forecast onto each of its
 * cells, a crop's water need onto each yield row. Benchmark round 5: this was only to be found inside
 * the forecast form ("copy onto each record"). Kept: records imported later get it too.
 */
export default function LinkedValueField({ kind }: { kind: EntityType }) {
  const { can } = useCapabilities();
  const derive = useDeriveFields();
  const kinds = useEntityTypes(kind.domain_id, { limit: 500 });
  const [pick, setPick] = useState("");
  const [of, setOf] = useState("");
  const [said, setSaid] = useState<{ error: boolean; text: string } | null>(null);
  // This kind's link fields, each with the kind it links to.
  const links = (kind.attributes ?? []).filter((a) => a.data_type === "reference")
    .map((a) => ({ link: a.name, to: (kinds.data?.items ?? []).find((k) => k.id === a.target_type_id) }))
    .filter((l): l is { link: string; to: EntityType } => l.to !== undefined);
  if (!can("domain.edit") || links.length === 0) return null;
  const chosen = links.find((l) => l.link === pick) ?? links[0];
  const numbers = (chosen.to.attributes ?? []).filter((a) => ["number", "integer", "boolean"].includes(a.data_type)).map((a) => a.name);
  const ready = numbers.includes(of);
  return (
    <form aria-label="A number of the linked record" className="mt-4 rounded-md border border-slate-200 bg-white p-4 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        setSaid(null);
        derive.mutate({ entityTypeId: kind.id, body: { op: "from_link", field: chosen.link, of } }, {
          onSuccess: (done) => setSaid({ error: false, text: `${done.made.join(", ")} copied onto ${done.records} ${kind.name} records`
            + `${done.left_empty ? `; ${done.left_empty} link to no ${chosen.to.name} with one` : ""}. Records imported later get it too.` }),
          onError: (err) => setSaid({ error: true, text: formatApiError(err) }),
        });
      }}>
      <h2 className="mb-1 text-base font-semibold text-slate-900">A number of the linked record</h2>
      <p className="mb-2 text-xs text-slate-600">
        Each {kind.name} gets the {of || "…"} of the {chosen.to.name} it links to by <span className="font-mono">{chosen.link}</span>,
        as the field <span className="font-mono">{chosen.link}_{of || "…"}</span>. (A data value over {chosen.to.name} needs no copy:
        an equation reads it through the link, as <span className="font-mono">rate[{chosen.link}[i]]</span>.)
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-slate-600">Through
          <select aria-label="Through the link" className="ml-1 rounded border border-slate-300 px-2 py-1 font-mono text-sm"
            value={chosen.link} onChange={(e) => { setPick(e.target.value); setOf(""); }}>
            {links.map((l) => <option key={l.link} value={l.link}>{l.link} (to {l.to.name})</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-600">Its
          <select aria-label="The linked record's number" className="ml-1 rounded border border-slate-300 px-2 py-1 font-mono text-sm"
            value={of} onChange={(e) => setOf(e.target.value)}>
            <option value="">choose…</option>
            {numbers.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <button type="submit" disabled={derive.isPending || !ready}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-white disabled:opacity-60">
          {derive.isPending ? "Copying…" : "Copy onto each"}
        </button>
      </div>
      {said && <p role={said.error ? "alert" : "status"} className={`mt-2 ${said.error ? "text-red-700" : "text-green-800"}`}>{said.text}</p>}
    </form>
  );
}
