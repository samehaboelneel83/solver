import { useState } from "react";
import { formatApiError } from "../api/errors";
import { useDeriveFields, type EntityType } from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";

/**
 * A number field computed from a record's own number fields -- `volume_vph / capacity_vph`,
 * `length_km / speed_kmh * 60` -- kept on each record so any rule or goal reads it as data
 * (benchmark, October 2026: a model's formulas cannot divide, and travel time and load ratios
 * could not be written). Computed now; computed again by pressing it again after the data changes.
 */
export default function FormulaField({ kind }: { kind: EntityType }) {
  const { can } = useCapabilities();
  const derive = useDeriveFields();
  const [name, setName] = useState("");
  const [formula, setFormula] = useState("");
  const [said, setSaid] = useState<{ error: boolean; text: string } | null>(null);
  const numbers = (kind.attributes ?? []).filter((a) => a.data_type === "number" || a.data_type === "integer").map((a) => a.name);
  if (!can("domain.edit") || numbers.length === 0) return null;
  return (
    <form aria-label="A field computed from others" className="rounded-md border border-slate-200 bg-white p-4 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        setSaid(null);
        derive.mutate({ entityTypeId: kind.id, body: { op: "formula", field: name.trim(), formula } }, {
          onSuccess: (done) => setSaid({ error: false, text: `${name} computed on ${done.records} records${done.left_empty ? `; ${done.left_empty} left empty (a field missing, or a division by zero)` : ""}.` }),
          onError: (err) => setSaid({ error: true, text: formatApiError(err) }),
        });
      }}>
      <h2 className="mb-1 text-base font-semibold text-slate-900">A field computed from others</h2>
      <p className="mb-2 text-xs text-slate-600">
        Number fields with + − × / and brackets, e.g. <code className="font-mono">{numbers.slice(0, 2).join(" / ") || "a / b"}</code>.
        Fields: <span className="font-mono">{numbers.join(", ")}</span>.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-slate-600">Name
          <input aria-label="Name of the computed field" className="ml-1 w-36 rounded border border-slate-300 px-2 py-1 font-mono text-sm"
            value={name} onChange={(e) => setName(e.target.value)} placeholder="vc_ratio" />
        </label>
        <label className="text-xs text-slate-600">=
          <input aria-label="Formula" className="ml-1 w-72 rounded border border-slate-300 px-2 py-1 font-mono text-sm"
            value={formula} onChange={(e) => setFormula(e.target.value)} placeholder="volume / capacity" />
        </label>
        <button type="submit" disabled={derive.isPending || !/^[a-z][a-z0-9_]*$/.test(name.trim()) || !formula.trim()}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-white disabled:opacity-60">
          {derive.isPending ? "Computing…" : "Compute"}
        </button>
      </div>
      {said && <p role={said.error ? "alert" : "status"} className={`mt-2 ${said.error ? "text-red-700" : "text-green-800"}`}>{said.text}</p>}
    </form>
  );
}
