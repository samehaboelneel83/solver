/**
 * Make a map layer from records (benchmark round 5): a buffer round each, the area each reaches by 0/1
 * data (its service area), or the places none of them reaches -- saved as map data, to show under an
 * answer or export. From an answer, only the records it chose.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { deriveLayer } from "../../api/gis";
import { formatApiError } from "../../api/errors";
import { useEntityTypes, useParameters } from "../../api/v1";

type How = "buffer" | "service_area" | "not_reached";
const HOW: [How, string][] = [["buffer", "a ring round each"], ["service_area", "the places each reaches"], ["not_reached", "the places none reaches"]];

export default function DeriveLayer({ domainId, kind, keys, title = "Make a map layer" }: {
  domainId: number;
  /** The kind's name, when it is fixed (an answer's chosen records). */
  kind?: string;
  /** Only these records (what an answer chose). */
  keys?: string[];
  title?: string;
}) {
  const client = useQueryClient();
  const types = useEntityTypes(domainId, { limit: 500 });
  const params = useParameters(domainId, { limit: 500 });
  const all = types.data?.items ?? [];
  const [picked, setPicked] = useState<number | "">("");
  const type = kind ? all.find((t) => t.name === kind) : all.find((t) => t.id === picked);
  const [how, setHow] = useState<How>("buffer");
  const [km, setKm] = useState("5");
  // 0/1 data over this kind and one other: who is within reach.
  const reach = (params.data?.items ?? []).filter((p) => type && p.index_type_ids.length === 2 && p.index_type_ids.includes(type.id)
    && p.index_type_ids[0] !== p.index_type_ids[1]);
  const [param, setParam] = useState<number | "">("");
  const paramId = param === "" ? reach.find((p) => /within|reach|cover/.test(p.name))?.id ?? reach[0]?.id : param;
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<{ text: string; id?: number } | null>(null);
  const label = type ? (how === "buffer" ? `${type.name} within ${km} km` : how === "service_area" ? `served by each ${type.name}` : `not reached by ${type.name}`) : "";
  const ready = !!type && (how === "buffer" ? Number(km) > 0 : paramId !== undefined) && (!keys || keys.length > 0);
  async function make() {
    if (!type) return;
    setBusy(true);
    setSaid(null);
    try {
      const made = await deriveLayer({ domain_id: domainId, name: name.trim() || label, how, entity_type_id: Number(type.id),
        ...(how === "buffer" ? { radius_km: Number(km) } : { parameter_id: Number(paramId) }), ...(keys ? { keys } : {}) });
      void client.invalidateQueries({ queryKey: ["gis"] });
      setSaid({ text: `Made ${made.name}: ${made.made} ${made.made === 1 ? "shape" : "shapes"}.`, id: made.id });
    } catch (e) {
      setSaid({ text: formatApiError(e) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="rounded-md border border-slate-200 bg-white p-3 text-sm">
      <summary className="cursor-pointer font-medium text-slate-800">{title}</summary>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        {!kind && (
          <label className="text-xs text-slate-600">From
            <select aria-label="Records to draw from" className="ml-1 rounded border px-2 py-1 text-sm" value={picked}
              onChange={(e) => setPicked(e.target.value ? Number(e.target.value) : "")}>
              <option value="">choose…</option>
              {all.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
        )}
        {kind && <span className="text-xs text-slate-600">From {keys ? `the ${keys.length} chosen` : "every"} {kind}</span>}
        <label className="text-xs text-slate-600">draw
          <select aria-label="What to draw" className="ml-1 rounded border px-2 py-1 text-sm" value={how} onChange={(e) => setHow(e.target.value as How)}>
            {HOW.map(([h, text]) => <option key={h} value={h}>{text}</option>)}
          </select>
        </label>
        {how === "buffer" ? (
          <label className="text-xs text-slate-600">of
            <input aria-label="Ring size in km" type="number" min="0" step="any" className="ml-1 w-20 rounded border px-2 py-1 text-sm"
              value={km} onChange={(e) => setKm(e.target.value)} /> km
          </label>
        ) : (
          <label className="text-xs text-slate-600">by
            <select aria-label="Who is within reach" className="ml-1 rounded border px-2 py-1 text-sm" value={paramId ?? ""}
              onChange={(e) => setParam(e.target.value ? Number(e.target.value) : "")}>
              {reach.length === 0 && <option value="">no 0/1 data over {type?.name ?? "it"} yet</option>}
              {reach.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
        )}
        <label className="text-xs text-slate-600">named
          <input aria-label="Name of the new layer" className="ml-1 w-44 rounded border px-2 py-1 text-sm" placeholder={label}
            value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <button type="button" disabled={busy || !ready} onClick={() => void make()}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-60">
          {busy ? "Making…" : "Make the layer"}
        </button>
      </div>
      {said && (
        <p role="status" className="mt-2 text-xs text-slate-700">
          {said.text}{said.id !== undefined && <> <Link className="underline" to={`/domains/${domainId}/map-data/${said.id}`}>Open it</Link>; it can be shown under an answer.</>}
        </p>
      )}
    </details>
  );
}
