import { useState } from "react";
import { formatApiError } from "../api/errors";
import { useDeriveFields, useEntityTypes, type EntityType } from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";

/**
 * Link each record to the record of another kind its code names -- a call to its district by
 * `dist_code`, a yield row to its parcel -- matched on the other kind's key or name, or one of its
 * fields (benchmark re-test, October 2026: a links file was made outside the app for this).
 */
export default function LinkByField({ kind }: { kind: EntityType }) {
  const { can } = useCapabilities();
  const derive = useDeriveFields();
  const kinds = useEntityTypes(kind.domain_id, { limit: 500 });
  const [of, setOf] = useState("");
  const [to, setTo] = useState("");
  const [match, setMatch] = useState("key");
  const [name, setName] = useState("");
  const [said, setSaid] = useState<{ error: boolean; text: string } | null>(null);
  const codes = (kind.attributes ?? []).filter((a) => ["text", "integer", "enum"].includes(a.data_type)).map((a) => a.name);
  const others = (kinds.data?.items ?? []).filter((k) => k.id !== kind.id && !k.is_abstract);
  if (!can("domain.edit") || codes.length === 0 || others.length === 0) return null;
  const target = others.find((k) => k.name === to);
  const field = name.trim() || (to ? `${to}_link` : "");
  const ready = !!of && !!target && /^[a-z][a-z0-9_]*$/.test(field);
  const select = "ml-1 rounded border border-slate-300 px-2 py-1 font-mono text-sm";
  return (
    <form aria-label="Link records by a code they hold" className="mt-4 rounded-md border border-slate-200 bg-white p-4 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        setSaid(null);
        derive.mutate({ entityTypeId: kind.id, body: { op: "link_by", field, of, to_kind: to, match } }, {
          onSuccess: (done) => {
            const d = done as typeof done & { unmatched?: string[]; ambiguous?: string[]; left_empty?: number };
            // The server lists the first 20; it counts all of them (benchmark round 3: "20 not" for 38).
            const missed = d.left_empty ?? (d.unmatched?.length ?? 0) + (d.ambiguous?.length ?? 0);
            setSaid({ error: false, text: `${done.records} ${kind.name} records linked to their ${to} by ${field}${missed
              ? `; ${missed} not${missed > (d.unmatched?.length ?? 0) + (d.ambiguous?.length ?? 0) ? ", among them" : ""}: ${[...(d.unmatched ?? []).map((u) => `${u} (no ${to} has it)`), ...(d.ambiguous ?? []).map((a) => `${a} (more than one ${to} has it)`)].slice(0, 5).join(", ")}`
              : ""}.` });
          },
          onError: (err) => setSaid({ error: true, text: formatApiError(err) }),
        });
      }}>
      <h2 className="mb-1 text-base font-semibold text-slate-900">Link records by a code they hold</h2>
      <p className="mb-2 text-xs text-slate-600">
        Each {kind.name} gets a link to the record its code names, case and spaces aside — a join, with no file of links to make.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-slate-600">Its field
          <select aria-label="The field holding the code" className={select} value={of} onChange={(e) => setOf(e.target.value)}>
            <option value="">choose…</option>
            {codes.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-600">names a
          <select aria-label="The kind it names" className={select} value={to} onChange={(e) => { setTo(e.target.value); setMatch("key"); }}>
            <option value="">choose…</option>
            {others.map((k) => <option key={k.id} value={k.name}>{k.name}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-600">by its
          <select aria-label="What of it the code matches" className={select} value={match} onChange={(e) => setMatch(e.target.value)}>
            <option value="key">key or name</option>
            {(target?.attributes ?? []).filter((a) => ["text", "integer", "enum"].includes(a.data_type)).map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-600">Link name
          <input aria-label="Name of the link" className="ml-1 w-40 rounded border border-slate-300 px-2 py-1 font-mono text-sm"
            value={name} onChange={(e) => setName(e.target.value)} placeholder={field || "in_district"} />
        </label>
        <button type="submit" disabled={derive.isPending || !ready} className="rounded-md bg-slate-900 px-3 py-1.5 text-white disabled:opacity-60">
          {derive.isPending ? "Linking…" : "Link"}
        </button>
      </div>
      {said && <p role={said.error ? "alert" : "status"} className={`mt-2 ${said.error ? "text-red-700" : "text-green-800"}`}>{said.text}</p>}
    </form>
  );
}
