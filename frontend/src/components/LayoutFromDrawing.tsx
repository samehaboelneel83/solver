import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import type { Id } from "../api/v1";

type Layer = { name: string; features: number; kinds: Record<string, number> };
type Drawing = { upload_id: string; filename: string; layers: Layer[]; local_metres: boolean; notes: string[] };
type Item = { name: string; length: string; width: string; turns: boolean; value: string; count: string };
type Preview = {
  form: "place" | "generated";
  grid_step_m: number;
  grid_note?: string;
  aisle_m: { asked: number; modelled: number; cells: number; side: string };
  areas: number;
  zones: string[];
  free_area_m2: number;
  candidates?: number;
  candidates_by_kind?: Record<string, number>;
  slots_by_kind?: Record<string, number>;
  upper_bound: { items: number; how: string };
  access?: { areas_without_access?: string[] } | null;
  not_modelled: string;
};
type Built = { problem_id?: Id; scenario_id?: Id; trial?: { status: string; objective?: number | null } };

const INPUT = "rounded border border-slate-300 px-2 py-1 text-sm";
const blankItem = (): Item => ({ name: "", length: "", width: "", turns: true, value: "1", count: "" });

/** The layers of one kind, as tick boxes. */
function LayerPicks({ label, layers, chosen, onChange, hint }: {
  label: string; layers: Layer[]; chosen: string[]; onChange: (next: string[]) => void; hint: string;
}) {
  return (
    <fieldset className="rounded border border-slate-200 p-3">
      <legend className="px-1 text-sm font-medium text-slate-800">{label}</legend>
      <p className="mb-2 text-xs text-slate-600">{hint}</p>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {layers.map((layer) => (
          <label key={layer.name} className="text-sm">
            <input type="checkbox" checked={chosen.includes(layer.name)} className="mr-1"
              onChange={(event) => onChange(event.target.checked ? [...chosen, layer.name]
                : chosen.filter((name) => name !== layer.name))} />
            {layer.name} <span className="text-xs text-slate-500">({layer.features}
            {Object.keys(layer.kinds).length ? `: ${Object.entries(layer.kinds).map(([k, n]) => `${n} ${k}`).join(", ")}` : ""})</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * Items laid out on a drawing -- beds in a camp, desks in rooms, stalls in a car park -- built into a problem
 * without the Assistant (owner, 9 October 2026): the same layout code and the same checked build as its
 * `make_layout` and `propose_plan` (`/api/v1/layouts/*`).
 */
export function LayoutFromDrawing({ domainId, name, onMade }: {
  domainId: Id; name: string; onMade: (problemId: Id) => void;
}) {
  const id = useId();
  const [drawing, setDrawing] = useState<Drawing | null>(null);
  const [areas, setAreas] = useState<string[]>([]);
  const [blocked, setBlocked] = useState<string[]>([]);
  const [access, setAccess] = useState<string[]>([]);
  const [label, setLabel] = useState("");
  const [items, setItems] = useState<Item[]>([blankItem()]);
  const [aisle, setAisle] = useState("0");
  const [side, setSide] = useState("any");
  const [step, setStep] = useState("");
  const [form, setForm] = useState<"place" | "candidates">("place");
  const [preview, setPreview] = useState<Preview | null>(null);

  const read = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      body.append("domain_id", String(domainId));
      return apiFetch<Drawing>("/api/v1/layouts/drawings", { method: "POST", body });
    },
    onSuccess: (got) => {
      setDrawing(got);
      setPreview(null);
      // Polygon layers are where items go, most often; nothing is chosen for the person beyond a guess they see.
      setAreas(got.layers.filter((l) => (l.kinds.polygon ?? 0) > 0).slice(0, 1).map((l) => l.name));
      setBlocked([]);
      setAccess([]);
      setLabel("");
    },
  });

  const options = () => ({
    upload_id: drawing?.upload_id,
    area_layers: areas,
    blocked_layers: blocked,
    access_layers: access,
    ...(label ? { label_layer: label } : {}),
    items: items.filter((it) => it.name.trim()).map((it) => ({
      name: it.name.trim(), length: Number(it.length), width: Number(it.width), rotations: it.turns ? [0, 90] : [0],
      value: Number(it.value || 1), ...(it.count.trim() ? { count: Number(it.count) } : {}),
    })),
    aisle: Number(aisle || 0),
    aisle_side: Number(aisle || 0) > 0 ? side : "none",
    ...(step.trim() ? { step: Number(step) } : {}),
    form,
  });
  const look = useMutation({
    mutationFn: () => apiFetch<Preview>("/api/v1/layouts/preview", { method: "POST", body: JSON.stringify(options()) }),
    onSuccess: setPreview,
  });
  const build = useMutation({
    mutationFn: (trial: boolean) => apiFetch<Built>("/api/v1/layouts/build", {
      method: "POST",
      body: JSON.stringify({ ...options(), domain_id: Number(domainId), problem_name: name.trim() || "Layout",
        ...(trial ? { dry_run: true, trial: true } : {}) }),
    }),
    onSuccess: (got, trial) => {
      if (!trial && got.problem_id !== undefined) onMade(got.problem_id);
    },
  });

  const itemsOk = items.some((it) => it.name.trim()) && items.every((it) => !it.name.trim()
    || (Number(it.length) > 0 && Number(it.width) > 0));
  const ready = Boolean(drawing) && areas.length > 0 && itemsOk;
  const setItem = (n: number, patch: Partial<Item>) => {
    setItems(items.map((it, k) => (k === n ? { ...it, ...patch } : it)));
    setPreview(null);
  };

  return (
    <section aria-label="Lay out on a drawing" className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <div>
        <label className="block text-sm font-medium text-slate-800" htmlFor={`${id}-file`}>
          The drawing (DXF, DWG, GeoJSON, KML, shapefile, GeoPackage)
        </label>
        <input id={`${id}-file`} type="file" className="mt-1 text-sm" disabled={read.isPending}
          onChange={(event) => event.target.files?.[0] && read.mutate(event.target.files[0])} />
        {read.isPending && <p role="status" className="text-sm text-slate-600">Reading the drawing…</p>}
        {read.isError && <p role="alert" className="text-sm text-red-700">{formatApiError(read.error)}</p>}
        {drawing && <p className="mt-1 text-sm text-slate-600">{drawing.filename}: {drawing.layers.length} layers
          {drawing.local_metres ? ", measured in metres from its lower-left corner" : ""}.</p>}
        {drawing?.notes.map((note) => <p key={note} className="text-xs text-amber-800">{note}</p>)}
      </div>

      {drawing && <>
        <LayerPicks label="Where items may go" layers={drawing.layers} chosen={areas}
          onChange={(next) => { setAreas(next); setPreview(null); }}
          hint="Layers whose closed shapes (rooms, camps, plots) items are placed in; each shape is an area of its own." />
        <LayerPicks label="What no item may cover" layers={drawing.layers} chosen={blocked}
          onChange={(next) => { setBlocked(next); setPreview(null); }}
          hint="Obstacles, columns, door fronts kept clear (optional)." />
        <LayerPicks label="Every item must be reachable from" layers={drawing.layers} chosen={access}
          onChange={(next) => { setAccess(next); setPreview(null); }}
          hint="Doors, exits, gates: every item's aisle then joins one of them through free space (optional)." />
        <label className="block text-sm">Names of the areas (a text layer, optional){" "}
          <select className={INPUT} value={label} onChange={(event) => { setLabel(event.target.value); setPreview(null); }}>
            <option value="">none</option>
            {drawing.layers.map((layer) => <option key={layer.name} value={layer.name}>{layer.name}</option>)}
          </select>
        </label>

        <fieldset className="rounded border border-slate-200 p-3">
          <legend className="px-1 text-sm font-medium text-slate-800">The items, in metres</legend>
          <table className="text-sm">
            <thead><tr className="text-left text-xs text-slate-600">
              <th className="pr-2">Name</th><th className="pr-2">Length</th><th className="pr-2">Width</th>
              <th className="pr-2">May turn</th><th className="pr-2">Worth</th><th className="pr-2">At most (optional)</th><th />
            </tr></thead>
            <tbody>{items.map((it, n) => (
              <tr key={n}>
                <td className="pr-2"><input aria-label={`Item ${n + 1} name`} className={`${INPUT} w-28`} value={it.name}
                  onChange={(event) => setItem(n, { name: event.target.value })} placeholder="bed" /></td>
                <td className="pr-2"><input aria-label={`Item ${n + 1} length`} className={`${INPUT} w-20`} inputMode="decimal"
                  value={it.length} onChange={(event) => setItem(n, { length: event.target.value })} /></td>
                <td className="pr-2"><input aria-label={`Item ${n + 1} width`} className={`${INPUT} w-20`} inputMode="decimal"
                  value={it.width} onChange={(event) => setItem(n, { width: event.target.value })} /></td>
                <td className="pr-2"><input aria-label={`Item ${n + 1} may turn`} type="checkbox" checked={it.turns}
                  onChange={(event) => setItem(n, { turns: event.target.checked })} /></td>
                <td className="pr-2"><input aria-label={`Item ${n + 1} worth`} className={`${INPUT} w-16`} inputMode="decimal"
                  value={it.value} onChange={(event) => setItem(n, { value: event.target.value })} /></td>
                <td className="pr-2"><input aria-label={`Item ${n + 1} at most`} className={`${INPUT} w-20`} inputMode="numeric"
                  value={it.count} onChange={(event) => setItem(n, { count: event.target.value })} /></td>
                <td>{items.length > 1 && <button type="button" className="text-xs text-red-700 underline"
                  onClick={() => { setItems(items.filter((_, k) => k !== n)); setPreview(null); }}>Remove</button>}</td>
              </tr>
            ))}</tbody>
          </table>
          <button type="button" className="mt-2 text-sm text-blue-700 underline"
            onClick={() => setItems([...items, blankItem()])}>Add a kind of item</button>
        </fieldset>

        <div className="flex flex-wrap gap-4">
          <label className="text-sm">Aisle beside each item (m, 0 for none){" "}
            <input className={`${INPUT} w-20`} inputMode="decimal" value={aisle}
              onChange={(event) => { setAisle(event.target.value); setPreview(null); }} /></label>
          {Number(aisle || 0) > 0 && <label className="text-sm">On which side{" "}
            <select className={INPUT} value={side} onChange={(event) => { setSide(event.target.value); setPreview(null); }}>
              <option value="any">any side</option><option value="long">a long side</option><option value="short">a short side</option>
            </select></label>}
          <label className="text-sm">Grid step (m, empty: the exact one for these sizes){" "}
            <input className={`${INPUT} w-20`} inputMode="decimal" value={step}
              onChange={(event) => { setStep(event.target.value); setPreview(null); }} /></label>
        </div>
        <fieldset className="text-sm">
          <legend className="font-medium text-slate-800">How it is modelled</legend>
          <label className="mr-4"><input type="radio" name={`${id}-form`} checked={form === "place"} className="mr-1"
            onChange={() => { setForm("place"); setPreview(null); }} />
            Placement on the exact grid (no list of positions; the layout solver places items itself)</label>
          <label><input type="radio" name={`${id}-form`} checked={form === "candidates"} className="mr-1"
            onChange={() => { setForm("candidates"); setPreview(null); }} />
            Every position listed (built by each run from the areas and kinds; any solver)</label>
        </fieldset>

        <div className="flex flex-wrap gap-2">
          <button type="button" className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
            disabled={!ready || look.isPending} onClick={() => look.mutate()}>
            {look.isPending ? "Laying it out…" : "Preview the layout"}
          </button>
        </div>
        {look.isError && <p role="alert" className="text-sm text-red-700">{formatApiError(look.error)}</p>}
        {preview && (
          <div role="region" aria-label="Layout preview" className="rounded border border-blue-200 bg-blue-50 p-3 text-sm">
            <p>Grid {preview.grid_step_m} m; aisle {preview.aisle_m.modelled} m as modelled
              {preview.aisle_m.cells ? ` (${preview.aisle_m.cells} cells, ${preview.aisle_m.side} side)` : ""};{" "}
              {preview.areas} areas, {preview.free_area_m2.toLocaleString("en-US")} m² free.</p>
            {preview.grid_note && <p className="text-amber-800">{preview.grid_note}</p>}
            <p>{preview.candidates !== undefined
              ? `${preview.candidates.toLocaleString("en-US")} candidate positions (${Object.entries(preview.candidates_by_kind ?? {}).map(([k, n]) => `${n.toLocaleString("en-US")} ${k}`).join(", ")}), built by each run.`
              : `Slots: ${Object.entries(preview.slots_by_kind ?? {}).map(([k, n]) => `${n.toLocaleString("en-US")} ${k}`).join(", ")}.`}</p>
            <p>At most {preview.upper_bound.items.toLocaleString("en-US")} items fit: {preview.upper_bound.how}.</p>
            {preview.access?.areas_without_access?.length ? <p className="text-amber-800">
              Areas with no access feature take no item: {preview.access.areas_without_access.join(", ")}.</p> : null}
            <p className="text-slate-700">Not modelled: {preview.not_modelled}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className="rounded border px-3 py-1.5 disabled:opacity-50" disabled={build.isPending}
                onClick={() => build.mutate(true)}>Check with a short trial solve</button>
              <button type="button" className="rounded bg-blue-700 px-3 py-1.5 text-white disabled:opacity-50"
                disabled={build.isPending || !name.trim()} onClick={() => build.mutate(false)}>
                {name.trim() ? `Make “${name.trim()}”` : "Name the problem above to make it"}
              </button>
            </div>
            {build.isPending && <p role="status">Checking and building…</p>}
            {build.isSuccess && build.variables && build.data.trial && (
              <p role="status" className="mt-2">Trial solve: {build.data.trial.status}
                {build.data.trial.objective !== undefined && build.data.trial.objective !== null
                  ? `, ${build.data.trial.objective.toLocaleString("en-US")} items` : ""}. Nothing was kept.</p>
            )}
            {build.isError && <p role="alert" className="mt-2 text-red-700">{formatApiError(build.error)}</p>}
          </div>
        )}
      </>}
    </section>
  );
}
