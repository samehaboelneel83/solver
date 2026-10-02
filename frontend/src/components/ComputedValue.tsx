import { useState } from "react";
import { formatApiError } from "../api/errors";
import { useDeriveValue, useParameters, type EntityType, type Id } from "../api/v1";

/**
 * A data value computed once from the records (benchmark, October 2026: worked out in a
 * spreadsheet and uploaded):
 * - read through a link: a parcel's suitability for each crop, from its soil and `suitability[soil, crop]`;
 * - 1 or 0 by a comparison: `rotation_ok[parcel, crop]` is 1 where the parcel's last crop is not that crop.
 */
export default function ComputedValue({ domainId, entityTypes, onMade }: {
  domainId: Id; entityTypes: EntityType[]; onMade?: (id: Id) => void;
}) {
  const derive = useDeriveValue();
  const parameters = useParameters(domainId, { limit: 500 });
  const [op, setOp] = useState<"lookup" | "compare">("lookup");
  const [kindName, setKindName] = useState("");
  const [field, setField] = useState("");
  const [source, setSource] = useState("");
  const [other, setOther] = useState("");
  const [against, setAgainst] = useState("key");
  const [compare, setCompare] = useState<"=" | "!=">("!=");
  const [name, setName] = useState("");
  const [said, setSaid] = useState<{ error: boolean; text: string } | null>(null);
  const kind = entityTypes.find((k) => k.name === kindName);
  const otherKind = entityTypes.find((k) => k.name === other);
  const fields = (kind?.attributes ?? []).filter((a) => (op === "lookup" ? a.data_type === "reference" : a.data_type !== "geometry"));
  const link = fields.find((a) => a.name === field);
  // Data values whose first index is the kind the chosen link names.
  const sources = (parameters.data?.items ?? []).filter((p) => link?.target_type_id != null && p.index_type_ids[0] === link.target_type_id);
  const ready = /^[a-z][a-z0-9_]*$/.test(name.trim()) && kind && field && (op === "lookup" ? source : other);
  const select = "ml-1 rounded border border-slate-300 px-2 py-1 font-mono text-sm";
  return (
    <form aria-label="A data value computed from the records" className="mb-6 rounded-md border border-slate-200 bg-white p-4 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        setSaid(null);
        const body = op === "lookup"
          ? { op, name: name.trim(), kind: kindName, field, source }
          : { op, name: name.trim(), kind: kindName, field, other, against, compare };
        derive.mutate({ domainId, body }, {
          onSuccess: (done) => { setSaid({ error: false, text: `${done.name} made with ${done.cells} values.` }); onMade?.(done.parameter_id); },
          onError: (err) => setSaid({ error: true, text: formatApiError(err) }),
        });
      }}>
      <h2 className="mb-1 text-base font-semibold text-slate-900">A data value computed from the records</h2>
      <div className="mb-2 flex gap-3 text-xs text-slate-700" role="radiogroup" aria-label="How it is computed">
        <label><input type="radio" checked={op === "lookup"} onChange={() => { setOp("lookup"); setField(""); }} /> read through a link</label>
        <label><input type="radio" checked={op === "compare"} onChange={() => { setOp("compare"); setField(""); }} /> 1 or 0 by a comparison</label>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-slate-600">For each
          <select aria-label="Kind" className={select} value={kindName} onChange={(e) => { setKindName(e.target.value); setField(""); }}>
            <option value="">choose…</option>
            {entityTypes.filter((k) => !k.is_abstract).map((k) => <option key={k.id} value={k.name}>{k.name}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-600">{op === "lookup" ? "through its link" : "its field"}
          <select aria-label={op === "lookup" ? "Link" : "Field compared"} className={select} value={field} onChange={(e) => setField(e.target.value)}>
            <option value="">choose…</option>
            {fields.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
          </select>
        </label>
        {op === "lookup" ? (
          <label className="text-xs text-slate-600">read
            <select aria-label="Data value read" className={select} value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">choose…</option>
              {sources.map((p) => <option key={p.id} value={p.name}>{p.name}</option>)}
            </select>
          </label>
        ) : (
          <>
            <select aria-label="Comparison" className={select} value={compare} onChange={(e) => setCompare(e.target.value as "=" | "!=")}>
              <option value="=">is</option>
              <option value="!=">is not</option>
            </select>
            <label className="text-xs text-slate-600">the
              <select aria-label="Against" className={select} value={against} onChange={(e) => setAgainst(e.target.value)}>
                <option value="key">key</option>
                {(otherKind?.attributes ?? []).map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
              </select>
            </label>
            <label className="text-xs text-slate-600">of each
              <select aria-label="Other kind" className={select} value={other} onChange={(e) => { setOther(e.target.value); setAgainst("key"); }}>
                <option value="">choose…</option>
                {entityTypes.filter((k) => !k.is_abstract).map((k) => <option key={k.id} value={k.name}>{k.name}</option>)}
              </select>
            </label>
          </>
        )}
        <label className="text-xs text-slate-600">Name
          <input aria-label="Name of the data value" className="ml-1 w-40 rounded border border-slate-300 px-2 py-1 font-mono text-sm"
            value={name} onChange={(e) => setName(e.target.value)} placeholder={op === "lookup" ? "parcel_suit" : "rotation_ok"} />
        </label>
        <button type="submit" disabled={derive.isPending || !ready} className="rounded-md bg-slate-900 px-3 py-1.5 text-white disabled:opacity-60">
          {derive.isPending ? "Computing…" : "Compute"}
        </button>
      </div>
      {op === "lookup" && link && sources.length === 0 && (
        <p className="mt-2 text-xs text-amber-800">No data value is indexed first by the kind {field} links to.</p>
      )}
      {said && <p role={said.error ? "alert" : "status"} className={`mt-2 ${said.error ? "text-red-700" : "text-green-800"}`}>{said.text}</p>}
    </form>
  );
}
