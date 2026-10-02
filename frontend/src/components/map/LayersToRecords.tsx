/**
 * Map layers used by models (improvement plan 1.1 / 1.3): the features of one
 * or more layers become records of a kind -- one per feature, its shape a
 * geometry field, its properties fields, its area or length measured -- or
 * their shapes are attached to records already there, matched by key.
 *
 * Nothing here knows what the places are: yards, clinics, fields, stops.
 * Once records have a shape, distances, travel times, "within" links and run
 * maps all work on them.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { formatApiError } from "../../api/errors";
import {
  attachShapes, makeRecords, proposeRecords,
  type GisDataset, type RecordsProposal, type ShapesAttached,
} from "../../api/gis";
import { useEntityTypes } from "../../api/v1";

const INPUT = "rounded border border-slate-300 px-2 py-1 text-xs";

export default function LayersToRecords({ dataset, canEdit }: { dataset: GisDataset; canEdit: boolean }) {
  const client = useQueryClient();
  const [mode, setMode] = useState<"make" | "attach">("make");
  const [layers, setLayers] = useState<string[]>(dataset.layers.length === 1 ? [dataset.layers[0].name] : []);
  const [plan, setPlan] = useState<RecordsProposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ text: string; typeId?: number } | null>(null);
  const [attachType, setAttachType] = useState("");
  const [match, setMatch] = useState("");
  const [field, setField] = useState("shape");
  const [attached, setAttached] = useState<ShapesAttached | null>(null);
  const types = useEntityTypes(dataset.domain_id, { limit: 500, offset: 0 });
  const [addToExisting, setAddToExisting] = useState(false);
  // Read from the kinds there are now, so renaming clears the warning at once.
  const existing = plan && !done ? (types.data?.items ?? []).find((t) => t.name === plan.name.trim()) ?? null : null;

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      await work();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };
  const toggleLayer = (name: string, on: boolean) => {
    setPlan(null);
    setLayers((now) => (on ? [...now, name] : now.filter((n) => n !== name)));
  };

  if (!canEdit) {
    return <p className="text-xs text-slate-600">Ask someone who may edit this workspace to turn these layers into records.</p>;
  }

  return (
    <div className="space-y-3 text-xs">
      <p className="text-slate-700">
        Models read <strong>records</strong>, not drawings. Turn layers into records (one per feature, with its shape),
        or put the shapes onto records you already have — then distances, travel times and maps can be made from them.
      </p>
      <div role="radiogroup" aria-label="What to do" className="flex gap-3">
        <label className="inline-flex items-center gap-1">
          <input type="radio" name="layers-mode" checked={mode === "make"} onChange={() => setMode("make")} /> Make records
        </label>
        <label className="inline-flex items-center gap-1">
          <input type="radio" name="layers-mode" checked={mode === "attach"} onChange={() => setMode("attach")} /> Add shapes to records I have
        </label>
      </div>
      <fieldset className="space-y-1">
        <legend className="font-medium text-slate-700">Layers</legend>
        {dataset.layers.map((l) => (
          <label key={l.id} className="flex items-center gap-2">
            <input type="checkbox" checked={layers.includes(l.name)} onChange={(e) => toggleLayer(l.name, e.target.checked)} />
            <span className="font-mono">{l.name}</span>
            <span className="text-slate-500">{l.feature_count} features</span>
          </label>
        ))}
      </fieldset>

      {mode === "make" && (
        <div className="space-y-2">
          <button type="button" disabled={!layers.length || busy}
            onClick={() => void run(async () => setPlan(await proposeRecords(dataset.id, layers)))}
            className="rounded border border-blue-600 px-2 py-1 font-medium text-blue-700 disabled:opacity-50">
            {plan ? "Read the layers again" : "Show what it would make"}
          </button>
          {plan && (
            <div className="space-y-2 rounded border border-slate-200 bg-white p-2">
              <label className="block">Each feature becomes a{" "}
                <input aria-label="Kind of record" className={`${INPUT} w-32 font-mono`} value={plan.name}
                  onChange={(e) => setPlan({ ...plan, name: e.target.value })} />
              </label>
              {existing && (
                // User trial: hospitals went quietly into the "point" kind the sites had just made.
                <div role="alert" className="rounded border border-amber-300 bg-amber-50 p-2 text-amber-900">
                  <p>
                    A kind named <span className="font-mono">{existing.name}</span> already exists
                    {existing.attributes.length > 0 && <> (fields: {existing.attributes.map((a) => a.name).join(", ")})</>}.
                    These features would be added to it, and records with the same key refreshed.
                    Rename it above to make a kind of their own.
                  </p>
                  <label className="mt-1 flex items-center gap-1">
                    <input type="checkbox" checked={addToExisting} onChange={(e) => setAddToExisting(e.target.checked)} />
                    Yes, add them to {existing.name}
                  </label>
                </div>
              )}
              <label className="block">told apart by{" "}
                <select aria-label="Key property" className={INPUT} value={plan.key ?? ""}
                  onChange={(e) => {
                    // The key is not also a field; the one it was becomes one again.
                    const key = e.target.value || null;
                    setPlan({ ...plan, key, fields: plan.fields.map((f) => (f.property === key ? { ...f, skip: true }
                      : f.property === plan.key ? { ...f, skip: false } : f)) });
                  }}>
                  <option value="">its number</option>
                  {plan.key_candidates.map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
              </label>
              <label className="block">and named by{" "}
                <select aria-label="Name property" className={INPUT} value={plan.label ?? ""}
                  onChange={(e) => setPlan({ ...plan, label: e.target.value || null })}>
                  <option value="">no name</option>
                  {plan.fields.map((f) => <option key={f.property} value={f.property}>{f.property}</option>)}
                </select>
              </label>
              <p className="text-slate-600">
                {plan.features} records · shape in <span className="font-mono">{plan.geometry_field}</span>
                {plan.measures.length > 0 && <> · measured: {plan.measures.join(", ")}</>}
                {plan.skipped_text > 0 && <> · {plan.skipped_text} text labels left out</>}
                {plan.shapes.includes("line") && <> · a line is kept as its length and a point on it</>}
              </p>
              {plan.fields.length > 0 && (
                <table className="w-full">
                  <thead><tr className="text-left text-slate-500"><th>Property</th><th>Field</th><th>Type</th><th>Keep</th></tr></thead>
                  <tbody>
                    {plan.fields.map((f, i) => (
                      <tr key={f.property}>
                        <td className="pr-1 font-mono">{f.property}</td>
                        <td className="pr-1">
                          <input aria-label={`Field name for ${f.property}`} className={`${INPUT} w-28`} value={f.name}
                            onChange={(e) => setPlan({ ...plan, fields: plan.fields.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
                        </td>
                        <td className="pr-1 text-slate-600">{f.data_type}</td>
                        <td><input type="checkbox" aria-label={`Keep ${f.property}`} checked={!f.skip}
                          onChange={(e) => setPlan({ ...plan, fields: plan.fields.map((x, j) => (j === i ? { ...x, skip: !e.target.checked } : x)) })} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <button type="button" disabled={busy || (!!existing && !addToExisting) || !plan.name.trim()}
                onClick={() => void run(async () => {
                  const made = await makeRecords(dataset.id, layers, plan);
                  void client.invalidateQueries();
                  setDone({ text: `${made.made} ${made.type} records made${made.updated ? `, ${made.updated} refreshed` : ""}.`, typeId: made.entity_type_id });
                })}
                className="rounded bg-blue-600 px-3 py-1.5 font-medium text-white disabled:opacity-50">
                Make {plan.features} records
              </button>
            </div>
          )}
        </div>
      )}

      {mode === "attach" && (
        <div className="space-y-2 rounded border border-slate-200 bg-white p-2">
          <label className="block">Records of kind{" "}
            <select aria-label="Kind of record to add shapes to" className={INPUT} value={attachType} onChange={(e) => setAttachType(e.target.value)}>
              <option value="">choose…</option>
              {(types.data?.items ?? []).map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
            </select>
          </label>
          <label className="block">matched where the feature property{" "}
            <input aria-label="Feature property holding the record key" className={`${INPUT} w-28 font-mono`} placeholder="name" value={match}
              onChange={(e) => setMatch(e.target.value)} />{" "}
            equals the record's key
          </label>
          <label className="block">shape field{" "}
            <input aria-label="Shape field name" className={`${INPUT} w-28 font-mono`} value={field} onChange={(e) => setField(e.target.value)} />
          </label>
          <button type="button" disabled={busy || !layers.length || !attachType || !match}
            onClick={() => void run(async () => {
              const result = await attachShapes(dataset.id, { layers, type: attachType, match, field });
              setAttached(result);
              void client.invalidateQueries();
              setDone({ text: `${result.attached} ${result.type} records now have a shape.` });
            })}
            className="rounded bg-blue-600 px-3 py-1.5 font-medium text-white disabled:opacity-50">Add the shapes</button>
          {attached && (attached.records_without_shape.length > 0 || attached.unmatched_features.length > 0) && (
            <div className="text-amber-800">
              {attached.records_without_shape.length > 0 && <p>Still without a shape: {attached.records_without_shape.slice(0, 12).join(", ")}{attached.records_without_shape.length > 12 ? "…" : ""}</p>}
              {attached.unmatched_features.length > 0 && <p>Features no record matched: {attached.unmatched_features.slice(0, 12).join(", ")}{attached.unmatched_features.length > 12 ? "…" : ""}</p>}
            </div>
          )}
        </div>
      )}

      {error && <p role="alert" className="whitespace-pre-wrap text-red-700">{error}</p>}
      {done && (
        <p role="status" className="text-emerald-800">
          {done.text}{" "}
          <Link className="underline" to={`/domains/${dataset.domain_id}/data/records${done.typeId ? `?type=${done.typeId}` : ""}`}>Open the records</Link>
          {" · "}
          <Link className="underline" to={`/domains/${dataset.domain_id}/map-data`}>Compute distances and reach from them</Link>
        </p>
      )}
    </div>
  );
}
